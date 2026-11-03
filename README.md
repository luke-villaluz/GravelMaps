# GravelMaps

A local, Google-Maps-style router that sticks to **dirt, gravel and unpaved roads** whenever it can,
uses pavement only to connect, and treats highways as a last resort. Built on OpenStreetMap data
and runs entirely on your machine. You open it in Chrome at `http://localhost:8000`.

Two vehicle profiles:

- **Car**: any legal road or track, including rough/4WD-only ones (slide *Rough / 4x4* down or to
  *Never* for a regular or AWD car). Never trails.
- **Dual Sport**: everything a car can use, plus singletrack and roads OSM marks open to
  motorcycles/OHVs/ATVs (`motorcycle=yes`, `ohv=yes`, `atv=yes`), and tracks that are too narrow or
  rough for a car. Untagged hiking paths are never used. All of these bike-only ways share the
  *Singletrack / OHV* slider, which only appears for Dual Sport legs.

## Quick start

Needs Python 3.10+ and about 6 GB of free disk for all six default states.

```bash
git clone <this repo> GravelMaps
cd GravelMaps
ln -s "$PWD/run.py" ~/.local/bin/GravelMaps   # optional: a `GravelMaps` command that works from any directory
GravelMaps                                    # or: python3 run.py
```

With no arguments it shows a menu (start, start for your phone, change states, update or rebuild data,
refresh camping). Starting the server opens the map in Chrome (or your default browser if Chrome isn't
installed); type `q` and press Enter in the terminal to stop it. No need to activate the venv yourself.

