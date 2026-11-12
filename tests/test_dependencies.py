"""Every outside package the code imports must be installed, including imports inside functions,
which other tests may never reach. CI installs only requirements.txt, so a missing entry fails here."""
import ast
import importlib
import pathlib
import sys

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "gravelmaps"


def third_party_imports():
    names = set()
    for path in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add(node.module)
    return sorted(n for n in names if n.split(".")[0] not in sys.stdlib_module_names and n.split(".")[0] != "gravelmaps")


MAC_ONLY = {"webview", "AppKit", "PyObjCTools"}  # the Mac app window (pywebview, PyObjC): macOS only


@pytest.mark.parametrize("module", third_party_imports())
def test_dependency_installed(module):
    if module.split(".")[0] in MAC_ONLY and sys.platform != "darwin":
        pytest.skip("Mac only")
    importlib.import_module(module)
