"""Parse a state's .osm.pbf into a compact per-state way cache (data/ways/<state>.npz).

The cache keeps every routable way's node IDs and coordinates plus its categorical attributes.
Splitting into a routing graph happens later in graph.py, after states are merged, so ways that
cross state lines join up correctly.
"""
import json
import os
import time
from array import array

import numpy as np
import osmium

from . import tags as T
from .paths import pbf_path, ways_path


def _cache_meta(region):
    st = os.stat(pbf_path(region))
    return {"pbf_size": st.st_size, "pbf_mtime": int(st.st_mtime), "parse_version": T.PARSE_VERSION}


def is_fresh(region):
    path = ways_path(region)
    if not os.path.exists(path) or not os.path.exists(pbf_path(region)):
        return False
    with np.load(path) as z:
        return json.loads(bytes(z["meta"]).decode()) == _cache_meta(region)


def parse(region):
    src = pbf_path(region)
    t0 = time.time()

    way_ids = array("q")
    offsets = array("q", [0])
    node_ids = array("q")
    lats = array("i")
    lons = array("i")
    attrs = array("b")  # 5 bytes per way: road_class, surface, rough, legal, oneway
    detail = array("H")
    name_idx = array("i")
    names, name_lookup = [], {}

    place_name_idx = array("i")
    place_type = array("b")
    place_lat = array("i")
    place_lon = array("i")
    place_pop = array("i")
    barrier_ids = array("q")
    barrier_block = array("B")
    fuel = []  # [lat, lon, name, brand, hours, diesel]
    pois = []  # [lat, lon, category, kind, name, details]

    # All nodes still feed the location cache; these C++-side filters only trim what reaches
    # Python: ways need a highway tag (or one that marks a gas station, campground, mine etc.
    # drawn as an outline), nodes must be a searchable place, a barrier or a point of interest.
    fp = (osmium.FileProcessor(src, osmium.osm.NODE | osmium.osm.WAY)
          .with_locations("flex_mem")
          .with_filter(osmium.filter.KeyFilter("highway", "amenity", *T.POI_WAY_KEYS).enable_for(osmium.osm.WAY))
          .with_filter(osmium.filter.TagFilter(*T.PLACE_TAGS, *T.BARRIER_TAGS, T.FUEL_TAG, *T.POI_NODE_TAGS)
                       .enable_for(osmium.osm.NODE)))

    def intern(name):
        idx = name_lookup.get(name)
        if idx is None:
            idx = name_lookup[name] = len(names)
            names.append(name)
        return idx

    count = 0
    for w in fp:
        is_fuel = w.tags.get("amenity") == "fuel"
        if w.is_node():
            if is_fuel and w.location.valid():
                fuel.append([round(w.location.lat, 6), round(w.location.lon, 6), *T.fuel_info(w.tags)])
            poi = T.poi_info(w.tags)
            if poi and w.location.valid():
                pois.append([round(w.location.lat, 6), round(w.location.lon, 6), *poi])
            blocked = T.barrier_blocks(w.tags)
            if blocked:
                barrier_ids.append(w.id)
                barrier_block.append(blocked)
            kind = T.place_type(w.tags)
            name = T.place_name(w.tags)
            if kind is None or not name or not w.location.valid():
                continue
            place_name_idx.append(intern(name))
            place_type.append(kind)
            place_lat.append(w.location.y)
            place_lon.append(w.location.x)
            try:
                place_pop.append(min(int(w.tags.get("population", "0").replace(",", "")), 2**31 - 1))
            except ValueError:
                place_pop.append(0)
            continue
        poi = T.poi_info(w.tags) if w.tags.get("highway") in (None, "trailhead") else None
        if is_fuel or poi:  # an outline: keep its centre
            pts = [(n.location.lat, n.location.lon) for n in w.nodes if n.location.valid()]
            if pts:
                centre = [round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)]
                if is_fuel:
                    fuel.append([*centre, *T.fuel_info(w.tags)])
                if poi:
                    pois.append([*centre, *poi])
                # Hotels and the like are often drawn as building outlines; make those searchable too.
                kind, name = T.place_type(w.tags), T.place_name(w.tags)
                if kind is not None and name:
                    place_name_idx.append(intern(name))
                    place_type.append(kind)
                    place_lat.append(round(centre[0] * 1e7))
                    place_lon.append(round(centre[1] * 1e7))
                    place_pop.append(0)
        info = T.classify(w.tags)
        if info is None:
            continue
        refs, la, lo = [], [], []
        for n in w.nodes:
            loc = n.location
            if not loc.valid():
                continue
            refs.append(n.ref)
            la.append(loc.y)  # fixed-point, 1e-7 degrees
            lo.append(loc.x)
        if len(refs) < 2:
            continue
        way_ids.append(w.id)
        node_ids.extend(refs)
        lats.extend(la)
        lons.extend(lo)
        offsets.append(len(node_ids))
        attrs.extend(info)
        detail.append(T.detail_code(w.tags))
        name = T.display_name(w.tags)
        name_idx.append(intern(name) if name else -1)
        count += 1
        if count % 200_000 == 0:
            print(f"    {region}: {count:,} ways ...", flush=True)

    out = ways_path(region)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    a = np.frombuffer(attrs, dtype=np.int8).reshape(-1, 5)
    tmp = out + ".tmp.npz"
    np.savez(
        tmp,
        way_ids=np.frombuffer(way_ids, dtype=np.int64),
        offsets=np.frombuffer(offsets, dtype=np.int64),
        node_ids=np.frombuffer(node_ids, dtype=np.int64),
        lat=np.frombuffer(lats, dtype=np.int32),
        lon=np.frombuffer(lons, dtype=np.int32),
        road_class=a[:, 0].astype(np.uint8),
        surface=a[:, 1].astype(np.uint8),
        rough=a[:, 2].astype(np.uint8),
        legal=a[:, 3].astype(np.uint8),
        oneway=a[:, 4].copy(),
        detail=np.frombuffer(detail, dtype=np.uint16),
        name_idx=np.frombuffer(name_idx, dtype=np.int32),
        place_name_idx=np.frombuffer(place_name_idx, dtype=np.int32),
        place_type=np.frombuffer(place_type, dtype=np.int8),
        place_lat=np.frombuffer(place_lat, dtype=np.int32),
        place_lon=np.frombuffer(place_lon, dtype=np.int32),
        place_pop=np.frombuffer(place_pop, dtype=np.int32),
        barrier_ids=np.frombuffer(barrier_ids, dtype=np.int64),
        barrier_block=np.frombuffer(barrier_block, dtype=np.uint8),
        names=np.frombuffer(json.dumps(names).encode(), dtype=np.uint8),
        fuel=np.frombuffer(json.dumps(fuel).encode(), dtype=np.uint8),
        pois=np.frombuffer(json.dumps(pois).encode(), dtype=np.uint8),
        meta=np.frombuffer(json.dumps(_cache_meta(region)).encode(), dtype=np.uint8),
    )
    os.replace(tmp, out)
    print(f"  {region}: {count:,} routable ways, {len(node_ids):,} points, "
          f"{len(place_type):,} places, {len(barrier_ids):,} barriers, {len(fuel):,} gas stations, "
          f"{len(pois):,} points of interest in {time.time() - t0:.0f}s")
    return out
