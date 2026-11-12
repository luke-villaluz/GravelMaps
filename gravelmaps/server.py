"""FastAPI app: routing API, geocoding proxy and the static web UI, plus the setup screen
that downloads and builds map data from inside the app (Shell)."""
import os
import threading
import time

import requests
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import USER_AGENT, basemap, coords, pipeline
from .camping import CampingIndex
from .config import load_config, save_config
from .elevation import Elevation
from .graph import Graph
from .paths import STATIC, graph_dir
from .profiles import DEFAULT_PRESET, KIND_LABELS, KINDS, PRESETS, PROFILES
from .regions import CODES, STATES, parse_list
from .router import RouteError, Router
from .setupjob import SetupJob
from .tiles import RoadTiles
from .updater import updater

PHOTON = "https://photon.komoot.io/api/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"


# Size limits keep one request from tying up the server: far beyond any real trip, still bounded.
MAX_STOPS = 50
MAX_ELEVATION_COORDS = 500_000


class RouteRequest(BaseModel):
    points: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_STOPS)
    profile: str = "car"
    legs: list[list[float] | str] = Field(default=[], max_length=MAX_STOPS)
    vehicles: list[str] = Field(default=[], max_length=MAX_STOPS)  # per leg; defaults to `profile`


class ElevationRequest(BaseModel):
    coords: list[tuple[float, float]] = Field(max_length=MAX_ELEVATION_COORDS)  # [lon, lat]


