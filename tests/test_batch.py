import json

import pytest
from PIL import Image

from doudian_auto import batch
from doudian_auto.errors import DoudianError


def _product_set(tmp_path):
    product_id = '3850072900438720563'
    images = []
    for idx in range(9):
        size = (600, 600) if idx < 5 else (620, 900)
        path = tmp_path / f'asset-{idx}.png'
        Image.new('RGB', size, (idx * 20, 50, 100)).save(path)
        images.append(path)
    artifacts = tmp_path / 'artifacts.json'
    artifacts.write_text(json.dumps({'product_id': product_id,
        'title': '男士平角内裤纯棉中腰透气五色可选日常穿着',
        'mains': [str(p) for p in images[:5]],
        'details': [str(p) for p in images[5:]]}, ensure_ascii=False), encoding='utf-8')
    return product_id, artifacts


def _batch(tmp_path):
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [
        {'shop': '销霁百货', 'product_id': '3850072900438720563', 'source_title': '原商品标题'}
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    created = batch.create_batch(source, db_path=db)
    return db, created['batch_id']


def test_agent_claim_is_atomic_and_completion_requires_current_token(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db, lease_seconds=600)
    assert task['product_id'] == '3850072900438720563'
    assert batch.claim_next('agent-b', batch_id=batch_id, db_path=db) is None
    _, artifacts = _product_set(tmp_path)
    result = batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert result['state'] == 'ready'
    assert batch.batch_status(batch_id, db_path=db)['counts'] == {'ready': 1}


def test_stale_lease_cannot_submit_assets(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db, lease_seconds=60)
    conn = batch._db(db)
    conn.execute('UPDATE products SET lease_until=0 WHERE id=?', (task['id'],))
    conn.close()
    replacement = batch.claim_next('agent-b', batch_id=batch_id, db_path=db)
    _, artifacts = _product_set(tmp_path)
    with pytest.raises(DoudianError, match='领取已过期'):
        batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert replacement['lease_owner'] == 'agent-b'


def test_artifact_validator_rejects_duplicates_and_wrong_product(tmp_path):
    product_id, artifacts = _product_set(tmp_path)
    data = json.loads(artifacts.read_text(encoding='utf-8'))
    data['mains'][1] = data['mains'][0]
    artifacts.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(DoudianError, match='重复'):
        batch.validate_agent_artifacts(artifacts, product_id)
    with pytest.raises(DoudianError, match='商品ID'):
        batch.validate_agent_artifacts(artifacts, '3848316916011762046')


def test_unknown_submission_cannot_return_to_write_state(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db)
    _, artifacts = _product_set(tmp_path)
    batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    batch.set_execution_state(task['id'], 'editing', db_path=db)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.set_execution_state(task['id'], 'submitting', submission_state='unknown', db_path=db)
    with pytest.raises(DoudianError, match='只读核查'):
        batch.set_execution_state(task['id'], 'editing', db_path=db)
    with pytest.raises(DoudianError, match='不得由状态更新清除'):
        batch.set_execution_state(task['id'], 'blocked', submission_state='failed', db_path=db)


def test_ready_artifact_manifest_is_rehashed_before_use(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db)
    _, artifacts = _product_set(tmp_path)
    batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert batch.load_ready_artifacts(task['id'], db_path=db)['manifest']['product_id'] == task['product_id']
    artifacts.write_text(artifacts.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    with pytest.raises(DoudianError, match='发生变化'):
        batch.load_ready_artifacts(task['id'], db_path=db)


def test_one_product_in_two_batches_is_quarantined(tmp_path):
    db, _ = _batch(tmp_path)
    source = tmp_path / 'products-2.json'
    source.write_text(json.dumps({'products': [
        {'shop': '销霁百货', 'product_id': '3850072900438720563'}
    ]}, ensure_ascii=False), encoding='utf-8')
    created = batch.create_batch(source, db_path=db)
    assert created['blocked'] == 1
    assert batch.batch_status(created['batch_id'], db_path=db)['counts'] == {'blocked': 1}


def test_agent_preparation_parallelism_is_capped_at_three(tmp_path):
    source = tmp_path / 'four-products.json'
    source.write_text(json.dumps({'products': [
        {'shop': '测试店', 'product_id': f'385007290043872056{i}'} for i in range(1, 5)
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch_id = batch.create_batch(source, db_path=db)['batch_id']
    assert batch.claim_next('agent-1', batch_id=batch_id, db_path=db)
    assert batch.claim_next('agent-2', batch_id=batch_id, db_path=db)
    assert batch.claim_next('agent-3', batch_id=batch_id, db_path=db)
    assert batch.claim_next('agent-4', batch_id=batch_id, db_path=db) is None
