"""A* routing over the merged graph, plus snapping and GeoJSON assembly."""
import heapq
import math
import threading
from dataclasses import dataclass

import numpy as np
from numba import njit

from . import tags as T
from .graph import EARTH_R, FIXED, haversine
from .profiles import DEFAULT_PRESET, KINDS, PROFILES, Weights, parse_values


UNNAMED = {T.TRACK: "track", T.PATH: "trail", T.SERVICE: "service road", T.RESIDENTIAL: "street"}


# Road networks smaller than this (nodes) aren't snap targets: e.g. public streets fully ringed
# by private roads, which no legal route can reach.
MIN_COMPONENT = 1000


class RouteError(Exception):
    pass


@njit(cache=True)
def _hav(lat1, lon1, lat2, lon2):
    dp = lat2 - lat1
    dl = lon2 - lon1
    a = math.sin(dp / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(min(a, 1.0)))


@njit(cache=True)
def _astar(off, to, w, nlat, nlon, srcs, src_cost, tgts, tgt_cost, hscale):
    """Multi-source / multi-target A*.

    Returns (best_cost, target_index, csr entries along the path in order, settled count).
    best_cost is inf when no target is reachable.
    """
    n = off.size - 1
    rad = math.pi / 180 * 1e-7
    dist = np.full(n, np.inf)
    prev = np.full(n, -1, dtype=np.int32)
    tlat = np.empty(tgts.size)
    tlon = np.empty(tgts.size)
    for k in range(tgts.size):
        tlat[k] = nlat[tgts[k]] * rad
        tlon[k] = nlon[tgts[k]] * rad

    heap = [(0.0, 0.0, np.int64(0))]
    heap.pop()
    for i in range(srcs.size):
        s = srcs[i]
        if src_cost[i] < dist[s]:
            dist[s] = src_cost[i]
            c0 = np.float64(src_cost[i])
            heapq.heappush(heap, (c0, c0, np.int64(s)))

    best = np.inf
    best_k = -1
    settled = 0
    while heap:
        f, d, u = heapq.heappop(heap)
        if f >= best:
            break
        if d > dist[u]:
            continue
        settled += 1
        for k in range(tgts.size):
            if tgts[k] == u and d + tgt_cost[k] < best:
                best = d + tgt_cost[k]
                best_k = k
        for e in range(off[u], off[u + 1]):
            we = w[e]
            if not np.isfinite(we):
                continue
            v = to[e]
            nd = d + we
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = e
                vlat = nlat[v] * rad
                vlon = nlon[v] * rad
                h = np.inf
                for k in range(tgts.size):
                    hk = _hav(vlat, vlon, tlat[k], tlon[k])
                    if hk < h:
                        h = hk
                heapq.heappush(heap, (np.float64(nd + h * hscale), np.float64(nd), np.int64(v)))

    if best_k < 0:
        return np.inf, -1, np.empty(0, dtype=np.int64), settled

    path = []
    v = tgts[best_k]
    while prev[v] >= 0:
        e = prev[v]
        path.append(np.int64(e))
        # from-node of csr entry e
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if off[mid + 1] <= e:
                lo = mid + 1
            else:
                hi = mid
        v = lo
    out = np.empty(len(path), dtype=np.int64)
    for i in range(len(path)):
        out[i] = path[len(path) - 1 - i]
    return best, best_k, out, settled


