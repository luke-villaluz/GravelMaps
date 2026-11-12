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



# ---- the offline basemap endpoint --------------------------------------------------------------

@pytest.fixture
def basemap_client(data_dir, monkeypatch, tmp_path):
    from test_basemap import make_planet

    from gravelmaps import basemap
    data, tiles = make_planet(max_zoom=12)
    path = tmp_path / "base.pmtiles"
    path.write_bytes(data)
    monkeypatch.setattr(basemap, "is_built", lambda regions: True)
    monkeypatch.setattr(basemap, "path_for", lambda regions: str(path))
    write_ways(data_dir / "a.npz", grid_ways())
    G.build(["a"])
    monkeypatch.setattr(server, "CampingIndex", lambda: camping.CampingIndex(path=str(tmp_path / "none.json")))
    return TestClient(server.create_app(["a"])), tiles


def test_basemap_tiles(basemap_client):
    from pmtiles.tile import tileid_to_zxy
    client, tiles = basemap_client
    assert client.get("/api/region").json()["basemap"] is True
    t, data = next((t, d) for t, d in tiles.items() if tileid_to_zxy(t)[0] == 12)
    z, x, y = tileid_to_zxy(t)
    r = client.get(f"/api/basemap/{z}/{x}/{y}.mvt")
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert r.content == data  # the test client unpacks the gzip, as a browser does
    assert client.get("/api/basemap/12/0/0.mvt").status_code == 204   # outside the download
    assert client.get("/api/basemap/16/0/0.mvt").status_code == 204   # deeper than the data


def test_no_basemap(client):
    assert client.get("/api/region").json()["basemap"] is False
    assert client.get("/api/basemap/5/5/5.mvt").status_code == 204


# ---- the shell: setup screen until there is a map ----------------------------------------------

@pytest.fixture
def no_config(monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(server, "load_config", lambda: dict(saved))
    monkeypatch.setattr(server, "save_config", lambda cfg: saved.update(cfg))
    return saved


def test_setup_screen_without_data(no_config):
    client = TestClient(server.Shell(None))
    page = client.get("/")
    assert page.status_code == 200 and "GravelMaps Setup" in page.text
    status = client.get("/api/setup/status").json()
    assert status["ready"] is False and status["job"] is None and status["regions"] == []
    assert client.get("/api/region").status_code == 404
    names = [s["name"] for s in client.get("/api/setup/states").json()]
    assert "California" in names and names == sorted(names)
    assert client.post("/api/setup", json={"states": ["zz"]}).status_code == 400


def test_setup_job_loads_the_map(no_config, monkeypatch, data_dir, tmp_path):
    from gravelmaps import pipeline
    write_ways(data_dir / "a.npz", grid_ways())
    monkeypatch.setattr(server, "CampingIndex", lambda: camping.CampingIndex(path=str(tmp_path / "none.json")))
    monkeypatch.setattr(pipeline, "steps", lambda regions, *a: [("graph", "Building the routing graph")])
    monkeypatch.setattr(pipeline, "run", lambda regions, update_data, rebuild, report: (
        report.step("graph", "Building"), report.progress(5, 10), G.build(["a"])))
    monkeypatch.setattr(server, "graph_ready", lambda regions: False)
    monkeypatch.setattr(server, "parse_list", lambda text: ["a"])
    monkeypatch.setattr(server, "CODES", {"a": "aa"})

    shell = server.Shell(None)
    client = TestClient(shell)
    started = client.post("/api/setup", json={"states": ["aa"]}).json()
    assert started["steps"][0]["key"] == "graph"
    shell.job.thread.join(10)
    status = client.get("/api/setup/status").json()
    assert status["ready"] is True and status["job"]["finished"] and status["job"]["error"] is None
    assert status["job"]["steps"][0]["state"] == "done"
    assert no_config["regions"] == ["a"]
    assert client.get("/api/region").json()["regions"] == ["a"]   # now the map is served
    assert "GravelMaps Setup" not in client.get("/").text


def test_setup_job_reports_errors(no_config, monkeypatch):
    import requests

    from gravelmaps import pipeline
    monkeypatch.setattr(pipeline, "steps", lambda regions, *a: [("fetch:nevada", "Downloading")])

    def offline(regions, update_data, rebuild, report):
        report.step("fetch:nevada", "Downloading")
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(pipeline, "run", offline)
    shell = server.Shell(None)
    client = TestClient(shell)
    client.post("/api/setup", json={"states": ["nv"]})
    shell.job.thread.join(10)
    job = client.get("/api/setup/status").json()["job"]
    assert job["steps"][0]["state"] == "failed" and "internet" in job["error"]
    assert client.get("/api/setup/status").json()["ready"] is False
    assert "regions" not in no_config
