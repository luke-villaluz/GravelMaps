"""GravelMaps command line.

  python -m gravelmaps run      # setup if needed, then serve (what run.py calls)
  python -m gravelmaps setup    # choose regions, download, build
  python -m gravelmaps serve    # start the web server only
"""
import argparse
import json
import os
import sys
import threading
import webbrowser

from . import build, fetch, graph
from .paths import CONFIG, DATA, pbf_path
from .regions import DEFAULT_REGIONS, US_STATES, parse_list


def load_config():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {}


def save_config(cfg):
    os.makedirs(DATA, exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


def ask_regions():
    print("\nWhich states should GravelMaps cover?")
    print("Available: " + ", ".join(US_STATES))
    print(f"Press Enter for the default: {', '.join(DEFAULT_REGIONS)}")
    print("(All six take about 2.5 GB of downloads and ~10 minutes to build.)")
    while True:
        text = input("States (comma-separated): ").strip()
        if not text:
            return list(DEFAULT_REGIONS)
        try:
            return parse_list(text)
        except ValueError as e:
            print(f"  {e}")


def setup(args):
    cfg = load_config()
    if args.regions:
        cfg["regions"] = parse_list(args.regions)
    elif not cfg.get("regions"):
        cfg["regions"] = ask_regions() if sys.stdin.isatty() else list(DEFAULT_REGIONS)
    save_config(cfg)
    regions = cfg["regions"]

    for r in regions:
        if args.update_data or not os.path.exists(pbf_path(r)):
            print(f"Downloading {r} ...")
            fetch.fetch(r, force=args.update_data)

    for r in regions:
        if args.rebuild or not build.is_fresh(r):
            print(f"Parsing {r} (one-time) ...")
            build.parse(r)

    if args.rebuild or not graph.is_fresh(regions):
        print("Building routing graph ...")
        graph.build(regions)
    return regions


def serve(args, regions=None):
    import uvicorn
    from .server import create_app

    regions = regions or load_config().get("regions")
    if not regions:
        sys.exit("No regions configured yet; run `python run.py` first.")
    app = create_app(regions)
    url = f"http://localhost:{args.port}"
    print(f"\nGravelMaps is running at {url}  (Ctrl+C to stop)\n")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def main():
    ap = argparse.ArgumentParser(prog="gravelmaps")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "setup", "serve"])
    ap.add_argument("--regions", help="comma-separated states, e.g. nevada,utah (saved for next time)")
    ap.add_argument("--rebuild", action="store_true", help="re-parse and rebuild the graph")
    ap.add_argument("--update-data", action="store_true", help="re-download fresh OSM data")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach it from your phone on the same Wi-Fi")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.command in ("run", "setup"):
        regions = setup(args)
        if args.command == "run":
            serve(args, regions)
    else:
        serve(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
