from copy import deepcopy
from types import SimpleNamespace

import pytest

from doudian_auto import official_sku_codes as codes
from doudian_auto.errors import DoudianError, WaitingHuman


PID = '3790019980637110699'
SKUS = ['3387918799208229', '3387918799208230', '3387918799208231']
IDENTITY = {'product_id': PID, 'shop': '样板店'}
REFERENCE = {**IDENTITY, 'api_request_id': 'p1:100:request', 'api_body_sha256': '1' * 64,
             'page_url': f'https://fxg.jinritemai.com/ffa/g/create?product_id={PID}',
             'expected_sku_ids': SKUS}


def _row(sku, value=''):
    return {'sku_id': sku, 'code': value, 'observed': True, 'input_count': 1}


def _frame(rows, *, pending=0, **overrides):
    return {'product_id': PID, 'page_url': REFERENCE['page_url'], 'shop_confirmed': True,
            'navigation_id': 1000.0, 'ready': True, 'code_column': '商家编码',
            'pending_count': pending, 'rows': rows, **overrides}


@pytest.fixture
def probe(monkeypatch):
    state = SimpleNamespace(frames=[], calls=[], elapsed=0.0)

    def invoke(editor, operation, identity, navigation_id):
        state.calls.append((operation, deepcopy(identity), navigation_id))
        state.elapsed += 0.01
        frame = state.frames.pop(0) if len(state.frames) > 1 else state.frames[0]
        if isinstance(frame, Exception):
            raise frame
        return deepcopy(frame)

    monkeypatch.setattr(codes, '_probe', invoke)
    monkeypatch.setattr(codes, 'monotonic', lambda: state.elapsed)
    monkeypatch.setattr(codes, 'sleep', lambda seconds: setattr(state, 'elapsed', state.elapsed + seconds))
    return state


def _collect(probe, **kwargs):
    return codes.collect_official_sku_codes(SimpleNamespace(), IDENTITY, REFERENCE, **kwargs)


def test_scrolls_skeletons_and_accumulates_all_skus_by_identity_with_explicit_empty_values(probe):
    probe.frames = [_frame([_row(SKUS[1]), _row(SKUS[0])], pending=1),
                    _frame([_row(SKUS[1]), _row(SKUS[0])], pending=1),
                    _frame([_row(SKUS[2]), _row(SKUS[1])])]
    original = deepcopy(REFERENCE)
    proof = _collect(probe)
    assert codes.validate_sku_code_evidence(proof, REFERENCE) == dict.fromkeys(SKUS, '')
    assert [row['sku_id'] for row in proof['rows']] == SKUS
    assert proof['api_request_id'] == REFERENCE['api_request_id']
    assert proof['api_body_sha256'] == REFERENCE['api_body_sha256']
    assert [call[0] for call in probe.calls] == ['read', 'scroll_pending', 'scroll_pending']
    assert all(call[1] == IDENTITY for call in probe.calls)
    assert [call[2] for call in probe.calls] == [None, 1000.0, 1000.0]
    assert REFERENCE == original


def test_incomplete_coverage_exhausts_budget_without_filling_missing_code(probe):
    probe.frames = [_frame([_row(SKUS[0])], pending=2)]
    with pytest.raises(DoudianError, match='1/3') as caught:
        _collect(probe, seconds=0.45)
    assert caught.value.code == 'official_sku_code_incomplete'
    assert len(probe.calls) <= 4


