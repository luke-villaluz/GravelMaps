import os

from helpers import write_ways

from gravelmaps import graph as G

TRACK = {"highway": "track"}


def test_ways_split_at_intersections(data_dir):
    # Two roads crossing at node 2 make five nodes and four edges.
    write_ways(data_dir / "a.npz", [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.99), (3, 40.0, -117.98)], TRACK),
        (2, [(4, 39.99, -117.99), (2, 40.0, -117.99), (5, 40.01, -117.99)], TRACK),
    ])
    G.build(["a"])
    g = G.Graph(["a"])
    assert g.meta["counts"]["nodes"] == 5
    assert g.meta["counts"]["edges"] == 4
    assert len(g.csr_to) == 8  # every edge can be driven both ways


def test_oneway_has_one_direction(data_dir):
    write_ways(data_dir / "a.npz", [
        (1, [(1, 40.0, -118.0), (2, 40.0, -117.99)], {"highway": "unclassified", "oneway": "yes"}),
        (2, [(2, 40.0, -117.99), (3, 40.0, -117.98)], TRACK),
    ])
    G.build(["a"])
    g = G.Graph(["a"])
    assert len(g.csr_to) == 3


def test_edge_length_is_great_circle_distance(data_dir):
    write_ways(data_dir / "a.npz", [(1, [(1, 40.0, -118.0), (2, 40.0, -117.99)], TRACK)])
    G.build(["a"])
    g = G.Graph(["a"])
    assert abs(float(g.edge_len[0]) - 852.0) < 2  # 0.01° of longitude at 40°N


def test_rebuild_when_a_state_changes(data_dir):
    path = data_dir / "a.npz"
    write_ways(path, [(1, [(1, 40.0, -118.0), (2, 40.0, -117.99)], TRACK)])
    assert not G.is_fresh(["a"])
    G.build(["a"])
    assert G.is_fresh(["a"])
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 60))
    assert not G.is_fresh(["a"])
