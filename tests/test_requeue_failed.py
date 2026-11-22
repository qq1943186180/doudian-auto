"""结清「平台已判定失败且零变更」的提交，并重新排队。

这些测试钉住两件事：证据不齐时一行都不改；证据齐时只做「清基线 + 归零尝试 + 写可重新预检
的错误前缀」，并把原提交意图留在事件里。
"""

import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.requeue_failed import (
    FAILED_REQUEUE_PREFIX,
    requeue_failed_submission,
)


PID = '3850072900438720563'
SHOP = '样板店'
BASELINE = 'a' * 64
MANIFEST = 'b' * 64


@pytest.fixture
def queue(tmp_path):
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [{'product_id': PID, 'shop': SHOP,
                                                'source_title': '原商品标题'}]},
                                 ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    created = batch.create_batch(source, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """UPDATE products SET state='blocked', submission_state='unknown',
                   submission_attempts=1, baseline_json=?, baseline_hash=?, artifacts_hash=?,
                   artifacts_path='/tmp/x.json', upload_map_json='[{"slot":"mains:1"}]',
                   readback_json='{}', readback_hash=?, submission_intent_json='{"attempt":1}'
               WHERE product_id=?""",
            (json.dumps({'title': '原商品标题', 'mains': [], 'details': [],
                         'protected': {}, 'slot_plan': {'mains': 5, 'details': 2}},
                        ensure_ascii=False),
             BASELINE, MANIFEST, 'c' * 64, PID))
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM products WHERE product_id=?', (PID,)).fetchone())
    return SimpleNamespace(db=db, row=row, tmp=tmp_path)


def proof(queue, **overrides):
    document = {
        'schema_version': 1,
        'task_id': queue.row['id'],
        'product_id': PID,
        'shop': SHOP,
        'target_version': queue.row['target_version'],
        'baseline_sha256': BASELINE,
        'manifest_sha256': MANIFEST,
        'read_only': True,
        'observed_at': time.time(),
        'miaoshou_task': {'task_id': '36278985', 'finished': True, 'success_count': 0,
                          'fail_count': 1, 'reasons': ['尺码表数据非法，存在尺码表值重复'],
                          'product_id_confirmed': PID},
        'unchanged': {'title': True, 'mains': True, 'details': True, 'protected': True},
    }
    document.update(overrides)
    return document


def write(queue, document):
    path = queue.tmp / 'proof.json'
    path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    return path


def current(queue):
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute('SELECT * FROM products WHERE product_id=?', (PID,)).fetchone())


def events(queue):
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            'SELECT * FROM product_events WHERE task_id=? ORDER BY occurred_at', (queue.row['id'],))]


def test_complete_evidence_clears_the_record_and_requeues(queue):
    result = requeue_failed_submission(queue.row['id'], write(queue, proof(queue)), db_path=queue.db)

    assert result['submission_state'] == 'not_attempted'
    row = current(queue)
    assert row['state'] == 'blocked'
    assert row['submission_state'] == 'not_attempted'
    assert row['submission_attempts'] == 0
    assert row['baseline_hash'] is None and row['baseline_json'] is None
    assert row['artifacts_path'] is None and row['artifacts_hash'] is None
    assert json.loads(row['upload_map_json']) == []
    assert row['readback_hash'] is None
    assert row['last_error'].startswith(FAILED_REQUEUE_PREFIX)
    assert '尺码表数据非法' in row['last_error']
    recorded = events(queue)
    assert recorded and json.loads(recorded[-1]['detail'])['action'] == 'requeue_failed_submission'
    detail = json.loads(recorded[-1]['detail'])
    # 清空基线前必须留下可独立复核零变更的那部分内容，只留哈希无法再验证。
    assert detail['prior_baseline']['baseline_sha256'] == BASELINE
    assert detail['prior_baseline']['title'] == '原商品标题'
    assert detail['prior_baseline']['slot_plan'] == {'mains': 5, 'details': 2}


