"""Vehicles, road kinds, presets and routing costs. Edit freely; no rebuild needed.

Every way falls into one road kind (highway, major, paved, unknown, unpaved, rough, trail).
Each kind gets a 0-100 slider: 50 is neutral, higher means prefer, lower means avoid, 0 means never.

cost(edge) = travel_time_s * 2 ** ((50 - slider) / 10)

So with every slider at 50 the router finds the fastest route, and each 10 points of slider
makes a kind feel twice as fast (or slow) as it really is.
"""
from functools import lru_cache

import numpy as np

from . import tags as T

KINDS = ["highway", "major", "paved", "unknown", "unpaved", "rough", "trail"]
HIGHWAY, MAJOR, PAVED, UNKNOWN, UNPAVED, ROUGH, TRAIL = range(len(KINDS))
KIND_LABELS = ["Highway", "Major Road", "Paved", "Surface Unknown", "Dirt / Gravel", "Rough / 4x4", "Trail"]

PROFILES = {
    "car": {
        "label": "Car",
        "bit": T.CAR,
        "kinds": KINDS[:-1],  # cars never get trails
        # km/h, used for both cost and ETA
        "speed_paved": {T.MOTORWAY: 105, T.TRUNK: 90, T.PRIMARY: 80, T.SECONDARY: 70, T.TERTIARY: 60,
                        T.UNCLASSIFIED: 50, T.RESIDENTIAL: 40, T.SERVICE: 25, T.ROAD: 40, T.TRACK: 35, T.PATH: 15},
        "speed_unpaved": 45, "speed_track": 30, "speed_rough": 12, "speed_trail": 8,
    },
    "dualsport": {
        "label": "Dual Sport",
        "bit": T.MOTO,
        "kinds": KINDS,
        "speed_paved": {T.MOTORWAY: 85, T.TRUNK: 80, T.PRIMARY: 75, T.SECONDARY: 70, T.TERTIARY: 60,
                        T.UNCLASSIFIED: 50, T.RESIDENTIAL: 40, T.SERVICE: 25, T.ROAD: 40, T.TRACK: 35, T.PATH: 20},
        "speed_unpaved": 50, "speed_track": 35, "speed_rough": 18, "speed_trail": 15,
    },
}

# Slider values in KINDS order.
PRESETS = {
    "dirt":    {"label": "Only Dirt",       "values": [5, 20, 40, 85, 100, 100, 100]},
    "mostly":  {"label": "Mostly Dirt",     "values": [17, 54, 73, 80, 85, 85, 90]},
    "mixed":   {"label": "Mixed",           "values": [35, 55, 65, 65, 70, 50, 60]},
    "paved":   {"label": "Paved Backroads", "values": [15, 50, 75, 35, 30, 0, 0]},
    "highway": {"label": "Highway",         "values": [70, 65, 50, 20, 15, 0, 0]},
}
DEFAULT_PRESET = "mostly"


def parse_values(values):
    """Validate a slider list/dict into a tuple of ints in KINDS order."""
    if isinstance(values, str):
        values = PRESETS[values]["values"]
    if isinstance(values, dict):
        values = [values.get(k, 50) for k in KINDS]
    if len(values) != len(KINDS):
        raise ValueError(f"expected {len(KINDS)} slider values")
    return tuple(int(min(100, max(0, round(float(v))))) for v in values)


def multiplier(v):
    return np.inf if v <= 0 else 2.0 ** ((50 - v) / 10)


def way_kinds(g):
    rc, surface, rough = g.way_road_class, g.way_surface, g.way_rough
    kind = np.full(len(rc), PAVED, dtype=np.uint8)
    kind[(rc == T.MOTORWAY) | (rc == T.TRUNK)] = HIGHWAY
    kind[(rc == T.PRIMARY) | (rc == T.SECONDARY)] = MAJOR
    kind[surface == T.MAYBE_UNPAVED] = UNKNOWN
    kind[surface == T.UNPAVED] = UNPAVED
    kind[(surface == T.UNPAVED) & (rough == 1)] = ROUGH
    kind[rc == T.PATH] = TRAIL
    return kind


def way_speeds(g, profile):
    """km/h per way."""
    p = PROFILES[profile]
    rc, surface, rough = g.way_road_class, g.way_surface, g.way_rough
    paved = np.array([p["speed_paved"][i] for i in range(len(T.ROAD_CLASS_NAMES))], dtype=np.float32)
    s = paved[rc]
    s = np.where(surface != T.PAVED, np.float32(p["speed_unpaved"]), s)
    s = np.where((surface != T.PAVED) & (rc == T.TRACK), np.float32(p["speed_track"]), s)
    s = np.where((surface != T.PAVED) & (rough == 1), np.float32(p["speed_rough"]), s)
    s = np.where(rc == T.PATH, np.float32(p["speed_trail"]), s)
    return s


class Weights:
    """Per-(profile, sliders) cost arrays, cached because building one scans every edge."""

    def __init__(self, g):
        self.g = g
        self.kind = way_kinds(g)
        self.speeds = {p: way_speeds(g, p) for p in PROFILES}
        self.legal = {p: (g.way_legal & PROFILES[p]["bit"]) != 0 for p in PROFILES}
        self.way_cost = lru_cache(maxsize=16)(self._way_cost)
        self.get = lru_cache(maxsize=8)(self._build)

    def _way_cost(self, profile, values):
        """Seconds of 'felt' travel time per metre for each way (inf = never)."""
        mult = np.array([multiplier(v) for v in values], dtype=np.float64)
        cost = mult[self.kind] / (self.speeds[profile] / 3.6)
        return np.where(self.legal[profile], cost, np.inf).astype(np.float32)

    def edge_usable(self, profile):
        """Per-edge: legal for this vehicle and not closed by a gate or other barrier."""
        g = self.g
        return self.legal[profile][g.edge_way] & ((g.edge_block & PROFILES[profile]["bit"]) == 0)

    def _build(self, profile, values):
        g = self.g
        wc = self.way_cost(profile, values)
        edge = g.csr_code >> 1
        w = g.edge_len[edge] * wc[g.edge_way[edge]]
        w = np.where((g.edge_block[edge] & PROFILES[profile]["bit"]) != 0, np.float32(np.inf), w)
        finite = wc[np.isfinite(wc)]
        hscale = float(finite.min()) if finite.size else 1.0  # admissible: cheapest cost per metre
        return w.astype(np.float32), hscale
