"""Dispersed camping along Forest Service roads, read from the forests' own Motor Vehicle Use Maps.

The live MVUM road data says who may drive a road but nothing about camping. That lives only on
the printed maps (GeoPDFs), in three forms:
  - a forest-wide rule in the map's notes ("motor vehicle use off of designated roads for the
    purpose of dispersed camping is permitted for up to 150 feet from the centerline ..."),
    or the opposite ("... is not permitted on the Cleveland National Forest");
  - a "Dispersed Camping" table listing road numbers and the distance allowed;
  - dots drawn beside individual roads (a marker-font glyph), on the left, right or both sides.

`build()` finds every MVUM PDF for the configured states, reads those three things, matches them
to the MVUM road lines (fetched once from the Forest Service), and saves one JSON file. Forests
whose maps say nothing about camping keep the standard rule: park within one vehicle length of
the road (36 CFR 261.54) and walk to camp.

Extra sources: the Eastern Sierra "No Dispersed Camping" areas (Camp Like a Pro, which covers the
Inyo, whose MVUMs are silent) and the Forest Service's listed dispersed camping areas.
"""
import concurrent.futures as cf
import datetime
import hashlib
import html
import json
import math
import os
import re
import threading
import time

import numpy as np
import requests

from . import USER_AGENT
from .paths import DATA

CAMP_DIR = os.path.join(DATA, "camping")
SHEET_DIR = os.path.join(CAMP_DIR, "sheets")  # one cached extraction per PDF
OUT = os.path.join(CAMP_DIR, "camping.json")

FS = "https://www.fs.usda.gov"
EDW = "https://apps.fs.usda.gov/arcx/rest/services/EDW"
AGOL = "https://services1.arcgis.com/gGHDlz6USftL5Pau/arcgis/rest/services"
ESSRP = "https://services7.arcgis.com/f7OwBgqAiLjK3YHc/arcgis/rest/services/No_Dispersed_Camping/FeatureServer/0"
FS_GAP_S = 1.0  # seconds between requests to www.fs.usda.gov

# Regions 4 and 5 publish an index of their MVUM PDFs with each map's footprint.
INDEXES = {"r4": f"{AGOL}/R4_MVUM_Footprints_PUBLIC_VIEW/FeatureServer/0",
           "r5": f"{AGOL}/R5_MVUM_Footprints_Public/FeatureServer/0"}
# Regions 3 and 6 don't, so their forests' map pages are read instead: (region, page slug, name, states).
FOREST_PAGES = [
    ("r03", "apache-sitgreaves", "Apache-Sitgreaves", {"arizona"}), ("r03", "coconino", "Coconino", {"arizona"}),
    ("r03", "coronado", "Coronado", {"arizona"}), ("r03", "kaibab", "Kaibab", {"arizona"}),
    ("r03", "prescott", "Prescott", {"arizona"}), ("r03", "tonto", "Tonto", {"arizona"}),
    ("r03", "carson", "Carson", {"new-mexico"}), ("r03", "cibola", "Cibola", {"new-mexico"}),
    ("r03", "gila", "Gila", {"new-mexico"}), ("r03", "lincoln", "Lincoln", {"new-mexico"}),
    ("r03", "santafe", "Santa Fe", {"new-mexico"}),
    ("r06", "columbiarivergorge", "Columbia River Gorge", {"oregon", "washington"}),
    ("r06", "colville", "Colville", {"washington"}), ("r06", "deschutes", "Deschutes", {"oregon"}),
    ("r06", "fremont-winema", "Fremont-Winema", {"oregon"}), ("r06", "giffordpinchot", "Gifford Pinchot", {"washington"}),
    ("r06", "malheur", "Malheur", {"oregon"}), ("r06", "mbs", "Mt. Baker-Snoqualmie", {"washington"}),
    ("r06", "mthood", "Mt. Hood", {"oregon"}), ("r06", "ochoco", "Ochoco", {"oregon"}),
    ("r06", "okanogan-wenatchee", "Okanogan-Wenatchee", {"washington"}), ("r06", "olympic", "Olympic", {"washington"}),
    ("r06", "rogue-siskiyou", "Rogue River-Siskiyou", {"oregon", "california"}), ("r06", "siuslaw", "Siuslaw", {"oregon"}),
    ("r06", "umatilla", "Umatilla", {"oregon", "washington"}), ("r06", "umpqua", "Umpqua", {"oregon"}),
    ("r06", "wallowa-whitman", "Wallowa-Whitman", {"oregon", "idaho"}), ("r06", "willamette", "Willamette", {"oregon"}),
]
# States of the Region 4 forests (Region 5 is all California).
R4_STATES = {
    "ashley": {"utah", "wyoming"}, "boise": {"idaho"}, "bridger": {"wyoming"}, "caribou": {"idaho", "wyoming", "utah"},
    "dixie": {"utah"}, "fishlake": {"utah"}, "humboldt": {"nevada", "california"}, "manti": {"utah", "colorado"},
    "payette": {"idaho"}, "salmon": {"idaho"}, "sawtooth": {"idaho", "utah"}, "uinta": {"utah", "wyoming", "idaho"},
}

