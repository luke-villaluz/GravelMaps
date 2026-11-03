"""Raster road overlays drawn from the routing graph.

Two layers:
  main – highways and major roads, crisp from zoom 6 in, so you can see where the big roads go.
  dirt – every unpaved road, track and trail, subdued, only when zoomed in close. Esri's street
         map leaves most of these out.
"""
import io
import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from .graph import FIXED
from .profiles import HIGHWAY, MAJOR, PAVED, ROUGH, TRAIL, UNKNOWN, UNPAVED

OUT = 512        # pixels per tile (shown at 256 CSS px, so crisp on retina screens)
SUPER = 2        # supersampling factor for anti-aliasing
MAIN_GRID_DEG = 0.25
COARSE_BELOW_ZOOM = 10  # main roads use their own coarse index only for wide views

# Per layer: minimum zoom, the road kinds drawn (some only from a later zoom), and per-theme
# colours. "dark" lines go on light basemaps, "light" on satellite. Widths are CSS pixels by zoom.
# "halo" is the casing under each line: one colour, or one per kind.
LAYERS = {
    "main": {
        "min_zoom": 6,
        "kinds": [PAVED, MAJOR, HIGHWAY],  # draw order: highways end up on top
        "kind_min_zoom": {PAVED: 12},       # minor paved roads only once zoomed in
        "themes": {
            # Google Maps look: yellow-orange highways, white roads, each with a slightly darker edge.
            "dark": {"halo": {PAVED: (188, 188, 196, 220), MAJOR: (172, 172, 182, 240), HIGHWAY: (222, 160, 50, 255)},
                     PAVED: (255, 255, 255, 245), MAJOR: (255, 255, 255, 255), HIGHWAY: (252, 214, 104, 255)},
            "light": {"halo": (0, 0, 0, 170), PAVED: (210, 210, 215, 220),
                      MAJOR: (225, 225, 230, 235), HIGHWAY: (255, 255, 255, 255)},
        },
        "width": {PAVED: [(12, 0.9), (13, 1.1), (14, 1.4), (99, 1.8)],
                  MAJOR: [(7, 0.8), (8, 1.0), (9, 1.3), (11, 1.9), (99, 2.6)],
                  HIGHWAY: [(7, 1.4), (8, 1.7), (9, 2.1), (11, 2.8), (99, 3.6)]},
    },
    "dirt": {
        "min_zoom": 12,
        "kinds": [UNKNOWN, UNPAVED, ROUGH, TRAIL],
        "themes": {
            "dark": {"halo": (255, 255, 255, 80), "line": (90, 70, 50, 165)},
            "light": {"halo": (0, 0, 0, 60), "line": (240, 226, 204, 165)},
        },
        "width": {"line": [(12, 0.8), (13, 1.0), (14, 1.3), (99, 1.6)]},
    },
}


def _width(table, z):
    return next(w for max_z, w in table if z <= max_z)


def _edge_positions(g, edges):
    """Flat position indices for each edge's polyline, plus each polyline's length."""
    starts, ends = g.edge_pstart[edges], g.edge_pend[edges]
    lengths = ends - starts + 1
    offsets = np.concatenate([[0], np.cumsum(lengths)[:-1]])
    idx = np.arange(lengths.sum()) - np.repeat(offsets, lengths) + np.repeat(starts, lengths)
    return idx, lengths


def _coarse_index(g, edges):
    """(cell ids, edge ids, origin) bucketing edges into MAIN_GRID_DEG cells, for wide views."""
    if edges.size == 0:
        return np.empty(0, np.int64), np.empty(0, np.int64), (0, 0, 1, 1)
    idx, lengths = _edge_positions(g, edges)
    cy = np.floor(g.lat[idx] * FIXED / MAIN_GRID_DEG).astype(np.int64)
    cx = np.floor(g.lon[idx] * FIXED / MAIN_GRID_DEG).astype(np.int64)
    cells = (cy - cy.min()) * (cx.max() - cx.min() + 1) + (cx - cx.min())
    pairs = np.unique(np.column_stack([cells, np.repeat(edges, lengths)]), axis=0)
    return pairs[:, 0], pairs[:, 1], (int(cy.min()), int(cx.min()), int(cx.max() - cx.min() + 1), int(cy.max() - cy.min() + 1))


