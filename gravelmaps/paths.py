"""Locations of downloaded and generated data."""
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CONFIG = os.path.join(DATA, "config.json")
STATIC = os.path.join(ROOT, "static")


def pbf_path(region):
    return os.path.join(DATA, "pbf", f"{region}-latest.osm.pbf")


def ways_path(region):
    return os.path.join(DATA, "ways", f"{region}.npz")


def graph_dir(regions):
    key = hashlib.sha1(",".join(sorted(regions)).encode()).hexdigest()[:12]
    return os.path.join(DATA, "graphs", key)
