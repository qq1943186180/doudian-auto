"""`batch requeue` — a supported, fail-closed way back from a visual failure.

The proof must be a complete nine-image artifact manifest whose visual review has
five explicit pass/fail checks per image. A `conditional` or `pass_with_note`
opinion cannot be expressed in that schema, so it is refused rather than promoted.
"""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.visual_review import CHECKS, facts_hash

PID = '3850072900438720563'
SHOP = '样板店'
TITLE = '新款特大号家用桌面大容量收纳盒轻奢款'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def queue(tmp_path):
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [{'product_id': PID, 'shop': SHOP,
                                                'source_title': TITLE}]},
                                 ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch.create_batch(source, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM products').fetchone())
    return SimpleNamespace(db=db, row=row)


def make_manifest(queue, tmp_path, *, status='pass', generator='web-gpt-ego', name='art'):
    """Build a complete, valid nine-image artifact manifest with bound provenance."""
    d = tmp_path / name
    (d / 'prompts').mkdir(parents=True, exist_ok=True)

    ref = d / 'ref.png'
    Image.new('RGB', (700, 700), (12, 34, 56)).save(ref)
    ref_hash = _sha(ref)
    facts = {key: '参考图中可见奶白色圆角杯身与透明盖，细节与源图一致。' for key in CHECKS}
    source = {'product_id': PID, 'shop': SHOP, 'facts': facts,
              'references': [{'path': 'ref.png', 'sha256': ref_hash}]}
    source_path = d / 'source.json'
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')

    mains, details, records = [], [], []
    for slot in range(1, 6):
        p = d / f'main-{slot}.png'
        Image.new('RGB', (1024, 1024), (slot * 21, 70, 110)).save(p)
        mains.append(str(p))
        records.append(('main', slot, p))
    for slot in range(1, 5):
        p = d / f'detail-{slot}.png'
        Image.new('RGB', (1024, 1536), (90, slot * 31, 50)).save(p)
        details.append(str(p))
        records.append(('detail', slot, p))

    items = []
    for kind, slot, p in records:
        prompt = d / 'prompts' / f'{kind}-{slot}.txt'
        prompt.write_text('以参考图为依据做高保真商品图重制，保留印字与结构。', encoding='utf-8')
        items.append({
            'kind': kind, 'slot': slot, 'asset_sha256': _sha(p), 'generator': generator,
            'prompt': {'path': f'prompts/{kind}-{slot}.txt', 'sha256': _sha(prompt)},
            'checks': {key: {'status': status,
                             'observed': '实际看到奶白杯身、透明盖与银亮杯口环，未见到新增文字或第二只杯子。',
                             'reference_sha256': [ref_hash]} for key in CHECKS},
        })

    review = {'schema_version': 1, 'product_id': PID,
              'target_version': queue.row['target_version'], 'reviewer': 'workbuddy-visual',
              'source_snapshot': {'path': 'source.json', 'sha256': _sha(source_path)},
              'facts_sha256': facts_hash(facts), 'items': items}
    manifest = {'product_id': PID, 'target_version': queue.row['target_version'],
                'title': TITLE, 'mains': mains, 'details': details, 'visual_review': review}
    path = d / 'artifacts.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    return path


def block_visually(queue, *, reason='visual_quality_failed_after_retry', fail_rows=2):
    """Leave the historical failures a remake has to overcome."""
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET state='blocked', last_error=?, updated_at=? WHERE id=?",
                     (reason, time.time() - 100, queue.row['id']))
        for index in range(fail_rows):
            conn.execute('INSERT INTO asset_reviews VALUES(?,?,?,?,?,?,?,?)',
                         (queue.row['id'], 'detail', 3, f'{"a" * 63}{index}', index + 1,
                          'fail', 'b' * 64, time.time() - 100))


def test_a_qualified_opinion_is_refused(queue, tmp_path):
    # `conditional` / `pass_with_note` are not expressible in the review schema; the
    # validator must reject them rather than treat a qualified note as a pass.
    block_visually(queue)
    proof = make_manifest(queue, tmp_path, status='conditional')
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                               miaoshou_probe=lambda *_: True)
    assert exc.value.code == 'visual_review_incomplete'
    assert _state(queue) == 'blocked'


def test_a_non_visual_block_reason_is_refused(queue, tmp_path):
    block_visually(queue, reason='readback_mismatch')
    proof = make_manifest(queue, tmp_path)
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                               miaoshou_probe=lambda *_: True)
    assert exc.value.code == 'requeue_not_allowed'


def test_a_row_without_failed_review_history_is_refused(queue, tmp_path):
    block_visually(queue, fail_rows=0)
    proof = make_manifest(queue, tmp_path)
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                               miaoshou_probe=lambda *_: True)
    assert exc.value.code == 'requeue_evidence_missing'


def test_a_row_that_was_already_written_cannot_requeue(queue, tmp_path):
    block_visually(queue)
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET baseline_hash='deadbeef' WHERE id=?", (queue.row['id'],))
    proof = make_manifest(queue, tmp_path)
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                               miaoshou_probe=lambda *_: True)
    assert exc.value.code == 'requeue_not_allowed'