@njit(cache=True)
def _find(parent, x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


@njit(cache=True)
def _components(n, src, dst, usable):
    """Connected-component label per node, treating usable edges as undirected."""
    parent = np.arange(n)
    for e in range(src.size):
        if usable[e]:
            a = _find(parent, src[e])
            b = _find(parent, dst[e])
            if a != b:
                parent[max(a, b)] = min(a, b)
    for i in range(n):
        parent[i] = _find(parent, i)
    return parent


@dataclass
class Snap:
    edge: int
    seg: int         # position index p; the snapped point lies on segment p -> p+1
    lat: float
    lon: float
    along: float     # metres from the edge's start node to the snapped point
    dist: float      # metres from the clicked point to the road


class Router:
    def __init__(self, g):
        self.g = g
        self.weights = Weights(g)
        self.lock = threading.Lock()
        self.snappable = {p: self._snappable_edges(p) for p in PROFILES}
        self._warmup()

    def _snappable_edges(self, profile):
        g = self.g
        usable = self.weights.edge_usable(profile)
        label = _components(len(g.node_lat), g.edge_src, g.edge_dst, usable)
        size = np.bincount(label)
        big = size[label] >= min(MIN_COMPONENT, size.max())
        return usable & big[g.edge_src]

    def _warmup(self):
        off = np.array([0, 1, 1], dtype=np.int64)
        _astar(off, np.array([1], dtype=np.int32), np.array([1.0], dtype=np.float32),
               np.zeros(2, dtype=np.int32), np.zeros(2, dtype=np.int32),
               np.array([0], dtype=np.int64), np.array([0.0], dtype=np.float32),
               np.array([1], dtype=np.int64), np.array([0.0], dtype=np.float32), 1.0)

    # ---- snapping -------------------------------------------------------------------------
    def _edge_of(self, p):
        e = np.searchsorted(self.g.edge_pstart, p, side="right") - 1
        ok = (e >= 0) & (self.g.edge_pend[np.maximum(e, 0)] >= p)
        return np.where(ok, e, -1)

    def snap(self, lat, lon, profile, max_km=25):
        g = self.g
        gr = g.grid
        snappable = self.snappable[profile]
        cy = int(math.floor(lat / gr["deg"])) - gr["lat0"]
        cx = int(math.floor(lon / gr["deg"])) - gr["lon0"]
        cell_m = gr["deg"] * 111_000 * max(math.cos(math.radians(lat)), 0.2)
        kx = math.cos(math.radians(lat))
        best = None
        max_r = int(max_km * 1000 / cell_m) + 1
        for r in range(max_r + 1):
            if best is not None and best[0] < (r - 1) * cell_m:
                break
            cells = []
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dy), abs(dx)) != r:
                        continue
                    y, x = cy + dy, cx + dx
                    if 0 <= y < gr["ny"] and 0 <= x < gr["nx"]:
                        c = y * gr["nx"] + x
                        a, b = g.grid_start[c], g.grid_start[c + 1]
                        if b > a:
                            cells.append(g.grid_perm[a:b])
            if not cells:
                continue
            p = np.concatenate(cells).astype(np.int64)
            e = self._edge_of(p)
            # Use the segment starting at p; at an edge's last point use the one ending there.
            valid = e >= 0
            p, e = p[valid], e[valid]
            if p.size == 0:
                continue
            ok = snappable[e]
            p, e = p[ok], e[ok]
            if p.size == 0:
                continue
            p0 = np.where(p == g.edge_pend[e], p - 1, p)
            la0, lo0 = g.lat[p0] * FIXED, g.lon[p0] * FIXED
            la1, lo1 = g.lat[p0 + 1] * FIXED, g.lon[p0 + 1] * FIXED
            # Project onto each segment in a local flat frame (metres).
            ax, ay = (lo0 - lon) * kx * 111_320, (la0 - lat) * 111_320
            bx, by = (lo1 - lon) * kx * 111_320, (la1 - lat) * 111_320
            dx_, dy_ = bx - ax, by - ay
            ll = dx_ * dx_ + dy_ * dy_
            t = np.where(ll > 0, -(ax * dx_ + ay * dy_) / np.where(ll > 0, ll, 1), 0)
            t = np.clip(t, 0, 1)
            px, py = ax + t * dx_, ay + t * dy_
            d = np.hypot(px, py)
            i = int(np.argmin(d))
            if best is None or d[i] < best[0]:
                best = (float(d[i]), int(e[i]), int(p0[i]), float(t[i]),
                        float(la0[i] + t[i] * (la1[i] - la0[i])), float(lo0[i] + t[i] * (lo1[i] - lo0[i])))
        if best is None:
            raise RouteError(f"No drivable road within {max_km} km of {lat:.5f}, {lon:.5f} for this vehicle.")
        d, e, p0, t, slat, slon = best
        ps = int(g.edge_pstart[e])
        along = self._path_len(ps, p0) + t * self._path_len(p0, p0 + 1)
        return Snap(edge=e, seg=p0, lat=slat, lon=slon, along=along, dist=d)

    def _path_len(self, a, b):
        if b <= a:
            return 0.0
        la = self.g.lat[a:b + 1] * FIXED
        lo = self.g.lon[a:b + 1] * FIXED
        return float(haversine(la[:-1], lo[:-1], la[1:], lo[1:]).sum())

    # ---- routing --------------------------------------------------------------------------
    def _coords(self, a, b):
        """[lon, lat] list for positions a..b inclusive (reversed if b < a)."""
        step = 1 if b >= a else -1
        idx = np.arange(a, b + step, step)
        return np.column_stack([self.g.lon[idx] * FIXED, self.g.lat[idx] * FIXED]).tolist()

    def _leg(self, A, B, profile, values):
        g = self.g
        w, hscale = self.weights.get(profile, values)
        # The partial edges at either end are used even if their kind is set to "never":
        # you're already standing on them.
        wc = self.weights.way_cost(profile, tuple(max(v, 1) for v in values))

        def ends(s):
            way = int(g.edge_way[s.edge])
            m = float(wc[way])
            length = float(g.edge_len[s.edge])
            return way, m, length, int(g.way_oneway[way])

        wa, ma, la, owa = ends(A)
        wb, mb, lb, owb = ends(B)
        srcs, scost, sdir = [], [], []
        if owa != -1:
            srcs.append(int(g.edge_dst[A.edge])); scost.append(max(la - A.along, 0) * ma); sdir.append(1)
        if owa != 1:
            srcs.append(int(g.edge_src[A.edge])); scost.append(A.along * ma); sdir.append(-1)
        tgts, tcost, tdir = [], [], []
        if owb != -1:
            tgts.append(int(g.edge_src[B.edge])); tcost.append(B.along * mb); tdir.append(1)
        if owb != 1:
            tgts.append(int(g.edge_dst[B.edge])); tcost.append(max(lb - B.along, 0) * mb); tdir.append(-1)

        direct = np.inf
        direct_dir = 0
        if A.edge == B.edge:
            if B.along >= A.along and owa != -1:
                direct, direct_dir = (B.along - A.along) * ma, 1
            elif B.along <= A.along and owa != 1:
                direct, direct_dir = (A.along - B.along) * ma, -1

        cost, k, entries, settled = np.inf, -1, np.empty(0, dtype=np.int64), 0
        if srcs and tgts:
            with self.lock:
                cost, k, entries, settled = _astar(
                    g.csr_off, g.csr_to, w, g.node_lat, g.node_lon,
                    np.array(srcs, dtype=np.int64), np.array(scost, dtype=np.float32),
                    np.array(tgts, dtype=np.int64), np.array(tcost, dtype=np.float32),
                    hscale * 0.995)
        if not np.isfinite(cost) and not np.isfinite(direct):
            if 0 in values[:len(KINDS)]:
                raise RouteError("No route with these settings. Try allowing more road types (no sliders at Never).")
            raise RouteError("No legal route found between these points for this vehicle.")

        pieces = []  # (way, coords)
        if direct <= cost:
            if direct_dir == 1:
                mid = self._coords(A.seg + 1, B.seg) if B.seg >= A.seg + 1 else []
            else:
                mid = self._coords(A.seg, B.seg + 1) if A.seg >= B.seg + 1 else []
            pieces.append((wa, [[A.lon, A.lat], *mid, [B.lon, B.lat]]))
            return pieces, settled

        codes = g.csr_code[entries]
        first_node = int(g.edge_src[codes[0] >> 1] if (codes[0] & 1) == 0 else g.edge_dst[codes[0] >> 1]) if len(codes) else tgts[k]
        start_dir = sdir[srcs.index(first_node)] if first_node in srcs else sdir[0]
        ps, pe = int(g.edge_pstart[A.edge]), int(g.edge_pend[A.edge])
        if start_dir == 1:
            pieces.append((wa, [[A.lon, A.lat], *self._coords(A.seg + 1, pe)]))
        else:
            pieces.append((wa, [[A.lon, A.lat], *self._coords(A.seg, ps)]))
        for c in codes:
            e = int(c >> 1)
            a, b = int(g.edge_pstart[e]), int(g.edge_pend[e])
            pieces.append((int(g.edge_way[e]), self._coords(b, a) if c & 1 else self._coords(a, b)))
        ps, pe = int(g.edge_pstart[B.edge]), int(g.edge_pend[B.edge])
        if tdir[k] == 1:
            pieces.append((wb, [*self._coords(ps, B.seg), [B.lon, B.lat]]))
        else:
            pieces.append((wb, [*self._coords(pe, B.seg + 1), [B.lon, B.lat]]))
        return pieces, settled

    def route(self, points, profile="car", legs=None, vehicles=None):
        """legs: one slider setting per leg (preset name, list or dict); default preset if omitted.
        vehicles: one profile per leg (e.g. drive the car in, then ride the bike); defaults to `profile`."""
        if len(points) < 2:
            raise RouteError("Need at least a start and an end point.")
        legs = list(legs or [])
        legs += [DEFAULT_PRESET] * (len(points) - 1 - len(legs))
        try:
            settings = [parse_values(v) for v in legs[: len(points) - 1]]
        except (KeyError, ValueError, TypeError) as err:
            raise RouteError(f"Bad route settings: {err}") from None
        n_legs = len(points) - 1
        vehicles = list(vehicles or [])
        vehicles += [profile] * (n_legs - len(vehicles))
        vehicles = vehicles[:n_legs]
        for v in vehicles:
            if v not in PROFILES:
                raise RouteError(f"Unknown vehicle {v!r}")
        # A stop where the vehicle changes is snapped once per vehicle: the car may park on the
        # road while the bike starts on the trail next to it.
        snap_cache = {}

        def snap(i, vehicle):
            if (i, vehicle) not in snap_cache:
                snap_cache[i, vehicle] = self.snap(*points[i], vehicle)
            return snap_cache[i, vehicle]

        pieces, settled = [], 0
        for i in range(n_legs):
            try:
                leg, s = self._leg(snap(i, vehicles[i]), snap(i + 1, vehicles[i]), vehicles[i], settings[i])
            except RouteError as err:
                raise RouteError(f"Leg {i + 1}: {err}") from None
            pieces.extend((i, way, coords) for way, coords in leg)
            settled += s
        snaps = [snap(i, vehicles[min(i, n_legs - 1)]) for i in range(len(points))]
        return self._assemble(pieces, snaps, vehicles, settled)

    def _assemble(self, pieces, snaps, vehicles, settled):
        g = self.g
        features, steps = [], []
        totals = {}
        legs = [{"distance_m": 0.0, "duration_s": 0.0, "unpaved_m": 0.0, "vehicle": v} for v in vehicles]
        prev_leg = 0
        dist_total = time_total = 0.0
        for leg_i, way, coords in pieces:
            if len(coords) < 2:
                continue
            arr = np.asarray(coords)
            length = float(haversine(arr[:-1, 1], arr[:-1, 0], arr[1:, 1], arr[1:, 0]).sum())
            if length < 0.5:  # e.g. a click snapped exactly onto a junction
                continue
            rc = int(g.way_road_class[way])
            kind = KINDS[self.weights.kind[way]]
            ni = int(g.way_name_idx[way])
            name = g.names[ni] if ni >= 0 else ""
            detail = int(g.way_detail[way])
            secs = length / (float(self.weights.speeds[vehicles[leg_i]][way]) / 3.6)
            dist_total += length
            time_total += secs
            totals[kind] = totals.get(kind, 0.0) + length
            legs[leg_i]["distance_m"] += length
            legs[leg_i]["duration_s"] += secs
            if kind in ("unpaved", "rough", "trail"):
                legs[leg_i]["unpaved_m"] += length
            props = features[-1]["properties"] if features else None
            if props and props["kind"] == kind and props["name"] == name and props["leg"] == leg_i and props["_detail"] == detail:
                features[-1]["geometry"]["coordinates"].extend(coords[1:])
                props["distance_m"] += length
            else:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": list(coords)},
                    "properties": {"kind": kind, "name": name, "highway": T.ROAD_CLASS_NAMES[rc],
                                   "distance_m": length, "leg": leg_i, "_detail": detail,
                                   "details": T.describe_detail(detail)},
                })
            label = name or f"unnamed {UNNAMED.get(rc, 'road')}"
            if leg_i != prev_leg and vehicles[leg_i] != vehicles[prev_leg]:
                steps.append({"name": f"Switch to {PROFILES[vehicles[leg_i]]['label']}", "kind": "switch",
                              "vehicle": vehicles[leg_i], "distance_m": 0.0,
                              "start": [coords[0][1], coords[0][0]]})
            prev_leg = leg_i
            if steps and steps[-1]["name"] == label:
                steps[-1]["distance_m"] += length
            else:
                steps.append({"name": label, "kind": kind, "distance_m": length,
                              "start": [coords[0][1], coords[0][0]]})
        for f in features:
            del f["properties"]["_detail"]
        unpaved = sum(totals.get(k, 0.0) for k in ("unpaved", "rough", "trail"))
        return {
            "type": "FeatureCollection",
            "features": features,
            "summary": {
                "distance_m": dist_total,
                "duration_s": time_total,
                "unpaved_m": unpaved,
                "unknown_m": totals.get("unknown", 0.0),
                "by_kind_m": totals,
                "settled_nodes": int(settled),
            },
            "legs": legs,
            "steps": steps,
            "snapped": [[s.lat, s.lon] for s in snaps],
        }
