# GravelMaps

[![CI](https://github.com/luke-villaluz/GravelMaps/actions/workflows/ci.yml/badge.svg)](https://github.com/luke-villaluz/GravelMaps/actions/workflows/ci.yml)

A route planner that favors dirt, gravel and unpaved roads, built on OpenStreetMap data.
Everything runs on your own Mac, and once the maps are downloaded it works with no internet:
the map, routing, place search, typed coordinates and dispersed camping info.

## Get the Mac app

1. Download the DMG for your Mac from the [latest release](https://github.com/luke-villaluz/GravelMaps/releases/latest):
   **GravelMaps-arm64.dmg** for Apple Silicon (M1 and later), **GravelMaps-x86_64.dmg** for Intel
   (Apple menu → About This Mac shows which you have).
2. Open it and drag **GravelMaps** onto **Applications**.
3. Open GravelMaps. The first time, macOS says it can't verify the app, because GravelMaps is free
   and not registered with Apple. Open **System Settings → Privacy & Security**, scroll down, click
   **Open Anyway**, and confirm. You only do this once.
4. Pick your states. GravelMaps downloads their maps once (about 1–2 GB and 10–30 minutes per
   state), and from then on works offline.

To keep it in the Dock, right-click its Dock icon → Options → Keep in Dock. New versions install
themselves from inside the app ("New version available"), and your map data is kept.

### What works offline

| Works offline | Needs internet |
|---|---|
| The street map (downloaded during setup), routing, GPX export | Satellite and Topo basemaps |
| Search for towns, peaks, trailheads, campgrounds… | Street-address search |
| Typed coordinates, e.g. `38.5733, -109.5498` or Garmin's `N38 34.398 W109 32.988` | Public land, wilderness, forest and MVUM overlays |
| Dispersed camping rules, gas stations, points of interest | Elevation profiles of areas you haven't routed before |

Features that need internet are greyed out while you're offline and come back on their own.

## Install from the terminal (macOS or Linux)

The app above is the easy way on a Mac. The terminal version also runs on Linux and opens in your
browser at `http://localhost:8000`.

- Free disk for your map data: about 4 GB for California, less for any other state
- No API keys or accounts. Python 3.10+ is used if you have it; if not, the installer downloads a
  private copy.

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

## Development

Edit the code, then see it in the app: `install.sh --app` makes a **GravelMaps (Dev)** app in
`~/Applications` that runs straight from this checkout (keep it in the Dock; reopen it to pick up
changes). `python run.py desktop` does the same from the terminal. Releasing a new version for
everyone else is a tag push; see [RELEASING.md](RELEASING.md).


```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .                   # Python lint
.venv/bin/python -m pytest               # Python tests
npx eslint@10.14.0 static/js tests/js    # front-end lint (needs Node)
node --test "tests/js/*.test.mjs"        # front-end tests
```

GitHub Actions runs all of these on every push, on Linux and macOS (Apple Silicon and Intel), and
also tests `install.sh`.

## Project layout

| Path | Contents |
|---|---|
| `install.sh` | Creates the `GravelMaps` command in `~/.local/bin` |
| `run.py` | Launcher: creates the venv, installs deps, runs `python -m gravelmaps` |
| `gravelmaps/` | Python package: download, parsing, routing graph, router, map tiles, server |
| `static/` | Web front end: `index.html`, `setup.html`, `style.css`, ES modules in `js/` (entry point `js/main.js`), and Leaflet, protomaps-leaflet and Roboto in `vendor/` |
| `tests/` | pytest suite, plus Node tests for the front end in `tests/js/` |
| `packaging/` | Mac app build: PyInstaller recipe, icon, DMG contents |
| `data/` | Downloaded and built data (not in git) |

## Notes

- Routing uses OSM tags only. Check Motor Vehicle Use Maps and land-manager closures before you go.
- Map data © OpenStreetMap contributors (ODbL). Offline map: [Protomaps](https://protomaps.com) (OpenStreetMap data). Online tiles: Esri, OpenTopoMap. Overlays: BLM, USDA
  Forest Service. Search: Photon, Nominatim. Elevation: AWS Terrain Tiles.

## License

MIT. See [LICENSE](LICENSE). The license covers the code; map data and tiles keep their own terms above.
