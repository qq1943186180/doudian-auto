import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from doudian_auto import stalled_read_recovery as recovery
from doudian_auto.errors import DoudianError
from doudian_auto.miaoshou_editor import VISIBLE_DOM


SESSION = 'miaoshou-prepared-recovery-20261103'
SPACE_ID = 31
PAGE = 'p1'
PRODUCT_ID = '3848315786359865811'
SHOP = '销霁百货'
TOKEN = 'f8160f3f3ccb48fe9a187f8d8bac4e24'
QUICK_EDIT = 'https://v2-dd.chengji-inc.com/product/quick_edit'
ROUTE = 'v2-dd.chengji-inc.com/product/quick_edit'


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _navigation_code(*, shop=SHOP, product_id=PRODUCT_ID, marker='a' * 32):
    params = {'shop': shop, 'product_id': product_id, 'marker': marker}
    return VISIBLE_DOM + '(' + json.dumps('navigation_toggle') + ',' + json.dumps(params, ensure_ascii=True) + ')'


@pytest.fixture
def case(tmp_path):
    root = tmp_path / 'ego-sessions' / 'session-key'
    root.mkdir(parents=True)
    bridge = SimpleNamespace(session=SESSION, session_dir=root)
    state_path = root / 'state.json'
    state = {
        'spaceId': SPACE_ID, 'runId': 'original-run', 'active': PAGE,
        'pages': {ROUTE: PAGE, 'fxg.jinritemai.com/ffa/g/create': 'p2',
                  'v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field': 'p3'},
        'requests': {'old-read': {'url': 'https://v2-dd.chengji-inc.com/api/v2/product/product/getProductBaseEditInfo',
                                  'status': 200, 'body': 'retained-request'}},
        'capture': True,
    }
    _write(state_path, state)
    pending = {'token': TOKEN, 'action': 'evaluate', 'run_id': 'same-bridge-run'}
    request = {
        'action': 'evaluate', 'args': {'code': _navigation_code()},
        'session': SESSION, 'runId': 'same-bridge-run', 'statePath': str(state_path.resolve()),
    }
    result = {'ok': False, 'error': {'code': 'EGO_PAGE_EVALUATION_TIMED_OUT',
              'executionStopped': False, 'mayHaveLateEffects': True}}
    pending_path = _write(root / 'pending-command.json', pending)
    request_path = _write(root / f'{TOKEN}.json', request)
    result_path = _write(root / f'{TOKEN}.result.json', result)
    proof = {
        'reviewer': 'human-reviewer', 'session': SESSION, 'space_id': SPACE_ID,
        'page': PAGE, 'product_id': PRODUCT_ID, 'shop': SHOP, 'pending_token': TOKEN,
        'request_sha256': _hash(request_path), 'result_sha256': _hash(result_path),
    }
    proof_path = _write(tmp_path / 'proof.json', proof)
    return SimpleNamespace(root=root, bridge=bridge, state_path=state_path, state=state,
                           pending_path=pending_path, request_path=request_path,
                           result_path=result_path, proof_path=proof_path, proof=proof)


def _receipt(intent, *, before=None, remaining=None, owned=None, ok=True):
    before = before or ['p1', 'p2', 'p3']
    remaining = remaining if remaining is not None else ['p2', 'p3']
    owned = owned if owned is not None else ['p2', 'p3']
    return {
        'schema_version': 1, 'ok': ok, 'nonce': intent['nonce'],
        'session': SESSION, 'space_id': SPACE_ID, 'page': PAGE,
        'page_url': QUICK_EDIT, 'product_id': PRODUCT_ID, 'shop': SHOP,
        'pending_token': TOKEN, 'pending_sha256': intent['pending_sha256'],
        'request_sha256': intent['request_sha256'], 'result_sha256': intent['result_sha256'],
        'proof_sha256': intent['proof_sha256'], 'close_called': True,
        'target_opened_by': 'agent', 'closed_page': PAGE,
        'mayHaveLateEffects': False,
        'before_labels': before, 'remaining_pages': remaining,
        'remaining_owned_pages': owned, 'active_page': owned[0],
    }


