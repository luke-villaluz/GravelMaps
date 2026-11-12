"""Download Geofabrik .osm.pbf extracts with resume and md5 verification."""
import hashlib
import os
import sys
import time

import requests

from . import USER_AGENT
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


def fetch(region, force=False, progress=None):
    """Download the extract for `region` unless it is already complete. Returns the file path.

    progress(done_bytes, total_bytes) replaces the terminal progress line when given."""
    dest = pbf_path(region)
    url = url_for(region)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"

    if os.path.exists(dest) and not force:
        return dest

    for attempt in range(1, ATTEMPTS + 1):
        try:
            _download(region, url, part, progress)
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
            if attempt == ATTEMPTS:
                raise RuntimeError(f"Download of {region} kept failing ({e}). Run again to resume.") from None
            print(f"\n  connection dropped, resuming ({attempt}/{ATTEMPTS - 1}) ...")
            time.sleep(3 * attempt)

    expected = requests.get(url + ".md5", headers={"User-Agent": USER_AGENT}, timeout=60)
    if expected.ok:
        want = expected.text.split()[0]
        if _md5(part) != want:
            os.remove(part)
            raise RuntimeError(f"Checksum mismatch for {region}; deleted the partial file, please run again.")
    os.replace(part, dest)
    return dest


def _download(region, url, part, progress=None):
    done = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"User-Agent": USER_AGENT, **({"Range": f"bytes={done}-"} if done else {})}
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
                if progress:
                    progress(done, total)
                else:
                    _progress(region, done, total)
        if not progress:
            print()