@pytest.mark.parametrize('rows,code', [
    ([_row(SKUS[0]), _row(SKUS[0])], 'official_sku_code_duplicate_row'),
    ([_row('3387918799208999')], 'official_sku_code_evidence_invalid'),
    ([_row(SKUS[0], None)], 'official_sku_code_evidence_invalid'),
    ([{'sku_id': SKUS[0], 'observed': True, 'input_count': 1}], 'official_sku_code_evidence_invalid'),
    ([{**_row(SKUS[0]), 'observed': False}], 'official_sku_code_evidence_invalid'),
    ([{**_row(SKUS[0]), 'input_count': 2}], 'official_sku_code_evidence_invalid'),
    ([{**_row(SKUS[0]), 'sku_id': []}], 'official_sku_code_evidence_invalid'),
])
def test_unobserved_ambiguous_or_unknown_rows_cannot_supply_a_code(probe, rows, code):
    probe.frames = [_frame(rows, pending=2)]
    with pytest.raises(DoudianError) as caught:
        _collect(probe)
    assert caught.value.code == code
    assert len(probe.calls) == 1


def test_conflicting_repeated_sku_value_is_rejected_even_during_scroll(probe):
    probe.frames = [_frame([_row(SKUS[0])], pending=2),
                    _frame([_row(SKUS[0], 'changed'), _row(SKUS[1]), _row(SKUS[2])])]
    with pytest.raises(DoudianError) as caught:
        _collect(probe)
    assert caught.value.code == 'official_sku_code_conflict'
    assert [call[0] for call in probe.calls] == ['read', 'scroll_pending']


@pytest.mark.parametrize('changes,code', [
    ({'product_id': '3790019980637110698'}, 'wrong_identity'),
    ({'shop_confirmed': False}, 'wrong_identity'),
    ({'page_url': 'https://other.example/'}, 'wrong_identity'),
    ({'navigation_id': 2000.0}, 'official_sku_code_navigation_changed'),
])
def test_mid_collection_identity_or_navigation_changes_are_rejected(probe, changes, code):
    probe.frames = [_frame([_row(SKUS[0])], pending=2),
                    _frame([_row(SKUS[1]), _row(SKUS[2])], **changes)]
    with pytest.raises(DoudianError) as caught:
        _collect(probe)
    assert caught.value.code == code


def test_human_takeover_propagates_without_further_probe_calls(probe):
    probe.frames = [WaitingHuman('verification_required', '需要验证')]
    with pytest.raises(WaitingHuman) as caught:
        _collect(probe)
    assert caught.value.waiting is True
    assert len(probe.calls) == 1


def test_request_time_and_row_order_do_not_change_stable_value_hash(probe):
    probe.frames = [_frame([_row(sku) for sku in SKUS])]
    proof = _collect(probe)
    newer = deepcopy(proof)
    newer.update(api_request_id='p1:200:new-request', observed_at=proof['observed_at'] + 1)
    newer['rows'].reverse()
    assert codes.code_rows_sha256(newer['rows']) == proof['rows_sha256']
    reference = {**REFERENCE, 'api_request_id': newer['api_request_id']}
    assert codes.validate_sku_code_evidence(newer, reference) == dict.fromkeys(SKUS, '')
    with pytest.raises(DoudianError) as caught:
        codes.validate_sku_code_evidence(proof, reference)
    assert caught.value.code == 'official_sku_code_stale'


def test_code_value_changes_change_hash_and_forged_or_partial_proofs_are_rejected(probe):
    probe.frames = [_frame([_row(sku) for sku in SKUS])]
    proof = _collect(probe)
    changed = deepcopy(proof)
    changed['rows'][-1]['code'] = 'a-real-code'
    assert codes.code_rows_sha256(changed['rows']) != proof['rows_sha256']
    with pytest.raises(DoudianError):
        codes.validate_sku_code_evidence(changed, REFERENCE)
    partial = deepcopy(proof)
    partial['rows'].pop()
    with pytest.raises(DoudianError) as caught:
        codes.validate_sku_code_evidence(partial, REFERENCE)
    assert caught.value.code == 'official_sku_code_incomplete'
    wrong_body = {**REFERENCE, 'api_body_sha256': '2' * 64}
    with pytest.raises(DoudianError) as caught:
        codes.validate_sku_code_evidence(proof, wrong_body)
    assert caught.value.code == 'official_sku_code_stale'
