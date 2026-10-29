# GravelMaps

A local, Google-Maps-style router that sticks to **dirt, gravel and unpaved roads** whenever it can,
uses pavement only to connect, and treats highways as a last resort. Built on OpenStreetMap data
and runs entirely on your machine. You open it in Chrome at `http://localhost:8000`.

Two vehicle profiles:

- **Car**: any legal road or track, including rough/4WD-only ones (slide *Rough / 4x4* down or to
  *Never* for a regular or AWD car). Never trails.
- **Dual Sport**: everything a car can use, plus singletrack and roads OSM marks open to
  motorcycles/OHVs/ATVs (`motorcycle=yes`, `ohv=yes`, `atv=yes`), and tracks that are too narrow or
  rough for a car. Untagged hiking paths are never used.

## Quick start

Needs Python 3.10+ and about 6 GB of free disk for all six default states.

```bash
git clone <this repo> GravelMaps
cd GravelMaps
python3 run.py
```

The first run:
1. creates a `.venv` and installs dependencies,
2. asks which states to cover (press Enter for WA, OR, CA, NV, AZ, UT),
3. downloads those states from [Geofabrik](https://download.geofabrik.de/) (~2.5 GB for all six),
4. builds the routing graph (a few minutes, one time),
5. opens your browser.

After that, `python3 run.py` starts in seconds.

### Options

```bash
python3 run.py --regions nevada,utah   # change states (any US state; saved for next time)
python3 run.py --update-data           # re-download fresh OSM data and rebuild
python3 run.py --rebuild               # rebuild from already-downloaded data
python3 run.py --port 8080 --no-browser
python3 run.py --host 0.0.0.0          # reach it from your phone on the same Wi-Fi
```

(Over plain HTTP on a LAN address, browsers block "use my location", so the location button only
works on `localhost`.)

## Using it

- Start typing a place and pick a suggestion, or click the map. Towns, peaks, campgrounds,
  trailheads, hot springs and gas stations come from the downloaded OSM data, so they show up
  instantly (even offline). Addresses fall back to an online geocoder.
- Type **"San Luis Obispo to Monterey"** in the start box and press Enter to set both ends at once.
  `lat, lon` works too.
- Drag markers to adjust. Click the route to add a stop, and click a stop's marker to remove it.
- **Route Style**: pick a preset (*Only Dirt*, *Mostly Dirt*, *Mixed*, *Paved Backroads*,
  *Highway*), or open **Customize Road Types** for a slider per road type, from *Never* through
  *Avoid*, *Neutral* and *Prefer*. All sliders at Neutral gives the plain fastest route.
- **Different style per leg**: with stops added, tabs appear for each leg (A → 1, 1 → B, …). Tap one
  to edit just that leg, e.g. Highway from SLO to Monterey and Only Dirt on the way back.
  *Apply to All Legs* copies the current leg's style everywhere.
- **Map / Satellite / Topo** in the top-right switches the basemap. Main roads are drawn with
  extra contrast so you can see where the big roads go. Zoomed in close (level 13+), GravelMaps also
  draws every dirt road, track and trail from its own OSM data in a muted line, since the basemaps
  leave most of them out.
- **Export GPX** to load the route into Gaia, onX, OsmAnd, a Garmin, etc.
- The URL holds the whole route, so you can bookmark it or send it to a friend running GravelMaps.

Route colors: orange = dirt/gravel, pink dashed = rough/4x4, green dotted = trail,
yellow = surface unknown (usually dirt in the rural West), blue = paved, purple = major road,
red = highway.

## How it works

| File | Role |
|---|---|
| `run.py` | stdlib-only bootstrap: venv, deps, then `python -m gravelmaps run` |
| `gravelmaps/fetch.py` | resumable Geofabrik download with md5 check |
| `gravelmaps/tags.py` | OSM tags → road class, surface (paved / unknown / unpaved), roughness, legality per vehicle |
| `gravelmaps/build.py` | pyosmium pass over each state's `.pbf` → `data/ways/<state>.npz` |
| `gravelmaps/graph.py` | merges states (deduping border-crossing ways), splits at intersections, builds a CSR graph + spatial grid as memory-mapped `.npy` files |
| `gravelmaps/profiles.py` | vehicles, road kinds, **presets**, and the cost formula |
| `gravelmaps/places.py` | offline place search (towns, peaks, campgrounds, gas…) built from the same OSM data |
| `gravelmaps/tiles.py` | renders the dirt-road overlay tiles from the routing graph |
| `gravelmaps/elevation.py` | elevation profiles from AWS Terrain Tiles (cached in `data/dem/`) |
| `gravelmaps/router.py` | numba-compiled A*, snapping clicks onto the nearest legal road, GeoJSON output |
| `gravelmaps/server.py` | FastAPI: `/api/route`, `/api/geocode` (offline places, then Photon/Nominatim), `/api/region`, static UI |
| `static/` | Leaflet front end |

### Tuning

Route cost is travel time scaled by the slider for that road kind: each 10 points above 50 makes a
road type "feel" twice as fast, each 10 below makes it feel twice as slow, and 0 forbids it. Edit
the presets or speeds in `gravelmaps/profiles.py` and restart; no rebuild needed. If you change `gravelmaps/tags.py`, bump `PARSE_VERSION` so the state
caches are rebuilt.

### Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

## Caveats

- Private, closed, permit-only and abandoned roads are never used. Gates tagged locked or private,
  bollards, concrete blocks and chains block the road; ordinary unlocked gates (cattle gates) don't.
- OSM is only as good as its mappers. A gate that's locked in real life but not tagged that way
  will still be routed through, many rural roads have no surface tag (shown as "surface unknown"),
  and seasonal closures and washouts aren't known. **Check MVUMs and land-manager closures before
  you go.**
- Trail legality comes from OSM tags only. When in doubt, the dirt bike profile leaves a trail out.

Map data © OpenStreetMap contributors (ODbL). Tiles: Esri, OpenTopoMap. Search: Photon (Komoot), Nominatim.