The first run:
1. creates a `.venv` and installs dependencies,
2. asks which states to cover (press Enter for WA, OR, CA, NV, AZ, UT),
3. downloads those states from [Geofabrik](https://download.geofabrik.de/) (~2.5 GB for all six),
4. builds the routing graph (a few minutes, one time),
5. opens your browser.

After that, starting takes seconds.

### Options

Every menu item is also a flag, which skips the menu (`GravelMaps` and `python3 run.py` are interchangeable):

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
- **High Elevation** (the last slider) works on how high up a road is instead of what it's made of:
  slide right to seek ridgelines, passes and summit roads, left to stay low (snow season). The
  *High Country* preset is Mostly Dirt plus a strong pull uphill. "High" means well above the
  nearby valley floor or above ~6,000 ft, from free terrain tiles (~50 MB, downloaded once during
  setup).
- **Different style per leg**: with stops added, tabs appear for each leg (A → 1, 1 → B, …). Tap one
  to edit just that leg, e.g. Highway from SLO to Monterey and Only Dirt on the way back.
  *Apply to All Legs* copies the current leg's style everywhere.
- **Different vehicle per leg**: the Car / Dual Sport tabs set the vehicle for the leg you're
  editing, so you can drive the truck to a trailhead and ride the bike from there. The turn list
  marks the stop where you switch.
- **Map / Satellite / Topo** at the top of the map switches the basemap. Main roads are redrawn in
  Google Maps colors (yellow highways, white major roads) so you can see where the big roads go. Zoomed in close (level 12+), GravelMaps also
  draws every dirt road, track and trail from its own OSM data in a muted line, since the basemaps
  leave most of them out.
- **Overlays** (the *Map Overlays* card, top right, under the markers) come straight from the land agencies'
  free map services, so they need an internet connection:
  - *Public land*: who manages the land (BLM, Forest Service, National Park, state, military,
    tribal…), in the BLM's colors, with a key. Private land is left clear.
  - *Wilderness areas* (no motor vehicles or bikes) and *Forest boundaries*.
  - *MVUM roads & trails* (zoom 10+): the Forest Service's Motor Vehicle Use Maps. Click a road or
    trail for the vehicle classes allowed (cars, high-clearance, UTVs, ATVs, motorcycles) and the
    dates open. Not every forest publishes MVUM data (e.g. the Okanogan-Wenatchee doesn't).
    The popup also says what that forest's printed map allows for camping along its roads.
  - *Dispersed camping* (zoom 9+, works offline): where you may drive off a forest road to camp,
    read from each forest's printed MVUM PDFs by `python -m gravelmaps camping` (run once during
    setup; add `--refresh` to re-download every PDF). The live MVUM data has no camping fields, so
    this reads the maps themselves: forest-wide rules in their notes ("up to 150 feet from the
    centerline of all roads", or "not permitted"), the *Dispersed Camping* tables of road numbers,
    and the camping dots printed beside individual roads (matched to the road lines via the GeoPDF
    coordinates). Yellow lines allow it (click for the distance, side and source map), red lines are
    on forests that prohibit it, red areas are Eastern Sierra no-camping land (private, LADWP,
    parks), and yellow dots are the Forest Service's listed dispersed camping areas. Roads that
    aren't drawn are on maps with no corridors: park within one vehicle length and walk to camp.
    Coverage follows what the forests print, e.g. the Inyo's MVUMs say nothing about camping; some
    older maps are scans with no readable text.
- **Map Markers** (the card at the top right, above the overlays) is both the key and the filter for the map's pins.
  Click a marker type to show or hide it, or a heading (Gas, Water, Camping, Trailheads, Sights)
  for the whole group. The switch next to the title unchecks (or checks) every type at once, so you
  can turn everything off and then click just the ones you want, like Ruins or Gas. Pins show at every zoom level; zoomed out, overlapping pins are thinned
  to the most useful one (named places and camping first). All from OSM, so coverage varies:
  - *Gas*: tap a station for brand, hours and diesel, and *Add as stop* to route through it.
    Each route lists the gas within a mile of it by mile marker, plus the longest stretch without
    gas (highlighted over 100 mi, since that's about a small dual sport's range).
  - *Water*: drinking water, fill stations and springs (springs say whether they're tagged potable).
  - *Camping*: campgrounds (orange), **dispersed camping** (green with a dashed ring), RV parks and
    backcountry cabins, with fee, toilets and water when mapped.
  - *Trailheads*: trailheads (brown) and **OHV staging areas** (red, with a motorcycle), picked out
    by name ("Staging", "OHV") or OHV/motorcycle access tags.
  - *Sights*: ghost towns, mines, ruins, petroglyphs, hot springs, viewpoints, peaks (with
    elevation), fire lookouts, arches and caves.
- **Export GPX** to load the route into Gaia, onX, OsmAnd, a Garmin, etc.
- The URL holds the whole route, so you can bookmark it or send it to a friend running GravelMaps.

Route colors: orange = dirt/gravel, pink dashed = rough/4x4, green dotted = singletrack/OHV,
yellow = surface unknown (usually dirt in the rural West), blue = paved, purple = major road,
red = highway.

## How it works

| File | Role |
|---|---|
| `run.py` | stdlib-only bootstrap: venv, deps, then `python -m gravelmaps` (menu with no args) |
| `gravelmaps/menu.py` | arrow-key launcher menu |
| `gravelmaps/fetch.py` | resumable Geofabrik download with md5 check |
| `gravelmaps/tags.py` | OSM tags → road class, surface (paved / unknown / unpaved), roughness, legality per vehicle |
| `gravelmaps/build.py` | pyosmium pass over each state's `.pbf` → `data/ways/<state>.npz` |
| `gravelmaps/graph.py` | merges states (deduping border-crossing ways), splits at intersections, builds a CSR graph + spatial grid as memory-mapped `.npy` files |
| `gravelmaps/profiles.py` | vehicles, road kinds, **presets**, and the cost formula |
| `gravelmaps/places.py` | offline place search (towns, peaks, campgrounds, gas…) built from the same OSM data |
| `gravelmaps/tiles.py` | renders the dirt-road overlay tiles from the routing graph |
| `gravelmaps/elevation.py` | elevation profiles from AWS Terrain Tiles (cached in `data/dem/`) |
| `gravelmaps/camping.py` | reads the Forest Service MVUM PDFs (Region 4/5 indexes, Region 3/6 forest pages) for camping rules, tables and dots → `data/camping/camping.json` |
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

Map data © OpenStreetMap contributors (ODbL). Tiles: Esri, OpenTopoMap. Overlays: BLM, USDA Forest Service. Search: Photon (Komoot), Nominatim.
