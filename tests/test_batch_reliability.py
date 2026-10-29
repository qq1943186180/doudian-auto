import json

import pytest
from PIL import Image

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.visual_review import file_hash
from test_batch import _batch, _product_set, offline_course_search


def _claim(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('reviewer', batch_id=batch_id, db_path=db)
    _, path = _product_set(tmp_path, task['target_version'])
    return db, task, path


def _complete(db, task, path):
    return batch.complete_agent_task(task['id'], 'reviewer', task['lease_token'], path, db_path=db)


def test_missing_visual_review_and_changed_reference_cannot_enter_ready(tmp_path):
    db, task, path = _claim(tmp_path)
    data = json.loads(path.read_text(encoding='utf-8'))
    missing = {key: value for key, value in data.items() if key != 'visual_review'}
    path.write_text(json.dumps(missing), encoding='utf-8')
    with pytest.raises(DoudianError, match='逐项目视检查'):
        _complete(db, task, path)
    path.write_text(json.dumps(data), encoding='utf-8')
    source = json.loads((tmp_path / f'source-{task["product_id"]}.json').read_text(encoding='utf-8'))
    Image.new('RGB', (600, 600), 'red').save(source['references'][0]['path'])
    with pytest.raises(DoudianError) as changed:
        _complete(db, task, path)
    assert changed.value.code == 'reference_image_changed'
    assert batch.batch_status(task['batch_id'], db_path=db)['counts'] == {'agent_claimed': 1}


def test_two_failed_versions_quarantine_only_this_product(tmp_path):
    db, task, path = _claim(tmp_path)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['visual_review']['items'][0]['checks']['printing'].update(status='fail', observed='waistband print missing')
    path.write_text(json.dumps(data), encoding='utf-8')
    first = _complete(db, task, path)
    assert first['state'] == 'agent_claimed'
    assert [slot['slot'] for slot in first['failed_slots']] == [1]
    # Unchanged 8 successful slots are reusable; only the rejected slot is regenerated.
    Image.new('RGB', (600, 600), (255, 0, 0)).save(data['mains'][0])
    data['visual_review']['items'][0]['asset_sha256'] = file_hash(data['mains'][0])
    path.write_text(json.dumps(data), encoding='utf-8')
    second = _complete(db, task, path)
    assert second['state'] == 'blocked'
    assert second['reason'] == 'visual_quality_failed_after_retry'
    conn = batch._db(db)
    assert conn.execute('SELECT count(*) FROM asset_reviews').fetchone()[0] == 10
    assert conn.execute('SELECT submission_attempts FROM products').fetchone()[0] == 0
    conn.close()


def test_failed_unchanged_image_cannot_be_relabelled_pass(tmp_path):
    db, task, path = _claim(tmp_path)
    data = json.loads(path.read_text(encoding='utf-8'))
    check = data['visual_review']['items'][0]['checks']['identity']
    check['status'] = 'fail'
    path.write_text(json.dumps(data), encoding='utf-8')
    _complete(db, task, path)
    check['status'] = 'pass'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(DoudianError) as conflict:
        _complete(db, task, path)
    assert conflict.value.code == 'visual_review_conflict'


def test_saved_external_work_is_quarantined_idempotently_and_unknown_is_preserved(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.batch_status(batch_id, db_path=db)['products'][0]
    conn = batch._db(db)
    conn.execute("UPDATE products SET state='submitted',submission_state='unknown',submission_attempts=1 WHERE id=?", (task['id'],))
    conn.close()
    path = tmp_path / 'observation.json'
    path.write_text(json.dumps({'product_id': task['product_id'], 'shop': '销霁百货', 'stage': 'saved_listed'}), encoding='utf-8')
    result = batch.reconcile_observation(path, db_path=db)
    assert result['quarantined_task_ids'] == [task['id']]
    assert result['full_revision_verified'] is False
    assert batch.reconcile_observation(path, db_path=db)['quarantined_task_ids'] == []
    current = batch.batch_status(batch_id, db_path=db)['products'][0]
    assert current['state'] == 'blocked'
    assert current['submission_state'] == 'unknown'
    assert current['submission_attempts'] == 1
    assert batch.claim_next('other', batch_id=batch_id, db_path=db) is None


@pytest.mark.parametrize('stage', ['verified', 'saved', 'blocked_link_import_unknown'])
def test_imported_old_work_cannot_be_claimed_as_new(tmp_path, stage):
    path = tmp_path / 'products.json'
    path.write_text(json.dumps([{'shop': '销霁百货', 'product_id': '3850072653520044313', 'stage': stage}]), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    result = batch.create_batch(path, db_path=db)
    assert result['blocked'] == 1
    assert batch.claim_next('agent', batch_id=result['batch_id'], db_path=db) is None
