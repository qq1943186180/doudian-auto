"""Releasing a row that never got past its read-only checks.

A preflight failure is a read that failed once, so the only honest way to release the row
is to read again and find it passes. These tests pin the two halves of that: the flag that
allows the re-read (it widens which rows may be read, nothing more) and `reopen_blocked`
(which consumes a fresh report and refuses everything else).
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from doudian_auto import batch, preflight
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
    created = batch.create_batch(source, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM products').fetchone())
    return SimpleNamespace(db=db, row=row, batch_id=created['batch_id'])


def block(queue, error='preflight_exception: official_sku_code_incomplete; 仅确认7/44个SKU。'):
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET state='blocked', last_error=? WHERE id=?",
                     (error, queue.row['id']))
        conn.row_factory = sqlite3.Row
        return dict(conn.execute('SELECT * FROM products WHERE id=?', (queue.row['id'],)).fetchone())


def report(queue, path, *, eligible=True, observed_at=None, product_id=None,
           target_version=None, digest=None, reason=None, message=None,
           miaoshou_listed=True):
    entry = {'task_id': queue.row['id'], 'product_id': product_id or PID, 'shop': SHOP,
             'target_version': target_version or queue.row['target_version'],
             'read_only': True, 'eligible': eligible,
             'state': 'eligible' if eligible else 'blocked'}
    if reason is not None:
        entry['reason'] = reason
        entry['message'] = message or ''
    entry['evidence'] = {'miaoshou_listed': miaoshou_listed, 'snapshot_read': True,
                         'observed_at': time.time() if observed_at is None else observed_at,
                         'snapshot_sha256': digest or ('a' * 64)}
    path.write_text(json.dumps({'products': [entry]}, ensure_ascii=False), encoding='utf-8')
    return path


def test_a_preflight_blocked_row_reopens_on_a_fresh_eligible_report(queue, tmp_path):
    block(queue)
    proof = report(queue, tmp_path / 'summary.json')
    result = batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert result['state'] == 'needs_agent'
    assert result['outcome'] == 'reopened'
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT state,last_error FROM products WHERE id=?',
                           (queue.row['id'],)).fetchone()
        events = conn.execute('SELECT from_state,to_state FROM product_events WHERE task_id=?',
                              (queue.row['id'],)).fetchall()
    assert (row['state'], row['last_error']) == ('needs_agent', None)
    assert ('blocked', 'needs_agent') in [tuple(event) for event in events]


def test_a_failing_report_refreshes_the_reason_instead_of_reopening(queue, tmp_path):
    # A row that fails again for a different reason must stop advertising the old one:
    # twelve-day-old reasons sent this project hunting a defect that was already fixed.
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', eligible=False,
                   reason='writer_image_slots_incomplete', message='详情仅2张，需至少4张。')
    result = batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert result['outcome'] == 'reason_refreshed'
    assert result['state'] == 'blocked'
    assert result['last_error'].startswith('preflight_exception: writer_image_slots_incomplete;')
    stored = _last_error(queue)
    assert stored.startswith('preflight_exception: writer_image_slots_incomplete;')
    assert _state(queue) == 'blocked'


def test_a_refreshed_reason_can_be_rechecked_again(queue, tmp_path):
    # The prefix is preserved precisely so the row stays eligible for another read.
    block(queue)
    first = report(queue, tmp_path / 'one.json', eligible=False,
                   reason='writer_image_slots_incomplete', message='详情仅2张。')
    batch.apply_preflight_report(queue.row['id'], first, db_path=queue.db)
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM products WHERE id=?', (queue.row['id'],)).fetchone()
        widened = preflight._skip_reason(conn, row, recheck_blocked=True)
    assert widened is None


def test_a_failing_report_without_a_reason_is_refused(queue, tmp_path):
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', eligible=False, reason='')
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'reopen_unproven'
    assert _state(queue) == 'blocked'


def test_a_stale_report_is_refused(queue, tmp_path):
    block(queue)
    proof = report(queue, tmp_path / 'summary.json')
    old = time.time() - 3600
    os.utime(proof, (old, old))          # freshness is judged from the report file itself
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'reopen_unproven'
    assert _state(queue) == 'blocked'


def test_a_report_for_another_version_is_refused(queue, tmp_path):
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', target_version='legacy-somethingelse')
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'reopen_unproven'
    assert _state(queue) == 'blocked'


def test_a_row_blocked_for_a_write_is_never_reopened(queue, tmp_path):
    # The distinguishing fact is the reason: only a failed preflight means nothing was
    # written. A readback mismatch could describe a save that did land.
    block(queue, error='readback_mismatch')
    proof = report(queue, tmp_path / 'summary.json')
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'reopen_unproven'
    assert _state(queue) == 'blocked'


def test_a_row_that_already_has_a_baseline_is_refused(queue, tmp_path):
    block(queue)
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET baseline_hash='deadbeef' WHERE id=?", (queue.row['id'],))
    proof = report(queue, tmp_path / 'summary.json')
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'reopen_unproven'
    assert _state(queue) == 'blocked'


def test_the_flag_widens_which_rows_may_be_read_and_nothing_else(queue):
    blocked = block(queue)
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM products WHERE id=?', (blocked['id'],)).fetchone()
        strict = preflight._skip_reason(conn, row)
        widened = preflight._skip_reason(conn, row, recheck_blocked=True)
    assert strict == ('queue_state_ineligible', '队列状态为 blocked，不作为新素材候选。')
    assert widened is None


def test_the_flag_does_not_widen_a_row_blocked_for_something_else(queue):
    blocked = block(queue, error='doudian_product_deleted: 商品不存在')
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM products WHERE id=?', (blocked['id'],)).fetchone()
        widened = preflight._skip_reason(conn, row, recheck_blocked=True)
    assert widened == ('queue_state_ineligible', '队列状态为 blocked，不作为新素材候选。')


def _state(queue):
    with sqlite3.connect(queue.db) as conn:
        return conn.execute('SELECT state FROM products WHERE id=?', (queue.row['id'],)).fetchone()[0]


def _last_error(queue):
    with sqlite3.connect(queue.db) as conn:
        return conn.execute('SELECT last_error FROM products WHERE id=?',
                            (queue.row['id'],)).fetchone()[0]


def test_a_skipped_row_is_refused_rather_than_reasoned(queue, tmp_path):
    # `skipped` means another guard refused the row and nothing was read. Writing that in
    # as a preflight failure would replace a true reason with a false one.
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', eligible=False, reason='already_verified')
    with sqlite3.connect(queue.db) as conn:
        pass
    entry = json.loads(proof.read_text(encoding='utf-8'))
    entry['products'][0]['state'] = 'skipped'
    proof.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'reopen_unproven'
    assert _last_error(queue).startswith('preflight_exception: official_sku_code_incomplete;')


def test_a_skipped_row_is_refused_rather_than_reasoned(queue, tmp_path):
    # `skipped` means another guard refused the row and nothing was read. Writing that in
    # as a preflight failure would replace a true reason with a false one.
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', eligible=False, reason='already_verified')
    with sqlite3.connect(queue.db) as conn:
        pass
    entry = json.loads(proof.read_text(encoding='utf-8'))
    entry['products'][0]['state'] = 'skipped'
    proof.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'reopen_unproven'
    assert _last_error(queue).startswith('preflight_exception: official_sku_code_incomplete;')


def test_a_failed_read_leaves_the_reason_alone(queue, tmp_path):
    # A read that never produced a snapshot learned nothing about the listing. Recording
    # "the page was not ready" as the reason would bury the real one behind a transient.
    block(queue)
    before = _last_error(queue)
    proof = report(queue, tmp_path / 'summary.json', eligible=False,
                   reason='editor_not_ready', message='商品编辑页尚未加载。')
    entry = json.loads(proof.read_text(encoding='utf-8'))
    entry['products'][0]['evidence'] = {'read_only': True, 'snapshot_read': False}
    proof.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
    result = batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert result['outcome'] == 'read_failed'
    assert result['attempt'] == 'editor_not_ready'
    assert _last_error(queue) == before
    assert _state(queue) == 'blocked'


def test_a_report_without_miaoshou_proof_cannot_reopen(queue, tmp_path):
    # Writes go through 妙手, so an official-side pass is not enough to release a row.
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', miaoshou_listed=None)
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'miaoshou_listing_unproven'
    assert _state(queue) == 'blocked'


def test_miaoshou_absence_also_blocks_reopening(queue, tmp_path):
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', miaoshou_listed=False)
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'miaoshou_listing_unproven'
    assert _state(queue) == 'blocked'


def test_a_report_without_miaoshou_proof_cannot_reopen(queue, tmp_path):
    # Writes go through 妙手, so an official-side pass is not enough to release a row.
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', miaoshou_listed=None)
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'miaoshou_listing_unproven'
    assert _state(queue) == 'blocked'


def test_miaoshou_absence_also_blocks_reopening(queue, tmp_path):
    block(queue)
    proof = report(queue, tmp_path / 'summary.json', miaoshou_listed=False)
    with pytest.raises(DoudianError) as exc:
        batch.apply_preflight_report(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'miaoshou_listing_unproven'
    assert _state(queue) == 'blocked'
