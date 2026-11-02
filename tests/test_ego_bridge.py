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
        request = max((p for p in tmp_path.rglob('*.json') if len(p.stem) == 32),
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


def test_real_child_pipe_does_not_extend_timeout_and_unsettled_round_blocks_next(tmp_path, monkeypatch):
    import sys
    import time
    monkeypatch.setattr('doudian_auto.ego_bridge.DATA_ROOT', tmp_path)
    monkeypatch.setattr('doudian_auto.ego_bridge.shutil.which', lambda name: sys.executable)
    real_run = subprocess.run
    calls = []
    def launch(command, **kwargs):
        calls.append(command)
        kwargs['timeout'] = 0.15
        return real_run([sys.executable, '-c',
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(1.5)'],stdout=sys.stdout,stderr=sys.stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)); time.sleep(5)"], **kwargs)
    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', launch)
    bridge = Bridge('ego', session='offline-deadline')
    started = time.monotonic()
    with pytest.raises(DoudianError) as timeout:
        bridge.command('click', {'selector': 'button'})
    assert timeout.value.code == 'ego_transport_unknown'
    assert time.monotonic() - started < 1.2
    with pytest.raises(DoudianError) as pending:
        bridge.command('snapshot')
    assert pending.value.code == 'ego_operation_unsettled'
    assert len(calls) == 1
    record = json.loads((bridge.session_dir/'pending-command.json').read_text())
    result = bridge.session_dir / (record['token']+'.result.json')
    result.write_text('{"ok":')
    with pytest.raises(DoudianError) as partial:
        bridge.require_ready()
    assert partial.value.code == 'ego_operation_unsettled'
    assert len(calls) == 1
    result.write_text(json.dumps({'ok':False,'error':{'mayHaveLateEffects':True}}))
    with pytest.raises(DoudianError):
        bridge.command('snapshot')
    assert len(calls) == 1
    result.write_text(json.dumps({'ok':True,'data':{'success':True}}))
    # A known completed late result unlocks observations, never a save replay.
    def observe(command, **kwargs):
        requests=[p for p in bridge.session_dir.glob('*.json') if len(p.stem)==32]
        request=max(requests,key=lambda p:p.stat().st_mtime_ns)
        request.with_name(request.stem+'.result.json').write_text(json.dumps({'ok':True,'data':{'observed':True}}))
        calls.append(command)
    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', observe)
    assert bridge.command('snapshot') == {'observed':True}
    assert len(calls) == 2


def test_broken_pending_record_stops_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr('doudian_auto.ego_bridge.DATA_ROOT', tmp_path)
    monkeypatch.setattr('doudian_auto.ego_bridge.shutil.which', lambda name: 'ego-browser.cmd')
    bridge = Bridge('ego')
    bridge.session_dir.mkdir(parents=True)
    pending = bridge.session_dir/'pending-command.json'
    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', lambda *a, **k: pytest.fail('must not launch'))
    for text in ('{', '[]', '{"token":"../../other"}'):
        pending.write_text(text)
        with pytest.raises(DoudianError) as refused:
            bridge.command('snapshot')
        assert refused.value.code == 'ego_operation_unsettled'