DOT_NEAR_M = 250        # a camping dot belongs to a road this close (dots sit ~50-150 m off the line on paper)
DOT_COVER = 0.4         # share of a road's length that must have dots beside it
SAMPLE_M = 100          # road resolution for the dot check
ROADSIDE = ("Motor vehicles may be parked within one vehicle length from the edge of the road when it is safe "
            "to do so (36 CFR 261.54). No corridors for driving off the road to camp are designated on this map.")


# ---------- helpers ----------

def _session():
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _norm_forest(name):
    """'Mt. Baker-Snoqualmie National Forest' -> 'mtbakersnoqualmie', to match names between sources."""
    name = re.sub(r"national (forests?|scenic area|recreation area)|management unit|\bnf\b", "", name.lower())
    return re.sub(r"[^a-z]", "", name)


def _pip(x, y, ring):
    """Point in polygon (ray casting); ring is [[lon, lat], ...]."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polys(x, y, polys):
    return any(_pip(x, y, ring) for ring in polys)


def _arcgis_query(http, url, where="1=1", fields="*", geometry=True, offset_deg=None, page=2000):
    """All features of an ArcGIS layer as GeoJSON features, following pagination."""
    feats, start = [], 0
    while True:
        params = {"where": where, "outFields": fields, "returnGeometry": str(geometry).lower(), "outSR": 4326,
                  "geometryPrecision": 5, "resultOffset": start, "resultRecordCount": page, "f": "geojson"}
        if offset_deg:
            params["maxAllowableOffset"] = offset_deg
        for attempt in range(4):
            try:
                r = http.get(f"{url}/query", params=params, timeout=180)
                r.raise_for_status()
                fc = r.json()
                if "features" in fc:
                    break
                raise requests.RequestException(str(fc.get("error", fc))[:200])
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 + 3 * attempt)
        feats += fc["features"]
        more = fc.get("exceededTransferLimit") or fc.get("properties", {}).get("exceededTransferLimit")
        if len(fc["features"]) < page and not more:
            return feats
        start += len(fc["features"])
        if not fc["features"]:
            return feats


def _rings(geom):
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


# ---------- finding the PDFs ----------

def _indexed_sheets(http, states):
    """Region 4/5 MVUMs from their published indexes: url, forest, title and footprint."""
    out = []
    for region, url in INDEXES.items():
        for f in _arcgis_query(http, url, offset_deg=0.002):
            a = f["properties"]
            pdf = a.get("Download_URL") or a.get("View_URL")
            if not pdf or not pdf.lower().endswith(".pdf"):
                continue
            forest = (a.get("FOREST_NAME") or a.get("Forest_fullname") or "").strip()
            if region == "r5":
                sheet_states = {"california"}
            else:
                key = next((k for k in R4_STATES if forest.lower().startswith(k)), None)
                sheet_states = R4_STATES.get(key, set())
            if not sheet_states & states:
                continue
            title = " – ".join(t.strip() for t in (a.get("P_Title"), a.get("D_Title")) if t and t.strip())
            out.append({"url": pdf, "forest": forest, "title": title, "footprint": _rings(f["geometry"])})
    return out


def _page_sheets(http, states):
    """Region 3/6 MVUMs: every /media file linked from a forest's maps pages (checked later by content)."""
    out = []
    for region, slug, name, forest_states in FOREST_PAGES:
        if not forest_states & states:
            continue
        pages, seen, links = [f"{FS}/{region}/{slug}/maps-guides"], set(), {}
        while pages and len(seen) < 6:
            page = pages.pop(0)
            if page in seen:
                continue
            seen.add(page)
            try:
                r = _get(http, page)
            except requests.RequestException as e:
                print(f"  {name}: couldn't read {page} ({e})")
                continue
            for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
                text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())
                href = html.unescape(href)
                if href.startswith("/"):
                    href = FS + href
                if re.search(r"/media/\d+$|\.pdf$", href) and not re.search(r"avenza", href):
                    links.setdefault(href, text)
                elif re.search(r"mvum|motor-vehicle", href, re.I) and href.startswith(f"{FS}/{region}/{slug}/"):
                    pages.append(href)
        out += [{"url": u, "forest": name, "title": t, "footprint": [], "check": True} for u, t in links.items()]
    return out


