"""Elevation profiles from the free AWS Terrain Tiles (terrarium PNGs, ~30 m resolution).

Tiles are fetched on demand and cached under data/dem/, so areas you've routed before work offline.
"""
import math
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image

from .graph import haversine
from .paths import DATA

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CACHE = os.path.join(DATA, "dem")
MAX_SAMPLES = 1500
HYSTERESIS_M = 5  # ignore wiggles smaller than this when totalling climb, to filter DEM noise


class Elevation:
    def __init__(self):
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "GravelMaps/0.1"
        self.lock = threading.Lock()
        self.tiles = OrderedDict()  # (z, x, y) -> float32 (256, 256), LRU

    def _load(self, key):
        z, x, y = key
        path = os.path.join(CACHE, str(z), str(x), f"{y}.png")
        if not os.path.exists(path):
            r = self.http.get(TILE_URL.format(z=z, x=x, y=y), timeout=20)
            r.raise_for_status()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(r.content)
            os.replace(tmp, path)
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
        return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768

    def _tiles(self, keys):
        with self.lock:
            missing = [k for k in keys if k not in self.tiles]
        if missing:
            with ThreadPoolExecutor(8) as pool:
                loaded = dict(zip(missing, pool.map(self._load, missing)))
            with self.lock:
                self.tiles.update(loaded)
        with self.lock:
            out = {}
            for k in keys:
                self.tiles.move_to_end(k)
                out[k] = self.tiles[k]
            while len(self.tiles) > 400:
                self.tiles.popitem(last=False)
        return out

    def sample(self, lat, lon, z):
        """Elevation in metres at each point, bilinear within each tile."""
        n = 2 ** z * 256
        px = (np.asarray(lon) + 180) / 360 * n - 0.5
        lat_r = np.radians(np.clip(lat, -85, 85))
        py = (1 - np.arcsinh(np.tan(lat_r)) / math.pi) / 2 * n - 0.5
        tx, ty = (np.floor(px) // 256).astype(int), (np.floor(py) // 256).astype(int)
        fx, fy = np.clip(px - tx * 256, 0, 255), np.clip(py - ty * 256, 0, 255)
        tiles = self._tiles([(z, a, b) for a, b in sorted(set(zip(tx.tolist(), ty.tolist())))])
        out = np.empty(len(px), dtype=np.float64)
        for i, (a, b, x, y) in enumerate(zip(tx, ty, fx, fy)):
            t = tiles[(z, a, b)]
            x0, y0 = min(int(x), 254), min(int(y), 254)
            dx, dy = x - x0, y - y0
            top = t[y0, x0] * (1 - dx) + t[y0, x0 + 1] * dx
            bot = t[y0 + 1, x0] * (1 - dx) + t[y0 + 1, x0 + 1] * dx
            out[i] = top * (1 - dy) + bot * dy
        return out

    def profile(self, coords):
        """coords: [[lon, lat], ...] along the route. Returns samples and climb statistics."""
        c = np.asarray(coords, dtype=np.float64)
        if len(c) < 2:
            raise ValueError("need at least two points")
        seg = haversine(c[:-1, 1], c[:-1, 0], c[1:, 1], c[1:, 0])
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(cum[-1])
        spacing = max(30.0, total / MAX_SAMPLES)
        d = np.linspace(0, total, max(2, int(total / spacing) + 1))
        lat = np.interp(d, cum, c[:, 1])
        lon = np.interp(d, cum, c[:, 0])
        # Coarser tiles for long routes keep the number of downloads reasonable.
        z = 12 if total < 150_000 else 11 if total < 600_000 else 10
        e = self.sample(lat, lon, z)
        if len(e) >= 5:  # light smoothing: roads don't follow every DEM pixel
            e = np.convolve(np.pad(e, 2, mode="edge"), np.ones(5) / 5, mode="valid")

        gain = loss = 0.0
        ref = e[0]
        for v in e[1:]:
            if v - ref >= HYSTERESIS_M:
                gain += v - ref
                ref = v
            elif ref - v >= HYSTERESIS_M:
                loss += ref - v
                ref = v

        k = max(1, round(400 / (d[1] - d[0])))  # grade averaged over ~400 m
        grade = np.abs(e[k:] - e[:-k]) / (d[k:] - d[:-k]) if len(e) > k else np.zeros(1)

        return {
            "samples": [[round(float(a), 1), round(float(b), 1), round(float(la), 6), round(float(lo), 6)]
                        for a, b, la, lo in zip(d, e, lat, lon)],
            "gain_m": round(float(gain), 1),
            "loss_m": round(float(loss), 1),
            "max_m": round(float(e.max()), 1),
            "min_m": round(float(e.min()), 1),
            "max_grade": round(float(grade.max()), 4),
        }
