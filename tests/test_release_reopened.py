"""Explicit `batch release-reopened` release path for `manual_block: reopened_closure:`."""

import json
import os
import sqlite3
import time
from types import SimpleNamespace

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError

PID = '3848315893817934633'
SHOP = '销霁百货'


@pytest.fixture
def reopened_queue(tmp_path):
    src = tmp_path / 'products.json'
    src.write_text(json.dumps({'products': [{'product_id': PID, 'shop': SHOP, 'source_title': '测试商品'}]},
                              ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch.create_batch(src, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM products').fetchone())
        now = time.time() - 120
        conn.execute("UPDATE products SET state='blocked', last_error=?, updated_at=? WHERE id=?",
                     (batch.REOPENED_CLOSURE_PREFIX + '误关重开', now, row['id']))
        conn.execute('INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail) VALUES(?,?,?,?,?)',
                     (row['id'], 'closed_unreachable', 'blocked', now,
                      json.dumps({'event_kind': 'reopen_unreachable', 'confirmed_by': 'reviewer'})))
    return SimpleNamespace(db=db, row=row)


def _proof(queue, path, *, eligible=True, miaoshou_listed=True, observed_at=None, target_version=None):
    entry = {
        'task_id': queue.row['id'],
        'product_id': PID,
        'shop': SHOP,
        'target_version': target_version or queue.row['target_version'],
        'read_only': True,
        'eligible': eligible,
        'state': 'eligible' if eligible else 'blocked',
        'evidence': {
            'miaoshou_listed': miaoshou_listed,
            'snapshot_read': True,
            'observed_at': time.time() if observed_at is None else observed_at,
            'snapshot_sha256': 'a' * 64,
        },
    }
    path.write_text(json.dumps({'products': [entry]}, ensure_ascii=False), encoding='utf-8')
    return path


def test_release_reopened_succeeds_and_is_idempotent(reopened_queue, tmp_path):
    proof = _proof(reopened_queue, tmp_path / 'summary.json')
    first = batch.release_reopened_closure(reopened_queue.row['id'], proof, db_path=reopened_queue.db)
    assert first['state'] == 'needs_agent'
    assert first['outcome'] == 'released'
    replay = batch.release_reopened_closure(reopened_queue.row['id'], proof, db_path=reopened_queue.db)
    assert replay['state'] == 'needs_agent'
    assert replay['outcome'] == 'already_released'


def test_auto_recheck_still_refuses_reopened_closure(reopened_queue, tmp_path):
    proof = _proof(reopened_queue, tmp_path / 'summary.json')
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(reopened_queue.row['id'], proof, db_path=reopened_queue.db)
    assert exc.value.code == 'reopen_unproven'


def test_release_reopened_rejects_old_proof_or_subsequent_block(reopened_queue, tmp_path):
    stale_proof = _proof(reopened_queue, tmp_path / 'old.json', observed_at=time.time() - 200)
    with pytest.raises(DoudianError):
        batch.release_reopened_closure(reopened_queue.row['id'], stale_proof, db_path=reopened_queue.db)

    with sqlite3.connect(reopened_queue.db) as conn:
        conn.execute('INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail) VALUES(?,?,?,?,?)',
                     (reopened_queue.row['id'], 'needs_agent', 'blocked', time.time() - 30, 'new block'))
    fresh = _proof(reopened_queue, tmp_path / 'fresh.json')
    with pytest.raises(DoudianError):
        batch.release_reopened_closure(reopened_queue.row['id'], fresh, db_path=reopened_queue.db)


def test_preflight_recheck_observes_reopened_closure_with_session(reopened_queue, tmp_path, monkeypatch):
    from doudian_auto import preflight as preflight_mod
    seen_sessions = []

    class DummyBridge:
        def __init__(self, endpoint='ego', session='doudian-auto', timeout=25):
            self.endpoint = endpoint
            self.session = session

    class DummyOfficial:
        def __init__(self, bridge):
            self.bridge = bridge

        def open(self, product_id):
            pass

        def wait_ready(self):
            pass

        def inspect(self):
            import hashlib
            from doudian_auto.official_skus import _normalize
            raw_rows = [{'sku_id': '1001', 'id': '1001', 'price': '39.88',
                         'stock_info': {'stock_num': 100}, 'step_stock_info': {'stock_num': 0},
                         'spec_detail_ids': ['2001'], 'sku_status': True, 'code': 'C1'}]
            specs = [{'name': '颜色', 'spec_values': [{'id': '2001', 'name': 'S1'}]}]
            rows = [{'sku_id': '1001', 'spec_ids': ['2001'], 'price': '39.88',
                     'stock': 100, 'step_stock': 0, 'enabled': True, 'code': 'C1'}]
            payload = {'rows': rows, 'raw_rows': _normalize(raw_rows), 'specs': _normalize(specs)}
            sku_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            return {
                'product_id': PID, 'shop': SHOP, 'shop_confirmed': True,
                'draft_loaded': False, 'rejected': False, 'detail_status': 'ready',
                'title': '测试商品',
                'mains': ['https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_' + '1' * 32 + '_sx_1_www800-800'],
                'details': ['https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_' + '2' * 32 + '_sx_1_www800-800'],
                'protected': [
                    {'section': 'goodsEditScrollContainer-基础信息', 'observation': 'ready',
                     'inputs': [], 'selections': [], 'static_fields': [], 'images': []},
                    {'section': 'goodsEditScrollContainer-价格库存', 'observation': 'ready',
                     'inputs': [], 'selections': ['现货'], 'static_fields': [], 'images': []},
                    {'section': 'goodsEditScrollContainer-服务与履约', 'observation': 'ready',
                     'inputs': [], 'selections': ['7天无理由'], 'static_fields': [], 'images': []},
                ],
                'required_attributes': {'observed': True, 'complete': True, 'missing': [], 'completion_percent': 100,
                                        'fields': [{'name': '材质', 'required': True, 'values': ['ABS']}]},
                'sku_evidence': {'complete': True, 'product_id': PID, 'shop_id': '999', 'count': 1, **payload, 'sha256': sku_sha},
            }

    class DummyMiaoshou:
        def __init__(self, bridge, shop, *, session='doudian-auto'):
            seen_sessions.append(session)
            self.bridge = bridge
            self.shop = shop
            self.session = session

        def row_present(self, product_id):
            return True

    monkeypatch.setattr(preflight_mod, 'Bridge', DummyBridge)
    monkeypatch.setattr(preflight_mod, '_existing_ego_space', lambda bridge, expected=None: None)
    monkeypatch.setattr(preflight_mod, 'Editor', DummyOfficial)
    monkeypatch.setattr('doudian_auto.miaoshou_editor.MiaoshouEditor', DummyMiaoshou)
    monkeypatch.setattr(preflight_mod, '_stable_snapshot_with_sku_retry', lambda ed, ident: (ed.inspect(), True))

    out_dir = tmp_path / 'pf'
    summary = preflight_mod.preflight_products(
        'ego', product_ids=[PID], db_path=reopened_queue.db, report_dir=out_dir,
        recheck_blocked=True, check_miaoshou=True, session='unblock-p3')
    assert summary['products'][0]['eligible'] is True, json.dumps(summary['products'][0], ensure_ascii=False)
    assert summary['products'][0]['evidence']['miaoshou_listed'] is True
    assert seen_sessions == ['unblock-p3']
