"""Setup: download map data and build everything GravelMaps needs for a set of states.

Shared by the terminal (`python -m gravelmaps setup`) and the app's setup screen, which follow
along through a Reporter.
"""
import os
import sys

import requests

from . import basemap, build, fetch, graph
from .paths import pbf_path


class Reporter:
    """Prints progress to the terminal. The app's setup screen swaps in its own (see setupjob.py)."""

    def step(self, key, title):
        print(f"{title} ...", flush=True)

    def progress(self, done, total):
        """Bytes so far in the current download."""
        sys.stdout.write(f"\r  {done / 1e6:,.0f} / {total / 1e6:,.0f} MB ({done * 100 / max(total, 1):.0f}%)")
        sys.stdout.flush()
        if done >= total:
            print()

    def warn(self, message):
        print(f"  {message}", flush=True)


def steps(regions, update_data=False, rebuild=False):
    """What run() will do, as (key, title) pairs: lets a UI show the whole list up front."""
    out = []
    for r in regions:
        if update_data or not os.path.exists(pbf_path(r)):
            out.append((f"fetch:{r}", f"Downloading {_name(r)} road data"))
    for r in regions:
        if rebuild or update_data or not build.is_fresh(r):
            out.append((f"parse:{r}", f"Reading {_name(r)} roads (one-time)"))
    if rebuild or update_data or not graph.is_fresh(regions):
        out.append(("graph", "Building the routing graph"))
    if update_data or not basemap.is_built(regions):
        out.append(("basemap", "Downloading the offline map"))
    from . import elevation
    if not os.path.exists(elevation.heights_path(regions)):
        out.append(("elevation", "Scoring road elevations"))
    from . import camping
    if not camping.is_built():
        out.append(("camping", "Reading Forest Service camping rules"))
    return out


def run(regions, update_data=False, rebuild=False, report=None):
    report = report or Reporter()
    for key, title in steps(regions, update_data, rebuild):
        report.step(key, title)
        kind, _, region = key.partition(":")
        if kind == "fetch":
            fetch.fetch(region, force=update_data, progress=report.progress)
        elif kind == "parse":
            build.parse(region)
        elif kind == "graph":
            graph.build(regions)
        elif kind == "basemap":
            if update_data and basemap.is_built(regions):
                os.remove(basemap.path_for(regions))
            basemap.build(regions, progress=report.progress)
        elif kind == "elevation":
            _elevation(regions, report)
        elif kind == "camping":
            build_camping(regions, refresh=False, report=report)
    return regions


def _elevation(regions, report):
    # Terrain for the High Elevation slider. Optional: without it that slider is just hidden.
    from . import elevation
    try:
        elevation.build_edge_heights(regions)
    except requests.RequestException as e:
        report.warn(f"skipped, couldn't download terrain ({e}); the High Elevation slider stays off.")
    except Exception as e:  # optional: never let it stop GravelMaps from starting
        report.warn(f"skipped ({type(e).__name__}: {e}); the High Elevation slider stays off.")


def build_camping(regions, refresh, report=None):
    # Dispersed camping rules from the forests' MVUM PDFs. Optional: without it that overlay is hidden.
    from . import camping
    report = report or Reporter()
    try:
        camping.build(regions, refresh=refresh)
    except requests.RequestException as e:
        report.warn(f"skipped, couldn't reach the Forest Service ({e}); the camping overlay stays off.")
    except Exception as e:  # optional: never let it stop GravelMaps from starting
        report.warn(f"skipped ({type(e).__name__}: {e}); the camping overlay stays off.")


def _name(region):
    return region.replace("-", " ").title()
