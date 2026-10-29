"""Download Geofabrik .osm.pbf extracts with resume and md5 verification."""
import hashlib
import os
import sys
import time

import requests

from .paths import pbf_path
from .regions import url_for

CHUNK = 1 << 20
ATTEMPTS = 6


def _progress(region, done, total):
    if total:
        pct = done * 100 / total
        sys.stdout.write(f"\r  {region}: {done / 1e6:,.0f} / {total / 1e6:,.0f} MB ({pct:.0f}%)")
    else:
        sys.stdout.write(f"\r  {region}: {done / 1e6:,.0f} MB")
    sys.stdout.flush()


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK * 8), b""):
            h.update(block)
    return h.hexdigest()


def fetch(region, force=False):
    """Download the extract for `region` unless it is already complete. Returns the file path."""
    dest = pbf_path(region)
    url = url_for(region)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"

    if os.path.exists(dest) and not force:
        return dest

    for attempt in range(1, ATTEMPTS + 1):
        try:
            _download(region, url, part)
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
            if attempt == ATTEMPTS:
                raise RuntimeError(f"Download of {region} kept failing ({e}). Run again to resume.") from None
            print(f"\n  connection dropped, resuming ({attempt}/{ATTEMPTS - 1}) ...")
            time.sleep(3 * attempt)

    expected = requests.get(url + ".md5", timeout=60)
    if expected.ok:
        want = expected.text.split()[0]
        if _md5(part) != want:
            os.remove(part)
            raise RuntimeError(f"Checksum mismatch for {region}; deleted the partial file, please run again.")
    os.replace(part, dest)
    return dest


def _download(region, url, part):
    done = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with requests.get(url, stream=True, headers=headers, timeout=60) as r:
        if r.status_code == 416:  # .part is already complete
            return
        r.raise_for_status()
        if done and r.status_code != 206:  # server ignored the Range header
            done = 0
        total = int(r.headers.get("Content-Length", 0)) + done
        with open(part, "ab" if done else "wb") as f:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)
                done += len(chunk)
                _progress(region, done, total)
        print()
