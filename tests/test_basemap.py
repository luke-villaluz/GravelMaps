"""The offline basemap: tile selection, the extract against a fake planet, and serving tiles."""
import gzip
import io

import numpy as np
import pytest
from pmtiles.tile import Compression, TileType, tileid_to_zxy, zxy_to_tileid
from pmtiles.writer import Writer

from gravelmaps import basemap as B

LAT, LON = 38.57, -109.55  # Moab


def make_planet(max_zoom=B.MAX_ZOOM, around=(LAT, LON), extra_ocean_run=True):
    """A small PMTiles 'planet': every tile within a few z11 tiles of `around`, plus one far-off tile
    and a run of identical 'ocean' tiles crossing the coverage edge. Returns (bytes, {tileid: data})."""
    cx, cy = B._tile_xy(np.array([around[0]]), np.array([around[1]]), B.COVER_ZOOM)
    cx, cy = int(cx[0]), int(cy[0])
    tiles = {}
    for z in range(max_zoom + 1):
        d = z - B.COVER_ZOOM
        if d < 0:
            x, y = cx >> -d, cy >> -d
            tiles[zxy_to_tileid(z, x, y)] = f"{z}/{x}/{y}".encode()
            continue
        for x in range((cx - 3) << d, (cx + 4) << d):
            for y in range((cy - 3) << d, (cy + 4) << d):
                tiles[zxy_to_tileid(z, x, y)] = f"{z}/{x}/{y}".encode()
    far = zxy_to_tileid(11, 10, 10)
    tiles[far] = b"far away"
    if extra_ocean_run:  # identical content: the writer stores these as one run entry
        for t in range(far + 1, far + 50):
            tiles[t] = b"ocean"
    buf = io.BytesIO()
    w = Writer(buf)
    for t in sorted(tiles):
        w.write_tile(t, gzip.compress(tiles[t], mtime=0))
    w.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
                "min_lon_e7": 0, "min_lat_e7": 0, "max_lon_e7": 0, "max_lat_e7": 0,
                "center_zoom": 0, "center_lon_e7": 0, "center_lat_e7": 0}, {"name": "fake planet"})
    return buf.getvalue(), tiles


@pytest.fixture
def fake_planet(monkeypatch, tmp_path):
    data, tiles = make_planet()

    class FakeRemote:
        def __init__(self, url):
            pass

        def get(self, offset, length):
            return data[offset:offset + length]

    monkeypatch.setattr(B, "Remote", FakeRemote)
    monkeypatch.setattr(B, "DIR", str(tmp_path))
    monkeypatch.setattr(B, "path_for", lambda regions: str(tmp_path / "test.pmtiles"))
    monkeypatch.setattr(B, "_graph_points", lambda regions: (np.array([LAT]), np.array([LON])))
    monkeypatch.setattr(B, "GAP", 64)       # small, so the fake planet still needs several requests
    monkeypatch.setattr(B, "CHUNK", 4096)
    return tiles


def test_varints_round_trip():
    v = np.array([0, 1, 127, 128, 16383, 16384, 2 ** 40, 2 ** 63 - 1], np.uint64)
    assert (B._decode_varints(B._encode_varints(v)) == v).all()


def test_wanted_ranges_cover_descendants_and_ancestors():
    cover = np.array([[100, 200]])
    rs, re = B.wanted_ranges(cover, max_zoom=13)
    inside = lambda t: bool(((rs <= t) & (t < re)).any())  # noqa: E731
    for z in range(0, B.COVER_ZOOM):
        assert inside(zxy_to_tileid(z, 100 >> (B.COVER_ZOOM - z), 200 >> (B.COVER_ZOOM - z)))
    for x in range(400, 404):
        for y in range(800, 804):
            assert inside(zxy_to_tileid(13, x, y))
    assert not inside(zxy_to_tileid(13, 404, 800))
    assert not inside(zxy_to_tileid(11, 101, 200))
    assert not inside(zxy_to_tileid(14, 0, 0))


def test_cover_adds_a_margin():
    cover = B.cover_tiles(np.array([LAT]), np.array([LON]))
    assert len(cover) == 9


def test_build_extracts_exactly_the_covered_tiles(fake_planet):
    out = B.build(["x"], source="fake")
    local = B.LocalBasemap(out)
    rs, re = B.wanted_ranges(B.cover_tiles(np.array([LAT]), np.array([LON])))
    for t, data in fake_planet.items():
        z, x, y = tileid_to_zxy(t)
        got = local.get(z, x, y)
        wanted = bool(((rs <= t) & (t < re)).any())
        if wanted:
            assert got is not None and gzip.decompress(got) == data, (z, x, y)
        else:
            assert got is None, (z, x, y)
    assert local.gzipped
    assert local.header["max_zoom"] == B.MAX_ZOOM
    local.close()


def test_build_resumes(fake_planet, monkeypatch):
    real_write = B._write_next
    calls = []

    def flaky(f, window, chunks, *rest):
        calls.append(window[0][0])
        if len(calls) == 25:  # B.build saves its place every 20 chunks
            raise ConnectionError("dropped")
        return real_write(f, window, chunks, *rest)

    monkeypatch.setattr(B, "_write_next", flaky)
    with pytest.raises(ConnectionError):
        B.build(["x"], source="fake")
    calls.clear()
    def counting(f, window, *rest):
        calls.append(window[0][0])
        return real_write(f, window, *rest)

    monkeypatch.setattr(B, "_write_next", counting)
    out = B.build(["x"], source="fake")
    assert calls[0] == 21  # chunks 0-20 were kept from the first try
    local = B.LocalBasemap(out)
    rs, re = B.wanted_ranges(B.cover_tiles(np.array([LAT]), np.array([LON])))
    for t, data in fake_planet.items():
        if ((rs <= t) & (t < re)).any():
            assert gzip.decompress(local.get(*tileid_to_zxy(t))) == data
    local.close()
