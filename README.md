# GravelMaps

A route planner that favors dirt, gravel and unpaved roads, built on OpenStreetMap data.
Routing runs on your own machine, and the app opens in your browser at `http://localhost:8000`.

## Requirements

- macOS or Linux
- Free disk for your map data: about 3 GB for California, less for any other state

No API keys or accounts. Python 3.10+ is used if you have it; if not, the installer downloads a
private copy.

## Install

Open Terminal (on a Mac: press Cmd+Space, type "Terminal", press Enter), paste this line and press
Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/luke-villaluz/GravelMaps/main/install.sh | bash
```

This downloads GravelMaps to `~/GravelMaps` and starts it. On the first start, press Enter to
choose "Start GravelMaps", then type the states you want as lowercase two-letter codes
separated by spaces (e.g. `ca` or `ca nv wa`) and press Enter. It downloads the map data and
builds the routes, which can take 10–20 minutes, and then the map opens in your browser.

After that, open a new terminal window any time and type `GravelMaps`.

To update, paste the same line again. Your map data is kept.

### With Git

```bash
git clone https://github.com/luke-villaluz/GravelMaps.git
GravelMaps/install.sh
```

If you move the repo folder, run `install.sh` again from its new location. Update with `git pull`.

## Usage

```bash
GravelMaps
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
GravelMaps --regions ca nv         # state codes; saved for next time
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
| `install.sh` | Creates the `GravelMaps` command in `~/.local/bin` |
| `run.py` | Launcher: creates the venv, installs deps, runs `python -m gravelmaps` |
| `gravelmaps/` | Python package: download, parsing, routing graph, router, map tiles, server |
| `static/` | Web front end (Leaflet) |
| `tests/` | pytest suite |
| `data/` | Downloaded and built data (not in git) |

## Notes

- Routing uses OSM tags only. Check Motor Vehicle Use Maps and land-manager closures before you go.
- Map data © OpenStreetMap contributors (ODbL). Tiles: Esri, OpenTopoMap. Overlays: BLM, USDA
  Forest Service. Search: Photon, Nominatim. Elevation: AWS Terrain Tiles.

## License

MIT. See [LICENSE](LICENSE). The license covers the code; map data and tiles keep their own terms above.
