"""GravelMaps command line.

  python -m gravelmaps          # interactive menu when run in a terminal with no arguments
  python -m gravelmaps run      # setup if needed, then serve
  python -m gravelmaps setup    # choose regions, download, build
  python -m gravelmaps serve    # start the web server only
  python -m gravelmaps camping  # re-read the Forest Service MVUMs for dispersed camping
  python -m gravelmaps desktop  # the Mac app: its own window, setup screen included
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from . import pipeline
from .config import load_config, save_config
from .regions import HOW_TO, codes, parse_list


def ask_regions():
    print("\nWhich states should GravelMaps cover?")
    print(HOW_TO + "  (dc and pr work too)")
    print("(Downloads are up to 1.3 GB per state; California is the largest.)")
    while True:
        text = input("States: ").strip()
        if not text:
            print("  Enter at least one state.")
            continue
        try:
            return parse_list(text)
        except ValueError as e:
            print(f"  {e}")


def setup(args):
    cfg = load_config()
    if args.regions:
        try:
            cfg["regions"] = parse_list(" ".join(args.regions))
        except ValueError as e:
            sys.exit(str(e))
    elif not cfg.get("regions"):
        if not sys.stdin.isatty():
            sys.exit("No states chosen yet; run again with --regions, e.g. --regions ca nv")
        cfg["regions"] = ask_regions()
    save_config(cfg)
    return pipeline.run(cfg["regions"], update_data=args.update_data, rebuild=args.rebuild)


def open_browser(url):
    # Prefer Chrome on macOS; fall back to whatever the default browser is.
    if sys.platform == "darwin":
        r = subprocess.run(["open", "-a", "Google Chrome", url], capture_output=True)
        if r.returncode == 0:
            return
    webbrowser.open(url)


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # UDP connect sends nothing; it just picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return None


def free_port(port):
    """Stop whatever is already listening on `port` (usually a GravelMaps left running elsewhere)."""
    try:
        r = subprocess.run(["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)
    except FileNotFoundError:
        return
    pids = [int(p) for p in r.stdout.split() if int(p) != os.getpid()]
    for pid in pids:
        print(f"Stopping the process already using port {port} (pid {pid}) ...")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + 5
    while pids and time.time() < deadline:
        time.sleep(0.1)
        pids = [p for p in pids if alive(p)]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def serve(args, regions=None):
    import uvicorn

    from .server import Shell

    # With no map data yet, the page opens on the setup screen instead.
    app = Shell(regions or load_config().get("regions"))
    free_port(args.port)
    url = f"http://localhost:{args.port}"
    print(f"\nGravelMaps is running at {url}")
    if args.host == "0.0.0.0" and (ip := lan_ip()):
        print(f"On your phone (same Wi-Fi): http://{ip}:{args.port}")
    interactive = sys.stdin.isatty()
    print("Type q and press Enter to stop.\n" if interactive else "Press Ctrl+C to stop.\n")
    if not args.no_browser:
        timer = threading.Timer(1.0, open_browser, [url])
        timer.daemon = True
        timer.start()
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning"))
    if interactive:
        threading.Thread(target=wait_for_quit, args=(server,), daemon=True).start()
    server.run()
    print("GravelMaps stopped.")


def wait_for_quit(server):
    for line in sys.stdin:
        if line.strip().lower() == "q":
            server.should_exit = True
            return
        print("Type q and press Enter to stop.")


MENU = [
    ("Start GravelMaps", "open the map in Chrome", ["run"]),
    ("Start for phone", "also reachable from devices on your Wi-Fi", ["run", "--host", "0.0.0.0"]),
    ("Change states", "pick which states to cover, then start", "regions"),
    ("Update map data", "re-download fresh OSM data, rebuild, then start", ["run", "--update-data"]),
    ("Rebuild", "rebuild from already-downloaded data, then start", ["run", "--rebuild"]),
    ("Refresh camping data", "re-read every Forest Service MVUM PDF", ["camping", "--refresh"]),
    ("Quit", "", None),
]


def menu_argv():
    from .menu import choose

    regions = load_config().get("regions")
    title = "GravelMaps" + (f"  ·  covering {' '.join(codes(regions))}" if regions else "")
    i = choose(title, [(label, hint) for label, hint, _ in MENU])
    argv = None if i is None else MENU[i][2]
    if argv == "regions":
        argv = ["run", "--regions", *codes(ask_regions())]
    return argv


def main():
    argv = sys.argv[1:]
    if not argv and sys.stdin.isatty():
        argv = menu_argv()
        if argv is None:
            return

    ap = argparse.ArgumentParser(prog="gravelmaps")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "setup", "serve", "camping", "desktop"])
    ap.add_argument("--regions", nargs="+", metavar="CODE", help="state codes, e.g. ca nv (saved for next time)")
    ap.add_argument("--rebuild", action="store_true", help="re-parse and rebuild the graph")
    ap.add_argument("--update-data", action="store_true", help="re-download fresh OSM data")
    ap.add_argument("--refresh", action="store_true", help="with `camping`: download and re-read every MVUM PDF")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach it from your phone on the same Wi-Fi")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--self-test", action="store_true", help="with `desktop`: start, answer one request, quit")
    args = ap.parse_args(argv)

    if args.command == "desktop":
        from . import desktop
        desktop.main(self_test=args.self_test)
    elif args.command == "camping":
        regions = load_config().get("regions")
        if not regions:
            sys.exit("No regions configured yet; run `GravelMaps` first.")
        pipeline.build_camping(regions, refresh=args.refresh)
    elif args.command in ("run", "setup"):
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
