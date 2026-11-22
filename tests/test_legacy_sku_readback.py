"""Audited read-only closeout for historical virtual-SKU-grid `readback_mismatch`."""

import hashlib
import json
import sqlite3
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.legacy_readback import verify_legacy_sku_grid_readback
from doudian_auto.official_skus import _normalize

PID = '3850071893537325881'
SHOP = '销霁百货'
TITLE = '2026新款男童春秋直筒休闲裤中大童洋气时尚童装潮款童装裤子'
M_URLS = [
    f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www1024-1024'
    for i in range(1, 6)
]
D_URLS = [
    f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www1024-1536'
    for i in range(10, 14)
]
TAIL_URL = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_00000000000000000000000000000099_sx_100_www800-800'


def _sku_ev(product_id=PID):
    raw_rows = [
        {'sku_id': f'100{i}', 'id': f'100{i}', 'price': f'{38 + i}.88',
         'stock_info': {'stock_num': 500 - i}, 'step_stock_info': {'stock_num': 0},
         'spec_detail_ids': [f'200{i}'], 'sku_status': True, 'code': f'CODE-{i}'}
        for i in range(1, 4)
    ]
    specs = [{'name': '颜色', 'spec_values': [{'id': f'200{i}', 'name': f'S{i}'} for i in range(1, 4)]}]
    rows = sorted([{
        'sku_id': r['sku_id'], 'spec_ids': r['spec_detail_ids'], 'price': r['price'],
        'stock': r['stock_info']['stock_num'], 'step_stock': 0,
        'enabled': True, 'code': r['code'],
    } for r in raw_rows], key=lambda x: x['sku_id'])
    payload = {'rows': rows, 'raw_rows': _normalize(raw_rows), 'specs': _normalize(specs)}
    sha = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {'complete': True, 'product_id': product_id, 'shop_id': '999', 'count': 3,
            **payload, 'sha256': sha}


def _sku_row_inputs(code, price):
    return [
        {'type': 'text', 'name': '', 'value': price, 'checked': None, 'disabled': False},
        {'type': 'radio', 'name': '', 'value': '1', 'checked': True, 'disabled': False},
        {'type': 'radio', 'name': '', 'value': '-1', 'checked': False, 'disabled': False},
        {'type': 'number', 'name': '', 'value': '', 'checked': None, 'disabled': False},
        {'type': 'text', 'name': '', 'value': code, 'checked': None, 'disabled': False},
        {'type': 'text', 'name': '', 'value': '', 'checked': None, 'disabled': False},
    ]


