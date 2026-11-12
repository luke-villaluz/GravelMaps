"""Saved settings (data/config.json): which states GravelMaps covers."""
import json
import os

from .paths import CONFIG, DATA


def load_config():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {}


def save_config(cfg):
    os.makedirs(DATA, exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG)