def _fake_subprocess(monkeypatch, case, *, receipt_factory=None, timeout=False,
                     mutate_request=False, owned=True, url=QUICK_EDIT, returncode=0):
    calls = []

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        intent_path = case.root / f'stalled-read-recovery-{TOKEN}.intent.json'
        intent = json.loads(intent_path.read_text(encoding='utf-8'))
        script_path = Path(intent['script_path'])
        script = script_path.read_text(encoding='utf-8')
        assert script.count('await page.close()') == 1
        assert "taskSpace(s.space_id)" in script
        assert 'page.evaluate' not in script and 'page.click' not in script
        assert 'save_button' not in script and 'fill(' not in script and 'goto(' not in script
        if receipt_factory:
            receipt = receipt_factory(intent)
        else:
            receipt = _receipt(intent)
        if not owned:
            receipt['target_opened_by'] = 'user'
        if url != QUICK_EDIT:
            receipt['page_url'] = url
        if mutate_request:
            case.request_path.write_text(case.request_path.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        if not timeout or receipt_factory:
            _write(Path(intent['receipt_path']), receipt)
        if timeout:
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(recovery.shutil, 'which', lambda name: 'ego-browser.cmd')
    monkeypatch.setattr(recovery.subprocess, 'run', launch)
    return calls


@pytest.mark.parametrize('bad_kind', ['button', 'arbitrary_js'])
def test_only_exact_navigation_toggle_read_can_be_recovered(case, monkeypatch, bad_kind):
    request = json.loads(case.request_path.read_text(encoding='utf-8'))
    if bad_kind == 'button':
        request['args']['code'] = _navigation_code().replace('navigation_toggle', 'save_button')
    else:
        request['args']['code'] = 'document.querySelector("button").click()'
    _write(case.request_path, request)
    case.proof['request_sha256'] = _hash(case.request_path)
    _write(case.proof_path, case.proof)
    calls = _fake_subprocess(monkeypatch, case)

    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert calls == []
    assert case.pending_path.exists()
    assert not list(case.root.glob('*.intent.json'))


@pytest.mark.parametrize('source', ['request_action', 'pending_action', 'session', 'state_path'])
def test_wrong_command_source_or_session_is_rejected_before_close(case, monkeypatch, source):
    request = json.loads(case.request_path.read_text(encoding='utf-8'))
    pending = json.loads(case.pending_path.read_text(encoding='utf-8'))
    if source == 'request_action':
        request['action'] = 'click'
        _write(case.request_path, request)
        case.proof['request_sha256'] = _hash(case.request_path)
    elif source == 'pending_action':
        pending['action'] = 'click'
        _write(case.pending_path, pending)
    elif source == 'session':
        request['session'] = 'another-session'
        _write(case.request_path, request)
        case.proof['request_sha256'] = _hash(case.request_path)
    else:
        request['statePath'] = str(case.root / 'other-state.json')
        _write(case.request_path, request)
        case.proof['request_sha256'] = _hash(case.request_path)
    _write(case.proof_path, case.proof)
    calls = _fake_subprocess(monkeypatch, case)

    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert calls == []
    assert case.pending_path.exists()


@pytest.mark.parametrize('field,value', [
    ('request_sha256', '0' * 64), ('result_sha256', '0' * 64),
    ('product_id', '3848315786359865812'), ('shop', '另一家店'),
    ('session', 'another-session'), ('space_id', 32), ('page', 'p2'),
])
def test_proof_identity_and_hash_bindings_are_strict(case, monkeypatch, field, value):
    case.proof[field] = value
    _write(case.proof_path, case.proof)
    calls = _fake_subprocess(monkeypatch, case)

    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert calls == []
    assert case.pending_path.exists()


@pytest.mark.parametrize('change', ['finished', 'cleanup', 'active', 'space', 'route'])
def test_taskspace_state_must_still_be_the_same_live_owned_page(case, monkeypatch, change):
    state = dict(case.state)
    if change == 'finished':
        state['finished'] = True
    elif change == 'cleanup':
        state['cleanup'] = {'phase': 'finishing'}
    elif change == 'active':
        state['active'] = 'p2'
    elif change == 'space':
        state['spaceId'] = 999
    else:
        state['pages'] = {key: value for key, value in state['pages'].items() if key != ROUTE}
    _write(case.state_path, state)
    calls = _fake_subprocess(monkeypatch, case)

    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert calls == []
    assert case.pending_path.exists()


@pytest.mark.parametrize('failure', ['wrong_result_code', 'execution_stopped', 'no_late_effects'])
def test_only_exact_late_evaluate_result_can_authorize_close(case, monkeypatch, failure):
    result = json.loads(case.result_path.read_text(encoding='utf-8'))
    if failure == 'wrong_result_code':
        result['error']['code'] = 'EGO_CLICK_TIMED_OUT'
    elif failure == 'execution_stopped':
        result['error']['executionStopped'] = True
    else:
        result['error']['mayHaveLateEffects'] = False
    _write(case.result_path, result)
    case.proof['result_sha256'] = _hash(case.result_path)
    _write(case.proof_path, case.proof)
    calls = _fake_subprocess(monkeypatch, case)

    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert calls == []
    assert case.pending_path.exists()


@pytest.mark.parametrize('bad_page', ['user_owned', 'wrong_url', 'other_page_removed', 'late_effects'])
def test_sdk_receipt_must_confirm_target_ownership_and_preserve_other_labels(
        case, monkeypatch, bad_page):
    def bad_receipt(intent):
        if bad_page == 'other_page_removed':
            return _receipt(intent, remaining=['p3'], owned=['p3'])
        if bad_page == 'late_effects':
            receipt = _receipt(intent)
            receipt['mayHaveLateEffects'] = True
            return receipt
        return _receipt(intent)

    calls = _fake_subprocess(monkeypatch, case, receipt_factory=bad_receipt,
                             owned=(bad_page != 'user_owned'),
                             url=('https://v2-dd.chengji-inc.com/product/quick_edit?x=1'
                                  if bad_page == 'wrong_url' else QUICK_EDIT))
    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert len(calls) == 1
    assert case.pending_path.exists()
    intent = json.loads(next(case.root.glob('*.intent.json')).read_text(encoding='utf-8'))
    assert Path(intent['receipt_path']).is_file()
    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)
    assert len(calls) == 1