@pytest.fixture
def legacy_row(tmp_path):
    src = tmp_path / 'products.json'
    src.write_text(json.dumps({'products': [{'product_id': PID, 'shop': SHOP, 'source_title': '旧标题'}]},
                              ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch.create_batch(src, db_path=db)

    art = tmp_path / 'artifacts.json'
    art.write_text(json.dumps({'product_id': PID, 'title': TITLE}, ensure_ascii=False), encoding='utf-8')
    art_hash = hashlib.sha256(art.read_bytes()).hexdigest()

    sku_ev = _sku_ev()
    non_grid_head = [{'type': 'radio', 'name': '', 'value': '0', 'checked': True, 'disabled': False}]
    non_grid_tail = [{'type': 'text', 'name': '', 'value': '39.88~41.88', 'checked': None, 'disabled': True}]
    legacy_grid = _sku_row_inputs('CODE-1', '39.88') + _sku_row_inputs('CODE-2', '40.88')
    non_grid_inputs = non_grid_head + non_grid_tail

    def _base_sec(inputs_list, include_grid_free=False):
        price_blk = {'section': 'goodsEditScrollContainer-价格库存', 'observation': 'ready',
                     'inputs': inputs_list, 'selections': ['现货'], 'static_fields': [], 'images': []}
        if include_grid_free:
            price_blk['inputs_without_sku_grid'] = non_grid_inputs
        return [
            {'section': 'goodsEditScrollContainer-基础信息', 'observation': 'ready',
             'inputs': [{'type': 'text', 'name': '', 'value': 'v', 'checked': None, 'disabled': False}],
             'selections': [], 'static_fields': [], 'images': []},
            {'section': 'goodsEditScrollContainer-价格库存', **price_blk},
            {'section': 'goodsEditScrollContainer-服务与履约', 'observation': 'ready',
             'inputs': [], 'selections': ['7天无理由'], 'static_fields': [], 'images': []},
        ]

    miao_prot = {
        'root.categoryId': 1000003304, 'root.brandName': '无品牌', 'specPrices': [
            {'skuId': int(f'100{i}'), 'specDetailIds': [int(f'200{i}')], 'price': f'{38+i}.88',
             'stockNum': 500-i, 'stepStockNum': 0, 'code': f'CODE-{i}', 'skuStatus': True}
            for i in range(1, 4)
        ], 'freightId': 1, 'status': 1, 'draftStatus': 0, 'specPics': [],
        'mainImageThreeToFour': '', 'whiteBackGroundPicUrl': '', 'afterSaleService': {},
        'checkStatus': 1, 'startSaleType': 0,
    }
    dd_before = {
        'product_id': PID, 'shop_confirmed': True, 'shop': SHOP, 'draft_loaded': False, 'rejected': False,
        'title': '旧标题', 'mains': M_URLS, 'details': D_URLS + [TAIL_URL],
        'protected': _base_sec(non_grid_head + legacy_grid + non_grid_tail, include_grid_free=False),
        'sku_evidence': sku_ev,
    }
    baseline = {
        'product_id': PID, 'shop': SHOP, 'title': '旧标题', 'mains': M_URLS, 'details': D_URLS + [TAIL_URL],
        'protected': miao_prot, 'doudian_baseline': dd_before,
    }
    b_str = json.dumps(baseline, ensure_ascii=False, sort_keys=True)
    b_hash = hashlib.sha256(b_str.encode()).hexdigest()

    mappings = [
        *[{'slot': f'mains:{i}', 'source_sha256': f'{i:064x}', 'remote_key': u.split('ecom-shop-material/')[1],
           'remote_url': u, 'asset_state': 'permanent', 'confirmed': True} for i, u in enumerate(M_URLS, 1)],
        *[{'slot': f'details:{i}', 'source_sha256': f'{10+i:064x}', 'remote_key': u.split('ecom-shop-material/')[1],
           'remote_url': u, 'asset_state': 'permanent', 'confirmed': True} for i, u in enumerate(D_URLS, 1)],
    ]
    upload_map = [{**m, 'asset_state': 'staged' if m['slot'].startswith('details:') else 'permanent',
                   'remote_key': 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/x?a=1' if m['slot'].startswith('details:') else m['remote_key'],
                   'remote_url': 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/x?a=1' if m['slot'].startswith('details:') else m['remote_url']}
                  for m in mappings]

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM products').fetchone())
        conn.execute(
            '''UPDATE products SET state='blocked', submission_state='unknown', submission_attempts=1,
                    last_error='readback_mismatch', artifacts_path=?, artifacts_hash=?,
                    baseline_json=?, baseline_hash=?, upload_map_json=?, updated_at=? WHERE id=?''',
            (str(art), art_hash, b_str, b_hash, json.dumps(upload_map), time.time() - 60, row['id']),
        )
        row = dict(conn.execute('SELECT * FROM products WHERE id=?', (row['id'],)).fetchone())

    # Fresh snapshots after save (window now shows 3 SKU rows instead of 2)
    live_grid = legacy_grid + _sku_row_inputs('CODE-3', '41.88')
    dd_after = {
        'product_id': PID, 'shop_confirmed': True, 'shop': SHOP, 'draft_loaded': False, 'rejected': False,
        'title': TITLE, 'mains': M_URLS, 'details': D_URLS + [TAIL_URL],
        'protected': _base_sec(non_grid_head + live_grid + non_grid_tail, include_grid_free=True),
        'sku_evidence': sku_ev,
    }
    miao_after = {
        'product_id': PID, 'shop': SHOP, 'protected_complete': True,
        'title': TITLE, 'mains': M_URLS, 'details': D_URLS + [TAIL_URL],
        'protected': {**miao_prot, 'startSaleType': 1, 'checkStatus': 7},
    }
    return SimpleNamespace(db=db, row=row, tmp=tmp_path, miao_after=miao_after,
                           dd_after=dd_after, mappings=mappings, art_hash=art_hash, b_hash=b_hash)


def _write_proof(ctx, *, dd_mod=None):
    m_p = ctx.tmp / 'miao.json'
    d_p = ctx.tmp / 'dd.json'
    m_p.write_text(json.dumps(ctx.miao_after, ensure_ascii=False), encoding='utf-8')
    d_p.write_text(json.dumps(dd_mod or ctx.dd_after, ensure_ascii=False), encoding='utf-8')
    proof = {
        'read_only': True, 'reviewer': 'codex-audit', 'task_id': ctx.row['id'],
        'product_id': PID, 'shop': SHOP, 'target_version': ctx.row['target_version'],
        'baseline_sha256': ctx.b_hash, 'manifest_sha256': ctx.art_hash, 'observed_at': time.time(),
        'miaoshou': {'path': 'miao.json', 'sha256': hashlib.sha256(m_p.read_bytes()).hexdigest()},
        'doudian': {'path': 'dd.json', 'sha256': hashlib.sha256(d_p.read_bytes()).hexdigest()},
        'final_asset_mappings': ctx.mappings,
    }
    p_p = ctx.tmp / 'proof.json'
    p_p.write_text(json.dumps(proof, ensure_ascii=False), encoding='utf-8')
    return p_p


def test_legacy_sku_grid_readback_verifies_exact_diff(legacy_row):
    proof = _write_proof(legacy_row)
    res = verify_legacy_sku_grid_readback(legacy_row.row['id'], proof, db_path=legacy_row.db)
    assert res['state'] == 'verified'
    assert res['submission_state'] == 'verified_by_readback'
    assert res['sku_grid_diff']['stripped_virtual_sku_rows'] == 2
    assert res['sku_grid_diff']['bound_sku_codes'] == ['CODE-1', 'CODE-2']
    with sqlite3.connect(legacy_row.db) as conn:
        row = conn.execute('SELECT state,submission_state,submission_attempts,last_error FROM products WHERE id=?',
                           (legacy_row.row['id'],)).fetchone()
    assert tuple(row) == ('verified', 'verified_by_readback', 1, None)


def test_legacy_readback_refuses_non_grid_commercial_change(legacy_row):
    dd_bad = deepcopy(legacy_row.dd_after)
    dd_bad['protected'][2]['selections'] = ['不支持7天']
    proof = _write_proof(legacy_row, dd_mod=dd_bad)
    with pytest.raises(DoudianError) as exc:
        verify_legacy_sku_grid_readback(legacy_row.row['id'], proof, db_path=legacy_row.db)
    assert exc.value.code == 'commercial_changed'


def test_legacy_readback_refuses_unknown_grid_input_diff(legacy_row):
    dd_bad = deepcopy(legacy_row.dd_after)
    dd_bad['protected'][1]['inputs_without_sku_grid'][0]['value'] = '999'
    proof = _write_proof(legacy_row, dd_mod=dd_bad)
    with pytest.raises(DoudianError) as exc:
        verify_legacy_sku_grid_readback(legacy_row.row['id'], proof, db_path=legacy_row.db)
    assert exc.value.code == 'legacy_readback_unproven'


@pytest.mark.parametrize('tamper_extra', [False, True])
def test_legacy_readback_handles_nested_size_spec_grid_diff(legacy_row, tamper_extra):
    dd_mod = deepcopy(legacy_row.dd_after)
    size_cells = [{'type': 'text', 'name': '', 'value': f'{s}码', 'checked': None, 'disabled': False}
                  for s in (100, 110, 120)]
    old_inputs = [{'type': 'radio', 'name': '', 'value': '0', 'checked': True, 'disabled': False}]
    tail_inputs = [{'type': 'text', 'name': '', 'value': '39.88~41.88', 'checked': None, 'disabled': True}]
    new_base_inputs = old_inputs + _sku_row_inputs('CODE-1', '39.88') + size_cells + _sku_row_inputs('CODE-2', '40.88') + tail_inputs
    base = json.loads(legacy_row.row['baseline_json'])
    base['doudian_baseline']['protected'][1]['inputs'] = new_base_inputs
    b_str = json.dumps(base, ensure_ascii=False, sort_keys=True)
    b_hash = hashlib.sha256(b_str.encode()).hexdigest()
    with sqlite3.connect(legacy_row.db) as conn:
        conn.execute('UPDATE products SET baseline_json=?, baseline_hash=? WHERE id=?',
                     (b_str, b_hash, legacy_row.row['id']))
    legacy_row.b_hash = b_hash
    # Right side inputs_without_sku_grid retains size_cells (not wrapped in tr[data-row-key])
    right_non_grid = old_inputs + size_cells + tail_inputs
    live_inputs = old_inputs + _sku_row_inputs('CODE-1', '39.88') + size_cells + _sku_row_inputs('CODE-2', '40.88')
    if tamper_extra:
        live_inputs.insert(-6, {'type': 'text', 'name': '', 'value': 'EXTRA_TAMPER', 'checked': None, 'disabled': False})
    dd_mod['protected'][1]['inputs'] = live_inputs + _sku_row_inputs('CODE-3', '41.88') + tail_inputs
    dd_mod['protected'][1]['inputs_without_sku_grid'] = right_non_grid
    proof = _write_proof(legacy_row, dd_mod=dd_mod)
    if tamper_extra:
        with pytest.raises(DoudianError) as exc:
            verify_legacy_sku_grid_readback(legacy_row.row['id'], proof, db_path=legacy_row.db)
        assert exc.value.code == 'legacy_readback_unproven'
    else:
        res = verify_legacy_sku_grid_readback(legacy_row.row['id'], proof, db_path=legacy_row.db)
        assert res['state'] == 'verified'
        assert res['sku_grid_diff']['stripped_live_virtual_sku_rows'] == 1
        assert res['sku_grid_diff']['live_bound_sku_codes'] == ['CODE-3']
