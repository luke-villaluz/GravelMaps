"""Merge per-state way caches into one routing graph, cached as memory-mapped .npy files.

Terminology:
  position  – one point in the flat per-way coordinate arrays (lat/lon, fixed-point 1e-7°)
  node      – a graph vertex: a way endpoint or a point shared by more than one way
  edge      – the stretch of one way between two consecutive nodes, spanning positions
              pstart..pend (inclusive)
  csr entry – a directed traversal of an edge; code = edge * 2 + (1 if traversed backwards)
"""
import json
import os
import shutil
import time

import numpy as np

from . import places
from .paths import graph_dir, ways_path

GRAPH_VERSION = 3
GRID_DEG = 0.01
FIXED = 1e-7
EARTH_R = 6371008.8

WAY_ARRAYS = ["road_class", "surface", "rough", "legal", "oneway", "name_idx"]


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle metres between points given in degrees (numpy-vectorized)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.minimum(a, 1.0)))


def _sources_meta(regions):
    return {
        "version": GRAPH_VERSION,
        "regions": sorted(regions),
        "sources": {r: int(os.stat(ways_path(r)).st_mtime) for r in sorted(regions)},
    }


def is_fresh(regions):
    meta_path = os.path.join(graph_dir(regions), "meta.json")
    if not os.path.exists(meta_path):
        return False
    with open(meta_path) as f:
        meta = json.load(f)
    return {k: meta.get(k) for k in ("version", "regions", "sources")} == _sources_meta(regions)


def _merge_ways(regions):
    """Concatenate state caches, dropping ways that appear in more than one state."""
    parts = {k: [] for k in ["way_ids", "lengths", "node_ids", "lat", "lon", "barrier_ids", "barrier_block",
                             *WAY_ARRAYS]}
    names = []
    for r in regions:
        with np.load(ways_path(r)) as z:
            parts["way_ids"].append(z["way_ids"])
            parts["lengths"].append(np.diff(z["offsets"]))
            for k in ["node_ids", "lat", "lon", "road_class", "surface", "rough", "legal", "oneway",
                      "barrier_ids", "barrier_block"]:
                parts[k].append(z[k])
            ni = z["name_idx"].astype(np.int32)
            parts["name_idx"].append(np.where(ni >= 0, ni + len(names), -1).astype(np.int32))
            names.extend(json.loads(bytes(z["names"]).decode()))
    cat = {k: np.concatenate(v) for k, v in parts.items()}

    _, first = np.unique(cat["way_ids"], return_index=True)
    keep = np.zeros(len(cat["way_ids"]), dtype=bool)
    keep[first] = True
    pos_keep = np.repeat(keep, cat["lengths"])
    merged = {k: cat[k][keep] for k in ["way_ids", "lengths", *WAY_ARRAYS]}
    for k in ["node_ids", "lat", "lon"]:
        merged[k] = cat[k][pos_keep]
    # A barrier seen in two states keeps the union of what it blocks.
    bids, inv = np.unique(cat["barrier_ids"], return_inverse=True)
    bmask = np.zeros(len(bids), dtype=np.uint8)
    np.bitwise_or.at(bmask, inv, cat["barrier_block"])
    merged["barrier_ids"], merged["barrier_block"] = bids, bmask
    return merged, names


