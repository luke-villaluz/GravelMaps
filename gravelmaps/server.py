"""FastAPI app: routing API, geocoding proxy and the static web UI."""
import re
import time

import requests
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .elevation import Elevation
from .graph import Graph
from .paths import STATIC
from .profiles import DEFAULT_PRESET, KIND_LABELS, KINDS, PRESETS, PROFILES
from .router import RouteError, Router
from .tiles import RoadTiles

PHOTON = "https://photon.komoot.io/api/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GravelMaps/0.1 (personal back-road router; https://github.com/)"
LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")


class RouteRequest(BaseModel):
    points: list[tuple[float, float]]
    profile: str = "car"
    legs: list[list[float] | str] = []


class ElevationRequest(BaseModel):
    coords: list[tuple[float, float]]  # [lon, lat]


def create_app(regions):
    g = Graph(regions)
    router = Router(g)
    elevation = Elevation()
    road_tiles = RoadTiles(g, router.weights.kind)
    tile_version = str(int(time.time()))  # busts browser caches when the server (or tile style) changes
    app = FastAPI(title="GravelMaps")
    http = requests.Session()
    http.headers["User-Agent"] = USER_AGENT

    @app.get("/api/region")
    def region():
        return {
            "regions": g.regions,
            "bbox": g.bbox,
            "profiles": {k: {"label": v["label"], "kinds": v["kinds"]} for k, v in PROFILES.items()},
            "kinds": [{"key": k, "label": label} for k, label in zip(KINDS, KIND_LABELS)],
            "presets": PRESETS,
            "default_preset": DEFAULT_PRESET,
            "tile_version": tile_version,
        }

    @app.post("/api/route")
    def route(req: RouteRequest):
        try:
            return router.route(req.points, req.profile, req.legs)
        except RouteError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/roads/{layer}/{z}/{x}/{y}.png")
    def roads_tile(layer: str, z: int, x: int, y: int, theme: str = "dark"):
        return Response(road_tiles.tile(layer, z, x, y, theme), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/api/elevation")
    def elevation_profile(req: ElevationRequest):
        try:
            return elevation.profile(req.coords)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except (requests.RequestException, OSError) as e:
            raise HTTPException(502, f"Elevation data unavailable: {e}")

    @app.get("/api/geocode")
    def geocode(q: str, lat: float | None = None, lon: float | None = None, remote: bool = True):
        """Offline OSM places first; online geocoders fill in addresses and anything else."""
        m = LATLON.match(q)
        if m:
            la, lo = float(m.group(1)), float(m.group(2))
            return [{"name": f"{la:.5f}, {lo:.5f}", "detail": "Coordinates", "lat": la, "lon": lo}]
        local = g.places.search(q, lat, lon)
        if not remote or len(local) >= 3:
            return local
        try:
            online = photon(q, lat, lon)
        except requests.RequestException:
            try:
                online = nominatim(q)
            except requests.RequestException as err:
                if local:
                    return local
                raise HTTPException(502, f"Search service unavailable: {err}")
        for hit in online:
            dup = any(h["name"] == hit["name"] and abs(h["lat"] - hit["lat"]) + abs(h["lon"] - hit["lon"]) < 0.05
                      for h in local)
            if not dup:
                local.append(hit)
        return local[:6]

    def photon(q, lat, lon):
        s, w, n, e = g.bbox
        params = {"q": q, "limit": 8, "bbox": f"{w - 0.5},{s - 0.5},{e + 0.5},{n + 0.5}"}
        if lat is not None and lon is not None:
            params.update({"lat": lat, "lon": lon})
        r = http.get(PHOTON, params=params, timeout=6)
        r.raise_for_status()
        out = []
        for f in r.json()["features"]:
            p = f["properties"]
            name = p.get("name") or " ".join(x for x in (p.get("housenumber"), p.get("street")) if x)
            if not name:
                continue
            detail = ", ".join(dict.fromkeys(
                x for x in (p.get("city") or p.get("county"), p.get("state")) if x and x != name))
            lo, la = f["geometry"]["coordinates"]
            out.append({"name": name, "detail": detail, "lat": la, "lon": lo,
                        "_demote": p.get("osm_value") in ("county", "state", "country")})
        out.sort(key=lambda x: x.pop("_demote"))
        return out[:6]

    def nominatim(q):
        s, w, n, e = g.bbox
        r = http.get(NOMINATIM, timeout=8, params={
            "q": q, "format": "jsonv2", "limit": 6, "countrycodes": "us",
            "viewbox": f"{w},{n},{e},{s}", "bounded": 0,
        })
        r.raise_for_status()
        out = []
        for x in r.json():
            name, _, detail = x["display_name"].partition(", ")
            out.append({"name": name, "detail": detail, "lat": float(x["lat"]), "lon": float(x["lon"])})
        return out

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
