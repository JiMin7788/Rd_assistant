import pytest

from rdom.policy import data_mode


@pytest.fixture(autouse=True)
def data_mode_off(monkeypatch, tmp_path):
    """AI-NOTE: config/data_mode.toml is committed with sevens = true; every test runs with the switch OFF
    (missing file) unless it points data_mode.FILE at its own file, so the existing tests see today's play."""
    monkeypatch.setattr(data_mode, "FILE", str(tmp_path / "no_data_mode.toml"))
