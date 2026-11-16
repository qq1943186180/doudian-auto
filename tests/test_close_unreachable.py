"""`closed_unreachable` — a human-signed end for one target version.

The state must not claim the product can never be written. It closes *this target
version* only, keeps the history, refuses every automatic recovery path, and
cannot be bypassed by re-importing the same shop/product into a new batch.
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError

PID = '3848315893817934633'
SHOP = '销霁百货'


@pytest.fixture
def row(tmp_path):
    src = tmp_path / 'products.json'
    src.write_text(json.dumps({'products': [
        {'product_id': PID, 'shop': SHOP, 'source_title': '漱口杯儿童PP带盖便携旅行牙具收纳杯'}]},
        ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch.create_batch(src, db_path=db)
    conn = batch._db(db)
    conn.execute("UPDATE products SET state='blocked',last_error=? WHERE id=?",
                 ('page_timeout: 妙手快速编辑列表中没有该商品', 1))
    conn.commit()
    record = dict(conn.execute('SELECT * FROM products').fetchone())
    conn.close()
    return SimpleNamespace(db=db, row=record)


def make_evidence(row, tmp_path, **overrides):
    data = {'shop': row.row['shop'], 'product_id': row.row['product_id'],
            'target_version': row.row['target_version'], 'observed_at': time.time(),
            'observed': '对照实验：确定在妙手的商品 True / 本商品 False / 对照 True / 本商品 False；写入路径不存在。'}
    data.update(overrides)
    path = tmp_path / 'evidence.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def close(row, tmp_path, evidence=None, **kwargs):
    args = {'reason': '妙手快速编辑列表中没有该商品，写入路径结构性不可达，按本目标版本结案',
            'evidence_path': evidence or make_evidence(row, tmp_path),
            'confirmed_by': 'workbuddy-human-confirm', 'db_path': row.db}
    args.update(kwargs)
    return batch.close_unreachable_task(row.row['id'], **args)


def state_of(row):
    return batch._db(row.db).execute('SELECT state FROM products WHERE id=?',
                                     (row.row['id'],)).fetchone()[0]


def test_reason_and_confirmation_are_required(row, tmp_path):
    with pytest.raises(DoudianError) as exc:
        close(row, tmp_path, reason='太短')
    assert exc.value.code == 'closure_reason_required'
    with pytest.raises(DoudianError) as exc:
        close(row, tmp_path, confirmed_by='   ')
    assert exc.value.code == 'closure_confirmation_required'


def test_evidence_must_bind_shop_product_and_version(row, tmp_path):
    for override in ({'product_id': '1234567890123456789'},
                     {'shop': '别的店'}, {'target_version': 'legacy-other'}):
        with pytest.raises(DoudianError) as exc:
            close(row, tmp_path, evidence=make_evidence(row, tmp_path, **override))
        assert exc.value.code == 'closure_binding_mismatch'


def test_stale_or_future_evidence_is_refused(row, tmp_path):
    for observed in (time.time() - 90000, time.time() + 600):
        with pytest.raises(DoudianError) as exc:
            close(row, tmp_path, evidence=make_evidence(row, tmp_path, observed_at=observed))
        assert exc.value.code == 'closure_evidence_stale'


def test_a_row_with_any_prior_write_cannot_be_closed(row, tmp_path):
    conn = batch._db(row.db)
    conn.execute("UPDATE products SET artifacts_path='some-artifacts.json' WHERE id=?", (row.row['id'],))
    conn.commit()
    conn.close()
    with pytest.raises(DoudianError) as exc:
        close(row, tmp_path)
    assert exc.value.code == 'closure_not_allowed'


def test_close_records_a_binding_event_and_keeps_history(row, tmp_path):
    result = close(row, tmp_path)
    assert result['state'] == 'closed_unreachable'
    assert state_of(row) == 'closed_unreachable'
    conn = batch._db(row.db)
    event = conn.execute("SELECT from_state,to_state,detail FROM product_events "
                         "WHERE task_id=? AND to_state='closed_unreachable'", (row.row['id'],)).fetchone()
    conn.close()
    assert (event['from_state'], event['to_state']) == ('blocked', 'closed_unreachable')
    detail = json.loads(event['detail'])
    assert detail['confirmed_by'] == 'workbuddy-human-confirm'
    assert detail['product_id'] == PID
    assert detail['target_version'] == row.row['target_version']
    assert len(detail['evidence_sha256']) == 64
    assert detail['reason']


def test_no_automatic_recovery_path_accepts_a_closed_row(row, tmp_path):
    close(row, tmp_path)
    # Every reopen path is gated on state == 'blocked' (or needs_agent), so a closed
    # row must be ignored rather than silently revived.
    with pytest.raises(DoudianError):
        batch.requeue_visual_task(row.row['id'], 'unused.json', db_path=row.db,
                                  miaoshou_probe=lambda *_: True)
    assert batch.recover_legacy_target_version_mismatch(
        row.row['id'], db_path=row.db, miaoshou_probe=lambda *_: True) is None
    with pytest.raises(DoudianError):
        batch.block_task(row.row['id'], '再收回一次但状态已经结案')
    assert state_of(row) == 'closed_unreachable'


def test_reimport_cannot_bypass_the_closure(row, tmp_path):
    close(row, tmp_path)
    src = tmp_path / 'reimport.json'
    src.write_text(json.dumps({'products': [
        {'product_id': PID, 'shop': SHOP, 'source_title': '换个标题重新导入'}]},
        ensure_ascii=False), encoding='utf-8')
    # create_batch does not raise on a conflicting shop/product: it imports the row
    # as blocked with the conflict recorded. That is the anti-bypass guard -- the
    # new row must never come back as needs_agent/ready.
    batch.create_batch(src, db_path=row.db)
    conn = batch._db(row.db)
    statuses = [dict(r) for r in conn.execute(
        'SELECT state,last_error FROM products WHERE shop=? AND product_id=?',
        (SHOP, PID))]
    conn.close()
    assert len(statuses) == 2
    assert any(r['state'] == 'closed_unreachable' for r in statuses)
    assert all(r['state'] == 'blocked' for r in statuses if r['state'] != 'closed_unreachable')
    assert state_of(row) == 'closed_unreachable'
