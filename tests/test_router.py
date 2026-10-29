import heapq
import json
import os

import numpy as np
import pytest

from gravelmaps import graph as G
from gravelmaps import profiles as P
from gravelmaps import router as R
from gravelmaps import tags as T


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ways_path", lambda r: str(tmp_path / f"{r}.npz"))
    monkeypatch.setattr(G, "graph_dir", lambda regions: str(tmp_path / ("g_" + "_".join(sorted(regions)))))
    return tmp_path


def write_ways(path, ways, barriers=()):
    """ways: list of (way_id, [(node_id, lat, lon), ...], tags); barriers: [(node_id, tags)]."""
    offsets, nids, lats, lons, attrs, name_idx, names = [0], [], [], [], [], [], []
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
        name = T.display_name(tags)
        name_idx.append(len(names) if name else -1)
        if name:
            names.append(name)
    a = np.array(attrs, dtype=np.int8)
    np.savez(path, way_ids=np.array(kept, dtype=np.int64), offsets=np.array(offsets, dtype=np.int64),
             node_ids=np.array(nids, dtype=np.int64), lat=np.array(lats, dtype=np.int32),
             lon=np.array(lons, dtype=np.int32), road_class=a[:, 0].astype(np.uint8),
             surface=a[:, 1].astype(np.uint8), rough=a[:, 2].astype(np.uint8),
             legal=a[:, 3].astype(np.uint8), oneway=a[:, 4],
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


def dijkstra(off, to, w, src):
    dist = np.full(len(off) - 1, np.inf)
    dist[src] = 0
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for e in range(off[u], off[u + 1]):
            nd = d + w[e]
            if nd < dist[to[e]]:
                dist[to[e]] = nd
                heapq.heappush(pq, (nd, to[e]))
    return dist


def test_astar_matches_dijkstra(data_dir):
    rng = np.random.default_rng(1)
    kinds = [{"highway": "track"}, {"highway": "primary"}, {"highway": "unclassified"},
             {"highway": "secondary", "surface": "gravel"}, {"highway": "residential"}]
    n = 12
    nid = lambda i, j: i * n + j + 1
    pt = lambda i, j: (nid(i, j), 39 + i * 0.01 + rng.uniform(-0.002, 0.002), -117 + j * 0.01)
    pts = {(i, j): pt(i, j) for i in range(n) for j in range(n)}
    ways, wid = [], 1
    for i in range(n):
        for j in range(n):
            for di, dj in ((0, 1), (1, 0)):
                if i + di < n and j + dj < n and rng.random() < 0.85:
                    ways.append((wid, [pts[i, j], pts[i + di, j + dj]], kinds[rng.integers(len(kinds))]))
                    wid += 1
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    g = r.g
    w, hscale = r.weights.get("car", P.parse_values("mostly"))
    for src in rng.integers(0, len(g.csr_off) - 1, 8):
        ref = dijkstra(g.csr_off, g.csr_to, w, int(src))
        for dst in rng.integers(0, len(g.csr_off) - 1, 8):
            cost, k, entries, _ = R._astar(
                g.csr_off, g.csr_to, w, g.node_lat, g.node_lon,
                np.array([src], dtype=np.int64), np.array([0], dtype=np.float32),
                np.array([dst], dtype=np.int64), np.array([0], dtype=np.float32), hscale * 0.995)
            assert cost == pytest.approx(ref[dst], rel=1e-5) if np.isfinite(ref[dst]) else not np.isfinite(cost)
            if np.isfinite(cost) and len(entries):
                assert float(w[entries].sum()) == pytest.approx(cost, rel=1e-5)


def test_cross_state_merge(data_dir):
    a = [(1, [(1, 40.0, -118.0), (2, 40.0, -117.99), (3, 40.0, -117.98)], {"highway": "track"}),
         (2, [(3, 40.0, -117.98), (4, 40.0, -117.97)], {"highway": "track", "name": "Border Rd"})]
    b = [(2, [(3, 40.0, -117.98), (4, 40.0, -117.97)], {"highway": "track", "name": "Border Rd"}),
         (3, [(4, 40.0, -117.97), (5, 40.0, -117.96)], {"highway": "track"})]
    write_ways(data_dir / "a.npz", a)
    write_ways(data_dir / "b.npz", b)
    r = make_router(["a", "b"])
    assert r.g.meta["counts"]["ways"] == 3
    res = r.route([(40.0001, -117.999), (40.0001, -117.961)])
    assert res["summary"]["distance_m"] == pytest.approx(haversine_m(-117.999, -117.961), rel=0.01)
    assert any(s["name"] == "Border Rd" for s in res["steps"])


def haversine_m(lon1, lon2, lat=40.0):
    return float(G.haversine(np.array([lat]), np.array([lon1]), np.array([lat]), np.array([lon2]))[0])


def test_presets_choose_dirt_or_highway(data_dir):
    # Straight primary road vs. a longer dirt detour to the north.
    ways = [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.9)], {"highway": "primary", "name": "Hwy"}),
        (2, [(1, 40.0, -118.0), (3, 40.03, -117.95), (2, 40.0, -117.9)], {"highway": "track", "name": "Dirt"}),
    ]
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    pts = [(40.0, -118.0), (40.0, -117.9)]
    assert {s["name"] for s in r.route(pts, legs=["mostly"])["steps"]} == {"Dirt"}
    assert {s["name"] for s in r.route(pts, legs=["highway"])["steps"]} == {"Hwy"}
    # all-neutral sliders = fastest route, which is the highway
    assert {s["name"] for s in r.route(pts, legs=[[50] * 7])["steps"]} == {"Hwy"}


