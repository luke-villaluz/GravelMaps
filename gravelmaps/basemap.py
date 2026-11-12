"""The offline street map: a Protomaps vector-tile extract covering the chosen states.

Protomaps publishes a daily OpenStreetMap basemap of the whole planet as one PMTiles file (~140 GB).
We read only what we need from it with HTTP range requests: its tile directory, then the tiles
over the area our routing graph covers. The result is a small PMTiles file of our own, served
tile by tile by the server (see LocalBasemap) and drawn in the browser by protomaps-leaflet.

Coverage follows the states' real shapes, not a bounding box: every zoom-11 tile (about 20 km
across) that contains a road from the graph, plus a ring of neighbours, gets all its tiles down to
zoom 15, and every tile above it at lower zooms. In PMTiles' Hilbert-curve tile ids all the
descendants of one tile at a given zoom are one contiguous id range, which keeps this cheap.

PMTiles format: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
"""
import gzip
import json
import mmap
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
import requests
from pmtiles.tile import Compression, deserialize_header, serialize_header, zxy_to_tileid

from . import USER_AGENT
from .graph import FIXED
from .paths import DATA, graph_dir

BUILDS = "https://build-metadata.protomaps.dev/builds.json"
SOURCE = "https://build.protomaps.com/{key}"
DIR = os.path.join(DATA, "basemap")

COVER_ZOOM = 11   # coverage is decided per tile at this zoom
MAX_ZOOM = 15     # the basemap's deepest zoom; the browser overzooms past it
DATA_START = 16384  # header and root directory must fit before this (spec), tile data follows
GAP = 64 << 10      # merge tile reads closer together than this into one request
CHUNK = 8 << 20     # but keep each request at most about this big
WORKERS = 8
ATTEMPTS = 6
LEAF_SIZE = 4096


# ---- varint directories, vectorised (the pmtiles package decodes these one entry at a time) ----

def _decode_varints(buf):
    a = np.frombuffer(buf, np.uint8)
    ends = np.flatnonzero(a < 128)
    starts = np.concatenate([[0], ends[:-1] + 1])
    shift = (np.arange(a.size) - np.repeat(starts, ends - starts + 1)).astype(np.uint64) * np.uint64(7)
    return np.add.reduceat((a & 127).astype(np.uint64) << shift, starts)


