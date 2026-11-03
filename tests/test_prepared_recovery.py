import hashlib
import json
import os
import sqlite3
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.prepared_recovery import recover_prepared_after_reads
from test_batch import _product_set
from test_preflight import _snapshot


PID = '3850072900438720563'
SHOP = '销霁百货'
ERROR = 'official_repeat_snapshot_unstable:slot_order_changed'


@pytest.fixture(scope='module')
def prepared_template(tmp_path_factory):
    root = tmp_path_factory.mktemp('prepared-template')
    source = root / 'products.json'
    source.write_text(json.dumps({'products': [
        {'shop': SHOP, 'product_id': PID, 'source_title': '袜子原商品'}]}, ensure_ascii=False),
        encoding='utf-8')
    db = root / 'queue.sqlite3'
    batch_id = batch.create_batch(source, db_path=db)['batch_id']
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        product = dict(conn.execute('SELECT * FROM products WHERE batch_id=?', (batch_id,)).fetchone())
    _, artifact = _product_set(root, product['target_version'], product_id=PID)
    data = json.loads(artifact.read_text(encoding='utf-8'))
    now = time.time()
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE products SET state='blocked',last_error=?,artifacts_path=?,artifacts_hash=? WHERE id=?",
                     (ERROR, str(artifact.resolve()), batch._digest(artifact), product['id']))
        for item in data['visual_review']['items']:
            conn.execute('INSERT INTO asset_reviews(task_id,kind,slot,asset_sha256,attempt,decision,review_sha256,occurred_at) '
                         'VALUES(?,?,?,?,?,?,?,?)',
                         (product['id'], item['kind'], item['slot'], item['asset_sha256'],
                          1, 'pass', 'e' * 64, now))
        row = dict(conn.execute('SELECT * FROM products WHERE id=?', (product['id'],)).fetchone())
    return SimpleNamespace(db=db, task_id=product['id'], row=row, artifact=artifact,
                           tmp_path=root)


@pytest.fixture
def prepared(prepared_template, tmp_path, monkeypatch):
    monkeypatch.setattr(batch, '_active_doudian_job_conflict', lambda shop, product_id: None)
    db = tmp_path / 'queue.sqlite3'
    with sqlite3.connect(prepared_template.db) as source, sqlite3.connect(db) as target:
        source.backup(target)
    artifact = tmp_path / 'artifacts.json'
    shutil.copy2(prepared_template.artifact, artifact)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE products SET artifacts_path=?,artifacts_hash=? WHERE id=?',
                     (str(artifact.resolve()), batch._digest(artifact), prepared_template.task_id))
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM products WHERE id=?',
                                (prepared_template.task_id,)).fetchone())
    return SimpleNamespace(db=db, task_id=prepared_template.task_id, row=row, artifact=artifact,
                           tmp_path=tmp_path, proof=None, files=[])


def _miao(row, official, *, protected_extra=None):
    sku = official['sku_evidence']['rows'][0]
    protected = {
        'root.categoryId': 'cat-1', 'root.brandName': '无品牌',
        'specPrices': [{'skuId': sku['sku_id'], 'specDetailIds': sku['spec_ids'],
                        'price': sku['price'], 'stockNum': sku['stock'],
                        'stepStockNum': sku['step_stock'], 'code': sku['code'],
                        'skuStatus': sku['enabled']}],
        'freightId': 'freight-1', 'status': 1, 'draftStatus': 0, 'checkStatus': 3,
        'specPics': [], 'mainImageThreeToFour': [], 'whiteBackGroundPicUrl': '',
        'afterSaleService': {'type': 'standard'},
    }
    protected.update(protected_extra or {})
    return {
        'product_id': row['product_id'], 'shop': row['shop'], 'title': official['title'],
        'mains': list(official['mains']), 'details': list(official['details']),
        'protected': protected, 'protected_complete': True,
        'source': 'miaoshou:getProductBaseEditInfo', 'response_status': 200,
        'category_id': 'cat-1', 'brand_name': '无品牌',
    }


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


