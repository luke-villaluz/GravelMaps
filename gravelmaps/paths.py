"""Locations of downloaded and generated data.

From a checkout, data lives in data/ next to the code. In the packaged Mac app the code sits
inside the read-only app bundle, so data goes to ~/Library/Application Support/GravelMaps (kept
when the app is updated or reinstalled). GRAVELMAPS_DATA overrides either.
"""
import hashlib
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))  # running from the PyInstaller app bundle

if FROZEN:
    ROOT = sys._MEIPASS
    _default_data = os.path.expanduser("~/Library/Application Support/GravelMaps")
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _default_data = os.path.join(ROOT, "data")

DATA = os.environ.get("GRAVELMAPS_DATA") or _default_data
CONFIG = os.path.join(DATA, "config.json")
STATIC = os.path.join(ROOT, "static")

if FROZEN:
    # numba caches compiled code next to the source by default, which is inside the bundle.
    os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(DATA, "numba-cache"))


def pbf_path(region):
    return os.path.join(DATA, "pbf", f"{region}-latest.osm.pbf")


def ways_path(region):
    return os.path.join(DATA, "ways", f"{region}.npz")


def graph_dir(regions):
    key = hashlib.sha1(",".join(sorted(regions)).encode()).hexdigest()[:12]
    return os.path.join(DATA, "graphs", key)