def test_a_task_that_succeeded_anywhere_is_refused(queue):
    document = proof(queue, miaoshou_task={'task_id': '1', 'finished': True, 'success_count': 1,
                                           'fail_count': 1, 'reasons': ['x'],
                                           'product_id_confirmed': PID})
    with pytest.raises(DoudianError) as caught:
        requeue_failed_submission(queue.row['id'], write(queue, document), db_path=queue.db)
    assert caught.value.code == 'requeue_failed_unproven'
    assert current(queue)['submission_state'] == 'unknown'


@pytest.mark.parametrize('task', [
    {'task_id': '', 'finished': True, 'success_count': 0, 'fail_count': 1, 'reasons': ['x'],
     'product_id_confirmed': PID},
    {'finished': True, 'success_count': 0, 'fail_count': 1, 'reasons': ['x'],
     'product_id_confirmed': PID},
    {'task_id': '36278985', 'finished': True, 'success_count': 0, 'fail_count': 1, 'reasons': ['x'],
     'product_id_confirmed': '123'},
    {'task_id': '36278985', 'finished': True, 'success_count': 0, 'fail_count': 1, 'reasons': ['x']},
])
def test_the_platform_task_must_be_identified_and_belong_to_this_product(queue, task):
    with pytest.raises(DoudianError) as caught:
        requeue_failed_submission(queue.row['id'], write(queue, proof(queue, miaoshou_task=task)),
                                  db_path=queue.db)
    assert caught.value.code == 'requeue_failed_unproven'
    assert current(queue)['submission_state'] == 'unknown'


@pytest.mark.parametrize('task', [
    {'task_id': '1', 'finished': False, 'success_count': 0, 'fail_count': 1, 'reasons': ['x'],
     'product_id_confirmed': PID},
    {'task_id': '1', 'finished': True, 'success_count': 0, 'fail_count': 0, 'reasons': ['x'],
     'product_id_confirmed': PID},
    {'task_id': '1', 'finished': True, 'success_count': 0, 'fail_count': 1, 'reasons': [],
     'product_id_confirmed': PID},
    {'task_id': '1', 'finished': True, 'success_count': 0, 'fail_count': 1, 'reasons': ['   '],
     'product_id_confirmed': PID},
])
def test_unproven_task_state_is_refused(queue, task):
    with pytest.raises(DoudianError) as caught:
        requeue_failed_submission(queue.row['id'], write(queue, proof(queue, miaoshou_task=task)),
                                  db_path=queue.db)
    assert caught.value.code == 'requeue_failed_unproven'


@pytest.mark.parametrize('changed', ['title', 'mains', 'details', 'protected'])
def test_any_unproven_unchanged_field_is_refused(queue, changed):
    unchanged = {'title': True, 'mains': True, 'details': True, 'protected': True, changed: False}
    with pytest.raises(DoudianError) as caught:
        requeue_failed_submission(queue.row['id'], write(queue, proof(queue, unchanged=unchanged)),
                                  db_path=queue.db)
    assert caught.value.code == 'requeue_failed_unproven'


@pytest.mark.parametrize('override', [
    {'product_id': '123'},
    {'shop': '别的店'},
    {'target_version': 'legacy-other'},
    {'baseline_sha256': 'd' * 64},
    {'manifest_sha256': 'e' * 64},
    {'read_only': False},
    {'observed_at': time.time() - 3600},
])
def test_evidence_must_bind_to_this_row_and_be_fresh(queue, override):
    with pytest.raises(DoudianError) as caught:
        requeue_failed_submission(queue.row['id'], write(queue, proof(queue, **override)),
                                  db_path=queue.db)
    assert caught.value.code == 'requeue_failed_unproven'


def test_only_an_unknown_first_attempt_is_eligible(queue):
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET submission_state='accepted' WHERE product_id=?", (PID,))
    with pytest.raises(DoudianError) as caught:
        requeue_failed_submission(queue.row['id'], write(queue, proof(queue)), db_path=queue.db)
    assert caught.value.code == 'requeue_failed_unproven'