def _make_proof(prepared, *, official_mutator=None, miao_mutator=None,
                observation_mutator=None):
    row = prepared.row
    observations = []
    prepared.files = []
    for index in range(2):
        official = _snapshot(row)
        if official_mutator:
            official_mutator(index, official)
        miao = _miao(row, official)
        if miao_mutator:
            miao_mutator(index, miao)
        miao_path = _write_json(prepared.tmp_path / f'miaoshou-{index}.json', miao)
        official_path = _write_json(prepared.tmp_path / f'doudian-{index}.json', official)
        prepared.files.extend((miao_path, official_path))
        observations.append({
            'miaoshou': {'path': str(miao_path), 'sha256': batch._digest(miao_path)},
            'doudian': {'path': str(official_path), 'sha256': batch._digest(official_path)},
            'observed_at': time.time(),
        })
    proof = {
        'read_only': True, 'reviewer': 'human-reviewer', 'product_id': row['product_id'],
        'shop': row['shop'], 'target_version': row['target_version'],
        'manifest_sha256': row['artifacts_hash'], 'observations': observations,
    }
    if observation_mutator:
        observation_mutator(proof)
    proof_path = _write_json(prepared.tmp_path / 'proof.json', proof)
    prepared.proof = proof_path
    return proof_path


def _update(prepared, **values):
    with sqlite3.connect(prepared.db) as conn:
        conn.execute('UPDATE products SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE id=?',
                     [*values.values(), prepared.task_id])


def test_two_recent_complete_reads_recover_only_queue_state_and_record_proof(prepared):
    proof = _make_proof(prepared)
    with sqlite3.connect(prepared.db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('UPDATE products SET lease_owner=?,lease_token=?,lease_until=? WHERE id=?',
                     ('expired-agent', 'old-token', time.time() - 1, prepared.task_id))
        before = dict(conn.execute('SELECT * FROM products WHERE id=?', (prepared.task_id,)).fetchone())
        history_before = conn.execute('SELECT COUNT(*) FROM asset_reviews WHERE task_id=?',
                                      (prepared.task_id,)).fetchone()[0]

    result = recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)

    assert result == {
        'task_id': prepared.task_id, 'state': 'ready',
        'target_version': prepared.row['target_version'],
        'proof_sha256': batch._digest(proof), 'artifact_sha256': prepared.row['artifacts_hash'],
        'reviewer': 'human-reviewer',
    }
    with sqlite3.connect(prepared.db) as conn:
        conn.row_factory = sqlite3.Row
        after = dict(conn.execute('SELECT * FROM products WHERE id=?', (prepared.task_id,)).fetchone())
        event = json.loads(conn.execute(
            "SELECT detail FROM product_events WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (prepared.task_id,)).fetchone()[0])
        history_after = conn.execute('SELECT COUNT(*) FROM asset_reviews WHERE task_id=?',
                                     (prepared.task_id,)).fetchone()[0]
    assert after['state'] == 'ready' and after['last_error'] is None
    assert after['lease_owner'] is after['lease_token'] is after['lease_until'] is None
    for key in ('target_version', 'artifacts_path', 'artifacts_hash', 'source', 'facts_json',
                'submission_state', 'submission_attempts', 'baseline_json', 'baseline_hash',
                'upload_map_json', 'submission_intent_json', 'readback_json', 'readback_hash',
                'writer_preparation_json'):
        assert after[key] == before[key]
    assert event['proof_sha256'] == batch._digest(proof)
    assert event['artifact_sha256'] == before['artifacts_hash']
    assert event['reviewer'] == 'human-reviewer'
    assert event['target_version'] == before['target_version']
    assert history_after == history_before


@pytest.mark.parametrize('changes', [
    {'submission_state': 'unknown', 'submission_attempts': 1},
    {'submission_attempts': 1},
    {'upload_map_json': '[{"slot":"mains:1"}]'},
    {'baseline_json': '{}'},
    {'baseline_hash': 'a' * 64},
    {'submission_intent_json': '{}'},
    {'readback_json': '{}'},
    {'readback_hash': 'b' * 64},
    {'writer_preparation_json': '{}'},
    {'lease_owner': 'live-agent', 'lease_token': 'live-token', 'lease_until': 9999999999},
    {'execution_owner': 'writer', 'execution_token': 'live-execution', 'execution_until': 9999999999},
    {'execution_until': 9999999999},
])
def test_write_history_or_live_lease_keeps_task_blocked(prepared, changes):
    proof = _make_proof(prepared)
    _update(prepared, **changes)

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)

    with sqlite3.connect(prepared.db) as conn:
        row = conn.execute('SELECT state,last_error FROM products WHERE id=?',
                           (prepared.task_id,)).fetchone()
    assert row == ('blocked', ERROR)


@pytest.mark.parametrize('mutate_proof', [
    lambda proof: proof.update(product_id='3850071689249554609'),
    lambda proof: proof.update(shop='另一家店'),
    lambda proof: proof.update(target_version='another-version'),
    lambda proof: proof.update(manifest_sha256='0' * 64),
    lambda proof: proof.update(read_only=False),
    lambda proof: proof.update(reviewer='  '),
])
def test_proof_identity_or_manifest_binding_mismatch_is_rejected(prepared, mutate_proof):
    def alter(proof):
        mutate_proof(proof)
    path = _make_proof(prepared, observation_mutator=alter)

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, path, db_path=prepared.db)


