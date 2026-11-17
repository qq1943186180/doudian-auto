"""A recycled Ego task space must be repaired once, and its reason must survive.

Ego reclaims task spaces and later reuses the ids. The cached id in state.json
then fails while the space is being resolved (before any Page exists), so the
bridge re-points the cache and retries exactly once instead of reporting an
opaque "no automatic retry" that hides the real cause.
"""
import json

import pytest

from doudian_auto import ego_bridge
from doudian_auto.ego_bridge import EgoBridge
from doudian_auto.errors import DoudianError, WaitingHuman


def write_state(bridge, space_id=2, pages=None, active='p1'):
    path = bridge.session_dir / 'state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'spaceId': space_id,
                                'pages': pages if pages is not None else {'route': 'p1'},
                                'active': active, 'runId': 'r1', 'capture': False}),
                    encoding='utf-8')
    return path


def missing_space_error(message='task space not found: 5'):
    error = DoudianError('ego_error', 'Ego未确认完成操作；没有自动重试。')
    error.details = {'action': 'snapshot', 'raw_code': 'ego_error',
                     'raw_message': message, 'result_file': 'x.result.json'}
    return error


def test_recycled_space_is_aligned_then_retried_once(monkeypatch):
    bridge = EgoBridge(session='align-retry')
    state = write_state(bridge, space_id=5)
    monkeypatch.setattr(bridge, '_probe_space_result',
                        lambda: {'ok': True, 'spaceId': 2, 'created': False})
    replies = [missing_space_error(), {'observed': True}]
    actions = []

    def execute(action, args=None):
        actions.append(action)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(bridge, '_execute', execute)
    assert bridge.command('snapshot') == {'observed': True}
    assert actions == ['snapshot', 'snapshot']
    assert bridge.space_alignment == {'old': 5, 'new': 2, 'changed': True}

    repaired = json.loads(state.read_text(encoding='utf-8'))
    assert repaired['spaceId'] == 2
    # Tab routes belong to the dead space: keeping them would retarget a lost page.
    assert repaired['pages'] == {}
    assert repaired['active'] is None
    backup = bridge.session_dir / 'state.json.bak-auto'
    assert json.loads(backup.read_text(encoding='utf-8'))['spaceId'] == 5


def test_aligned_space_still_missing_reports_the_runtime_message(monkeypatch):
    bridge = EgoBridge(session='align-still-broken')
    write_state(bridge, space_id=5)
    monkeypatch.setattr(bridge, '_probe_space_result',
                        lambda: {'ok': True, 'spaceId': 2, 'created': False})
    actions = []

    def execute(action, args=None):
        actions.append(action)
        raise missing_space_error('task space not found: 2')

    monkeypatch.setattr(bridge, '_execute', execute)
    with pytest.raises(DoudianError) as raised:
        bridge.command('snapshot')
    assert raised.value.code == 'ego_error'
    assert raised.value.details['raw_message'] == 'task space not found: 2'
    # Exactly one repair and one retry: a second failure has to surface.
    assert actions == ['snapshot', 'snapshot']


def test_matching_space_is_never_rewritten(monkeypatch):
    bridge = EgoBridge(session='align-noop')
    state = write_state(bridge, space_id=2)
    before = state.read_text(encoding='utf-8')
    monkeypatch.setattr(bridge, '_probe_space_result',
                        lambda: {'ok': True, 'spaceId': 2, 'created': False})
    assert bridge.align_space() == 2
    assert state.read_text(encoding='utf-8') == before
    assert not (bridge.session_dir / 'state.json.bak-auto').exists()
    assert bridge.space_alignment == {'old': 2, 'new': 2, 'changed': False}


def test_probe_writes_a_file_and_coerces_the_reported_id(monkeypatch):
    bridge = EgoBridge(session='align-probe-ok')
    state = write_state(bridge, space_id=7)
    monkeypatch.setattr(ego_bridge.shutil, 'which', lambda name: 'ego-browser.cmd')

    def run(command, **kwargs):
        script = next(bridge.session_dir.glob('*.space.mjs'))
        source = script.read_text(encoding='utf-8')
        assert 'listTaskSpaces' in source and 'taskSpace' in source
        script.with_name(script.name.replace('.space.mjs', '.space.json')).write_text(
            json.dumps({'ok': True, 'spaceId': '2', 'created': False}), encoding='utf-8')

    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', run)
    assert bridge.align_space() == 2
    assert json.loads(state.read_text(encoding='utf-8'))['spaceId'] == 2


def test_probe_failure_keeps_state_and_reports_the_real_reason(monkeypatch):
    bridge = EgoBridge(session='align-probe-broken')
    state = write_state(bridge, space_id=5)
    before = state.read_text(encoding='utf-8')
    monkeypatch.setattr(ego_bridge.shutil, 'which', lambda name: 'ego-browser.cmd')

    def run(command, **kwargs):
        script = next(bridge.session_dir.glob('*.space.mjs'))
        script.with_name(script.name.replace('.space.mjs', '.space.json')).write_text(
            json.dumps({'ok': False, 'error': {'code': 'EGO_SPACE_LIST_FAILED',
                                               'message': 'browser-host is not reachable'}}),
            encoding='utf-8')

    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', run)
    with pytest.raises(DoudianError) as raised:
        bridge.align_space()
    assert raised.value.code == 'ego_space_align_failed'
    assert 'browser-host is not reachable' in str(raised.value)
    assert state.read_text(encoding='utf-8') == before
    assert not (bridge.session_dir / 'state.json.bak-auto').exists()


