import hashlib
import json
import os

import pytest

from doudian_auto import preclick_evidence as evidence
from doudian_auto.errors import DoudianError


def trace_fixture(tmp_path, monkeypatch):
    runtime = tmp_path / 'audited-runtime.mjs'
    runtime.write_text('audited test fixture', encoding='utf-8')
    digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
    monkeypatch.setattr(evidence, 'AUDITED_RUNTIME_SHA256', {digest})
    session = 'own-session'
    root = tmp_path / 'ego-sessions' / hashlib.sha256(session.encode()).hexdigest()[:24]
    root.mkdir(parents=True)
    marker = 'miao-batch-final-' + 'f' * 32
    def write(token, action, args, result, at):
        request = root / (token + '.json')
        response = root / (token + '.result.json')
        request.write_text(json.dumps({'session': session, 'runId': 'one-run', 'action': action, 'args': args}), encoding='utf-8')
        response.write_text(json.dumps(result), encoding='utf-8')
        os.utime(request, (at, at))
        os.utime(response, (at + .1, at + .1))
        return request, response
    write('a' * 32, 'evaluate', {'code': "button.J_batchEditProduct.setAttribute('data-codex-miao-batch','" + marker + "')"}, {'ok': True, 'data': {'value': {'count': 1}}}, 99)
    write('b' * 32, 'network', {'cmd': 'list'}, {'ok': True}, 100.1)
    write('c' * 32, 'network', {'cmd': 'start'}, {'ok': True}, 100.3)
    req, res = write('d' * 32, 'click', {'selector': '[data-codex-miao-batch="' + marker + '"]'},
                     {'ok': False, 'error': {'code': 'ego_target_not_unique', 'message': 'No unique actionable current DOM target.'}}, 100.5)
    trace = {'session': session, 'runtime_path': str(runtime), 'runtime_sha256': digest,
             'round_id': 'd' * 32, 'arm_round_id': 'a' * 32,
             'request_sha256': hashlib.sha256(req.read_bytes()).hexdigest(),
             'result_sha256': hashlib.sha256(res.read_bytes()).hexdigest()}
    intent = {'created_at': 100}
    outcome = {'occurred_at': 101, 'detail': json.dumps({'state': 'unknown', 'error': 'ego_target_not_unique'})}
    return trace, intent, outcome, root, write


def test_audited_preinput_trace_binds_one_rejected_final_click(tmp_path, monkeypatch):
    trace, intent, outcome, root, write = trace_fixture(tmp_path, monkeypatch)
    result = evidence.verify_native_preclick_trace(trace, intent, outcome, data_root=tmp_path)
    assert result['input_dispatched'] is False
    assert result['round_id'] == trace['round_id']


@pytest.mark.parametrize('change', ['changed_runtime', 'changed_result', 'wrong_session', 'another_click', 'missing_reply', 'late_failure', 'unknown_transport', 'wrong_arm'])
def test_possible_click_or_incomplete_provenance_stays_unknown(tmp_path, monkeypatch, change):
    trace, intent, outcome, root, write = trace_fixture(tmp_path, monkeypatch)
    if change == 'changed_runtime':
        trace['runtime_sha256'] = '0' * 64
    elif change == 'changed_result':
        trace['result_sha256'] = '0' * 64
    elif change == 'wrong_session':
        trace['session'] = 'unrelated-session'
    elif change == 'another_click':
        write('e' * 32, 'click', {'selector': 'button'}, {'ok': True}, 100.7)
    elif change == 'missing_reply':
        (root / ('b' * 32 + '.result.json')).unlink()
    elif change == 'late_failure':
        outcome['occurred_at'] = 135
    elif change == 'unknown_transport':
        outcome['detail'] = json.dumps({'state': 'unknown', 'error': 'ego_transport_unknown'})
    elif change == 'wrong_arm':
        trace['arm_round_id'] = 'b' * 32
    with pytest.raises(DoudianError, match='保持只读隔离'):
        evidence.verify_native_preclick_trace(trace, intent, outcome, data_root=tmp_path)