def build(regions):
    t0 = time.time()
    m, names = _merge_ways(regions)
    lengths = m["lengths"]
    npos = int(lengths.sum())
    nways = len(lengths)
    offsets = np.zeros(nways + 1, dtype=np.int64)
    np.cumsum(lengths, out=offsets[1:])
    pos_way = np.repeat(np.arange(nways, dtype=np.int32), lengths)

    # Nodes: way endpoints plus any OSM node used more than once.
    _, inverse, counts = np.unique(m["node_ids"], return_inverse=True, return_counts=True)
    is_node = counts[inverse] > 1
    is_node[offsets[:-1]] = True
    is_node[offsets[1:] - 1] = True
    node_pos = np.flatnonzero(is_node)
    osm_index = inverse[node_pos]
    uniq_osm, node_of_flagged = np.unique(osm_index, return_inverse=True)
    n_nodes = len(uniq_osm)
    first_pos = np.zeros(n_nodes, dtype=np.int64)
    first_pos[node_of_flagged[::-1]] = node_pos[::-1]
    del inverse, counts, is_node

    lat = m["lat"]
    lon = m["lon"]
    latd = lat * FIXED
    lond = lon * FIXED
    seg = haversine(latd[:-1], lond[:-1], latd[1:], lond[1:])
    cum = np.zeros(npos, dtype=np.float64)
    np.cumsum(seg, out=cum[1:])
    del seg, latd, lond

    # Edges join consecutive nodes within the same way.
    same_way = pos_way[node_pos[:-1]] == pos_way[node_pos[1:]]
    pstart = node_pos[:-1][same_way]
    pend = node_pos[1:][same_way]
    src = node_of_flagged[:-1][same_way].astype(np.int32)
    dst = node_of_flagged[1:][same_way].astype(np.int32)
    loop = src == dst
    pstart, pend, src, dst = pstart[~loop], pend[~loop], src[~loop], dst[~loop]
    edge_way = pos_way[pstart]
    edge_len = (cum[pend] - cum[pstart]).astype(np.float32)
    n_edges = len(src)
    del cum, pos_way

    # Edges passing through (or ending at) a blocking barrier are closed to the blocked profiles.
    pos_block = np.zeros(npos, dtype=np.uint8)
    if len(m["barrier_ids"]):
        idx = np.minimum(np.searchsorted(m["barrier_ids"], m["node_ids"]), len(m["barrier_ids"]) - 1)
        hit = m["barrier_ids"][idx] == m["node_ids"]
        pos_block[hit] = m["barrier_block"][idx[hit]]
    edge_block = np.zeros(n_edges, dtype=np.uint8)
    for bit in (1, 2):
        c = np.zeros(npos + 1, dtype=np.int64)
        np.cumsum((pos_block & bit) != 0, out=c[1:])
        edge_block |= np.where(c[pend + 1] - c[pstart] > 0, bit, 0).astype(np.uint8)
    del pos_block

    # Directed adjacency in CSR form.
    ow = m["oneway"][edge_way]
    e = np.arange(n_edges, dtype=np.int64)
    fwd = ow != -1
    bwd = ow != 1
    frm = np.concatenate([src[fwd], dst[bwd]])
    to = np.concatenate([dst[fwd], src[bwd]])
    code = np.concatenate([e[fwd] * 2, e[bwd] * 2 + 1]).astype(np.int32)
    order = np.argsort(frm, kind="stable")
    csr_to = to[order]
    csr_code = code[order]
    csr_off = np.zeros(n_nodes + 1, dtype=np.int64)
    np.cumsum(np.bincount(frm, minlength=n_nodes), out=csr_off[1:])
    del frm, to, code, order

    # Spatial grid over all positions for snapping clicks to the nearest road.
    lat0 = int(np.floor(lat.min() * FIXED / GRID_DEG))
    lon0 = int(np.floor(lon.min() * FIXED / GRID_DEG))
    gy = (np.floor(lat * FIXED / GRID_DEG).astype(np.int64) - lat0)
    gx = (np.floor(lon * FIXED / GRID_DEG).astype(np.int64) - lon0)
    ny, nx = int(gy.max()) + 1, int(gx.max()) + 1
    cell = gy * nx + gx
    grid_perm = np.argsort(cell, kind="stable").astype(np.int32)
    grid_start = np.zeros(ny * nx + 1, dtype=np.int64)
    np.cumsum(np.bincount(cell, minlength=ny * nx), out=grid_start[1:])
    del cell, gx, gy

    arrays = {
        "lat": lat, "lon": lon,
        "node_lat": lat[first_pos], "node_lon": lon[first_pos],
        "edge_src": src, "edge_dst": dst, "edge_way": edge_way.astype(np.int32),
        "edge_pstart": pstart.astype(np.int64), "edge_pend": pend.astype(np.int64),
        "edge_len": edge_len, "edge_block": edge_block,
        "csr_off": csr_off, "csr_to": csr_to, "csr_code": csr_code,
        "grid_perm": grid_perm, "grid_start": grid_start,
        **{f"way_{k}": m[k] for k in WAY_ARRAYS},
    }

    out = graph_dir(regions)
    tmp = out + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for k, v in arrays.items():
        np.save(os.path.join(tmp, f"{k}.npy"), v)
    meta = _sources_meta(regions)
    meta.update({
        "grid": {"lat0": lat0, "lon0": lon0, "ny": ny, "nx": nx, "deg": GRID_DEG},
        "bbox": [float(lat.min() * FIXED), float(lon.min() * FIXED),
                 float(lat.max() * FIXED), float(lon.max() * FIXED)],
        "counts": {"ways": nways, "positions": npos, "nodes": n_nodes, "edges": n_edges,
                   "blocked_edges": int((edge_block != 0).sum())},
    })
    with open(os.path.join(tmp, "meta.json"), "w") as f:
        json.dump(meta, f)
    with open(os.path.join(tmp, "names.json"), "w") as f:
        json.dump(names, f)
    n_places = places.build([(r, ways_path(r)) for r in regions], os.path.join(tmp, "places.json"))
    shutil.rmtree(out, ignore_errors=True)
    os.replace(tmp, out)
    print(f"  graph: {n_nodes:,} nodes, {n_edges:,} edges from {nways:,} ways, "
          f"{n_places:,} places in {time.time() - t0:.0f}s")
    return out


class Graph:
    """Read-only view of a built graph; large arrays are memory-mapped."""

    def __init__(self, regions):
        d = graph_dir(regions)
        with open(os.path.join(d, "meta.json")) as f:
            self.meta = json.load(f)
        with open(os.path.join(d, "names.json")) as f:
            self.names = json.load(f)
        for fn in os.listdir(d):
            if fn.endswith(".npy"):
                setattr(self, fn[:-4], np.load(os.path.join(d, fn), mmap_mode="r"))
        # Small, hot arrays go fully into RAM.
        for k in ["csr_off", "csr_to", "csr_code", "node_lat", "node_lon", "edge_len", "edge_way", "edge_block",
                  *[f"way_{k}" for k in WAY_ARRAYS]]:
            setattr(self, k, np.ascontiguousarray(getattr(self, k)))
        self.grid = self.meta["grid"]
        self.bbox = self.meta["bbox"]
        self.regions = self.meta["regions"]
        self.places = places.PlaceIndex(os.path.join(d, "places.json"))
