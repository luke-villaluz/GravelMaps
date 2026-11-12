"""The Mac app: GravelMaps in its own window, with the server running inside the app.

The window opens straight away on a short "starting" screen while the map data loads, then shows
the map (or the setup screen when there's no map data yet). Closing the window quits everything.
"""
import os
import socket
import threading
import time

import requests

from .config import load_config
from .paths import DATA

# A fixed port keeps the page's origin the same between launches, which keeps its saved settings
# (theme, basemap, sliders) in the browser storage. Next ports are fallbacks if something else has it.
PORT = 47817
PORT_TRIES = 10

SPLASH = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#202124;color:#9aa0a6;font:15px -apple-system,Helvetica,Arial,sans-serif;
display:grid;place-items:center} .b{text-align:center} .e{font-size:44px;margin-bottom:10px}
.s{display:inline-block;width:14px;height:14px;border:2px solid #8ab4f8;border-right-color:transparent;border-radius:50%;
animation:r .9s linear infinite;vertical-align:-2px;margin-right:8px} @keyframes r{to{transform:rotate(360deg)}}
</style></head><body><div class="b"><div class="e">🚙</div><span class="s"></span>Starting GravelMaps…</div></body></html>"""


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _running_gravelmaps(port):
    """True if a GravelMaps (say, started from the terminal) already answers on this port."""
    try:
        return requests.get(f"http://127.0.0.1:{port}/api/setup/status", timeout=1).ok
    except requests.RequestException:
        return False


class Server:
    """Uvicorn in a background thread."""

    def __init__(self, port):
        self.port = port
        self.uvicorn = None
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="gravelmaps-server")

    def _run(self):
        import uvicorn

        from .server import Shell
        try:
            app = Shell(load_config().get("regions"))  # loads the map data: the slow part
            self.uvicorn = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
            self.uvicorn.run()
        except Exception as e:  # shown in the window instead of a silent exit
            self.error = e
            raise

    def wait_ready(self, timeout=300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.error:
                return False
            if self.uvicorn and self.uvicorn.started:
                return True
            time.sleep(0.05)
        return False

    def stop(self):
        if self.uvicorn:
            self.uvicorn.should_exit = True
        self.thread.join(5)


def _dock_icon():
    """Run from a checkout, the process is Python, so give the Dock our icon instead of Python's."""
    from .paths import FROZEN, ROOT
    icon = os.path.join(ROOT, "packaging", "icon.icns")
    if FROZEN or not os.path.exists(icon):
        return
    try:
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper
        image = NSImage.alloc().initWithContentsOfFile_(icon)
        AppHelper.callAfter(lambda: NSApplication.sharedApplication().setApplicationIconImage_(image))
    except Exception:
        pass  # only cosmetic


def main(self_test=False):
    port = next((p for p in range(PORT, PORT + PORT_TRIES) if _port_free(p) or _running_gravelmaps(p)), None)
    if port is None:
        raise SystemExit(f"Ports {PORT}-{PORT + PORT_TRIES - 1} are all in use.")
    server = None
    if _port_free(port):
        server = Server(port)
        server.thread.start()
    url = f"http://127.0.0.1:{port}/"

    if self_test:  # for CI: start up, answer one request, quit
        ok = server.wait_ready() if server else True
        ok = ok and requests.get(url + "api/setup/status", timeout=10).ok
        if server:
            server.stop()
        raise SystemExit(0 if ok else 1)

    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True  # GPX export
    window = webview.create_window("GravelMaps", html=SPLASH, width=1440, height=920, min_size=(720, 520),
                                   background_color="#202124", text_select=True)

    from . import updater
    updater.quit_app = window.destroy  # an installed update restarts the app

    def show_map():
        _dock_icon()
        if server is None or server.wait_ready():
            window.load_url(url)
        else:
            err = server.error or "it took too long to start"
            window.load_html(SPLASH.replace('<span class="s"></span>Starting GravelMaps…',
                                            f"GravelMaps couldn't start: {err}"))

    storage = os.path.join(DATA, "webview")
    os.makedirs(storage, exist_ok=True)
    webview.start(show_map, private_mode=False, storage_path=storage)
    if server:
        server.stop()
