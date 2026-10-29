import json
import subprocess

import pytest

from doudian_auto.bridge import Bridge
from doudian_auto.ego_bridge import EgoBridge
from doudian_auto.errors import DoudianError


def test_bridge_selects_native_ego_and_isolates_session_files(tmp_path, monkeypatch):
    monkeypatch.setattr('doudian_auto.ego_bridge.DATA_ROOT', tmp_path)
    bridge = Bridge('ego', session='商品/测试')
    assert isinstance(bridge, EgoBridge)
    assert bridge.session_dir.parent == tmp_path / 'ego-sessions'
    assert '/' not in bridge.session_dir.name


def test_timeout_never_replays_the_command(tmp_path, monkeypatch):
    monkeypatch.setattr('doudian_auto.ego_bridge.DATA_ROOT', tmp_path)
    monkeypatch.setattr('doudian_auto.ego_bridge.shutil.which', lambda name: 'ego-browser.cmd')
    calls = []
    def timeout(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', timeout)
    with pytest.raises(DoudianError) as error:
        Bridge('ego').command('click', {'selector': '[data-verified="yes"]'})
    assert error.value.code == 'ego_transport_unknown'
    assert len(calls) == 1
    assert not list(tmp_path.rglob('transport.lock'))


def test_locked_refs_fail_without_retry_and_round_files_are_unique(tmp_path, monkeypatch):
    monkeypatch.setattr('doudian_auto.ego_bridge.DATA_ROOT', tmp_path)
    monkeypatch.setattr('doudian_auto.ego_bridge.shutil.which', lambda name: 'ego-browser.cmd')
    calls = []
    def locked(command, **kwargs):
        calls.append(command)
        request = max((p for p in tmp_path.rglob('*.json') if not p.name.endswith('.result.json')),
                      key=lambda p: p.stat().st_mtime_ns)
        output = request.with_name(request.stem + '.result.json')
        output.write_text(json.dumps({'ok': False, 'error': {'message': 'EPERM refs.json'}}), encoding='utf-8')
    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', locked)
    for _ in range(2):
        # An explicit later observation is a new round, not a replay of the click.
        with pytest.raises(DoudianError) as error:
            Bridge('ego').command('snapshot')
        assert error.value.code == 'ego_state_locked'
    assert len(calls) == 2
    assert calls[0][-1] != calls[1][-1]