def test_nonzero_sdk_exit_never_finalizes_even_with_a_receipt(case, monkeypatch):
    calls = _fake_subprocess(monkeypatch, case, returncode=1)
    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)
    assert len(calls) == 1
    assert case.pending_path.exists()
    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)
    assert len(calls) == 1


def test_success_closes_only_p1_once_and_preserves_requests_and_old_result(case, monkeypatch):
    requests_before = json.loads(case.state_path.read_text(encoding='utf-8'))['requests']
    request_bytes = case.request_path.read_bytes()
    result_bytes = case.result_path.read_bytes()
    pending_data = json.loads(case.pending_path.read_text(encoding='utf-8'))
    calls = _fake_subprocess(monkeypatch, case)

    result = recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert kwargs['timeout'] == 35
    assert kwargs['stdout'] is subprocess.DEVNULL and kwargs['stderr'] is subprocess.DEVNULL
    assert result['recovered'] is True
    assert result['closed_page'] == 'p1'
    assert result['remaining_pages'] == ['p2', 'p3']
    assert Path(result['evidence_path']).is_file()
    state = json.loads(case.state_path.read_text(encoding='utf-8'))
    assert state['pages'] == {key: value for key, value in case.state['pages'].items() if key != ROUTE}
    assert state['active'] == 'p2' and state['capture'] is False
    assert state['requests'] == requests_before
    assert case.request_path.read_bytes() == request_bytes
    assert case.result_path.read_bytes() == result_bytes
    assert not case.pending_path.exists()
    audit = json.loads(next(case.root.glob('*.audit.json')).read_text(encoding='utf-8'))
    assert audit['pending'] == pending_data
    assert audit['request_sha256'] == case.proof['request_sha256']
    assert audit['result_sha256'] == case.proof['result_sha256']
    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)
    assert len(calls) == 1


def test_timeout_without_receipt_persists_intent_and_never_recloses(case, monkeypatch):
    calls = _fake_subprocess(monkeypatch, case, timeout=True)

    with pytest.raises(DoudianError, match='禁止再次close'):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert len(calls) == 1
    assert case.pending_path.exists()
    intent_path = next(case.root.glob('*.intent.json'))
    intent = json.loads(intent_path.read_text(encoding='utf-8'))
    assert intent['phase'] == 'close_pending'
    assert not Path(intent['receipt_path']).exists()
    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)
    assert len(calls) == 1


def test_complete_late_receipt_can_finalize_without_replaying_close(case, monkeypatch):
    calls = _fake_subprocess(monkeypatch, case, timeout=True)
    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)
    intent_path = next(case.root.glob('*.intent.json'))
    intent = json.loads(intent_path.read_text(encoding='utf-8'))
    _write(Path(intent['receipt_path']), _receipt(intent))

    result = recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert result['recovered'] is True
    assert result['closed_page'] == PAGE
    assert result['remaining_pages'] == ['p2', 'p3']
    assert not case.pending_path.exists()
    assert len(calls) == 1


def test_request_change_during_close_aborts_without_changing_state_or_pending(case, monkeypatch):
    before_state = case.state_path.read_bytes()
    calls = _fake_subprocess(monkeypatch, case, mutate_request=True)

    with pytest.raises(DoudianError):
        recovery.recover_stalled_read(case.bridge, case.proof_path)

    assert len(calls) == 1
    assert case.pending_path.exists()
    assert case.state_path.read_bytes() == before_state