def test_a_stale_manifest_cannot_open_a_round(queue, tmp_path):
    block_visually(queue)
    proof = make_manifest(queue, tmp_path)
    old = time.time() - 3600
    os.utime(proof, (old, old))
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                               miaoshou_probe=lambda *_: True)
    assert exc.value.code == 'requeue_evidence_stale'


def test_requeue_opens_a_new_round_and_stamps_events(queue, tmp_path):
    block_visually(queue)
    proof = make_manifest(queue, tmp_path)
    result = batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                               miaoshou_probe=lambda *_: True)
    assert result['state'] == 'needs_agent' and result['round'] == 1
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        events = [tuple(e) for e in conn.execute(
            'SELECT from_state,to_state FROM product_events WHERE task_id=?', (queue.row['id'],))]
        started = batch._visual_round_start(conn, queue.row['id'])
    assert ('blocked', 'visual_round_opened') in events
    assert ('visual_round_opened', 'needs_agent') in events
    assert started > 0
    assert _state(queue) == 'needs_agent'


def test_attempt_count_restarts_after_requeue(queue, tmp_path):
    # Two historical failures used to make the next good asset attempt=3, which the
    # `attempt > 2` guard re-blocked forever. After a requeue the count is per round.
    block_visually(queue)
    proof = make_manifest(queue, tmp_path)
    batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                               miaoshou_probe=lambda *_: True)
    claim = batch.claim_next('tester', product_id=PID, db_path=queue.db)
    batch.complete_agent_task(queue.row['id'], claim['lease_owner'], claim['lease_token'],
                              proof, db_path=queue.db)
    with sqlite3.connect(queue.db) as conn:
        conn.row_factory = sqlite3.Row
        state = conn.execute('SELECT state FROM products WHERE id=?', (queue.row['id'],)).fetchone()[0]
        new = [dict(r) for r in conn.execute(
            'SELECT attempt,decision FROM asset_reviews WHERE task_id=? AND occurred_at>=?',
            (queue.row['id'], batch._visual_round_start(conn, queue.row['id'])))]
    assert state != 'blocked'
    assert new and all(row['attempt'] == 1 for row in new)


def _state(queue):
    with sqlite3.connect(queue.db) as conn:
        return conn.execute('SELECT state FROM products WHERE id=?', (queue.row['id'],)).fetchone()[0]

def test_requeue_requires_miaoshou_proof(queue, tmp_path):
    # Every write goes through 妙手. A proof from the official page alone is not
    # enough -- this was exactly how task 48 was wrongly released once.
    block_visually(queue)
    proof = make_manifest(queue, tmp_path)
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db)
    assert exc.value.code == 'miaoshou_listing_unproven'


def test_an_unreadable_miaoshou_probe_is_not_treated_as_absent(queue, tmp_path):
    block_visually(queue)
    proof = make_manifest(queue, tmp_path)
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], proof, db_path=queue.db,
                                  miaoshou_probe=lambda *_: None)
    assert exc.value.code == 'miaoshou_listing_unproven'
    assert _state(queue) == 'blocked'


def test_requeue_replaces_prewrite_artifacts_reference_and_rejects_unchanged_assets(queue, tmp_path):
    old_proof = make_manifest(queue, tmp_path, name='old_art')
    old_hash = hashlib.sha256(old_proof.read_bytes()).hexdigest()
    block_visually(queue, reason='root_visual_review_failed_after_retry: detail:3 failed')
    with sqlite3.connect(queue.db) as conn:
        conn.execute('UPDATE products SET artifacts_path=?, artifacts_hash=? WHERE id=?',
                     (str(old_proof), old_hash, queue.row['id']))
    # Reusing identical manifest hash must be refused.
    with pytest.raises(DoudianError) as same_exc:
        batch.requeue_visual_task(queue.row['id'], old_proof, db_path=queue.db,
                                  miaoshou_probe=lambda *_: True)
    assert same_exc.value.code == 'requeue_evidence_stale'

    # Providing regenerated assets supersedes prior_artifacts_path and records audit detail.
    new_proof = make_manifest(queue, tmp_path, name='new_art')
    Image.new('RGB', (1024, 1536), (11, 22, 33)).save(tmp_path / 'new_art' / 'detail-3.png')
    # Re-create manifest hashes cleanly via make_manifest on a fresh dir with unique content
    new_dir = tmp_path / 'new_art_2'
    new_proof = make_manifest(queue, tmp_path, name='new_art_2')
    # Mutate detail-3 color in make_manifest by rewriting its content & hashes? Easier: reuse make_manifest?
    # Note: make_manifest uses deterministic RGB by slot, so alter detail-3 and update manifest hashes cleanly.
    data = json.loads(new_proof.read_text(encoding='utf-8'))
    d3 = new_dir / 'detail-3.png'
    Image.new('RGB', (1024, 1536), (11, 22, 33)).save(d3)
    new_sha = _sha(d3)
    for item in data['visual_review']['items']:
        if item['kind'] == 'detail' and item['slot'] == 3:
            item['asset_sha256'] = new_sha
    new_proof.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    res = batch.requeue_visual_task(queue.row['id'], new_proof, db_path=queue.db,
                                    miaoshou_probe=lambda *_: True)
    assert res['state'] == 'needs_agent'
    with sqlite3.connect(queue.db) as conn:
        row = conn.execute('SELECT artifacts_path, artifacts_hash, state FROM products WHERE id=?',
                           (queue.row['id'],)).fetchone()
    assert tuple(row) == (None, None, 'needs_agent')


