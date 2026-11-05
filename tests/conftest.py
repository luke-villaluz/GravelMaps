import pytest

from gravelmaps import graph as G


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ways_path", lambda r: str(tmp_path / f"{r}.npz"))
    monkeypatch.setattr(G, "graph_dir", lambda regions: str(tmp_path / ("g_" + "_".join(sorted(regions)))))
    return tmp_path
