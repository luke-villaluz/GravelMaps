# PyInstaller recipe for GravelMaps.app.   Build:  packaging/build_app.sh
import os
import re

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "gravelmaps", "__init__.py")).read()).group(1)

datas = [(os.path.join(ROOT, "static"), "static")]
binaries = []
hiddenimports = [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
]
# Packages with compiled parts or imports PyInstaller can't see on its own.
for pkg in ["numba", "llvmlite", "osmium", "pymupdf", "webview", "pmtiles", "scipy.spatial", "scipy.sparse"]:
    d, b, h = collect_all(pkg)
    datas, binaries, hiddenimports = datas + d, binaries + b, hiddenimports + h

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[ROOT],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports + ["gravelmaps." + m[:-3] for m in os.listdir(os.path.join(ROOT, "gravelmaps"))
                                   if m.endswith(".py") and m != "__init__.py"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyInstaller"],
    # As plain .py files: numba's cache=True needs real source files to key its cache on.
    module_collection_mode={"gravelmaps": "py"},
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GravelMaps", console=False, upx=False,
          target_arch=None, codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="GravelMaps", upx=False)
app = BUNDLE(
    coll,
    name="GravelMaps.app",
    icon=os.path.join(SPECPATH, "icon.icns"),
    bundle_identifier="io.github.luke-villaluz.gravelmaps",
    version=VERSION,
    info_plist={
        "CFBundleName": "GravelMaps",
        "CFBundleDisplayName": "GravelMaps",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.navigation",
        "NSHighResolutionCapable": True,
        "NSLocationWhenInUseUsageDescription": "GravelMaps shows where you are on the map.",
        # The app talks to its own server on 127.0.0.1 over plain http.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