def test_unusable_space_id_is_a_named_failure(monkeypatch):
    bridge = EgoBridge(session='align-bad-id')
    write_state(bridge, space_id=5)
    monkeypatch.setattr(bridge, '_probe_space_result', lambda: {'ok': True, 'spaceId': None})
    with pytest.raises(DoudianError) as raised:
        bridge.align_space()
    assert raised.value.code == 'ego_space_align_failed'
    assert 'None' in str(raised.value)


def test_other_failures_are_not_retried(monkeypatch):
    bridge = EgoBridge(session='align-no-retry')
    write_state(bridge, space_id=2)
    actions = []

    def execute(action, args=None):
        actions.append(action)
        raise DoudianError('ego_state_locked', 'Ego未确认完成操作；本地页面状态文件被占用。')

    monkeypatch.setattr(bridge, '_execute', execute)
    monkeypatch.setattr(bridge, '_probe_space_result',
                        lambda: pytest.fail('must not probe for an unrelated failure'))
    with pytest.raises(DoudianError) as raised:
        bridge.command('snapshot')
    assert raised.value.code == 'ego_state_locked'
    assert actions == ['snapshot']


def test_module_align_space_returns_the_live_id(monkeypatch):
    monkeypatch.setattr(EgoBridge, '_probe_space_result',
                        lambda self: {'ok': True, 'spaceId': 3, 'created': False})
    # No cached state yet: the runtime creates state.json on the first real command.
    assert ego_bridge.align_space('module-level') == 3


def test_repair_failure_keeps_the_original_message(monkeypatch):
    bridge = EgoBridge(session='align-repair-fails')
    write_state(bridge, space_id=5)

    def broken():
        raise DoudianError(ego_bridge.SPACE_ALIGN_FAILED,
                           'Ego任务空间探测失败：browser-host is not reachable')

    monkeypatch.setattr(bridge, '_probe_space_result', broken)

    def execute(action, args=None):
        raise missing_space_error()

    monkeypatch.setattr(bridge, '_execute', execute)
    with pytest.raises(DoudianError) as raised:
        bridge.command('snapshot')
    assert raised.value.code == 'ego_space_align_failed'
    assert 'browser-host is not reachable' in str(raised.value)
    assert raised.value.details['original_message'] == 'task space not found: 5'


def test_handed_over_space_is_never_retried(monkeypatch):
    bridge = EgoBridge(session='align-handover')
    write_state(bridge, space_id=2)
    attempts = []

    def execute(action, args=None):
        attempts.append(action)
        error = WaitingHuman('ego_control_required', 'Ego任务控制已交给你，请完成当前页面后恢复任务。')
        error.details = {'raw_code': 'ego_control_required', 'raw_message': 'task space not found: 2'}
        raise error

    monkeypatch.setattr(bridge, '_execute', execute)
    monkeypatch.setattr(bridge, '_probe_space_result',
                        lambda: pytest.fail('must not re-point a space handed back to the user'))
    with pytest.raises(DoudianError) as raised:
        bridge.command('snapshot')
    assert raised.value.code == 'ego_control_required'
    assert attempts == ['snapshot']


def test_real_transport_retries_after_repair_without_touching_pending(monkeypatch):
    # The whole chain, not a stub: round 1 fails in the runtime, the probe repairs
    # state.json, and the retry has to pass the pending marker round 1 left behind.
    bridge = EgoBridge(session='align-e2e')
    state = write_state(bridge, space_id=5)
    monkeypatch.setattr(ego_bridge.shutil, 'which', lambda name: 'ego-browser.cmd')
    tokens = []

    def run(command, **kwargs):
        script = max(bridge.session_dir.glob('*.mjs'), key=lambda p: p.stat().st_mtime_ns)
        if script.name.endswith('.space.mjs'):
            script.with_name(script.name.replace('.space.mjs', '.space.json')).write_text(
                json.dumps({'ok': True, 'spaceId': 2, 'created': False}), encoding='utf-8')
            return
        tokens.append(script.stem)
        out = script.with_name(script.stem + '.result.json')
        if len(tokens) == 1:
            out.write_text(json.dumps({'ok': False, 'error': {
                'code': 'ego_error', 'message': 'task space not found: 5'}}), encoding='utf-8')
        else:
            out.write_text(json.dumps({'ok': True, 'data': {'observed': True}}), encoding='utf-8')

    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', run)
    assert bridge.command('snapshot') == {'observed': True}
    assert len(tokens) == 2 and tokens[0] != tokens[1]
    assert json.loads(state.read_text(encoding='utf-8'))['spaceId'] == 2
    assert (bridge.session_dir / 'state.json.bak-auto').is_file()
