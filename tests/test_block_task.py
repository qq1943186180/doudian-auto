"""`batch block` — the reverse of a release, limited to rows that were never written.

`apply_preflight_report` can move a row from blocked to needs_agent. When that
release turns out to be wrong (task 22 was released on official-side evidence
and is missing from 妙手 entirely), there has to be a way back that is
auditable, rather than a hand-edited row.
"""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError


PID = '3850072900438720563'
SHOP = '样板店'


@pytest.fixture
def queue(tmp_path):
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [{'product_id': PID, 'shop': SHOP,
                                                'source_title': '原商品标题'}]},
                                 ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch.create_batch(source, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM products').fetchone())
    return SimpleNamespace(db=db, row=row)


def ready(queue, **changes):
    fields = {'state': 'needs_agent'}
    fields.update(changes)
    with sqlite3.connect(queue.db) as conn:
        assignments = ','.join('%s=?' % key for key in fields)
        conn.execute('UPDATE products SET %s WHERE id=?' % assignments,
                     (*fields.values(), queue.row['id']))
    return fields


def test_a_ready_row_can_be_withheld_with_a_stated_reason(queue):
    ready(queue)
    result = batch.block_task(queue.row['id'],
                              '妙手快速编辑列表中没有该商品，写入路径不可用', db_path=queue.db)
    assert result['state'] == 'blocked'
    assert result['last_error'].startswith('manual_block: ')
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT state,last_error FROM products WHERE id=?',
                           (queue.row['id'],)).fetchone()
        events = [tuple(event) for event in conn.execute(
            'SELECT from_state,to_state FROM product_events WHERE task_id=?', (queue.row['id'],))]
    assert (row['state'], row['last_error'].split(':')[0]) == ('blocked', 'manual_block')
    assert ('needs_agent', 'blocked') in events


def test_a_manual_block_is_not_reversable_by_the_automatic_recheck(queue):
    # The prefix is deliberate: a hand-made decision must not be undone by the next
    # automatic recheck, which only looks at preflight failures.
    ready(queue)
    result = batch.block_task(queue.row['id'], '妙手快速编辑列表中没有该商品，写入路径不可用',
                              db_path=queue.db)
    from doudian_auto import preflight
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM products WHERE id=?', (queue.row['id'],)).fetchone()
        assert preflight._skip_reason(conn, row, recheck_blocked=True) is not None
    assert result['last_error'].startswith('manual_block: ')


def test_a_row_with_a_save_attempt_cannot_be_withheld(queue):
    # Blocking here would erase the record of a write that may have landed.
    ready(queue, state='needs_agent', submission_state='unknown')
    with pytest.raises(DoudianError) as exc:
        batch.block_task(queue.row['id'], '妙手快速编辑列表中没有该商品，写入路径不可用',
                         db_path=queue.db)
    assert exc.value.code == 'block_not_allowed'


def test_a_row_that_already_has_a_baseline_cannot_be_withheld(queue):
    ready(queue)
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET baseline_hash='deadbeef' WHERE id=?", (queue.row['id'],))
    with pytest.raises(DoudianError) as exc:
        batch.block_task(queue.row['id'], '妙手快速编辑列表中没有该商品，写入路径不可用',
                         db_path=queue.db)
    assert exc.value.code == 'block_not_allowed'


def test_a_verified_row_cannot_be_withheld(queue):
    ready(queue, state='verified')
    with pytest.raises(DoudianError) as exc:
        batch.block_task(queue.row['id'], '妙手快速编辑列表中没有该商品，写入路径不可用',
                         db_path=queue.db)
    assert exc.value.code == 'block_not_allowed'


def test_the_reason_must_say_something(queue):
    ready(queue)
    with pytest.raises(DoudianError) as exc:
        batch.block_task(queue.row['id'], '   ', db_path=queue.db)
    assert exc.value.code == 'block_reason_required'


def test_a_refreshed_reason_mentions_a_missing_miaoshou_product(queue, tmp_path):
    # Official-side reasons alone read as fixable. When the product is absent from the
    # list every write goes through, the reason has to say so.
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET state='blocked',last_error=? WHERE id=?",
                     ('preflight_exception: required_attributes_missing; 缺安装方式。',
                      queue.row['id']))
    entry = {'task_id': queue.row['id'], 'product_id': PID, 'shop': SHOP,
             'target_version': queue.row['target_version'], 'read_only': True,
             'eligible': False, 'state': 'blocked', 'reason': 'writer_image_slots_incomplete',
             'message': '主图3张。',
             'evidence': {'snapshot_read': True, 'miaoshou_listed': False,
                          'observed_at': __import__('time').time(),
                          'snapshot_sha256': 'b' * 64}}
    proof = tmp_path / 'summary.json'
    proof.write_text(json.dumps({'products': [entry]}, ensure_ascii=False), encoding='utf-8')
    result = batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert result['outcome'] == 'reason_refreshed'
    assert '妙手快速编辑列表中没有该商品' in result['last_error']