def test_a_second_attempt_is_not_eligible(queue):
    with sqlite3.connect(queue.db) as conn:
        conn.execute('UPDATE products SET submission_attempts=2 WHERE product_id=?', (PID,))
    with pytest.raises(DoudianError):
        requeue_failed_submission(queue.row['id'], write(queue, proof(queue)), db_path=queue.db)


def test_a_sibling_revision_blocks_the_requeue(queue):
    with sqlite3.connect(queue.db) as conn:
        conn.execute(
            """INSERT INTO products(batch_id,shop,product_id,source,facts_json,state,submission_state,updated_at)
               VALUES(?,?,?,?,?,'blocked','not_attempted',?)""",
            (queue.row['batch_id'] + '-other', SHOP, PID, '{}', '{}', time.time()))
    with pytest.raises(DoudianError) as caught:
        requeue_failed_submission(queue.row['id'], write(queue, proof(queue)), db_path=queue.db)
    assert caught.value.code == 'requeue_failed_unproven'


def test_an_unreadable_proof_is_refused(queue):
    path = queue.tmp / 'proof.json'
    path.write_text('{not json', encoding='utf-8')
    with pytest.raises(Exception):
        requeue_failed_submission(queue.row['id'], path, db_path=queue.db)
    assert current(queue)['submission_state'] == 'unknown'