# ---------- reading a PDF ----------

_SENT = re.compile(r"(?<=[a-z0-9)\]])\.\s+(?=[A-Z])")
_FEET = r"(\d{2,4})\s*(?:feet|ft)\b"


def _sentences(text):
    return [s.strip() for s in _SENT.split(text) if s.strip()]


# The rule itself, wherever it sits in the notes (legend text often runs into it with no full stop):
# "Motor vehicle use off of designated roads [and trails] for the purpose of dispersed camping is ..."
_RULE = re.compile(r"motor(?:ized)?\s*vehicle\s*use\s*off\s*(?:of\s*)?(?:the\s*)?designated\s*(roads?|trails?)"
                   r"((?:\s*(?:and/or|and|or|&)\s*(?:designated\s*)?trails?)?)([^.]{0,40}?)\s*for\s*the\s*purposes?\s*of\s*"
                   r"dispersed\s*camping(.*?)(?:\.(?=\s+[A-Z])|$)", re.I | re.S)
# Local exceptions: "Dispersed camping not allowed in the Grimes Creek along roads 261 and 364 ..."
_NOTE = re.compile(r"(?:no\s+dispersed\s+camping|dispersed\s+camping\s+(?:is\s+)?(?:not\s+(?:allowed|permitted)|prohibited))"
                   r"[^.]{0,250}", re.I)


