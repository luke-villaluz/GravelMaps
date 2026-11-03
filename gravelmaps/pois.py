"""Gas stations and other points of interest: merged from the state caches, looked up by map view
and (gas) along a route."""
import json
import os

import numpy as np

from . import graph  # graph imports this module too; only used at call time
from .tags import POI_RANK

DUPLICATE_M = 80      # a place mapped both as a point and as an outline
NEAR_ROUTE_M = 1600   # "along the route": within a mile of it
SAMPLE_M = 150        # route resolution for the along-route search
CLUTTER_PX = 30       # map-view thinning: one pin per this many screen pixels
CELL_DEG = 0.02       # coarse cells (~2 km) to shortlist stations near the route


def _merge(paths, key, out_path, sort_key, group=lambda r: None):
    """Merge one list from each state cache, drop duplicates (same group, within DUPLICATE_M), save as JSON.
    Rows are [lat, lon, ...]; sort_key orders them first, so the copy kept from a duplicate pair is
    the better one."""
    rows = []
    for path in paths:
        with np.load(path) as z:
            if key in z:
                rows += json.loads(bytes(z[key]).decode())
    rows.sort(key=sort_key)
    kept, cells = [], {}
    for r in rows:
        cy, cx = int(r[0] * 1000), int(r[1] * 1000)  # ~100 m cells
        near = [kept[i] for dy in (-1, 0, 1) for dx in (-1, 0, 1) for i in cells.get((cy + dy, cx + dx), ())]
        if any(group(k) == group(r) and graph.haversine(r[0], r[1], k[0], k[1]) < DUPLICATE_M for k in near):
            continue
        cells.setdefault((cy, cx), []).append(len(kept))
        kept.append(r)
    with open(out_path, "w") as f:
        json.dump(kept, f, separators=(",", ":"))
    return len(kept)


def build_fuel(paths, out_path):
    """Stations as [lat, lon, name, brand, hours, diesel]; named ones win over unnamed duplicates."""
    return _merge(paths, "fuel", out_path, sort_key=lambda r: not r[2])


def build_pois(paths, out_path):
    """Points as [lat, lon, category, kind, name, details], in priority order: named first, then by kind."""
    return _merge(paths, "pois", out_path, sort_key=lambda r: (not r[4], POI_RANK.get(r[3], 99)), group=lambda r: r[2])


class _Points:
    def __init__(self, path):
        self.rows = []
        if os.path.exists(path):
            with open(path) as f:
                self.rows = json.load(f)
        self.lat = np.array([r[0] for r in self.rows], dtype=np.float64)
        self.lon = np.array([r[1] for r in self.rows], dtype=np.float64)

    def __len__(self):
        return len(self.rows)

    def _in_bbox(self, s, w, n, e):
        return np.flatnonzero((self.lat >= s) & (self.lat <= n) & (self.lon >= w) & (self.lon <= e))

    def _thin(self, idx, zoom):
        """At most one point per CLUTTER_PX square on screen at this zoom, keeping the earliest
        (rows are in priority order), so pins don't pile up when zoomed out."""
        if zoom is None or not idx.size:
            return idx
        cell = 360 / 2 ** zoom / 256 * CLUTTER_PX  # degrees; latitude cells a bit taller, which is fine
        keys = np.floor(self.lat[idx] / cell).astype(np.int64) * 10_000_000 + np.floor(self.lon[idx] / cell).astype(np.int64)
        _, first = np.unique(keys, return_index=True)
        return idx[np.sort(first)]


class PoiIndex(_Points):
    def __init__(self, path):
        super().__init__(path)
        self.kind = np.array([r[3] for r in self.rows], dtype=object)

    def in_bbox(self, s, w, n, e, kinds, zoom=None, limit=2500):
        """Points of the given kinds in a map view, most important first, thinned for the zoom."""
        idx = self._in_bbox(s, w, n, e)
        idx = self._thin(idx[np.isin(self.kind[idx], list(kinds))], zoom)[:limit]
        return [{"lat": r[0], "lon": r[1], "cat": r[2], "kind": r[3], "name": r[4], **r[5]}
                for r in (self.rows[i] for i in idx)]


def _station(row, **extra):
    lat, lon, name, brand, hours, diesel = row
    return {"lat": lat, "lon": lon, "name": name or "Gas station", "brand": brand if brand != name else "",
            "hours": hours, "diesel": diesel, **extra}


class FuelIndex(_Points):
    def in_bbox(self, s, w, n, e, zoom=None, limit=2000):
        return [_station(self.rows[i]) for i in self._thin(self._in_bbox(s, w, n, e), zoom)[:limit]]

    def along(self, coords):
        """Stations within a mile of a route ([[lon, lat], ...]), in route order, plus the longest gap."""
        c = np.asarray(coords, dtype=np.float64)
        if len(c) < 2 or not self.rows:
            return {"stations": [], "longest_gap": None}
        seg = graph.haversine(c[:-1, 1], c[:-1, 0], c[1:, 1], c[1:, 0])
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(cum[-1])
        d = np.linspace(0, total, max(2, int(total / SAMPLE_M) + 1))
        slat, slon = np.interp(d, cum, c[:, 1]), np.interp(d, cum, c[:, 0])

        # Shortlist stations whose coarse cell touches the route, then measure exactly.
        cells = set()
        for cy, cx in zip(np.floor(slat / CELL_DEG).astype(int), np.floor(slon / CELL_DEG).astype(int)):
            cells.update((cy + dy, cx + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        pad = CELL_DEG * 2
        box = np.flatnonzero((self.lat >= slat.min() - pad) & (self.lat <= slat.max() + pad)
                             & (self.lon >= slon.min() - pad) & (self.lon <= slon.max() + pad))
        cand = [i for i in box if (int(np.floor(self.lat[i] / CELL_DEG)), int(np.floor(self.lon[i] / CELL_DEG))) in cells]

        found = []
        for i in cand:
            dist = graph.haversine(self.lat[i], self.lon[i], slat, slon)
            j = int(dist.argmin())
            if dist[j] <= NEAR_ROUTE_M:
                found.append((float(d[j]), float(dist[j]), i))
        found.sort()
        stations = [_station(self.rows[i], at_m=round(at), off_m=round(off)) for at, off, i in found]

        stops = [0.0, *[s["at_m"] for s in stations], total]
        gaps = np.diff(stops)
        k = int(gaps.argmax())
        return {"stations": stations,
                "longest_gap": {"from_m": round(stops[k]), "to_m": round(stops[k + 1]), "length_m": round(float(gaps[k])),
                                "from_start": k == 0, "to_end": k == len(gaps) - 1}}