@pytest.mark.parametrize('mode', ['valid', 'extra_selection_change', 'non_base_section_change', 'missing_interventions', 'status_on_shelf'])
def test_requeue_failed_with_expected_attribute_additions(queue, mode):
    import hashlib
    from copy import deepcopy
    from doudian_auto.official_skus import _normalize
    sku_raw = [{'sku_id': '1001', 'id': '1001', 'price': '19.99', 'stock_info': {'stock_num': 50},
                'step_stock_info': {'stock_num': 0}, 'spec_detail_ids': ['2001'], 'sku_status': True, 'code': 'C1'}]
    specs = [{'name': '颜色', 'spec_values': [{'id': '2001', 'name': '白色'}]}]
    sku_rows = [{'sku_id': '1001', 'spec_ids': ['2001'], 'price': '19.99', 'stock': 50, 'step_stock': 0, 'enabled': True, 'code': 'C1'}]
    payload = {'rows': sku_rows, 'raw_rows': _normalize(sku_raw), 'specs': _normalize(specs)}
    sku_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    sku_ev = {'complete': True, 'product_id': PID, 'shop_id': '999', 'count': 1, **payload, 'sha256': sku_sha}

    mains = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www800-800' for i in range(1, 6)]
    details = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www800-800' for i in range(11, 15)]
    base_dd = {
        'product_id': PID, 'shop': SHOP, 'shop_confirmed': True, 'title': '原商品标题',
        'mains': mains, 'details': details, 'draft_loaded': False, 'rejected': False,
        'required_attributes': {'observed': True, 'completion_percent': 80, 'missing': ['硬度'],
                                'fields': [{'name': '硬度', 'required': True, 'values': []}]},
        'sku_evidence': sku_ev,
        'protected': [
            {'section': 'goodsEditScrollContainer-基础信息', 'observation': 'ready',
             'inputs': [], 'selections': ['ABS'], 'static_fields': [], 'images': []},
            {'section': 'goodsEditScrollContainer-价格库存', 'observation': 'ready',
             'inputs': [], 'selections': ['现货'], 'static_fields': [], 'images': []},
        ],
    }
    miao_prot = {
        'status': 1, 'freightId': 1, 'startSaleType': 0, 'afterSaleService': {},
        'specPrices': [{'skuId': 1001, 'specDetailIds': [2001], 'price': '19.99',
                        'stockNum': 50, 'stepStockNum': 0, 'code': 'C1', 'skuStatus': True}],
    }
    saved_base = {
        'product_id': PID, 'shop': SHOP, 'title': '原商品标题', 'mains': mains, 'details': details,
        'slot_plan': {'mains': 5, 'details': 2}, 'protected': miao_prot, 'doudian_baseline': base_dd,
    }
    b_str = json.dumps(saved_base, ensure_ascii=False, sort_keys=True)
    b_hash = hashlib.sha256(b_str.encode()).hexdigest()
    with sqlite3.connect(queue.db) as conn:
        conn.execute('UPDATE products SET baseline_json=?, baseline_hash=? WHERE id=?',
                     (b_str, b_hash, queue.row['id']))
    queue.row['baseline_hash'] = b_hash

    curr_dd = deepcopy(base_dd)
    curr_dd['required_attributes'] = {'observed': True, 'completion_percent': 100, 'missing': [],
                                      'fields': [{'name': '硬度', 'required': True, 'values': ['软毛']}]}
    curr_dd['protected'][0]['selections'] = ['ABS', '软毛']
    if mode == 'extra_selection_change':
        curr_dd['protected'][0]['selections'].append('额外未声明')
    elif mode == 'non_base_section_change':
        curr_dd['protected'][1]['selections'] = ['预售']
    curr_miao = {'product_id': PID, 'shop': SHOP, 'protected_complete': True,
                 'title': '原商品标题', 'mains': mains, 'details': details,
                 'protected': {**miao_prot, 'status': 0 if mode == 'status_on_shelf' else 1}}

    m_path = queue.tmp / 'miao_curr.json'
    d_path = queue.tmp / 'dd_curr.json'
    m_path.write_text(json.dumps(curr_miao, ensure_ascii=False), encoding='utf-8')
    d_path.write_text(json.dumps(curr_dd, ensure_ascii=False), encoding='utf-8')
    doc = proof(queue, miaoshou_task={'task_id': '36278985', 'finished': True, 'success_count': 0,
                                      'fail_count': 1, 'reasons': ['缺硬度'], 'product_id_confirmed': PID})
    doc['baseline_sha256'] = b_hash
    doc['expected_attribute_additions'] = [{'field': '硬度', 'values': ['软毛']}]
    doc['interventions'] = [] if mode == 'missing_interventions' else [{'action': 'fill_required_attr', 'detail': '硬度=软毛'}]
    doc['snapshots'] = {
        'miaoshou': {'path': m_path.name, 'sha256': hashlib.sha256(m_path.read_bytes()).hexdigest()},
        'doudian': {'path': d_path.name, 'sha256': hashlib.sha256(d_path.read_bytes()).hexdigest()},
    }
    if mode == 'valid':
        res = requeue_failed_submission(queue.row['id'], write(queue, doc), db_path=queue.db)
        assert res['submission_state'] == 'not_attempted'
        assert res['attribute_backfill']['actual_added_selections'] == ['软毛']
        detail = json.loads(events(queue)[-1]['detail'])
        assert detail['attribute_backfill']['actual_added_selections'] == ['软毛']
    else:
        with pytest.raises(DoudianError) as caught:
            requeue_failed_submission(queue.row['id'], write(queue, doc), db_path=queue.db)
        assert caught.value.code == 'requeue_failed_unproven'