def _encode_varints(v):
    v = np.asarray(v, np.uint64)
    nbytes = np.maximum(1, (np.floor(np.log2(np.maximum(v, 1).astype(np.float64))).astype(np.int64) // 7) + 1)
    nbytes[v == 0] = 1
    idx = np.repeat(np.arange(v.size), nbytes)
    k = (np.arange(idx.size) - np.repeat(np.cumsum(nbytes) - nbytes, nbytes)).astype(np.uint64)
    out = ((v[idx] >> (k * np.uint64(7))) & np.uint64(127)).astype(np.uint8)
    out[k < (nbytes[idx] - 1).astype(np.uint64)] |= 128
    return out.tobytes()


def decode_directory(buf):
    """Gzipped directory bytes -> (tile_id, run_length, length, offset) int64 arrays."""
    v = _decode_varints(gzip.decompress(buf)).astype(np.int64)
    n = int(v[0])
    ids = np.cumsum(v[1:1 + n])
    run, length, raw = v[1 + n:1 + 2 * n], v[1 + 2 * n:1 + 3 * n], v[1 + 3 * n:1 + 4 * n]
    # An offset of 0 means "right after the previous entry"; anything else is offset + 1.
    anchor = raw > 0
    anchor[0] = True
    before = np.concatenate([[0], np.cumsum(length)[:-1]])  # total length of the entries before each one
    last = np.maximum.accumulate(np.where(anchor, np.arange(n), 0))
    offset = (raw[last] - 1) + before - before[last]
    return ids, run, length, offset


def encode_directory(ids, run, length, offset):
    n = len(ids)
    contiguous = np.zeros(n, bool)
    contiguous[1:] = offset[1:] == offset[:-1] + length[:-1]
    raw = np.where(contiguous, 0, offset + 1)
    deltas = np.diff(np.concatenate([[0], ids]))
    body = _encode_varints(np.concatenate([[n], deltas, run, length, raw]).astype(np.uint64))
    return gzip.compress(body, mtime=0)


def _directories(ids, run, length, offset, max_root):
    """(root bytes, leaves bytes), splitting into leaf directories when the root would be too big."""
    root = encode_directory(ids, run, length, offset)
    if len(root) <= max_root:
        return root, b""
    size = LEAF_SIZE
    while True:
        leaves, rid, rlen, roff = [], [], [], []
        pos = 0
        for i in range(0, len(ids), size):
            s = slice(i, i + size)
            leaf = encode_directory(ids[s], run[s], length[s], offset[s])
            rid.append(ids[i])
            roff.append(pos)
            rlen.append(len(leaf))
            leaves.append(leaf)
            pos += len(leaf)
        root = encode_directory(np.array(rid), np.zeros(len(rid), np.int64), np.array(rlen), np.array(roff))
        if len(root) <= max_root:
            return root, b"".join(leaves)
        size *= 2


# ---- which tiles we want ---------------------------------------------------------------------

def _tile_xy(lat, lon, z):
    n = 2 ** z
    x = np.floor((lon + 180) / 360 * n)
    r = np.radians(np.clip(lat, -85.05, 85.05))
    y = np.floor((1 - np.log(np.tan(r) + 1 / np.cos(r)) / np.pi) / 2 * n)
    return np.clip(x, 0, n - 1).astype(np.int64), np.clip(y, 0, n - 1).astype(np.int64)


def cover_tiles(lat, lon):
    """Unique zoom-COVER_ZOOM tiles (x, y) around the given points, each with a one-tile margin."""
    x, y = _tile_xy(np.asarray(lat, np.float64), np.asarray(lon, np.float64), COVER_ZOOM)
    n = 2 ** COVER_ZOOM
    xy = np.unique(np.column_stack([x, y]), axis=0)
    rings = [np.column_stack([np.clip(xy[:, 0] + dx, 0, n - 1), np.clip(xy[:, 1] + dy, 0, n - 1)])
             for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
    return np.unique(np.concatenate(rings), axis=0)


def wanted_ranges(cover, max_zoom=MAX_ZOOM):
    """Merged, sorted [start, end) tile-id ranges for the cover tiles' ancestors and descendants."""
    starts, ends = [], []
    for z in range(COVER_ZOOM):
        for x, y in np.unique(cover >> (COVER_ZOOM - z), axis=0):
            t = zxy_to_tileid(z, int(x), int(y))
            starts.append(t)
            ends.append(t + 1)
    for z in range(COVER_ZOOM, max_zoom + 1):
        d = z - COVER_ZOOM
        side = (1 << d) - 1
        for x, y in cover:
            x0, y0 = int(x) << d, int(y) << d
            # A Hilbert curve enters every sub-square at one of its corners, so the smallest corner
            # id starts the contiguous range of all 4^d descendants.
            t = min(zxy_to_tileid(z, x0 + a, y0 + b) for a in (0, side) for b in (0, side))
            starts.append(t)
            ends.append(t + 4 ** d)
    order = np.argsort(starts)
    s, e = np.array(starts, np.int64)[order], np.array(ends, np.int64)[order]
    # Merge overlapping and touching ranges.
    reach = np.maximum.accumulate(e)
    new = np.concatenate([[True], s[1:] > reach[:-1]])
    return s[new], np.maximum.reduceat(e, np.flatnonzero(new))


def _overlaps(a, b, rs, re):
    """Mask of [a, b) intervals that intersect any of the merged ranges [rs, re)."""
    i = np.searchsorted(re, a, side="right")
    ok = i < len(rs)
    out = np.zeros(len(a), bool)
    out[ok] = rs[i[ok]] < b[ok]
    return out


def _clip(ids, run, length, offset, rs, re):
    """Keep only the parts of tile entries (runs included) inside the wanted ranges."""
    keep = _overlaps(ids, ids + np.maximum(run, 1), rs, re)
    ids, run, length, offset = ids[keep], run[keep], length[keep], offset[keep]
    single = run == 1
    inside = single.copy()
    if single.any():
        i = np.searchsorted(re, ids[single], side="right")
        ok = i < len(rs)
        inside_s = np.zeros(single.sum(), bool)
        inside_s[ok] = rs[i[ok]] <= ids[single][ok]
        inside[single] = inside_s
    parts = [(ids[inside], run[inside], length[inside], offset[inside])]
    # Runs (the same tile repeated, mostly open ocean) may only partly overlap: split them.
    for k in np.flatnonzero(run > 1):
        a, b = ids[k], ids[k] + run[k]
        j = np.searchsorted(re, a, side="right")
        cut = []
        while j < len(rs) and rs[j] < b:
            lo, hi = max(a, rs[j]), min(b, re[j])
            cut.append((lo, hi - lo))
            j += 1
        if cut:
            c = np.array(cut, np.int64)
            parts.append((c[:, 0], c[:, 1], np.full(len(c), length[k]), np.full(len(c), offset[k])))
    return tuple(np.concatenate([p[i] for p in parts]) for i in range(4))


# ---- remote reads ----------------------------------------------------------------------------

class Remote:
    def __init__(self, url):
        self.url = url
        self.local = threading.local()

    def _session(self):
        if not hasattr(self.local, "s"):
            self.local.s = requests.Session()
            self.local.s.headers["User-Agent"] = USER_AGENT
        return self.local.s

    def get(self, offset, length):
        for attempt in range(1, ATTEMPTS + 1):
            try:
                r = self._session().get(self.url, timeout=60,
                                        headers={"Range": f"bytes={offset}-{offset + length - 1}"})
                r.raise_for_status()
                if r.status_code != 206 or len(r.content) != length:
                    raise requests.RequestException(f"short read ({len(r.content)} of {length} bytes)")
                return r.content
            except requests.RequestException:
                if attempt == ATTEMPTS:
                    raise
                time.sleep(2 * attempt)


def latest_source():
    r = requests.get(BUILDS, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return SOURCE.format(key=sorted(b["key"] for b in r.json() if b["key"].endswith(".pmtiles"))[-1])


# ---- planning and downloading ----------------------------------------------------------------

def _graph_points(regions):
    d = graph_dir(regions)
    lat = np.load(os.path.join(d, "node_lat.npy"), mmap_mode="r")
    lon = np.load(os.path.join(d, "node_lon.npy"), mmap_mode="r")
    return np.asarray(lat, np.float64) * FIXED, np.asarray(lon, np.float64) * FIXED


def plan(regions, source=None):
    """Work out which tiles to fetch. Only directories are downloaded (a few MB)."""
    source = source or latest_source()
    remote = Remote(source)
    header = deserialize_header(remote.get(0, 127))
    lat, lon = _graph_points(regions)
    cover = cover_tiles(lat, lon)
    rs, re = wanted_ranges(cover)

    found = []
    todo = [decode_directory(remote.get(header["root_offset"], header["root_length"]))]
    while todo:
        ids, run, length, offset = todo.pop()
        is_leaf = run == 0
        if (~is_leaf).any():
            found.append(_clip(ids[~is_leaf], run[~is_leaf], length[~is_leaf], offset[~is_leaf], rs, re))
        if is_leaf.any():
            # A leaf directory holds the ids from its own first id up to the next entry's.
            nxt = np.concatenate([ids[1:], [np.iinfo(np.int64).max]])
            sel = is_leaf & _overlaps(ids, nxt, rs, re)
            base = header["leaf_directory_offset"]
            reads = [(base + o, n) for o, n in zip(offset[sel].tolist(), length[sel].tolist())]
            with ThreadPoolExecutor(WORKERS) as pool:
                todo.extend(pool.map(lambda r: decode_directory(remote.get(*r)), reads))
    ids, run, length, offset = (np.concatenate([f[i] for f in found]) for i in range(4))
    order = np.argsort(ids, kind="stable")
    ids, run, length, offset = ids[order], run[order], length[order], offset[order]

    uniq_off, first = np.unique(offset, return_index=True)
    uniq_len = length[first]
    lo = lat.min(), lon.min()
    hi = lat.max(), lon.max()
    return {
        "source": source, "header": header, "cover": cover,
        "entries": (ids, run, length, offset),
        "tiles": (uniq_off, uniq_len),
        "bytes": int(uniq_len.sum()),
        "bounds": (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])),
    }


def _chunks(off, length):
    """Group sorted tile reads into ranged requests: [(first tile, end tile, start byte, end byte)]."""
    end = off + length
    out, i, n = [], 0, len(off)
    while i < n:
        j = i + 1
        while j < n and off[j] - end[j - 1] <= GAP and end[j] - off[i] <= CHUNK:
            j += 1
        out.append((i, j, int(off[i]), int(end[j - 1])))
        i = j
    return out


def path_for(regions):
    return os.path.join(DIR, os.path.basename(graph_dir(regions)) + ".pmtiles")


def is_built(regions):
    return os.path.exists(path_for(regions))


def build(regions, progress=None, source=None):
    """Download the basemap for `regions` into data/basemap/. Resumes an interrupted download."""
    progress = progress or (lambda done, total: None)
    p = plan(regions, source)
    header, data_base = p["header"], p["header"]["tile_data_offset"]
    uniq_off, uniq_len = p["tiles"]
    new_off = np.concatenate([[0], np.cumsum(uniq_len)[:-1]])  # tiles are packed in source order
    chunks = _chunks(uniq_off, uniq_len)
    total = p["bytes"]

    os.makedirs(DIR, exist_ok=True)
    out = path_for(regions)
    part, state = out + ".part", out + ".part.json"
    sig = {"source": p["source"], "tiles": len(uniq_off), "bytes": total}
    done_chunks = 0
    if os.path.exists(part) and os.path.exists(state):
        with open(state) as f:
            saved = json.load(f)
        if saved.get("sig") == sig:
            done_chunks = saved["chunks"]
    with open(part, "r+b" if done_chunks else "wb") as f:
        pos = DATA_START + (int(new_off[chunks[done_chunks][0]]) if done_chunks < len(chunks) else total)
        f.truncate(pos)
        f.seek(pos)
        written = pos - DATA_START
        progress(written, total)
        remote = Remote(p["source"])
        with ThreadPoolExecutor(WORKERS) as pool:
            # Keep a bounded window of requests in flight and write them back in order.
            window = []
            for k in range(done_chunks, len(chunks)):
                c = chunks[k]
                window.append((k, pool.submit(remote.get, data_base + c[2], c[3] - c[2])))
                if len(window) >= WORKERS * 2:
                    written = _write_next(f, window, chunks, uniq_off, uniq_len, written, total, progress, state, sig)
            while window:
                written = _write_next(f, window, chunks, uniq_off, uniq_len, written, total, progress, state, sig)

        ids, run, length, offset = p["entries"]
        offset = new_off[np.searchsorted(uniq_off, offset)]
        root, leaves = _directories(ids, run, length, offset, DATA_START - 127)
        meta = {}
        try:
            raw = remote.get(header["metadata_offset"], header["metadata_length"])
            meta = json.loads(gzip.decompress(raw) if header["internal_compression"] == Compression.GZIP else raw)
        except (ValueError, OSError, requests.RequestException):
            pass  # the metadata is informational; the tiles are what matter
        meta["gravelmaps"] = {"source": p["source"], "regions": regions, "max_zoom": MAX_ZOOM}
        meta_bytes = gzip.compress(json.dumps(meta).encode(), mtime=0)

        f.seek(DATA_START + total)
        f.write(meta_bytes)
        f.write(leaves)
        s, w, n, e = p["bounds"]
        h = dict(header)
        h.update({
            "root_offset": 127, "root_length": len(root),
            "metadata_offset": DATA_START + total, "metadata_length": len(meta_bytes),
            "leaf_directory_offset": DATA_START + total + len(meta_bytes), "leaf_directory_length": len(leaves),
            "tile_data_offset": DATA_START, "tile_data_length": total,
            "addressed_tiles_count": int(run.sum()), "tile_entries_count": len(ids),
            "tile_contents_count": len(uniq_off), "clustered": True, "internal_compression": Compression.GZIP,
            "min_zoom": 0, "max_zoom": MAX_ZOOM,
            "min_lon_e7": int(w * 1e7), "min_lat_e7": int(s * 1e7),
            "max_lon_e7": int(e * 1e7), "max_lat_e7": int(n * 1e7),
            "center_zoom": 7, "center_lon_e7": int((w + e) / 2 * 1e7), "center_lat_e7": int((s + n) / 2 * 1e7),
        })
        f.seek(0)
        f.write(serialize_header(h))
        f.write(root)
    os.replace(part, out)
    if os.path.exists(state):
        os.remove(state)
    # Basemaps for other state choices are kept: switching back is then instant.
    return out


def _write_next(f, window, chunks, uniq_off, uniq_len, written, total, progress, state, sig):
    k, fut = window.pop(0)
    i, j, start, _ = chunks[k]
    buf = fut.result()
    for t in range(i, j):
        a = int(uniq_off[t]) - start
        f.write(buf[a:a + int(uniq_len[t])])
    written += int(uniq_len[i:j].sum())
    progress(written, total)
    if k % 20 == 0 or k == len(chunks) - 1:
        f.flush()
        with open(state, "w") as s:
            json.dump({"sig": sig, "chunks": k + 1}, s)
    return written


# ---- serving ---------------------------------------------------------------------------------

class LocalBasemap:
    """Reads tiles out of our own PMTiles file."""

    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.header = deserialize_header(self.mm[:127])
        h = self.header
        self.root = decode_directory(self.mm[h["root_offset"]:h["root_offset"] + h["root_length"]])
        self.leaf = lru_cache(maxsize=256)(self._leaf)

    def _leaf(self, offset, length):
        base = self.header["leaf_directory_offset"] + offset
        return decode_directory(self.mm[base:base + length])

    def get(self, z, x, y):
        """Raw (gzip-compressed) vector tile bytes, or None."""
        if z > self.header["max_zoom"] or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
            return None
        tid = zxy_to_tileid(z, x, y)
        ids, run, length, offset = self.root
        for _ in range(4):
            i = int(np.searchsorted(ids, tid, side="right")) - 1
            if i < 0:
                return None
            if run[i] == 0:
                ids, run, length, offset = self.leaf(int(offset[i]), int(length[i]))
                continue
            if tid >= ids[i] + run[i]:
                return None
            a = self.header["tile_data_offset"] + int(offset[i])
            return self.mm[a:a + int(length[i])]
        return None

    @property
    def gzipped(self):
        return self.header["tile_compression"] == Compression.GZIP

    def close(self):
        self.mm.close()
        self.f.close()
