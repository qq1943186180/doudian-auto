from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from doudian_auto import batch, preflight
from doudian_auto.errors import DoudianError, WaitingHuman
from doudian_auto.jobs import Lock
from doudian_auto.official_skus import parse_official_skus


IDS = ['3850072900438720563', '3850072900438720564', '3850072900438720565']
SESSION = 'existing-user-taskspace'


@pytest.fixture
def queue(tmp_path):
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [
        {'product_id': pid, 'shop': f'样板店{index}', 'source_title': '原商品标题'}
        for index, pid in enumerate(IDS)
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    created = batch.create_batch(source, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute('SELECT * FROM products ORDER BY id')]
    return SimpleNamespace(db=db, batch_id=created['batch_id'], rows=rows, source=source)


def _snapshot(row, *, main_count=5, detail_count=4):
    pid = row['product_id']
    url = f'https://fxg.jinritemai.com/ffa/g/create?product_id={pid}'
    body = {'errno': 0, 'code': 0, 'data': {
        'context': {'product_id': pid, 'shop_id': '177970452',
                    'operation_type': 'normal', 'model_type': 'normal'},
        'model': {'sku_detail': {'value': [
            {'sku_id': '3387918799208229', 'id': '3387918799208229',
             'price': '10.00', 'stock_info': {'stock_num': 12},
             'step_stock_info': {'stock_num': 0}, 'spec_detail_ids': ['100001'],
             'code': 'fixture', 'sku_status': True}]},
            'spec_detail': {'value': [{'name': '颜色', 'spec_values': [{'id': '100001', 'name': '黑色'}]}]}}}}
    sku = parse_official_skus({'status': 200, 'completed': True, 'requestId': 'fixture:' + pid,
        'url': 'https://fxg.jinritemai.com/product/tproduct/getSchema',
        'page_url': url, 'body': json.dumps(body)}, product_id=pid)
    return {'product_id': pid, 'shop_confirmed': True, 'url': url, 'title': '原商品标题',
        'draft_loaded': False, 'rejected': False,
        'mains': [f'https://example.com/{pid}/main-{index}.png' for index in range(main_count)],
        'details': [f'https://example.com/{pid}/detail-{index}.png' for index in range(detail_count)],
        'main_delete_count': main_count, 'detail_declared': detail_count,
        'detail_cards': detail_count, 'detail_slots': detail_count, 'detail_delete_count': detail_count,
        'detail_status': 'ready', 'sku_evidence': sku,
        'protected': [{'section': 'goodsEditScrollContainer-' + name, 'observation': 'ready',
            'inputs': [], 'selections': ['完整观察'], 'static_fields': [], 'images': []}
            for name in ('基础信息', '价格库存', '服务与履约')],
        'required_attributes': {'observed': True, 'completion_percent': 100, 'fields': [
            {'name': '品牌', 'required': True, 'values': ['无品牌']},
            {'name': '硬度', 'required': True, 'values': ['中硬']},
            {'name': '可选项', 'required': False, 'values': []}], 'missing': []}}


@pytest.fixture
def browser(queue, monkeypatch):
    calls, identities = [], []
    snapshots = {row['product_id']: _snapshot(row) for row in queue.rows}

    class ReadOnlyBridge:
        def __init__(self, endpoint, *, session, timeout):
            calls.append({'endpoint': endpoint, 'session': session, 'timeout': timeout})
            self.session = session
            self.session_dir = batch.DATA_ROOT / 'ego-sessions' / hashlib.sha256(session.encode()).hexdigest()[:24]

        def command(self, action, args=None):
            pytest.fail(f'Preflight must not finish, close, fill, save or upload: {action}')

    def read(editor, identity):
        assert (batch.DATA_ROOT / 'browser.lock').is_file()
        identities.append(deepcopy(identity))
        value = snapshots[identity['product_id']]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(identity)
        return deepcopy(value)

    monkeypatch.setattr(preflight, 'Bridge', ReadOnlyBridge)
    monkeypatch.setattr(preflight, 'Editor', lambda bridge: SimpleNamespace(bridge=bridge))
    monkeypatch.setattr(batch, '_stable_doudian_snapshot', read)
    return SimpleNamespace(calls=calls, identities=identities, snapshots=snapshots)


def _run(queue, **kwargs):
    return preflight.preflight_products('http://127.0.0.1:10086', product_ids=IDS[:2],
        session=SESSION, db_path=queue.db, **kwargs)


def _update(queue, product_id=IDS[0], **values):
    with sqlite3.connect(queue.db) as conn:
        conn.execute('UPDATE products SET ' + ','.join(key + '=?' for key in values) + ' WHERE product_id=?',
                     [*values.values(), product_id])


def test_missing_required_attributes_block_only_this_product_and_never_change_queue(queue, browser, monkeypatch):
    proof = browser.snapshots[IDS[0]]['required_attributes']
    proof['fields'][1]['values'] = []
    proof['missing'] = ['硬度']
    proof['completion_percent'] = 50
    before = queue.db.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail('Read-only preflight must never open the migrating DB helper or mutate a queue')

    for name in ('_db', 'claim_next', 'claim_execution', 'complete_agent_task', 'record_baseline',
                 'set_execution_state', 'begin_submission'):
        monkeypatch.setattr(batch, name, forbidden)
    result = _run(queue)

    assert queue.db.read_bytes() == before
    first, second = result['products']
    assert first['eligible'] is False
    assert first['reason'] == 'required_attributes_missing'
    assert first['missing_fields'] == ['硬度']
    assert first['evidence']['snapshot_read'] is True
    assert first['evidence']['required_attributes']['completion_percent'] == 50
    assert second['eligible'] is True
    assert result['candidate_product_ids'] == [IDS[1]]
    assert result['counts'] == {'eligible': 1, 'blocked': 1, 'skipped': 0}
    assert browser.identities == [{'product_id': row['product_id'], 'shop': row['shop'],
        'edit_url': f'https://fxg.jinritemai.com/ffa/g/create?product_id={row["product_id"]}'}
        for row in queue.rows[:2]]
    assert [item['target_version'] for item in result['products']] == [row['target_version'] for row in queue.rows[:2]]
    assert len(set(item['target_version'] for item in result['products'])) == 2
    assert browser.calls == [{'endpoint': 'http://127.0.0.1:10086', 'session': SESSION, 'timeout': 25}]
    assert all(item['elapsed_seconds'] >= item['read_elapsed_seconds'] >= 0 for item in result['products'])
    assert not (batch.DATA_ROOT / 'browser.lock').exists()


@pytest.mark.parametrize('change', ['product', 'shop', 'shop_confirmation', 'sku_product'])
def test_wrong_identity_is_not_a_candidate_and_does_not_abort_next_read(queue, browser, change):
    snapshot = browser.snapshots[IDS[0]]
    if change == 'product':
        snapshot['product_id'] = IDS[2]
    elif change == 'shop':
        snapshot['shop'] = '另一家店'
    elif change == 'shop_confirmation':
        snapshot['shop_confirmed'] = False
    else:
        snapshot['sku_evidence']['product_id'] = IDS[2]
    result = _run(queue)
    assert result['products'][0]['reason'] == 'wrong_identity'
    assert result['candidate_product_ids'] == [IDS[1]]


@pytest.mark.parametrize('flag', ['draft_loaded', 'rejected'])
def test_draft_or_rejected_official_page_is_blocked(queue, browser, flag):
    browser.snapshots[IDS[0]][flag] = True
    result = _run(queue)
    assert result['products'][0]['reason'] == 'doudian_draft_or_rejected'
    assert result['products'][0]['evidence'][flag] is True
    assert result['candidate_product_ids'] == [IDS[1]]


@pytest.mark.parametrize('field,code', [
    ('required_attributes', 'required_attributes_unobserved'),
    ('sku_evidence', 'official_sku_incomplete'),
    ('protected', 'protected_snapshot_incomplete'),
    ('draft_loaded', 'official_business_state_unobserved'),
    ('title', 'official_content_incomplete'),
    ('mains', 'official_content_incomplete'),
    ('details', 'official_content_incomplete'),
    ('detail_status', 'official_content_incomplete'),
])
def test_missing_official_evidence_is_never_treated_as_complete(queue, browser, field, code):
    del browser.snapshots[IDS[0]][field]
    result = _run(queue)
    assert result['products'][0]['reason'] == code
    assert result['candidate_product_ids'] == [IDS[1]]


def test_partial_required_attribute_progress_and_unobserved_protected_blocks_fail(queue, browser):
    browser.snapshots[IDS[0]]['required_attributes']['completion_percent'] = 90
    browser.snapshots[IDS[1]]['protected'][1]['observation'] = 'unobserved'
    result = _run(queue)
    assert [item['reason'] for item in result['products']] == [
        'required_attributes_unobserved', 'protected_snapshot_incomplete']
    assert result['candidate_product_ids'] == []


@pytest.mark.parametrize('main_count,detail_count', [(4, 4), (5, 3)])
def test_official_image_slots_must_satisfy_current_writer_before_generating_assets(
        queue, browser, main_count, detail_count):
    browser.snapshots[IDS[0]] = _snapshot(queue.rows[0], main_count=main_count, detail_count=detail_count)
    before = queue.db.read_bytes()
    result = _run(queue)

    first, second = result['products']
    assert first['eligible'] is False
    assert first['reason'] == 'writer_image_slots_incomplete'
    assert f'主图{main_count}张、详情{detail_count}张' in first['message']
    assert first['evidence']['main_count'] == main_count
    assert first['evidence']['detail_count'] == detail_count
    assert second['evidence']['main_count'] == 5
    assert second['evidence']['detail_count'] == 4
    assert result['candidate_product_ids'] == [IDS[1]]
    assert queue.db.read_bytes() == before


def test_concrete_read_exception_is_recorded_and_next_product_is_read(queue, browser):
    browser.snapshots[IDS[0]] = DoudianError('official_sku_incomplete', '官方完整SKU响应未读到')
    result = _run(queue)
    assert result['products'][0]['reason'] == 'official_sku_incomplete'
    assert result['products'][0]['message'] == '官方完整SKU响应未读到'
    assert result['products'][0]['evidence']['snapshot_read'] is False
    assert result['products'][0]['read_elapsed_seconds'] >= 0
    assert result['candidate_product_ids'] == [IDS[1]]
    assert result['waiting_human'] is False
    assert result['products'][0]['waiting_human'] is False


@pytest.mark.parametrize('blocked_index', [0, 1])
@pytest.mark.parametrize('error', [
    WaitingHuman('ego_control_required', '浏览器已交给用户，请恢复任务控制。'),
    DoudianError('verification_required', '请先完成人工验证。', waiting=True),
])
def test_human_action_stops_browser_access_and_preserves_remaining_ids(
        queue, browser, tmp_path, blocked_index, error):
    browser.snapshots[IDS[blocked_index]] = error
    before = queue.db.read_bytes()
    result = preflight.preflight_products('http://127.0.0.1:10086', product_ids=IDS,
        limit=2, session=SESSION, db_path=queue.db, report_dir=tmp_path / 'reports')

    assert queue.db.read_bytes() == before
    assert [item['product_id'] for item in browser.identities] == IDS[:blocked_index + 1]
    assert len(result['products']) == blocked_index + 1
    current = result['products'][-1]
    assert current['product_id'] == IDS[blocked_index]
    assert current['reason'] == error.code
    assert current['waiting_human'] is True
    assert current['eligible'] is False
    assert result['waiting_human'] is True
    assert result['unprocessed_product_ids'] == IDS[blocked_index + 1:]
    assert result['candidate_product_ids'] == IDS[:blocked_index]
    assert result['counts'] == {'eligible': blocked_index, 'blocked': 1, 'skipped': 0}
    assert json.loads(Path(result['report_path']).read_text(encoding='utf-8')) == result
    assert not (batch.DATA_ROOT / 'browser.lock').exists()


@pytest.mark.parametrize('changes,code', [
    ({'state': 'verified'}, 'already_verified'),
    ({'submission_state': 'verified_by_readback'}, 'already_verified'),
    ({'submission_state': 'unknown', 'submission_attempts': 1}, 'submission_unknown'),
    ({'state': 'submitting'}, 'submission_unknown'),
    ({'submission_attempts': 1}, 'prior_submission'),
    ({'submission_state': 'accepted'}, 'prior_submission'),
    ({'state': 'agent_claimed', 'lease_owner': 'other-agent', 'lease_until': 9999999999}, 'queue_state_ineligible'),
    ({'state': 'editing'}, 'queue_state_ineligible'),
    ({'state': 'ready'}, 'queue_state_ineligible'),
    ({'state': 'blocked'}, 'queue_state_ineligible'),
    ({'execution_owner': 'other-writer', 'execution_until': 9999999999}, 'product_in_use'),
    ({'lease_owner': 'other-agent', 'lease_until': 9999999999}, 'product_in_use'),
    ({'artifacts_path': '/existing/material.json'}, 'existing_work'),
    ({'baseline_hash': 'existing-baseline'}, 'existing_work'),
    ({'upload_map_json': '[{"slot":"mains:1"}]'}, 'existing_work'),
])
def test_verified_unknown_or_in_use_products_are_skipped_without_opening_their_page(queue, browser, changes, code):
    _update(queue, **changes)
    before = queue.db.read_bytes()
    result = _run(queue)
    assert queue.db.read_bytes() == before
    first = result['products'][0]
    assert first['state'] == 'skipped'
    assert first['reason'] == code
    assert first['evidence']['snapshot_read'] is False
    assert first['read_elapsed_seconds'] == 0
    assert [identity['product_id'] for identity in browser.identities] == [IDS[1]]


@pytest.mark.parametrize('change,code', [
    ({'state': 'agent_claimed', 'lease_owner': 'other-agent', 'lease_until': 9999999999}, 'queue_state_ineligible'),
    ({'target_version': 'a-new-version'}, 'queue_identity_changed'),
    ({'shop': 'another-shop'}, 'queue_identity_changed'),
])
def test_queue_identity_and_occupancy_are_rechecked_after_official_read(queue, browser, change, code):
    snapshot = browser.snapshots[IDS[0]]

    def concurrent_change(identity):
        _update(queue, **change)
        return snapshot

    browser.snapshots[IDS[0]] = concurrent_change
    result = _run(queue)
    assert result['products'][0]['eligible'] is False
    assert result['products'][0]['reason'] == code
    assert result['candidate_product_ids'] == [IDS[1]]


@pytest.mark.parametrize('limit', [0, -1, 21, True, 1.5, '2'])
def test_limit_must_be_an_integer_from_one_to_twenty(queue, browser, limit):
    with pytest.raises(DoudianError) as caught:
        _run(queue, limit=limit)
    assert caught.value.code == 'invalid_limit'
    assert browser.calls == []


@pytest.mark.parametrize('ids,code', [
    ([], 'invalid_product_ids'), (IDS[0], 'invalid_product_ids'),
    ([IDS[0], IDS[0]], 'duplicate_product'), (['not-a-product'], 'invalid_product_ids'),
    (['３８５００７２９００４３８７２０５６３'], 'invalid_product_ids'),
])
def test_invalid_or_duplicate_ids_fail_before_any_browser_action(queue, browser, ids, code):
    with pytest.raises(DoudianError) as caught:
        preflight.preflight_products('ego', product_ids=ids, session=SESSION, db_path=queue.db)
    assert caught.value.code == code
    assert browser.calls == []


def test_unknown_id_even_beyond_limit_is_an_input_error_without_reports_or_browser_actions(queue, browser, tmp_path):
    report = tmp_path / 'not-created'
    with pytest.raises(DoudianError) as caught:
        preflight.preflight_products('ego', product_ids=[IDS[0], '3850072900438720999'],
            limit=1, session=SESSION, db_path=queue.db, report_dir=report)
    assert caught.value.code == 'unknown_product'
    assert browser.calls == []
    assert not report.exists()


def test_limit_preserves_explicit_order_and_lists_unprocessed_ids(queue, browser):
    result = preflight.preflight_products('http://127.0.0.1:10086', product_ids=list(reversed(IDS)),
        batch_id=queue.batch_id, limit=2, session=SESSION, db_path=queue.db)
    assert [item['product_id'] for item in result['products']] == list(reversed(IDS))[0:2]
    assert result['unprocessed_product_ids'] == [IDS[0]]


def test_ambiguous_product_requires_batch_and_other_versions_cannot_become_candidates(queue, browser):
    duplicate = batch.create_batch(queue.source, db_path=queue.db)
    with pytest.raises(DoudianError) as caught:
        _run(queue)
    assert caught.value.code == 'ambiguous_product'
    assert browser.calls == []
    result = _run(queue, batch_id=queue.batch_id)
    assert all(item['reason'] == 'product_queue_conflict' for item in result['products'])
    assert result['candidate_product_ids'] == []
    assert duplicate['batch_id'] != queue.batch_id
    assert browser.calls == []


def test_readonly_preflight_never_creates_missing_queue_or_migrates_empty_target_versions(queue, browser, tmp_path):
    missing = tmp_path / 'absent' / 'queue.sqlite3'
    with pytest.raises(DoudianError) as caught:
        preflight.preflight_products('ego', product_ids=[IDS[0]], session=SESSION, db_path=missing)
    assert caught.value.code == 'preflight_queue_missing'
    assert not missing.parent.exists()
    _update(queue, target_version='')
    before = queue.db.read_bytes()
    result = _run(queue)
    assert result['products'][0]['reason'] == 'queue_identity_incomplete'
    assert queue.db.read_bytes() == before


def test_global_browser_lock_excludes_preflight_and_is_never_stolen(queue, browser):
    path = batch.DATA_ROOT / 'browser.lock'
    with Lock(path):
        with pytest.raises(DoudianError) as caught:
            _run(queue)
        assert caught.value.code == 'busy'
        assert path.is_file()
        assert browser.calls == []


def _session_state(state):
    path = batch.DATA_ROOT / 'ego-sessions' / hashlib.sha256(SESSION.encode()).hexdigest()[:24] / 'state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding='utf-8')
    return path


@pytest.mark.parametrize('state,code', [
    (None, 'ego_session_missing'), ({'pages': {}}, 'ego_session_missing'),
    ({'spaceId': '1'}, 'ego_session_missing'),
    ({'spaceId': 1, 'finished': True}, 'ego_session_finished'),
])
def test_ego_missing_or_finished_space_does_not_create_or_reset_a_session(queue, browser, state, code):
    path = _session_state(state) if state is not None else None
    before = path.read_bytes() if path else None
    result = preflight.preflight_products('ego', product_ids=IDS[:2], session=SESSION, db_path=queue.db)
    assert [item['reason'] for item in result['products']] == [code, code]
    assert browser.identities == []
    if path:
        assert path.read_bytes() == before
    else:
        assert not (batch.DATA_ROOT / 'ego-sessions').exists()


def test_existing_ego_space_is_reused_without_finish_close_or_state_changes(queue, browser):
    path = _session_state({'spaceId': 1, 'active': 'p1', 'pages': {'official-route': 'p1'}})
    before = path.read_bytes()
    result = preflight.preflight_products('ego', product_ids=IDS[:2], session=SESSION, db_path=queue.db)
    assert result['candidate_product_ids'] == IDS[:2]
    assert all(item['evidence']['space_id'] == 1 for item in result['products'])
    assert path.read_bytes() == before
    assert browser.calls[0]['session'] == SESSION


def test_ego_space_changed_during_read_is_not_accepted(queue, browser):
    path = _session_state({'spaceId': 1, 'pages': {}})
    snapshot = browser.snapshots[IDS[0]]

    def change_space(identity):
        path.write_text(json.dumps({'spaceId': 2, 'pages': {}}), encoding='utf-8')
        return snapshot

    browser.snapshots[IDS[0]] = change_space
    result = preflight.preflight_products('ego', product_ids=IDS[:2], session=SESSION, db_path=queue.db)
    assert [item['reason'] for item in result['products']] == ['ego_session_changed', 'ego_session_changed']
    assert result['candidate_product_ids'] == []
    assert [item['product_id'] for item in browser.identities] == [IDS[0]]


def test_optional_reports_keep_readonly_evidence_and_redact_credentials(queue, browser, tmp_path):
    snapshot = browser.snapshots[IDS[0]]
    snapshot['context'] = {'token': 'TOP_LEVEL_SECRET'}
    snapshot['protected'][0]['access_token'] = 'NESTED_SECRET'
    snapshot['protected'][0]['inputs'] = [{'type': 'password', 'value': 'PASSWORD_SECRET'}]
    snapshot['mains'][0] = 'https://user:URL_SECRET@example.com/image.png?token=QUERY_SECRET&size=600'
    browser.snapshots[IDS[1]] = DoudianError('bridge_transport',
        'Authorization: Bearer AUTH_SECRET; Cookie: sid=COOKIE_SECRET; token=EXCEPTION_SECRET')
    result = _run(queue, report_dir=tmp_path / 'reports')
    report_path = Path(result['report_path'])
    saved_result = json.loads(report_path.read_text(encoding='utf-8'))
    assert saved_result == result
    assert result['candidate_product_ids'] == [IDS[0]]
    snapshot_path = Path(result['products'][0]['evidence']['snapshot_path'])
    saved = json.loads(snapshot_path.read_text(encoding='utf-8'))
    assert saved['target_version'] == queue.rows[0]['target_version']
    assert saved['shop'] == queue.rows[0]['shop']
    assert saved['snapshot']['sku_evidence']['count'] == 1
    text = report_path.read_text(encoding='utf-8') + snapshot_path.read_text(encoding='utf-8')
    for secret in ('TOP_LEVEL_SECRET', 'NESTED_SECRET', 'PASSWORD_SECRET', 'URL_SECRET',
                   'QUERY_SECRET', 'AUTH_SECRET', 'COOKIE_SECRET', 'EXCEPTION_SECRET'):
        assert secret not in text
    assert '[redacted]' in text


def test_calls_shared_stable_reader_for_fresh_complete_snapshots(queue, monkeypatch):
    opens, commands = [], []

    class Bridge:
        def __init__(self, endpoint, *, session, timeout):
            assert session == SESSION

        def command(self, action, args=None):
            assert action == 'cdp'
            commands.append(args)

    class Editor:
        def __init__(self, bridge):
            self.bridge = bridge

        def open(self, identity, *, fresh):
            assert fresh is True
            assert (batch.DATA_ROOT / 'browser.lock').is_file()
            opens.append(identity['product_id'])
            self.snapshot = _snapshot(next(row for row in queue.rows if row['product_id'] == identity['product_id']))

        def read_skus(self, identity):
            return deepcopy(self.snapshot['sku_evidence'])

        def dom(self, op, identity, **kwargs):
            assert op == 'scroll'

        def section_counts(self, identity):
            return {'基础信息': {'inputs': 1, 'text': 10, 'visible': True}}

        def wait_details(self, identity, seconds):
            return deepcopy(self.snapshot)

    monkeypatch.setattr(preflight, 'Bridge', Bridge)
    monkeypatch.setattr(preflight, 'Editor', Editor)
    monkeypatch.setattr(batch.time, 'sleep', lambda seconds: None)
    result = _run(queue)
    assert opens == IDS[:2]
    assert len(commands) == 4
    assert result['candidate_product_ids'] == IDS[:2]