def test_manifest_target_version_and_hash_must_stay_immutable(prepared):
    proof = _make_proof(prepared)
    data = json.loads(prepared.artifact.read_text(encoding='utf-8'))
    data['target_version'] = 'different-version'
    prepared.artifact.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    _update(prepared, artifacts_hash=batch._digest(prepared.artifact))
    proof_data = json.loads(proof.read_text(encoding='utf-8'))
    proof_data['manifest_sha256'] = batch._digest(prepared.artifact)
    _write_json(proof, proof_data)

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


def test_manifest_file_change_without_queue_hash_update_is_rejected(prepared):
    proof = _make_proof(prepared)
    data = json.loads(prepared.artifact.read_text(encoding='utf-8'))
    data['late_mutation'] = True
    prepared.artifact.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    with pytest.raises(DoudianError, match='哈希变化'):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


@pytest.mark.parametrize('issue', ['stale_time', 'stale_mtime', 'missing_file', 'same_paths',
                                   'one_observation', 'three_observations'])
def test_old_missing_or_reused_observation_files_are_rejected(prepared, issue):
    proof = _make_proof(prepared)
    data = json.loads(proof.read_text(encoding='utf-8'))
    if issue == 'stale_time':
        data['observations'][1]['observed_at'] = time.time() - 1801
    elif issue == 'stale_mtime':
        old = time.time() - 1801
        os.utime(prepared.files[-1], (old, old))
    elif issue == 'missing_file':
        data['observations'][1]['doudian']['path'] = str(prepared.tmp_path / 'gone.json')
        data['observations'][1]['doudian']['sha256'] = 'a' * 64
    elif issue == 'one_observation':
        data['observations'] = data['observations'][:1]
    elif issue == 'three_observations':
        data['observations'].append(data['observations'][1])
    else:
        data['observations'][1]['miaoshou'] = data['observations'][0]['miaoshou']
        data['observations'][1]['doudian'] = data['observations'][0]['doudian']
    _write_json(proof, data)

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