def test_per_leg_settings(data_dir):
    ways = [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.9), (5, 40.0, -117.8)], {"highway": "primary", "name": "Hwy"}),
        (2, [(1, 40.0, -118.0), (3, 40.03, -117.95), (2, 40.0, -117.9)], {"highway": "track", "name": "Dirt1"}),
        (3, [(2, 40.0, -117.9), (4, 40.03, -117.85), (5, 40.0, -117.8)], {"highway": "track", "name": "Dirt2"}),
    ]
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    res = r.route([(40.0, -118.0), (40.0, -117.9), (40.0, -117.8)], legs=["highway", "dirt"])
    by_leg = {}
    for f in res["features"]:
        by_leg.setdefault(f["properties"]["leg"], set()).add(f["properties"]["name"])
    assert by_leg == {0: {"Hwy"}, 1: {"Dirt2"}}
    assert len(res["legs"]) == 2 and all(leg["distance_m"] > 0 for leg in res["legs"])


def test_never_slider_excludes_kind(data_dir):
    ways = [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.9)], {"highway": "track", "tracktype": "grade5", "name": "Rough"}),
        (2, [(1, 40.0, -118.0), (3, 40.05, -117.95), (2, 40.0, -117.9)], {"highway": "primary", "name": "Hwy"}),
    ]
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    pts = [(40.0, -118.0), (40.0, -117.9)]
    no_rough = list(P.PRESETS["dirt"]["values"])
    no_rough[P.ROUGH] = 0
    assert {s["name"] for s in r.route(pts, legs=["dirt"])["steps"]} == {"Rough"}
    assert {s["name"] for s in r.route(pts, legs=[no_rough])["steps"]} == {"Hwy"}


def test_moto_only_trail(data_dir):
    ways = [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.9)], {"highway": "path", "motorcycle": "yes", "name": "Trail"}),
        (2, [(1, 40.0, -118.0), (3, 40.2, -117.95), (2, 40.0, -117.9)], {"highway": "track", "name": "Dirt"}),
    ]
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    pts = [(40.0, -118.0), (40.0, -117.9)]
    assert {s["name"] for s in r.route(pts, "dualsport")["steps"]} == {"Trail"}
    assert {s["name"] for s in r.route(pts, "car")["steps"]} == {"Dirt"}


def test_oneway_respected(data_dir):
    ways = [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.9)], {"highway": "track", "oneway": "yes", "name": "OW"}),
        (2, [(2, 40.0, -117.9), (3, 40.05, -117.95), (1, 40.0, -118.0)], {"highway": "track", "name": "Back"}),
    ]
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    assert {s["name"] for s in r.route([(40.0, -118.0), (40.0, -117.9)])["steps"]} == {"OW"}
    assert {s["name"] for s in r.route([(40.0, -117.9), (40.0, -118.0)])["steps"]} == {"Back"}


def test_same_edge_partial(data_dir):
    ways = [(1, [(1, 40.0, -118.0), (2, 40.0, -117.9)], {"highway": "track", "name": "Long"})]
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    res = r.route([(40.0, -117.98), (40.0, -117.92)])
    assert res["summary"]["distance_m"] == pytest.approx(haversine_m(-117.98, -117.92), rel=0.01)
    res = r.route([(40.0, -117.92), (40.0, -117.98)])
    assert res["summary"]["distance_m"] == pytest.approx(haversine_m(-117.98, -117.92), rel=0.01)


def test_snaps_past_unreachable_island(data_dir, monkeypatch):
    monkeypatch.setattr(R, "MIN_COMPONENT", 3)
    ways = [
        # main network: a track with a spur (4 graph nodes)
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.99), (3, 40.0, -117.98)], {"highway": "track", "name": "Main"}),
        (2, [(2, 40.0, -117.99), (6, 39.99, -117.99)], {"highway": "track", "name": "Spur"}),
        # public street whose only link is a private road (which the parser drops)
        (3, [(4, 40.001, -117.975), (5, 40.002, -117.975)], {"highway": "residential", "name": "Island"}),
    ]
    write_ways(data_dir / "a.npz", ways)
    r = make_router(["a"])
    res = r.route([(40.0, -118.0), (40.002, -117.975)])
    assert {s["name"] for s in res["steps"]} == {"Main"}


def _gate_network(data_dir, gate_tags):
    ways = [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.95), (3, 40.0, -117.9)], {"highway": "track", "name": "Gated"}),
        (2, [(1, 40.0, -118.0), (4, 40.05, -117.95), (3, 40.0, -117.9)], {"highway": "track", "name": "Around"}),
    ]
    write_ways(data_dir / "a.npz", ways, barriers=[(2, gate_tags)])
    return make_router(["a"])


def test_locked_gate_forces_detour(data_dir):
    r = _gate_network(data_dir, {"barrier": "gate", "locked": "yes"})
    for profile in ("car", "dualsport"):
        assert {s["name"] for s in r.route([(40.0, -118.0), (40.0, -117.9)], profile)["steps"]} == {"Around"}


def test_open_gate_is_passable(data_dir):
    r = _gate_network(data_dir, {"barrier": "gate"})
    assert {s["name"] for s in r.route([(40.0, -118.0), (40.0, -117.9)])["steps"]} == {"Gated"}


def test_bollard_blocks_both(data_dir):
    r = _gate_network(data_dir, {"barrier": "bollard"})
    assert {s["name"] for s in r.route([(40.0, -118.0), (40.0, -117.9)], "car")["steps"]} == {"Around"}
    assert {s["name"] for s in r.route([(40.0, -118.0), (40.0, -117.9)], "dualsport")["steps"]} == {"Around"}
