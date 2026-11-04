# GravelMaps

An offline route planner that favors dirt, gravel and unpaved roads, built on OpenStreetMap data.
It runs locally and opens in your browser at `http://localhost:8000`.

## Requirements

- macOS or Linux
- Python 3.10+
- Git
- About 6 GB of free disk for the six default states (WA, OR, CA, NV, AZ, UT)

## Install

```bash
git clone https://github.com/luke-villaluz/GravelMaps.git
cd GravelMaps
python3 run.py
```

The first run creates a `.venv`, installs dependencies, asks which states to cover, downloads them
from [Geofabrik](https://download.geofabrik.de/) and builds the routing graph. This takes a few
minutes. Later starts take seconds. You don't need to activate the venv yourself.

### Optional: a `GravelMaps` command

To run it from any directory:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/run.py" ~/.local/bin/GravelMaps
```

`~/.local/bin` must be on your `PATH`. If you move the repo, run the `ln` command again with `-sf`.

## Usage

```bash
GravelMaps        # or: python3 run.py
```

This opens a menu:

| Option | What it does |
|---|---|
| Start GravelMaps | Starts the server and opens it in Chrome |
| Start for phone | Same, but reachable from other devices on your Wi-Fi |
| Change states | Picks which states to cover, then starts |
| Update map data | Re-downloads OSM data, rebuilds, then starts |
| Rebuild | Rebuilds from already-downloaded data, then starts |
| Refresh camping data | Re-reads the Forest Service MVUM PDFs |

Type `q` and press Enter to stop the server. If something is already using the port, it's stopped first.

### Flags

Flags skip the menu:

```bash
GravelMaps --regions nevada,utah   # any US states; saved for next time
GravelMaps --update-data           # re-download OSM data and rebuild
GravelMaps --rebuild               # rebuild from downloaded data
GravelMaps --host 0.0.0.0          # reachable on your local network
GravelMaps --port 8080 --no-browser
GravelMaps serve                   # start the server without setup checks
GravelMaps camping --refresh       # re-read the MVUM PDFs
```

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

## Project layout

| Path | Contents |
|---|---|
| `run.py` | Launcher: creates the venv, installs deps, runs `python -m gravelmaps` |
| `gravelmaps/` | Python package: download, parsing, routing graph, router, map tiles, server |
| `static/` | Web front end (Leaflet) |
| `tests/` | pytest suite |
| `data/` | Downloaded and built data (not in git) |

## Notes

- Routing uses OSM tags only. Check Motor Vehicle Use Maps and land-manager closures before you go.
- Map data © OpenStreetMap contributors (ODbL). Tiles: Esri, OpenTopoMap. Overlays: BLM, USDA
  Forest Service. Search: Photon, Nominatim. Elevation: AWS Terrain Tiles.
