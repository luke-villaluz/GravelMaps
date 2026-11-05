import math

import pytest
from fastapi.testclient import TestClient
from helpers import write_ways

from gravelmaps import camping, server
from gravelmaps import graph as G


def grid_ways(n=4, step=0.01, lat0=40.0, lon0=-118.0):
    """An n×n grid of dirt tracks, plus one paved road along the bottom row."""
    nid = {(i, j): i * n + j + 1 for i in range(n) for j in range(n)}
    pt = {k: (v, lat0 + k[0] * step, lon0 + k[1] * step) for k, v in nid.items()}
    ways, wid = [], 1
    for i in range(n):
        for j in range(n):
            for di, dj in ((0, 1), (1, 0)):
                if i + di < n and j + dj < n:
                    tags = {"highway": "primary"} if i == 0 and di == 0 else {"highway": "track"}
                    ways.append((wid, [pt[i, j], pt[i + di, j + dj]], tags))
                    wid += 1
    return ways


@pytest.fixture
def client(data_dir, monkeypatch, tmp_path):
    write_ways(data_dir / "a.npz", grid_ways())
    G.build(["a"])
    # Don't read the real camping data, if this machine has any.
    monkeypatch.setattr(server, "CampingIndex", lambda: camping.CampingIndex(path=str(tmp_path / "none.json")))
    return TestClient(server.create_app(["a"]))


def tile_xy(lat, lon, z):
    n = 2 ** z
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def test_region(client):
    info = client.get("/api/region").json()
    assert info["regions"] == ["a"]
    assert info["default_preset"] in info["presets"]
    assert {"car", "dualsport"} <= set(info["profiles"])
    assert info["camping"]["ready"] is False


def test_route(client):
    res = client.post("/api/route", json={"points": [[40.0001, -117.999], [40.0299, -117.971]]})
    assert res.status_code == 200
    body = res.json()
    assert body["features"] and body["summary"]["distance_m"] > 3000
    assert "fuel" in body


@pytest.mark.parametrize("points", [[[40.0, -118.0]], [[40.0, -118.0]] * (server.MAX_STOPS + 1)])
def test_route_rejects_bad_stop_counts(client, points):
    assert client.post("/api/route", json={"points": points}).status_code == 422


def test_route_unknown_vehicle(client):
    res = client.post("/api/route", json={"points": [[40.0, -118.0], [40.03, -117.97]], "profile": "boat"})
    assert res.status_code == 422


def test_geocode_coordinates(client):
    hits = client.get("/api/geocode", params={"q": "40.5, -118.25"}).json()
    assert hits == [{"name": "40.50000, -118.25000", "detail": "Coordinates", "lat": 40.5, "lon": -118.25}]


def test_geocode_offline_only(client):
    assert client.get("/api/geocode", params={"q": "nowhere at all", "remote": False}).json() == []


def test_elevation_needs_two_points(client):
    assert client.post("/api/elevation", json={"coords": [[-118.0, 40.0]]}).status_code == 400


def test_road_tiles(client):
    z = 14
    x, y = tile_xy(40.015, -117.985, z)
    tile = client.get(f"/api/roads/dirt/{z}/{x}/{y}.png", params={"theme": "light"})
    assert tile.status_code == 200 and tile.headers["content-type"] == "image/png"
    empty = client.get(f"/api/roads/dirt/{z}/{x + 50}/{y}.png").content
    assert tile.content.startswith(b"\x89PNG") and tile.content != empty
    assert client.get(f"/api/roads/nope/{z}/{x}/{y}.png").content == empty


def test_serves_the_app(client):
    res = client.get("/")
    assert res.status_code == 200 and "GravelMaps" in res.text
    assert res.headers["cache-control"] == "no-cache"
