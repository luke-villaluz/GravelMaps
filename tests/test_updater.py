import os
import subprocess
import sys

import pytest

from gravelmaps import updater as U

mac = pytest.mark.skipif(sys.platform != "darwin", reason="uses hdiutil / ditto")


def test_version_order():
    assert U.version_tuple("0.10.0") > U.version_tuple("0.9.3")
    assert U.version_tuple("v1.2.3") == (1, 2, 3)


def test_not_supported_outside_the_app():
    info = U.Updater().check()
    assert info["supported"] is False and info["newer"] is False


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def release(tag):
    return {"tag_name": tag, "html_url": "https://example.com/notes",
            "assets": [{"name": U.asset_name(), "browser_download_url": "https://example.com/x.dmg", "size": 10}]}


def test_check_finds_newer(monkeypatch):
    monkeypatch.setattr(U, "app_bundle", lambda: "/Applications/GravelMaps.app")
    monkeypatch.setattr(U, "__version__", "0.2.0")
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: FakeResponse(release("v0.3.0")))
    info = U.Updater().check()
    assert info["newer"] and info["latest"] == "0.3.0" and "problem" not in info


def test_check_same_version_and_offline(monkeypatch):
    monkeypatch.setattr(U, "app_bundle", lambda: "/Applications/GravelMaps.app")
    monkeypatch.setattr(U, "__version__", "0.3.0")
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: FakeResponse(release("v0.3.0")))
    assert U.Updater().check()["newer"] is False

    def offline(*a, **k):
        raise U.requests.ConnectionError("offline")

    monkeypatch.setattr(U.requests, "get", offline)
    assert U.Updater().check() == {"supported": True, "current": "0.3.0", "latest": None, "newer": False}


def test_translocated_app_cant_update(monkeypatch):
    monkeypatch.setattr(U, "app_bundle", lambda: "/private/var/folders/x/AppTranslocation/ABC/d/GravelMaps.app")
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: FakeResponse(release("v99.0.0")))
    u = U.Updater()
    assert "Applications" in u.check()["problem"]
    with pytest.raises(ValueError):
        u.start()


def fake_app(path, marker):
    os.makedirs(os.path.join(path, "Contents", "MacOS"))
    with open(os.path.join(path, "Contents", "MacOS", "marker"), "w") as f:
        f.write(marker)


@mac
def test_extract_and_swap(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "UPDATES", str(tmp_path / "update"))
    os.makedirs(U.UPDATES)
    # A release DMG holding a "new" GravelMaps.app.
    src = tmp_path / "dmgsrc"
    fake_app(str(src / "GravelMaps.app"), "new")
    dmg = tmp_path / "GravelMaps.dmg"
    subprocess.run(["hdiutil", "create", "-volname", "GravelMaps", "-srcfolder", str(src), "-format", "UDZO", str(dmg)],
                   check=True, capture_output=True)
    staged = U._extract_app(str(dmg), os.path.join(U.UPDATES, "new"))

    target = tmp_path / "Applications" / "GravelMaps.app"
    fake_app(str(target), "old")
    waiter = subprocess.Popen(["sleep", "0.5"])  # stands in for the running app
    proc = U._hand_over(staged, str(target), pid=waiter.pid, relaunch=False)
    waiter.wait()
    assert proc.wait(20) == 0
    assert (target / "Contents" / "MacOS" / "marker").read_text() == "new"
    assert not os.path.exists(str(target) + ".old") and not os.path.exists(str(target) + ".new")
