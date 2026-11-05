"""Build tiny synthetic maps for tests: write way caches the way build.py does, then a graph."""
import json

import numpy as np

from gravelmaps import graph as G
from gravelmaps import router as R
from gravelmaps import tags as T


def write_ways(path, ways, barriers=()):
    """ways: list of (way_id, [(node_id, lat, lon), ...], tags); barriers: [(node_id, tags)]."""
    offsets, nids, lats, lons, attrs, name_idx, names, detail = [0], [], [], [], [], [], [], []
    kept = []
    for wid, pts, tags in ways:
        info = T.classify(tags)
        assert info is not None, tags
        kept.append(wid)
        for nid, la, lo in pts:
            nids.append(nid)
            lats.append(round(la * 1e7))
            lons.append(round(lo * 1e7))
        offsets.append(len(nids))
        attrs.append(info)
        detail.append(T.detail_code(tags))
        name = T.display_name(tags)
        name_idx.append(len(names) if name else -1)
        if name:
            names.append(name)
    a = np.array(attrs, dtype=np.int8)
    np.savez(path, way_ids=np.array(kept, dtype=np.int64), offsets=np.array(offsets, dtype=np.int64),
             node_ids=np.array(nids, dtype=np.int64), lat=np.array(lats, dtype=np.int32),
             lon=np.array(lons, dtype=np.int32), road_class=a[:, 0].astype(np.uint8),
             surface=a[:, 1].astype(np.uint8), rough=a[:, 2].astype(np.uint8),
             legal=a[:, 3].astype(np.uint8), oneway=a[:, 4], detail=np.array(detail, dtype=np.uint16),
             name_idx=np.array(name_idx, dtype=np.int32),
             place_name_idx=np.zeros(0, dtype=np.int32), place_type=np.zeros(0, dtype=np.int8),
             place_lat=np.zeros(0, dtype=np.int32), place_lon=np.zeros(0, dtype=np.int32),
             place_pop=np.zeros(0, dtype=np.int32),
             barrier_ids=np.array([b[0] for b in barriers], dtype=np.int64),
             barrier_block=np.array([T.barrier_blocks(b[1]) for b in barriers], dtype=np.uint8),
             names=np.frombuffer(json.dumps(names).encode(), dtype=np.uint8),
             meta=np.frombuffer(b"{}", dtype=np.uint8))


def make_router(regions):
    G.build(regions)
    return R.Router(G.Graph(regions))