def _change_official_sku(index, official):
    if index != 1:
        return
    evidence = official['sku_evidence']
    evidence['rows'][0]['price'] = '11'
    evidence['raw_rows'][0]['price'] = '11.00'
    payload = {key: evidence[key] for key in ('rows', 'raw_rows', 'specs')}
    evidence['sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def test_changed_sku_between_official_observations_is_rejected(prepared):
    proof = _make_proof(prepared, official_mutator=_change_official_sku)

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


@pytest.mark.parametrize('case', ['official_protected', 'required_attributes', 'miao_protected'])
def test_missing_protected_or_required_attributes_cannot_pass(prepared, case):
    def official_mutator(index, official):
        if index != 1:
            return
        if case == 'official_protected':
            del official['protected']
        elif case == 'required_attributes':
            del official['required_attributes']

    def miao_mutator(index, miao):
        if index == 1 and case == 'miao_protected':
            del miao['protected']['freightId']

    proof = _make_proof(prepared, official_mutator=official_mutator,
                        miao_mutator=miao_mutator)

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


@pytest.mark.parametrize('case', ['check_status', 'top_level', 'main_order', 'detail_order'])
def test_miaoshou_reads_must_match_on_raw_status_fields_and_image_order(prepared, case):
    def mutate(index, miao):
        if index != 1:
            return
        if case == 'check_status':
            miao['protected']['checkStatus'] = '3'
        elif case == 'top_level':
            miao['response_status'] = 201
        elif case == 'main_order':
            miao['mains'][0], miao['mains'][1] = miao['mains'][1], miao['mains'][0]
        else:
            miao['details'][0], miao['details'][1] = miao['details'][1], miao['details'][0]

    proof = _make_proof(prepared, miao_mutator=mutate)

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


def test_existing_visual_failure_or_failed_manifest_is_isolated(prepared):
    proof = _make_proof(prepared)
    with sqlite3.connect(prepared.db) as conn:
        conn.execute("UPDATE asset_reviews SET decision='fail' WHERE task_id=? AND slot=1",
                     (prepared.task_id,))

    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


def test_visual_review_failure_and_attempt_over_two_are_rejected(prepared):
    manifest = json.loads(prepared.artifact.read_text(encoding='utf-8'))
    manifest['visual_review']['items'][0]['checks']['identity']['status'] = 'fail'
    prepared.artifact.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    _update(prepared, artifacts_hash=batch._digest(prepared.artifact))
    proof = _make_proof(prepared)
    proof_data = json.loads(proof.read_text(encoding='utf-8'))
    proof_data['manifest_sha256'] = batch._digest(prepared.artifact)
    _write_json(proof, proof_data)
    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)

    # A previously exhausted slot is rejected independently of the current manifest.
    manifest['visual_review']['items'][0]['checks']['identity']['status'] = 'pass'
    prepared.artifact.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    _update(prepared, artifacts_hash=batch._digest(prepared.artifact))
    proof_data['manifest_sha256'] = batch._digest(prepared.artifact)
    _write_json(proof, proof_data)
    with sqlite3.connect(prepared.db) as conn:
        conn.execute('UPDATE asset_reviews SET attempt=3 WHERE task_id=? AND slot=1',
                     (prepared.task_id,))
    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


def test_same_product_version_conflict_and_active_official_job_are_rejected(prepared, monkeypatch, tmp_path):
    proof = _make_proof(prepared)
    source = tmp_path / 'duplicate.json'
    source.write_text(json.dumps({'products': [{'shop': SHOP, 'product_id': PID}]}, ensure_ascii=False),
                      encoding='utf-8')
    batch.create_batch(source, db_path=prepared.db)
    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)

    # Remove the synthetic duplicate so the independent official-job guard is reached.
    with sqlite3.connect(prepared.db) as conn:
        conn.execute('DELETE FROM products WHERE id!=?', (prepared.task_id,))
        conn.execute('DELETE FROM batches WHERE id NOT IN (SELECT batch_id FROM products)')
    monkeypatch.setattr(batch, '_active_doudian_job_conflict',
                        lambda shop, product_id: 'active official job')
    with pytest.raises(DoudianError):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)


def test_same_proof_cannot_be_reused_even_if_task_is_reblocked(prepared):
    proof = _make_proof(prepared)
    recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)
    _update(prepared, state='blocked', last_error=ERROR)

    with pytest.raises(DoudianError, match='已经使用过'):
        recover_prepared_after_reads(prepared.task_id, proof, db_path=prepared.db)
