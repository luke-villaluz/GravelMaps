"""In-app updates for the packaged Mac app, from GitHub Releases.

When online, the app asks GitHub for the latest release. If it's newer, the map shows an Update
button. Updating downloads the release's DMG for this Mac (Apple Silicon or Intel), copies the
new app out of it, and hands over to a small script that waits for this app to quit, swaps the
new version in and opens it. Map data lives outside the app, so it's kept.

The download is made by the app itself, not a browser, so macOS doesn't flag it as quarantined
and the new version opens without the "Open Anyway" step the first install needed.
"""
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import requests

from . import REPO, USER_AGENT, __version__
from .paths import DATA, FROZEN

LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 6 * 3600
UPDATES = os.path.join(DATA, "update")

quit_app = None  # set by desktop.py: closes the window, which quits the app


def version_tuple(v):
    return tuple(int(n) for n in re.findall(r"\d+", v)[:3])


def asset_name():
    return f"GravelMaps-{'arm64' if platform.machine() == 'arm64' else 'x86_64'}.dmg"


def app_bundle():
    """Path of the running GravelMaps.app, or None when not running from one."""
    if not FROZEN:
        return None
    path = os.path.realpath(sys.executable)  # .../GravelMaps.app/Contents/MacOS/GravelMaps
    app = os.path.dirname(os.path.dirname(os.path.dirname(path)))
    return app if app.endswith(".app") else None


class Updater:
    def __init__(self):
        self.checked_at = 0
        self.latest = None
        self.state = "idle"  # idle | downloading | installing | restarting | failed
        self.done_bytes = self.total_bytes = 0
        self.error = None
        self.lock = threading.Lock()

    def check(self, force=False):
        """{"supported", "current", "latest", "newer", "notes"}; never raises."""
        app = app_bundle()
        out = {"supported": app is not None, "current": __version__, "latest": None, "newer": False}
        if app is None:
            return out
        if "/AppTranslocation/" in app:  # run from the DMG or Downloads: can't replace itself there
            out["problem"] = "Move GravelMaps to your Applications folder to get updates."
        if force or time.time() - self.checked_at > CHECK_EVERY:
            try:
                r = requests.get(LATEST, timeout=6, headers={"User-Agent": USER_AGENT,
                                                             "Accept": "application/vnd.github+json"})
                r.raise_for_status()
                rel = r.json()
                asset = next((a for a in rel.get("assets", []) if a["name"] == asset_name()), None)
                self.latest = {"version": rel["tag_name"].lstrip("v"), "notes": rel.get("html_url"),
                               "url": asset and asset["browser_download_url"], "size": asset and asset["size"]}
                self.checked_at = time.time()
            except (requests.RequestException, KeyError, ValueError):
                pass  # offline or GitHub unreachable: try again next time
        if self.latest:
            out["latest"] = self.latest["version"]
            out["notes"] = self.latest["notes"]
            out["newer"] = bool(self.latest["url"]) and version_tuple(self.latest["version"]) > version_tuple(__version__)
        return out

    def status(self):
        return {"state": self.state, "done_bytes": self.done_bytes, "total_bytes": self.total_bytes, "error": self.error}

    def start(self):
        with self.lock:
            if self.state in ("downloading", "installing", "restarting"):
                return
            info = self.check()
            if not info["newer"] or info.get("problem"):
                raise ValueError(info.get("problem") or "Already up to date.")
            self.state, self.error = "downloading", None
        threading.Thread(target=self._install, daemon=True, name="gravelmaps-update").start()

    def _install(self):
        try:
            os.makedirs(UPDATES, exist_ok=True)
            dmg = os.path.join(UPDATES, asset_name())
            self._download(self.latest["url"], dmg)
            self.state = "installing"
            staged = _extract_app(dmg, os.path.join(UPDATES, "new"))
            os.remove(dmg)
            self.state = "restarting"
            _hand_over(staged, app_bundle())
            if quit_app:
                quit_app()
        except Exception as e:  # shown next to the Update button
            self.state, self.error = "failed", f"Update failed: {e}"

    def _download(self, url, dest):
        part = dest + ".part"
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            self.total_bytes = int(r.headers.get("Content-Length", 0))
            self.done_bytes = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    self.done_bytes += len(chunk)
        os.replace(part, dest)


def _extract_app(dmg, dest):
    """Copy GravelMaps.app out of the DMG into dest/; returns its path."""
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    mount = tempfile.mkdtemp(prefix="gravelmaps-update-")
    # hdiutil sometimes fails at first ("Resource temporarily unavailable"), so try a few times.
    for attempt in range(4):
        r = subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, dmg],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
        time.sleep(1 + 2 * attempt)
    else:
        shutil.rmtree(mount, ignore_errors=True)
        raise RuntimeError(f"couldn't open the download ({(r.stderr or r.stdout).strip()})")
    try:
        src = os.path.join(mount, "GravelMaps.app")
        if not os.path.isdir(src):
            raise RuntimeError("the download doesn't contain GravelMaps.app")
        app = os.path.join(dest, "GravelMaps.app")
        subprocess.run(["ditto", src, app], check=True, capture_output=True)
    finally:
        subprocess.run(["hdiutil", "detach", mount, "-quiet"], capture_output=True)
        shutil.rmtree(mount, ignore_errors=True)
    return app


def _hand_over(staged, target, pid=None, relaunch=True):
    """Start a script that swaps `staged` in for `target` once process `pid` (this one) exits, then
    opens it. Returns the script's process."""
    if not os.access(os.path.dirname(target), os.W_OK):
        raise PermissionError(f"can't write to {os.path.dirname(target)}")
    q = shlex.quote
    new, old = q(target + ".new"), q(target + ".old")
    # Copy next to the old app first, then swap names: a failure part way leaves the old app as it was.
    script = f"""#!/bin/sh
while kill -0 {pid or os.getpid()} 2>/dev/null; do sleep 0.2; done
rm -rf {new} {old}
if ditto {q(staged)} {new}; then
  mv {q(target)} {old} && mv {new} {q(target)} && rm -rf {old}
fi
rm -rf {new} {q(os.path.dirname(staged))}
xattr -dr com.apple.quarantine {q(target)} 2>/dev/null
{"open " + q(target) if relaunch else ""}
"""
    path = os.path.join(UPDATES, "install.sh")
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, 0o755)
    return subprocess.Popen(["/bin/sh", path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


updater = Updater()