class RoadTiles:
    def __init__(self, g, way_kind):
        self.g = g
        self.edge_kind = way_kind[g.edge_way]
        legal = g.way_legal[g.edge_way] != 0
        self.layer_edges = {name: np.isin(self.edge_kind, spec["kinds"]) & legal for name, spec in LAYERS.items()}

        # Main roads are few enough for their own coarse index, which low zooms need: a zoom-6
        # tile spans several degrees, far too much for the fine routing grid.
        self.coarse = {"main": _coarse_index(g, np.flatnonzero(np.isin(self.edge_kind, [MAJOR, HIGHWAY]) & legal))}

        self.tile = lru_cache(maxsize=2048)(self._render)
        buf = io.BytesIO()
        Image.new("RGBA", (OUT, OUT)).save(buf, "PNG")
        self.empty = buf.getvalue()

    # ---- edge lookup ------------------------------------------------------------------------
    def _fine_edges_in(self, layer, s, w, n, e):
        g, gr = self.g, self.g.grid
        m = 3  # cells of margin, to catch long straight segments crossing the tile
        y0 = max(int(math.floor(s / gr["deg"])) - gr["lat0"] - m, 0)
        y1 = min(int(math.floor(n / gr["deg"])) - gr["lat0"] + m, gr["ny"] - 1)
        x0 = max(int(math.floor(w / gr["deg"])) - gr["lon0"] - m, 0)
        x1 = min(int(math.floor(e / gr["deg"])) - gr["lon0"] + m, gr["nx"] - 1)
        if y0 > y1 or x0 > x1:
            return np.empty(0, dtype=np.int64)
        # Cells in one grid row are consecutive, so each row is a single slice of grid_perm.
        p = np.concatenate([g.grid_perm[g.grid_start[y * gr["nx"] + x0]:g.grid_start[y * gr["nx"] + x1 + 1]]
                            for y in range(y0, y1 + 1)]).astype(np.int64)
        edges = np.searchsorted(g.edge_pstart, p, side="right") - 1
        edges = np.unique(edges[(edges >= 0) & (g.edge_pend[np.maximum(edges, 0)] >= p)])
        return edges[self.layer_edges[layer][edges]]

    def _coarse_edges_in(self, layer, s, w, n, e):
        cells, edges, (cy0, cx0, nx, ny) = self.coarse[layer]
        y0 = max(int(math.floor(s / MAIN_GRID_DEG)) - cy0 - 1, 0)
        y1 = min(int(math.floor(n / MAIN_GRID_DEG)) - cy0 + 1, ny - 1)
        x0 = max(int(math.floor(w / MAIN_GRID_DEG)) - cx0 - 1, 0)
        x1 = min(int(math.floor(e / MAIN_GRID_DEG)) - cx0 + 1, nx - 1)
        if y0 > y1 or x0 > x1:
            return np.empty(0, dtype=np.int64)
        parts = []
        for y in range(y0, y1 + 1):
            a = np.searchsorted(cells, y * nx + x0, side="left")
            b = np.searchsorted(cells, y * nx + x1, side="right")
            parts.append(edges[a:b])
        return np.unique(np.concatenate(parts))

    # ---- drawing ----------------------------------------------------------------------------
    def _render(self, layer, z, x, y, theme):
        spec = LAYERS.get(layer)
        if spec is None or z < spec["min_zoom"] or theme not in spec["themes"]:
            return self.empty
        g = self.g
        n = 2 ** z
        w_lon, e_lon = x / n * 360 - 180, (x + 1) / n * 360 - 180
        n_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        s_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        if layer == "main" and z < COARSE_BELOW_ZOOM:
            edges = self._coarse_edges_in(layer, s_lat, w_lon, n_lat, e_lon)
        else:
            edges = self._fine_edges_in(layer, s_lat, w_lon, n_lat, e_lon)
        for kind, kmin in spec.get("kind_min_zoom", {}).items():
            if z < kmin:
                edges = edges[self.edge_kind[edges] != kind]
        if edges.size == 0:
            return self.empty

        idx, lengths = _edge_positions(g, edges)
        size = OUT * SUPER
        px = ((g.lon[idx] * FIXED + 180) / 360 * n - x) * size
        py = ((1 - np.arcsinh(np.tan(np.radians(g.lat[idx] * FIXED))) / math.pi) / 2 * n - y) * size
        # Drop vertices that land on the same pixel as the previous one (matters at low zoom).
        q = np.column_stack([np.round(px), np.round(py)])
        line_id = np.repeat(np.arange(len(edges)), lengths)
        first = np.r_[True, line_id[1:] != line_id[:-1]]
        last = np.r_[line_id[1:] != line_id[:-1], True]
        keep = first | last | np.r_[True, (q[1:] != q[:-1]).any(axis=1)]
        pts, line_id = q[keep], line_id[keep]
        bounds = np.flatnonzero(np.r_[True, line_id[1:] != line_id[:-1]])
        lines = np.split(pts, bounds[1:])
        kinds = self.edge_kind[edges]

        colors = spec["themes"][theme]
        img = Image.new("RGBA", (size, size))
        draw = ImageDraw.Draw(img)
        style = [(k, colors[k], _width(spec["width"][k], z)) for k in spec["kinds"]] if layer == "main" else \
                [(None, colors["line"], _width(spec["width"]["line"], z))]
        halo_w = {k: (w + 1.4) * 2 * SUPER for k, _, w in style}
        halo = colors["halo"]
        line_w = {k: w * 2 * SUPER for k, _, w in style}
        for line, k in zip(lines, kinds):
            key = k if layer == "main" else None
            fill = halo[key] if isinstance(halo, dict) else halo
            draw.line(line.ravel().tolist(), fill=fill, width=max(1, round(halo_w[key])), joint="curve")
        for key, color, _ in style:
            for line, k in zip(lines, kinds):
                if layer != "main" or k == key:
                    draw.line(line.ravel().tolist(), fill=color, width=max(1, round(line_w[key])), joint="curve")
        img = img.resize((OUT, OUT), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
