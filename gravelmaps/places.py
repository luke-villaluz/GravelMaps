"""Offline place search over towns, peaks, campgrounds, trailheads, gas stations etc. from OSM."""
import json
import math
import os
import re
import unicodedata

import numpy as np
from numba import njit

from .tags import PLACE_LABELS

FIXED = 1e-7
# Search rank per PLACE_TYPES entry (lower ranks higher).
TYPE_RANK = {"City": 0, "Town": 1, "Village": 2, "Hamlet": 3, "Ghost Town": 3, "Campground": 4,
             "Trailhead": 4, "Peak": 4, "Hot Spring": 4, "Gas Station": 5, "Neighborhood": 5,
             "Locality": 6, "Spring": 7}
STATE_ABBR = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "dc": "district-of-columbia",
    "fl": "florida", "ga": "georgia", "hi": "hawaii", "id": "idaho", "il": "illinois",
    "in": "indiana", "ia": "iowa", "ks": "kansas", "ky": "kentucky", "la": "louisiana",
    "me": "maine", "md": "maryland", "ma": "massachusetts", "mi": "michigan", "mn": "minnesota",
    "ms": "mississippi", "mo": "missouri", "mt": "montana", "ne": "nebraska", "nv": "nevada",
    "nh": "new-hampshire", "nj": "new-jersey", "nm": "new-mexico", "ny": "new-york",
    "nc": "north-carolina", "nd": "north-dakota", "oh": "ohio", "ok": "oklahoma", "or": "oregon",
    "pa": "pennsylvania", "pr": "puerto-rico", "ri": "rhode-island", "sc": "south-carolina",
    "sd": "south-dakota", "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont",
    "va": "virginia", "wa": "washington", "wv": "west-virginia", "wi": "wisconsin", "wy": "wyoming",
}


def normalize(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\bmount\b", "mt", re.sub(r"\bsaint\b", "st", text)).strip()


SETTLEMENTS = {"City", "Town", "Village", "Hamlet"}


@njit(cache=True)
def _nearest(qlat, qlon, slat, slon):
    out = np.empty(qlat.size, dtype=np.int64)
    for i in range(qlat.size):
        k = math.cos(math.radians(qlat[i]))
        best, bi = 1e18, -1
        for j in range(slat.size):
            d = (slat[j] - qlat[i]) ** 2 + ((slon[j] - qlon[i]) * k) ** 2
            if d < best:
                best, bi = d, j
        out[i] = bi
    return out


def pretty_region(r):
    return r.replace("-", " ").title()


def build(sources, out_path):
    """Merge (region, way cache path) sources' places into one JSON list:
    [name, type, lat, lon, population, region, near]."""
    rows, seen = [], set()
    for r, path in sources:
        with np.load(path) as z:
            names = json.loads(bytes(z["names"]).decode())
            for ni, t, la, lo, pop in zip(z["place_name_idx"], z["place_type"], z["place_lat"],
                                          z["place_lon"], z["place_pop"]):
                key = (names[ni], int(t), int(la) // 10_000, int(lo) // 10_000)  # ~1 km buckets
                if key in seen:
                    continue
                seen.add(key)
                rows.append([names[ni], int(t), round(int(la) * FIXED, 6), round(int(lo) * FIXED, 6), int(pop), r])
    town = [i for i, r in enumerate(rows) if PLACE_LABELS[r[1]] in SETTLEMENTS]
    other = [i for i, r in enumerate(rows) if PLACE_LABELS[r[1]] not in SETTLEMENTS]
    if town and other:
        near = _nearest(np.array([rows[i][2] for i in other]), np.array([rows[i][3] for i in other]),
                        np.array([rows[i][2] for i in town]), np.array([rows[i][3] for i in town]))
        for i, j in zip(other, near):
            rows[i].append(rows[town[j]][0])
    for r in rows:
        if len(r) == 6:
            r.append("")
    with open(out_path, "w") as f:
        json.dump(rows, f, separators=(",", ":"))
    return len(rows)


class PlaceIndex:
    def __init__(self, path):
        self.rows = []
        if os.path.exists(path):
            with open(path) as f:
                self.rows = json.load(f)
        self.keys = [normalize(r[0]) for r in self.rows]
        self.padded = [" " + k for k in self.keys]

    def search(self, query, lat=None, lon=None, limit=6):
        q = normalize(query)
        region = None
        # "Ely, NV" / "Ely Nevada": treat a trailing state as a filter.
        parts = q.rsplit(" ", 1)
        if len(parts) == 2:
            tail = parts[1]
            st = STATE_ABBR.get(tail) or (tail if tail in STATE_ABBR.values() else None)
            if st:
                q, region = parts[0], st
        for full in set(STATE_ABBR.values()):
            name = full.replace("-", " ")
            if q.endswith(" " + name) and len(q) > len(name) + 1:
                q, region = q[: -len(name) - 1].strip(), full
                break
        if len(q) < 2:
            return []

        pq = " " + q
        hits = []
        for i, k in enumerate(self.keys):
            if q not in k:
                continue
            row = self.rows[i]
            if region and row[5] != region:
                continue
            if k == q:
                level = 0
            elif k.startswith(q):
                level = 1
            elif pq in self.padded[i]:
                level = 2
            elif len(q) >= 4:
                level = 3
            else:
                continue
            label = PLACE_LABELS[row[1]]
            score = level * 4 + TYPE_RANK.get(label, 6) * 0.6 - min(math.log10(row[4] + 1), 7) * 0.3
            if lat is not None and lon is not None:
                dkm = math.hypot(row[2] - lat, (row[3] - lon) * math.cos(math.radians(lat))) * 111
                score += min(dkm / 250, 4)
            hits.append((score, i))
        hits.sort()
        out = []
        for _, i in hits[:limit]:
            name, t, la, lo, _, reg, near = self.rows[i]
            where = f"near {near}, {pretty_region(reg)}" if near and near != name else pretty_region(reg)
            out.append({"name": name, "detail": f"{PLACE_LABELS[t]} · {where}", "lat": la, "lon": lo})
        return out