def _camp_rules(text):
    """Forest-wide camping statements in a map's notes: rules with distances, a prohibition, local notes."""
    rules, prohibited = [], None
    for m in _RULE.finditer(text):
        s = m.group(0)[:600].strip()
        rest = m.group(4)
        if re.search(r"not\s+(?:be\s+)?(?:permitted|allowed)|prohibited", rest, re.I):
            prohibited = s
            continue
        if not re.search(r"permitted|allowed", rest, re.I):
            continue
        # "300 feet from the centerline of the road and 100 feet from the centerline of the trail"
        pairs = re.findall(_FEET + r"\s*(?:from|of)\s*(?:the\s*)?cent(?:er|re)\s*line\s*of\s*(?:the\s*|all\s*|a\s*)?"
                           r"(roads?|trails?)", s, re.I)
        if len(pairs) > 1:
            for ft, what in pairs:
                applies = "trails" if what.lower().startswith("trail") else "roads"
                rules.append({"applies": applies, "ft": int(ft), "text": s})
            continue
        ft = re.search(_FEET, rest, re.I)
        if not ft:
            continue
        subject, also_trails = m.group(1).lower(), bool(m.group(2).strip())
        applies = "both" if also_trails else ("trails" if subject.startswith("trail") else "roads")
        rules.append({"applies": applies, "ft": int(ft.group(1)), "text": s})
    notes = [" ".join(n.group(0).split()) for n in _NOTE.finditer(text)]
    seen, uniq = set(), []
    for r in rules:  # a map often repeats its notes on both sides
        key = (r["applies"], r["ft"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq, prohibited, list(dict.fromkeys(notes))[:6]


def _georef(doc, page):
    """The map frame's GeoPDF georeferencing: (bbox in PDF space, page-height, 3x3 homography to lon/lat)."""
    obj = doc.xref_object(page.xref, compressed=True)
    vp = obj.find("/VP")
    if vp < 0:
        return None
    best = None
    for m in re.finditer(r"/BBox\s*\[([^\]]*)\].*?/GPTS\s*\[([^\]]*)\](?:.*?/LPTS\s*\[([^\]]*)\])?", obj[vp:], re.S):
        bb = [float(v) for v in m.group(1).split()]
        g = [float(v) for v in m.group(2).split()]
        lp = [float(v) for v in m.group(3).split()] if m.group(3) else [0, 0, 0, 1, 1, 1, 1, 0]
        if len(bb) != 4 or len(g) < 8 or len(lp) < 8:
            continue
        area = abs((bb[2] - bb[0]) * (bb[3] - bb[1]))
        if best and best[0] >= area:
            continue  # several viewports (insets): keep the main map, the largest
        src = np.array(lp[:8]).reshape(4, 2)
        dst = np.array(g[:8]).reshape(4, 2)[:, ::-1]  # GPTS are lat, lon
        a = []
        for (u, v), (x, y) in zip(src, dst):
            a += [[u, v, 1, 0, 0, 0, -u * x, -v * x, x], [0, 0, 0, u, v, 1, -u * y, -v * y, y]]
        a = np.array(a)
        try:
            h = np.append(np.linalg.solve(a[:, :8], a[:, 8]), 1).reshape(3, 3)
        except np.linalg.LinAlgError:
            continue
        best = (area, bb, h)
    if not best:
        return None
    _, bb, h = best
    return bb, page.mediabox.height, h


def _to_geo(ref, x, y):
    bb, height, h = ref
    u = (x - bb[0]) / (bb[2] - bb[0])
    v = (height - y - bb[1]) / (bb[3] - bb[1])
    p = h @ [u, v, 1]
    return p[0] / p[2], p[1] / p[2]


def _frame(ref):
    bb, height, _ = ref
    corners = [(bb[0], height - bb[1]), (bb[2], height - bb[1]), (bb[2], height - bb[3]), (bb[0], height - bb[3])]
    ring = [list(map(lambda v: round(v, 5), _to_geo(ref, x, y))) for x, y in corners]
    return [ring + [ring[0]]]


def _dots(page, ref):
    """Camping corridor dots: small marker-font glyphs inside the map frame, as [lon, lat].

    Some maps draw other line symbols (trails open to motorcycles) with the same glyph, so each dot
    style (size and colour) counts only if its own samples in the legend, outside the map frame,
    are labelled for dispersed camping and nothing else."""
    bb, height, _ = ref
    x0, x1 = min(bb[0], bb[2]), max(bb[0], bb[2])
    y0, y1 = height - max(bb[1], bb[3]), height - min(bb[1], bb[3])

    def inside(cx, cy):
        return x0 <= cx <= x1 and y0 <= cy <= y1

    styles = {}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                if s["font"].startswith("ESRIDefaultMarker") and s["size"] <= 2.6 and s["chars"]:
                    styles.setdefault((round(s["size"], 1), s["color"]), []).append(s)
    if not styles:
        return []
    words = page.get_text("words")
    out = []
    for spans in styles.values():
        labels = set()
        for s in spans:
            cx, cy = (s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2
            if inside(cx, cy):
                continue  # on the map; legend samples sit outside the frame
            labels.add(" ".join(w[4] for w in words
                                if abs((w[1] + w[3]) / 2 - cy) < 5 and s["bbox"][2] - 2 < w[0] < s["bbox"][2] + 300))
        camping = any(re.search(r"dispersed|camping|game retrieval", t, re.I) for t in labels)
        other = any(re.search(r"motorcycle|open to|vehicles", t, re.I) and not re.search(r"dispersed|camping", t, re.I)
                    for t in labels)
        if not camping or other:
            continue
        for s in spans:
            for c in s["chars"]:
                cx, cy = (c["bbox"][0] + c["bbox"][2]) / 2, (c["bbox"][1] + c["bbox"][3]) / 2
                if inside(cx, cy):
                    lon, lat = _to_geo(ref, cx, cy)
                    out.append([round(lon, 5), round(lat, 5)])
    return out


def _tables(page):
    """'Dispersed Camping' tables: the road numbers in the box under the heading, and the distance."""
    import pymupdf
    out = []
    words = page.get_text("words")
    drawings = None
    for head in page.search_for("Dispersed Camping"):
        if drawings is None:
            drawings = [pymupdf.Rect(d["rect"]) for d in page.get_drawings() if d["rect"].height > 40]
        boxes = sorted((r for r in drawings if r.contains(head) and r.width < 900), key=lambda r: r.width * r.height)
        if not boxes:
            continue
        box = boxes[0]
        inside = [w for w in words if pymupdf.Rect(w[:4]).intersects(box) and w[1] >= head.y1 - 1]
        flat = [w for w in inside if (w[2] - w[0]) >= (w[3] - w[1]) * 0.8]  # skip rotated text
        ids = [w[4] for w in flat if re.fullmatch(r"\d{2,5}(?:-?[A-Z]{1,2}\d?)?", w[4])]
        text = " ".join(w[4] for w in sorted(inside, key=lambda w: (w[5], w[6], w[7])))
        m = re.search(_FEET + r"[^.]{0,60}", text, re.I)
        if len(ids) >= 3 and m:  # fewer is a legend box, not a table of roads
            side = re.search(r"\b(left|right|both)\b", text, re.I)
            out.append({"ids": list(dict.fromkeys(ids)), "ft": int(m.group(1)), "text": m.group(0).strip(),
                        "side": side.group(1).lower() if side else None})
    return out


def extract(path):
    """Everything about camping on one MVUM PDF."""
    import pymupdf
    doc = pymupdf.open(path)
    text, sheet = "", {"dots": [], "tables": [], "frame": []}
    for page in doc:
        page_text = " ".join(page.get_text().split())
        text += " " + page_text
        ref = _georef(doc, page)
        if ref:
            if not sheet["frame"]:
                sheet["frame"] = _frame(ref)
            sheet["dots"] += _dots(page, ref)
        if "Dispersed Camping" in page_text:
            sheet["tables"] += _tables(page)
    sheet["is_mvum"] = bool(re.search(r"motor\s*vehicle\s*use\s*map", text, re.I))
    sheet["has_text"] = len(text.strip()) > 200
    sheet["rules"], sheet["prohibited"], sheet["notes"] = _camp_rules(text)
    years = [int(y) for y in re.findall(r"\b(20[0-4]\d)\b", text) if 2005 <= int(y) <= datetime.date.today().year + 1]
    sheet["year"] = max(years) if years else None
    return sheet


def _sheet(http, s, refresh):
    """Download and read one PDF, cached by URL."""
    key = hashlib.sha1(s["url"].encode()).hexdigest()[:16]
    cache = os.path.join(SHEET_DIR, key + ".json")
    if os.path.exists(cache) and not refresh:
        with open(cache) as f:
            return {**s, **json.load(f)}
    tmp = os.path.join(SHEET_DIR, key + ".pdf")
    try:
        try:
            _download(http, s["url"], tmp)
        except requests.RequestException as e:
            # Not cached: fs.usda.gov turns away bursts of requests, so the next run tries again.
            return {**s, "is_mvum": False, "error": str(e)[:200], "retry": True}
        with open(tmp, "rb") as f:
            if f.read(5) != b"%PDF-":
                info = {"is_mvum": False, "error": "not a PDF"}
            else:
                info = extract(tmp)
    except Exception as e:  # a broken PDF shouldn't stop the build
        info = {"is_mvum": False, "error": str(e)[:200]}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    with open(cache, "w") as f:
        json.dump(info, f)
    return {**s, **info}


_fs_lock = threading.Lock()
_fs_last = [0.0]


def _polite(url):
    """One request at a time to www.fs.usda.gov, a second apart; other hosts go straight through."""
    if "fs.usda.gov/" not in url or "apps.fs.usda.gov" in url:
        return
    with _fs_lock:
        wait = _fs_last[0] + FS_GAP_S - time.time()
        if wait > 0:
            time.sleep(wait)
        _fs_last[0] = time.time()


def _get(http, url, **kw):
    """GET with backoff on the errors a busy or rate-limiting server gives (403/429/5xx)."""
    for attempt in range(4):
        _polite(url)
        r = http.get(url, timeout=300, **kw)
        if r.status_code in (403, 429) or r.status_code >= 500:
            r.close()
            if attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
        r.raise_for_status()
        return r


def _download(http, url, path):
    with _get(http, url, stream=True) as r:
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


# ---------- matching to roads ----------

def _segments(coords):
    c = np.asarray(coords, dtype=np.float64)
    return c[:-1], c[1:]


def _metres(lat):
    return 111320 * math.cos(math.radians(lat)), 110540


def _dot_cover(lines, grid, cell):
    """Share of a road's length with corridor dots beside it, and which side they're on."""
    hit = total = left = right = 0
    for line in lines:
        if len(line) < 2:
            continue
        a, b = _segments(line)
        kx, ky = _metres(a[0][1])
        seg = np.hypot((b[:, 0] - a[:, 0]) * kx, (b[:, 1] - a[:, 1]) * ky)
        for p, q, length in zip(a, b, seg):
            n = max(1, int(length // SAMPLE_M))
            for t in (np.arange(n) + 0.5) / n:
                x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
                total += 1
                cx, cy = int(x // cell), int(y // cell)
                near = [d for dx in (-1, 0, 1) for dy in (-1, 0, 1) for d in grid.get((cx + dx, cy + dy), ())]
                if not near:
                    continue
                d = np.asarray(near)
                dist = np.hypot((d[:, 0] - x) * kx, (d[:, 1] - y) * ky)
                close = d[dist < DOT_NEAR_M]
                if len(close):
                    hit += 1
                    cross = (q[0] - p[0]) * (close[:, 1] - p[1]) - (q[1] - p[1]) * (close[:, 0] - p[0])
                    left += int((cross > 0).sum())
                    right += int((cross < 0).sum())
    side = None
    if left or right:
        side = "both" if min(left, right) > 0.25 * (left + right) else ("left" if left > right else "right")
    return (hit / total if total else 0.0), side


def _id_matches(road_id, table_ids):
    """MVUM ids carry a district prefix the printed tables leave off: table '027A' is road '80027A'."""
    rid = (road_id or "").upper().replace("-", "")
    for t in table_ids:
        t = t.upper().replace("-", "")
        if rid == t or (rid.endswith(t) and 0 < len(rid) - len(t) <= 2 and rid[: len(rid) - len(t)].isdigit()):
            return True
    return False


def _lines(geom):
    if not geom:
        return []
    return geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]


def _match_forest(http, forest, sheets):
    """Camping status of each MVUM road and trail in one forest, from that forest's sheets."""
    roads = []
    has_specific = any(s["dots"] or s["tables"] for s in sheets)
    has_rule = any(s["rules"] or s["prohibited"] for s in sheets)
    if not (has_specific or has_rule):
        return roads
    # Dots from every georeferenced sheet of this forest, in a coarse grid.
    cell = 0.01
    grid = {}
    for s in sheets:
        for x, y in s["dots"]:
            grid.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
    where = "forestname = '" + forest.replace("'", "''") + "'"
    for layer, kind in ((1, "road"), (2, "trail")):
        feats = _arcgis_query(http, f"{EDW}/EDW_MVUM_01/MapServer/{layer}", where=where,
                              fields="id,name,symbol", offset_deg=0.00003)
        for f in feats:
            lines = _lines(f["geometry"])
            if not lines or not lines[0]:
                continue
            mid = lines[0][len(lines[0]) // 2]
            here = [s for s in sheets if not s["area"] or _in_polys(mid[0], mid[1], s["area"])] or sheets
            props = f["properties"]
            status = None
            for s in here:  # a forest-wide prohibition overrides everything on that map
                if s["prohibited"]:
                    status = {"s": "no", "src": s["i"]}
            if not status:
                for s in here:
                    for t in s["tables"]:
                        if _id_matches(props.get("id"), t["ids"]):
                            status = {"s": "yes", "ft": t["ft"], "side": t["side"], "how": "table", "src": s["i"]}
                            break
                    if status:
                        break
            if not status and grid:
                cover, side = _dot_cover(lines, grid, cell)
                if cover >= DOT_COVER:
                    src = next((s for s in here if s["dots"]), here[0])
                    ft = next((t["ft"] for t in src["tables"]), None) or next((r["ft"] for r in src["rules"]), None)
                    status = {"s": "yes", "ft": ft, "side": side, "how": "dots", "src": src["i"]}
            if not status:
                for s in here:
                    rule = next((r for r in s["rules"] if r["applies"] in ("both", kind + "s")), None)
                    if rule:
                        status = {"s": "yes", "ft": rule["ft"], "how": "rule", "src": s["i"]}
                        break
            if status:
                roads.append({"id": props.get("id"), "name": props.get("name"), "t": kind, **status,
                              "c": [[[round(x, 5), round(y, 5)] for x, y in ln] for ln in lines]})
    return roads


# ---------- extra sources ----------

def _essrp_zones(http):
    """Eastern Sierra areas where dispersed camping is not allowed (private, LADWP, parks, closures)."""
    zones = []
    for f in _arcgis_query(http, ESSRP, fields="OwnerDescr,Notes,description,Website", offset_deg=0.0003):
        a = f["properties"]
        rings = [[[round(x, 5), round(y, 5)] for x, y in r] for r in _rings(f["geometry"])]
        if rings:
            zones.append({"name": (a.get("description") or a.get("OwnerDescr") or "").strip(),
                          "note": (a.get("Notes") or "").strip(), "url": a.get("Website"), "rings": rings,
                          "src": "Eastern Sierra Sustainable Recreation Partnership (Camp Like a Pro)"})
    return zones


def _fs_sites(http, forests):
    """The Forest Service's listed dispersed camping areas, for the forests we cover."""
    want = {_norm_forest(f) for f in forests}
    out = []
    for f in _arcgis_query(http, f"{EDW}/EDW_RecreationOpportunities_01/MapServer/0",
                           where="markeractivity = 'Dispersed Camping'",
                           fields="recareaname,recareaurl,forestname,restrictions,feedescription"):
        a = f["properties"]
        if _norm_forest(a.get("forestname") or "") not in want or not f["geometry"]:
            continue
        x, y = f["geometry"]["coordinates"]
        out.append({"lat": round(y, 5), "lon": round(x, 5), "name": a.get("recareaname"), "url": a.get("recareaurl"),
                    "forest": a.get("forestname"),
                    "fees": re.sub(r"<[^>]+>", " ", a.get("feedescription") or "").strip()[:120]})
    return out


# ---------- the build ----------

def is_built():
    return os.path.exists(OUT)


def build(regions, refresh=False):
    """Read the MVUM PDFs for these states and write camping.json. `refresh` re-reads every PDF."""
    states = set(regions)
    os.makedirs(SHEET_DIR, exist_ok=True)
    http = _session()
    t0 = time.time()

    print("  finding Motor Vehicle Use Maps ...")
    found = _indexed_sheets(http, states) + _page_sheets(http, states)
    seen, todo = set(), []
    for s in found:
        if s["url"] not in seen:
            seen.add(s["url"])
            todo.append(s)
    print(f"  reading {len(todo)} PDFs (cached after the first time) ...")
    sheets, done = [], 0
    with cf.ThreadPoolExecutor(4) as ex:
        for s in ex.map(lambda s: _sheet(http, s, refresh), todo):
            done += 1
            if done % 25 == 0:
                print(f"    {done}/{len(todo)}")
            # Indexed maps are MVUMs by definition (a back side may never say so); crawled links must.
            if s.get("is_mvum") or (not s.get("check") and "error" not in s):
                sheets.append(s)

    # Name each sheet's forest as the road data does, and fix its area: the index footprint, else the GeoPDF frame.
    edw_names = {_norm_forest(name): name for name in _forest_names(http)}
    out_sheets = []
    for i, s in enumerate(sheets):
        key = _norm_forest(s["forest"])
        forest = edw_names.get(key) or next(
            (v for k, v in edw_names.items() if key and (k.startswith(key) or key.startswith(k))), s["forest"])
        out_sheets.append({
            "i": i, "forest": forest, "title": s["title"] or forest, "year": s.get("year"), "url": s["url"],
            "area": s["footprint"] or s["frame"], "rules": s["rules"], "prohibited": s["prohibited"],
            "notes": s["notes"], "tables": s["tables"], "dots": s["dots"], "has_text": s.get("has_text", True),
        })

    print("  matching camping rules to MVUM roads ...")
    by_forest = {}
    for s in out_sheets:
        by_forest.setdefault(s["forest"], []).append(s)
    roads = []
    for forest, fs in sorted(by_forest.items()):
        r = _match_forest(http, forest, fs)
        if r:
            print(f"    {forest}: {len(r):,} roads and trails with camping info")
        roads += r

    print("  extra sources: Eastern Sierra no-camping areas, Forest Service dispersed sites ...")
    try:
        zones = _essrp_zones(http) if "california" in states else []
    except requests.RequestException as e:
        print(f"    skipped Eastern Sierra areas ({e})")
        zones = []
    try:
        sites = _fs_sites(http, by_forest)
    except requests.RequestException as e:
        print(f"    skipped Forest Service sites ({e})")
        sites = []

    for s in out_sheets:  # the dots are only needed for matching
        s["dots"] = len(s["dots"])
        for t in s["tables"]:
            t["ids"] = len(t["ids"])
    data = {"built": datetime.date.today().isoformat(), "sheets": out_sheets, "roads": roads, "zones": zones, "sites": sites}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, OUT)
    n_rule = sum(1 for s in out_sheets if s["rules"] or s["prohibited"] or s["tables"] or s["dots"])
    print(f"  camping: {len(out_sheets)} MVUMs ({n_rule} with camping rules), {len(roads):,} roads and trails, "
          f"{len(zones)} no-camping areas, {len(sites)} listed sites in {time.time() - t0:.0f}s")


def _forest_names(http):
    params = {"where": "1=1", "outFields": "forestname", "groupByFieldsForStatistics": "forestname",
              "outStatistics": json.dumps([{"statisticType": "count", "onStatisticField": "objectid",
                                            "outStatisticFieldName": "n"}]),
              "f": "json"}
    r = http.get(f"{EDW}/EDW_MVUM_01/MapServer/1/query", params=params, timeout=120)
    r.raise_for_status()
    return [f["attributes"]["forestname"] for f in r.json().get("features", []) if f["attributes"].get("forestname")]


# ---------- serving ----------

class CampingIndex:
    """camping.json loaded for map-view queries and click lookups."""
    CELL = 0.05

    def __init__(self, path=OUT):
        self.ready = os.path.exists(path)
        data = {}
        if self.ready:
            with open(path) as f:
                data = json.load(f)
        self.built = data.get("built")
        self.sheets = data.get("sheets", [])
        self.roads = data.get("roads", [])
        self.zones = data.get("zones", [])
        self.sites = data.get("sites", [])
        self.grid = {}
        for i, r in enumerate(self.roads):
            xs = [p[0] for ln in r["c"] for p in ln]
            ys = [p[1] for ln in r["c"] for p in ln]
            r["bbox"] = (min(xs), min(ys), max(xs), max(ys))
            for cx in range(int(r["bbox"][0] // self.CELL), int(r["bbox"][2] // self.CELL) + 1):
                for cy in range(int(r["bbox"][1] // self.CELL), int(r["bbox"][3] // self.CELL) + 1):
                    self.grid.setdefault((cx, cy), []).append(i)
        for z in self.zones:
            xs = [p[0] for ring in z["rings"] for p in ring]
            ys = [p[1] for ring in z["rings"] for p in ring]
            z["bbox"] = (min(xs), min(ys), max(xs), max(ys))
        for s in self.sheets:
            pts = [p for ring in s["area"] for p in ring]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            s["bbox"] = (min(xs), min(ys), max(xs), max(ys)) if pts else None

    def in_bbox(self, s, w, n, e, limit=6000):
        """Roads with camping info, no-camping areas and listed sites in a map view."""
        idx = set()
        for cx in range(int(w // self.CELL), int(e // self.CELL) + 1):
            for cy in range(int(s // self.CELL), int(n // self.CELL) + 1):
                idx.update(self.grid.get((cx, cy), ()))
        roads = []
        for i in sorted(idx)[:limit]:
            r = self.roads[i]
            b = r["bbox"]
            if b[2] < w or b[0] > e or b[3] < s or b[1] > n:
                continue
            roads.append({k: r[k] for k in ("id", "name", "t", "s", "c")}
                         | {k: r[k] for k in ("ft", "side", "how", "src") if r.get(k) is not None})
        zones = [{k: z[k] for k in ("name", "note", "url", "rings", "src")} for z in self.zones
                 if not (z["bbox"][2] < w or z["bbox"][0] > e or z["bbox"][3] < s or z["bbox"][1] > n)]
        sites = [x for x in self.sites if s <= x["lat"] <= n and w <= x["lon"] <= e]
        return {"roads": roads, "zones": zones, "sites": sites}

    def at(self, lat, lon):
        """The MVUM sheets covering a point, newest first, and any no-camping area there."""
        hits = [sh for sh in self.sheets if sh["bbox"] and sh["bbox"][0] <= lon <= sh["bbox"][2]
                and sh["bbox"][1] <= lat <= sh["bbox"][3] and _in_polys(lon, lat, sh["area"])]
        hits.sort(key=lambda sh: -(sh["year"] or 0))
        fields = ("i", "forest", "title", "year", "url", "rules", "prohibited", "notes", "tables", "dots", "has_text")
        sheets = [{k: sh[k] for k in fields} for sh in hits[:4]]
        for sh in sheets:
            if not (sh["rules"] or sh["prohibited"] or sh["tables"] or sh["dots"]):
                sh["roadside"] = ROADSIDE
        zones = [{k: z[k] for k in ("name", "note", "url", "src")} for z in self.zones
                 if z["bbox"][0] <= lon <= z["bbox"][2] and z["bbox"][1] <= lat <= z["bbox"][3]
                 and _in_polys(lon, lat, z["rings"])]
        return {"sheets": sheets, "zones": zones, "built": self.built}

    def sheet(self, i):
        sh = self.sheets[i]
        return {k: sh[k] for k in ("forest", "title", "year", "url")}
