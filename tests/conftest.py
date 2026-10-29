"""Keep tests away from the user's live queue, browser locks and credentials."""
import pytest


@pytest.fixture(autouse=True)
def isolated_runtime_root(tmp_path, monkeypatch):
    from doudian_auto import batch, cli, ego_bridge, gui, jobs, workflow
    root = tmp_path / 'runtime'
    for module in (batch, cli, ego_bridge, gui, jobs, workflow):
        monkeypatch.setattr(module, 'DATA_ROOT', root)
    monkeypatch.setattr(batch, 'DB_PATH', root / 'batch.sqlite3')
