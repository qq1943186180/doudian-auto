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