@pytest.mark.parametrize(
    'case',
    [
        'empty_video_promo_valid',
        'video_text_other_diff',
        'wrong_section_same_text',
        'extra_image_with_promo',
        'start_sale_0_to_1_valid',
        'start_sale_missing_flag',
        'start_sale_1_to_0_reverse',
        'start_sale_0_to_2',
        'start_sale_status_0',
        'start_sale_missing_status',
        'start_sale_with_freight_diff',
    ],
)
def test_requeue_failed_backfill_empty_video_and_warehouse_preservation(queue, case):
    import hashlib
    from copy import deepcopy
    from doudian_auto.official_skus import _normalize

    old_promo = '主图视频 发布优质主图视频，介绍商品卖点，展示试穿试用效果，预计 转化率+0.5%'
    new_promo = old_promo + ' 一键生成'
    sku_raw = [{'sku_id': '1001', 'id': '1001', 'price': '19.99', 'stock_info': {'stock_num': 50},
                'step_stock_info': {'stock_num': 0}, 'spec_detail_ids': ['2001'], 'sku_status': True, 'code': 'C1'}]
    specs = [{'name': '颜色', 'spec_values': [{'id': '2001', 'name': '白色'}]}]
    sku_rows = [{'sku_id': '1001', 'spec_ids': ['2001'], 'price': '19.99', 'stock': 50, 'step_stock': 0, 'enabled': True, 'code': 'C1'}]
    payload = {'rows': sku_rows, 'raw_rows': _normalize(sku_raw), 'specs': _normalize(specs)}
    sku_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    sku_ev = {'complete': True, 'product_id': PID, 'shop_id': '999', 'count': 1, **payload, 'sha256': sku_sha}

    mains = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www800-800' for i in range(1, 6)]
    details = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www800-800' for i in range(11, 15)]
    base_dd = {
        'product_id': PID, 'shop': SHOP, 'shop_confirmed': True, 'title': '原商品标题',
        'mains': mains, 'details': details, 'draft_loaded': False, 'rejected': False,
        'required_attributes': {'observed': True, 'completion_percent': 80, 'missing': ['硬度'],
                                'fields': [{'name': '硬度', 'required': True, 'values': []}]},
        'sku_evidence': sku_ev,
        'protected': [
            {'section': 'goodsEditScrollContainer-基础信息', 'observation': 'ready',
             'inputs': [], 'selections': ['ABS'], 'static_fields': [], 'images': []},
            {'section': 'goodsEditScrollContainer-图文信息', 'observation': 'ready',
             'inputs': [], 'selections': [],
             'static_fields': [{'field': '主图视频', 'text': old_promo}],
             'images': []},
        ],
    }
    miao_prot = {
        'status': 1, 'freightId': 1, 'startSaleType': 0, 'afterSaleService': {},
        'specPrices': [{'skuId': 1001, 'specDetailIds': [2001], 'price': '19.99',
                        'stockNum': 50, 'stepStockNum': 0, 'code': 'C1', 'skuStatus': True}],
    }
    if case == 'start_sale_1_to_0_reverse':
        miao_prot['startSaleType'] = 1
    elif case == 'start_sale_status_0':
        miao_prot['status'] = 0
    saved_base = {
        'product_id': PID, 'shop': SHOP, 'title': '原商品标题', 'mains': mains, 'details': details,
        'slot_plan': {'mains': 5, 'details': 2}, 'protected': miao_prot, 'doudian_baseline': base_dd,
    }
    b_str = json.dumps(saved_base, ensure_ascii=False, sort_keys=True)
    b_hash = hashlib.sha256(b_str.encode()).hexdigest()
    with sqlite3.connect(queue.db) as conn:
        conn.execute('UPDATE products SET baseline_json=?, baseline_hash=? WHERE id=?',
                     (b_str, b_hash, queue.row['id']))
    queue.row['baseline_hash'] = b_hash

    curr_dd = deepcopy(base_dd)
    curr_dd['required_attributes'] = {'observed': True, 'completion_percent': 100, 'missing': [],
                                      'fields': [{'name': '硬度', 'required': True, 'values': ['软毛']}]}
    curr_dd['protected'][0]['selections'] = ['ABS', '软毛']
    curr_miao_prot = deepcopy(miao_prot)
    intervention = {'action': 'fill_required_attr', 'detail': '硬度=软毛'}

    if case == 'empty_video_promo_valid':
        curr_dd['protected'][1]['static_fields'][0]['text'] = new_promo
    elif case == 'video_text_other_diff':
        curr_dd['protected'][1]['static_fields'][0]['text'] = '主图视频 已上传 video.mp4'
    elif case == 'wrong_section_same_text':
        base_dd_extra = deepcopy(base_dd)
        base_dd_extra['protected'][0]['static_fields'] = [{'field': '主图视频', 'text': old_promo}]
        saved_base['doudian_baseline'] = base_dd_extra
        b_str = json.dumps(saved_base, ensure_ascii=False, sort_keys=True)
        b_hash = hashlib.sha256(b_str.encode()).hexdigest()
        with sqlite3.connect(queue.db) as conn:
            conn.execute('UPDATE products SET baseline_json=?, baseline_hash=? WHERE id=?',
                         (b_str, b_hash, queue.row['id']))
        queue.row['baseline_hash'] = b_hash
        curr_dd['protected'][0]['static_fields'] = [{'field': '主图视频', 'text': new_promo}]
    elif case == 'extra_image_with_promo':
        curr_dd['protected'][1]['static_fields'][0]['text'] = new_promo
        curr_dd['protected'][1]['images'] = ['https://example.com/extra.jpg']
    elif case == 'start_sale_0_to_1_valid':
        curr_miao_prot['startSaleType'] = 1
        intervention['preserves_warehouse_shelf'] = True
    elif case == 'start_sale_missing_flag':
        curr_miao_prot['startSaleType'] = 1
    elif case == 'start_sale_1_to_0_reverse':
        curr_miao_prot['startSaleType'] = 0
        intervention['preserves_warehouse_shelf'] = True
    elif case == 'start_sale_0_to_2':
        curr_miao_prot['startSaleType'] = 2
        intervention['preserves_warehouse_shelf'] = True
    elif case == 'start_sale_status_0':
        curr_miao_prot['startSaleType'] = 1
        intervention['preserves_warehouse_shelf'] = True
    elif case == 'start_sale_missing_status':
        curr_miao_prot['startSaleType'] = 1
        del curr_miao_prot['status']
        intervention['preserves_warehouse_shelf'] = True
    elif case == 'start_sale_with_freight_diff':
        curr_miao_prot['startSaleType'] = 1
        curr_miao_prot['freightId'] = 2
        intervention['preserves_warehouse_shelf'] = True

    curr_miao = {'product_id': PID, 'shop': SHOP, 'protected_complete': True,
                 'title': '原商品标题', 'mains': mains, 'details': details,
                 'protected': curr_miao_prot}
    m_path = queue.tmp / 'miao_curr.json'
    d_path = queue.tmp / 'dd_curr.json'
    m_raw = json.dumps(curr_miao, ensure_ascii=False)
    d_raw = json.dumps(curr_dd, ensure_ascii=False)
    m_path.write_text(m_raw, encoding='utf-8')
    d_path.write_text(d_raw, encoding='utf-8')

    doc = proof(queue, miaoshou_task={'task_id': '36278985', 'finished': True, 'success_count': 0,
                                      'fail_count': 1, 'reasons': ['缺硬度'], 'product_id_confirmed': PID})
    doc['baseline_sha256'] = b_hash
    doc['expected_attribute_additions'] = [{'field': '硬度', 'values': ['软毛']}]
    doc['interventions'] = [intervention]
    doc['snapshots'] = {
        'miaoshou': {'path': m_path.name, 'sha256': hashlib.sha256(m_path.read_bytes()).hexdigest()},
        'doudian': {'path': d_path.name, 'sha256': hashlib.sha256(d_path.read_bytes()).hexdigest()},
    }

    if case in ('empty_video_promo_valid', 'start_sale_0_to_1_valid'):
        res = requeue_failed_submission(queue.row['id'], write(queue, doc), db_path=queue.db)
        assert res['submission_state'] == 'not_attempted'
        assert d_path.read_text(encoding='utf-8') == d_raw
        if case == 'start_sale_0_to_1_valid':
            assert res['attribute_backfill']['warehouse_shelf_preservation']['policy'] == 'preserve_warehouse_v1'
    else:
        with pytest.raises(DoudianError) as caught:
            requeue_failed_submission(queue.row['id'], write(queue, doc), db_path=queue.db)
        assert caught.value.code == 'requeue_failed_unproven'