def test_requeue_still_rejects_any_baseline_intent_or_preparation(queue, tmp_path):
    block_visually(queue, reason='root_visual_review_failed_after_retry: x')
    new_proof = make_manifest(queue, tmp_path, name='blocked_art')
    with sqlite3.connect(queue.db) as conn:
        conn.execute("UPDATE products SET baseline_json='{}' WHERE id=?", (queue.row['id'],))
    with pytest.raises(DoudianError) as exc:
        batch.requeue_visual_task(queue.row['id'], new_proof, db_path=queue.db,
                                  miaoshou_probe=lambda *_: True)
    assert exc.value.code == 'requeue_not_allowed'


@pytest.mark.parametrize('mode', [
    'valid', 'tampered_sha', 'wrong_product', 'missing_hashes',
    'reuse_first_attempt', 'reuse_final_attempt', 'conflict_event',
])
def test_root_quarantine_requeue_with_zero_asset_reviews(queue, tmp_path, mode):
    old_first = make_manifest(queue, tmp_path, name='old_first')
    first_data = json.loads(old_first.read_text(encoding='utf-8'))
    first_d2_sha = first_data['visual_review']['items'][6]['asset_sha256']
    final_d2 = tmp_path / 'final_d2.png'
    Image.new('RGB', (1024, 1536), (111, 222, 33)).save(final_d2)
    final_d2_sha = _sha(final_d2)

    q_path = tmp_path / 'root-visual-quarantine.json'
    q_doc = {
        'task_id': queue.row['id'],
        'product_id': PID if mode != 'wrong_product' else '9999999999999999999',
        'target_version': queue.row['target_version'],
        'reviewer': 'root-reviewer',
        'status': 'fail_after_retry',
        'uploads': 0,
        'save_attempts': 0,
        'failed_slots': [{
            'kind': 'detail',
            'slot': 2,
            'checks': ['identity'],
            'final_asset': {} if mode == 'missing_hashes' else {'sha256': final_d2_sha},
            'first_failed_asset': {} if mode == 'missing_hashes' else {'sha256': first_d2_sha},
        }],
    }
    q_path.write_text(json.dumps(q_doc, ensure_ascii=False), encoding='utf-8')
    q_sha = _sha(q_path)
    if mode == 'tampered_sha':
        q_doc['reason'] = 'tampered'
        q_path.write_text(json.dumps(q_doc, ensure_ascii=False), encoding='utf-8')
    err_str = f'root_visual_review_failed_after_retry: detail2 failed. Root proof {q_path} sha256={q_sha}'
    block_visually(queue, reason=err_str, fail_rows=0)
    if mode == 'conflict_event':
        with sqlite3.connect(queue.db) as conn:
            conn.execute('INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail) VALUES(?,?,?,?,?)',
                         (queue.row['id'], 'agent_claimed', 'blocked', time.time() - 50,
                          f'root_visual_review_failed_after_retry: other. Root proof {q_path} sha256={"0"*64}'))

    new_proof = make_manifest(queue, tmp_path, name='fresh_round')
    new_data = json.loads(new_proof.read_text(encoding='utf-8'))
    if mode == 'reuse_first_attempt':
        # Already uses identical make_manifest deterministic pixel for detail-2 (same sha as first_d2_sha!)
        pass
    elif mode == 'reuse_final_attempt':
        p = Path(new_data['details'][1])
        p.write_bytes(final_d2.read_bytes())
        for it in new_data['visual_review']['items']:
            if it['kind'] == 'detail' and it['slot'] == 2:
                it['asset_sha256'] = final_d2_sha
        new_proof.write_text(json.dumps(new_data, ensure_ascii=False), encoding='utf-8')
    else:
        p = Path(new_data['details'][1])
        Image.new('RGB', (1024, 1536), (77, 88, 99)).save(p)
        fixed_sha = _sha(p)
        for it in new_data['visual_review']['items']:
            if it['kind'] == 'detail' and it['slot'] == 2:
                it['asset_sha256'] = fixed_sha
        new_proof.write_text(json.dumps(new_data, ensure_ascii=False), encoding='utf-8')

    if mode == 'valid':
        res = batch.requeue_visual_task(queue.row['id'], new_proof, db_path=queue.db,
                                        miaoshou_probe=lambda *_: True)
        assert res['state'] == 'needs_agent'
        assert res['round'] == 1
    else:
        with pytest.raises(DoudianError):
            batch.requeue_visual_task(queue.row['id'], new_proof, db_path=queue.db,
                                      miaoshou_probe=lambda *_: True)