def create_app(regions):
    g = Graph(regions)
    router = Router(g)
    elevation = Elevation()
    road_tiles = RoadTiles(g, router.weights.kind)
    camping = CampingIndex()
    # The offline street map; without it the UI keeps to the online basemaps.
    base_tiles = basemap.LocalBasemap(basemap.path_for(regions)) if basemap.is_built(regions) else None
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
            # The extra slider after the road kinds; hidden in the UI when terrain wasn't downloaded.
            "elevation": {"label": "High Elevation", "ready": getattr(g, "edge_high", None) is not None},
            "presets": PRESETS,
            "default_preset": DEFAULT_PRESET,
            "tile_version": tile_version,
            "camping": {"ready": camping.ready, "built": camping.built},
            "basemap": base_tiles is not None,
        }

    @app.post("/api/route")
    def route(req: RouteRequest):
        try:
            res = router.route(req.points, req.profile, req.legs, req.vehicles)
        except RouteError as e:
            raise HTTPException(422, str(e)) from e
        res["fuel"] = g.fuel.along([c for f in res["features"] for c in f["geometry"]["coordinates"]])
        return res

    @app.get("/api/fuel")
    def fuel(s: float, w: float, n: float, e: float, z: int | None = None):
        """Gas stations in a map view (south, west, north, east)."""
        return g.fuel.in_bbox(s, w, n, e, zoom=z)

    @app.get("/api/pois")
    def poi_list(s: float, w: float, n: float, e: float, kinds: str, z: int | None = None):
        """Points of interest in a map view, for a comma-separated list of kinds, thinned for zoom z."""
        return g.pois.in_bbox(s, w, n, e, [k for k in kinds.split(",") if k], zoom=z)

    @app.get("/api/camping")
    def camping_list(s: float, w: float, n: float, e: float):
        """Roads with dispersed camping rules, no-camping areas and listed camping areas in a map view."""
        return camping.in_bbox(s, w, n, e)

    @app.get("/api/camping/at")
    def camping_at(lat: float, lon: float):
        """The camping rules of the motor vehicle use maps covering a point."""
        return camping.at(lat, lon)

    @app.get("/api/roads/{layer}/{z}/{x}/{y}.png")
    def roads_tile(layer: str, z: int, x: int, y: int, theme: str = "dark"):
        return Response(road_tiles.tile(layer, z, x, y, theme), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/basemap/{z}/{x}/{y}.mvt")
    def basemap_tile(z: int, x: int, y: int):
        data = base_tiles.get(z, x, y) if base_tiles else None
        if data is None:  # outside the downloaded area: an empty tile, nothing drawn
            return Response(status_code=204)
        headers = {"Cache-Control": "public, max-age=86400"}
        if base_tiles.gzipped:
            headers["Content-Encoding"] = "gzip"  # the browser unpacks it
        return Response(data, media_type="application/x-protobuf", headers=headers)

    @app.post("/api/elevation")
    def elevation_profile(req: ElevationRequest):
        try:
            return elevation.profile(req.coords)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except (requests.RequestException, OSError) as e:
            raise HTTPException(502, f"Elevation data unavailable: {e}") from e

    @app.get("/api/geocode")
    def geocode(q: str, lat: float | None = None, lon: float | None = None, remote: bool = True):
        """Offline OSM places first; online geocoders fill in addresses and anything else."""
        ll = coords.parse(q)  # typed coordinates, e.g. from a GPS unit
        if ll:
            la, lo = ll
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
                raise HTTPException(502, f"Search service unavailable: {err}") from err
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

    @app.middleware("http")
    async def revalidate_ui(request, call_next):
        # Make browsers check for newer js/ modules and style.css on every load instead of reusing a stale copy.
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


class SetupRequest(BaseModel):
    states: list[str] = Field(min_length=1, max_length=60)  # two-letter codes, e.g. ["ca", "nv"]
    update_data: bool = False
    rebuild: bool = False


def graph_ready(regions):
    return bool(regions) and os.path.exists(os.path.join(graph_dir(regions), "meta.json"))


class Shell:
    """The whole web app, as served. Until a graph is built it shows the setup screen; then the
    map. Setup's API is always there, so the map's settings can change states or update data, and
    the old map keeps working until the new one is ready."""

    def __init__(self, regions=None):
        self.map_app = None
        self.regions = None
        self.job = None
        self.lock = threading.Lock()
        if graph_ready(regions):
            self.load(regions)
        self.setup_app = self._setup_app()

    def load(self, regions):
        app = create_app(regions)
        self.map_app, self.regions = app, regions

    def _finished(self, regions):
        cfg = load_config()
        cfg["regions"] = regions
        save_config(cfg)
        self.load(regions)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        path = scope.get("path", "")
        app = self.setup_app if self.map_app is None or path.startswith("/api/setup") else self.map_app
        await app(scope, receive, send)

    def _setup_app(self):
        app = FastAPI(title="GravelMaps setup")
        shell = self

        @app.get("/api/setup/states")
        def states():
            names = {c: n.replace("-", " ").title().replace(" Of ", " of ") for c, n in STATES.items()}
            return sorted(({"code": c, "name": n} for c, n in names.items()), key=lambda s: s["name"])

        @app.get("/api/setup/status")
        def status():
            regions = shell.job.regions if shell.job else (shell.regions or load_config().get("regions") or [])
            busy = shell.job is not None and shell.job.running
            return {
                "ready": shell.map_app is not None,
                "regions": regions,
                "codes": [CODES[r] for r in regions],
                "job": shell.job.status() if shell.job else None,
                # Steps still to do for the current states, e.g. the offline map after an upgrade.
                "pending": [t for _, t in pipeline.steps(shell.regions)] if shell.regions and not busy else [],
            }

        @app.post("/api/setup")
        def start(req: SetupRequest):
            try:
                regions = parse_list(" ".join(req.states))
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            with shell.lock:
                if shell.job and shell.job.running:
                    raise HTTPException(409, "Setup is already running.")
                shell.job = SetupJob(regions, req.update_data, req.rebuild, on_done=shell._finished).start()
            return shell.job.status()

        # ---- app updates (the packaged Mac app only; see updater.py) ----
        @app.get("/api/setup/update")
        def update_check(force: bool = False):
            return updater.check(force)

        @app.post("/api/setup/update")
        def update_start():
            try:
                updater.start()
            except ValueError as e:
                raise HTTPException(409, str(e)) from e
            return updater.status()

        @app.get("/api/setup/update/status")
        def update_status():
            return updater.status()

        @app.get("/")
        def setup_page():
            return FileResponse(os.path.join(STATIC, "setup.html"), headers={"Cache-Control": "no-cache"})

        @app.middleware("http")
        async def revalidate_ui(request, call_next):
            response = await call_next(request)
            if not request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-cache"
            return response

        app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
        return app
