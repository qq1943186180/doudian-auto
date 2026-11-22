"""Audited return of historical, resolved work to the existing preparation row."""

from collections import Counter
import hashlib
import json
import time
from pathlib import Path

from . import batch
from .errors import DoudianError
from .official_skus import verify_miaoshou_skus
from .preflight import _validate_snapshot
from .visual_review import _bound_file
from .workflow import is_permanent_material_url, is_temporary_upload_url, resource_key


_COMPLETED_EXTERNAL_STAGES = frozenset({
    'verified',
    'official_readback_complete',
    'saved_and_verified',
    'completed',
})
_COUNTER_KEYS = ('saveAttempts', 'saveCount', 'saveAttemptCount', 'submitCount', 'publishAttemptCount')
_AMBIGUOUS_NO_SAVE_STAGES = frozenset({'unknown', 'uploading', 'upload_unknown', 'saving'})


def _idle_count(value):
    # Only an explicit zero means "nothing moved". A missing counter, None, a
    # negative number, a bool or a string must not be coerced into agreement --
    # `'0' <= 0` would even raise instead of refusing the row.
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _no_temp_urls(snapshot):
    urls = [*(snapshot.get('mains') or []), *(snapshot.get('details') or [])]
    return not any(is_temporary_upload_url(url) for url in urls)


def _load_dual_snapshots(proof, proof_dir, row, *, now, max_age_seconds, preflight, fail):
    snapshots = []
    for key in ('miaoshou', 'doudian'):
        file = _bound_file(proof.get(key), proof_dir, 'external_rebaseline_unproven')
        if not 0 <= now - file.stat().st_mtime <= max_age_seconds:
            raise fail()
        snapshots.append(batch.read_json(file))
    miao, official = snapshots
    _validate_snapshot(official, dict(row))
    if preflight:
        from .prepared_recovery import _validate_miaoshou
        _validate_miaoshou(miao, official, dict(row))
    verify_miaoshou_skus(miao, official.get('sku_evidence'))
    if (miao.get('product_id') != row['product_id'] or miao.get('shop') != row['shop']
            or miao.get('protected_complete') is not True
            or miao.get('protected', {}).get('status') != 1
            or official.get('draft_loaded') is not False
            or official.get('rejected') is not False
            or not _no_temp_urls(miao) or not _no_temp_urls(official)
            or miao['title'] != official['title']
            or any([resource_key(x) for x in miao[k]] !=
                   [resource_key(x) for x in official[k]] for k in ('mains', 'details'))):
        raise fail()
    return miao, official


def _bind_observations(conn, task_id, row, proof, proof_dir, fail):
    observations = conn.execute('SELECT * FROM external_observations WHERE task_id=?', (task_id,)).fetchall()
    resolutions = proof.get('resolved_observations', [])
    if not observations or len(resolutions) != len(observations):
        raise fail()
    remaining = {x['evidence_sha256'] for x in observations}
    items = []
    for item in resolutions:
        if not isinstance(item, dict):
            raise fail()
        file = _bound_file(item.get('evidence'), proof_dir, 'external_rebaseline_unproven')
        digest = batch._digest(file)
        if digest not in remaining or not any(Path(x['evidence_path']).resolve() == file for x in observations):
            raise fail()
        history = batch.read_json(file)
        if not isinstance(history, dict):
            raise fail()
        if (str(history.get('product_id', history.get('productId'))) != row['product_id']
                or not str(item.get('reason', '')).strip()):
            raise fail()
        remaining.remove(digest)
        items.append((item, history))
    if remaining:
        raise fail()
    return observations, items


def _has_valid_live_audit(proof):
    audit = proof.get('live_audit')
    return (isinstance(audit, dict)
            and audit.get('read_only') is True
            and audit.get('live_baseline_clean') is True
            and audit.get('temp_urls_absent') is True
            and audit.get('shelf_status') == 1
            and bool(str(audit.get('reviewer', '')).strip())
            and bool(str(audit.get('summary', '')).strip()))


def _external_recorded_title(history):
    title = history.get('title')
    if isinstance(title, dict):
        return title.get('candidate') or title.get('target') or title.get('value')
    if isinstance(title, str) and title.strip():
        return title
    return history.get('candidateTitle')


def _observation_is_resolved(history, item, live_audit_ok):
    submitted = {key: str(history[key]).strip().lower()
                 for key in ('submission_status', 'submission_state', 'submissionStatus')
                 if history.get(key) is not None}
    status = (next(iter(submitted.values()))
              if len(set(submitted.values())) == 1 and 'unknown' not in submitted.values()
              else None)
    stage = str(history.get('stage') if history.get('stage') is not None
                else (history.get('phase') or '')).strip().lower()
    counters = {key: history[key] for key in _COUNTER_KEYS if key in history}
    counter_ok = all(_idle_count(value) for value in counters.values())
    no_uploads = history.get('uploadsStarted') in (None, False, 0)
    clean_not_attempted = (status == 'not_attempted'
                           and counter_ok
                           and no_uploads
                           and history.get('saved') is not True
                           and history.get('published') is not True
                           and stage not in _AMBIGUOUS_NO_SAVE_STAGES)
    never_saved = (history.get('saved') is False
                   and any(k in counters for k in ('saveAttempts', 'saveCount'))
                   and counter_ok
                   and no_uploads
                   and (not submitted or status == 'not_attempted'))
    prior_confirmed = (stage == 'verified'
                       and status in ('accepted', 'verified_by_readback'))
    resolution = item.get('resolution')
    if resolution == 'no_save_attempted':
        return clean_not_attempted or never_saved
    if resolution == 'prior_revision_confirmed':
        return prior_confirmed
    if resolution == 'live_server_baseline_verified':
        return live_audit_ok
    return False


def rebaseline_external(task_id, proof_path, *, db_path=None):
    """Keep version/history intact; never recover an unknown queue submission."""
    return _rebaseline(task_id, proof_path, db_path=db_path, preflight=False)


def recover_preflight(task_id, proof_path, *, db_path=None):
    """Recover only an untouched missing-attribute preparation after fresh dual reads."""
    return _rebaseline(task_id, proof_path, db_path=db_path, preflight=True)


def _rebaseline(task_id, proof_path, *, db_path, preflight):
    path = Path(proof_path).resolve()
    proof = batch.read_json(path)
    conn = batch._db(db_path)
    fail = lambda: DoudianError('external_rebaseline_unproven',
        '旧任务未核清或双端基线不完整，保持隔离，不重新保存。')
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        now = time.time()
        if preflight:
            expected_error = bool(row and str(row['last_error'] or '').startswith(
                'preflight_exception: required_attributes_missing;'))
        else:
            expected_error = bool(row and row['last_error'] == 'external_work_requires_rebaseline')
        if (row is None or row['state'] != 'blocked'
                or not expected_error
                or row['submission_state'] != 'not_attempted' or row['submission_attempts'] != 0
                or row['baseline_hash'] or row['artifacts_path'] or row['artifacts_hash']
                or json.loads(row['upload_map_json'] or '[]') != []
                or any((row[key] or 0) >= now for key in ('lease_until', 'execution_until'))):
            raise fail()
        if (not isinstance(proof, dict) or proof.get('read_only') is not True
                or any(proof.get(k) != row[k] for k in ('product_id', 'shop', 'target_version'))
                or not str(proof.get('reviewer', '')).strip()
                or conn.execute('SELECT 1 FROM products WHERE shop=? AND product_id=? AND id!=?',
                                (row['shop'], row['product_id'], task_id)).fetchone()
                or batch._active_doudian_job_conflict(row['shop'], row['product_id'])):
            raise fail()
        if preflight and (
                proof.get('prior_error') != row['last_error']
                or any(row[key] for key in ('baseline_json', 'submission_intent_json',
                                            'readback_json', 'readback_hash', 'writer_preparation_json'))
                or batch._source_has_prior_work(json.loads(row['source']))
                or conn.execute('SELECT 1 FROM asset_reviews WHERE task_id=?', (task_id,)).fetchone()
                or conn.execute('SELECT 1 FROM external_observations WHERE task_id=?', (task_id,)).fetchone()):
            raise fail()
        miao, official = _load_dual_snapshots(
            proof, path.parent, row, now=now, max_age_seconds=1800 if preflight else 7200,
            preflight=preflight, fail=fail)
        observations = []
        if not preflight:
            live_audit_ok = _has_valid_live_audit(proof)
            observations, items = _bind_observations(conn, task_id, row, proof, path.parent, fail)
            for item, history in items:
                if not _observation_is_resolved(history, item, live_audit_ok):
                    raise fail()
        source = json.loads(row['source'])
        source.update(source_title=miao['title'], name=miao['title'], stage='prepared',
                      status='1', statusName='下架')
        detail = {'kind': 'preflight_recovery' if preflight else 'external_rebaseline', 'proof_path': str(path),
                  'proof_sha256': batch._digest(path), 'target_version': row['target_version'],
                  'reviewer': proof['reviewer'], 'resolved_observation_sha256': sorted(
                      x['evidence_sha256'] for x in observations)}
        if preflight:
            detail['prior_error'] = row['last_error']
        conn.execute("UPDATE products SET state='needs_agent',last_error=NULL,source=?,"
                     "lease_owner=NULL,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                     (json.dumps(source, ensure_ascii=False), now, task_id))
        conn.execute('INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail) VALUES(?,?,?,?,?)',
                     (task_id, 'blocked', 'needs_agent', now, json.dumps(detail, ensure_ascii=False)))
        conn.commit()
        return {'task_id': task_id, 'state': 'needs_agent', 'target_version': row['target_version'], **detail}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_ALLOWED_UNRESOLVED_ADVISORIES = {
    'stale_list_summary': frozenset({
        '妙手列表摘要仍可能显示旧标题缓存；独立编辑器字段与官方抖店页均已读回新标题，作为权威结果。',
    }),
}


def _collect_unresolved_texts(history, fail):
    raw = history.get('unresolved')
    if not raw:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise fail()
        return [text]
    if isinstance(raw, list) and all(isinstance(x, str) and x.strip() for x in raw):
        return [x.strip() for x in raw]
    raise fail()


def _save_block_ok(history):
    save_block = history.get('save')
    if not isinstance(save_block, dict) or not save_block:
        return True
    if save_block.get('result') == 'fail':
        return False
    attempts = [(k, v) for k, v in save_block.items()
                if isinstance(k, str) and k.startswith('attempt') and isinstance(v, dict)]
    if attempts:
        # Sort attempt1, attempt2... numerically when possible
        attempts.sort(key=lambda kv: (len(kv[0]), kv[0]))
        return attempts[-1][1].get('result') == 'success'
    return save_block.get('result') in (None, 'success')


def _validate_acknowledged_unresolved(proof, unresolved_texts, official, expected_mains, expected_details, fail):
    ack = proof.get('acknowledged_unresolved')
    if not unresolved_texts:
        if ack is not None:
            raise fail()
        return None, None
    if not isinstance(ack, list) or len(ack) != len(unresolved_texts):
        raise fail()
    ack_texts = []
    for entry in ack:
        if not isinstance(entry, dict):
            raise fail()
        kind = entry.get('kind')
        text = entry.get('text')
        reason = entry.get('reason')
        allowed = _ALLOWED_UNRESOLVED_ADVISORIES.get(kind)
        if not allowed or text not in allowed or not isinstance(reason, str) or not reason.strip():
            raise fail()
        ack_texts.append(text)
    if Counter(ack_texts) != Counter(unresolved_texts):
        raise fail()
    vv = proof.get('visual_verification')
    expected_d_count = min(4, expected_details)
    if (not isinstance(vv, dict)
            or not isinstance(vv.get('reviewer'), str) or not vv['reviewer'].strip()
            or vv.get('all_clean_verified') is not True
            or vv.get('mains_keys') != [resource_key(u) for u in official['mains']]
            or len(vv.get('mains_keys') or []) != expected_mains
            or vv.get('details_keys') != [resource_key(u) for u in official['details'][:expected_d_count]]):
        raise fail()
    return ack, vv


def reconcile_external_verified(task_id, proof_path, *, db_path=None):
    """Close out an externally saved task when historical and fresh live dual reads match target."""
    path = Path(proof_path).resolve()
    proof = batch.read_json(path)
    conn = batch._db(db_path)
    fail = lambda: DoudianError('external_reconcile_unproven',
        '历史完成证据或双端现网回读不一致，拒绝直接核销为已验证。')
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        now = time.time()
        if (row is None or row['state'] != 'blocked'
                or row['last_error'] != 'external_work_requires_rebaseline'
                or row['submission_state'] != 'not_attempted' or row['submission_attempts'] != 0
                or row['baseline_hash'] or row['artifacts_path'] or row['artifacts_hash'] or row['readback_hash']
                or json.loads(row['upload_map_json'] or '[]') != []
                or any((row[key] or 0) >= now for key in ('lease_until', 'execution_until'))):
            raise fail()
        target_title = proof.get('target_title') if isinstance(proof, dict) else None
        if (not isinstance(proof, dict) or proof.get('read_only') is not True
                or (proof.get('task_id') is not None and proof.get('task_id') != task_id)
                or any(proof.get(k) != row[k] for k in ('product_id', 'shop', 'target_version'))
                or not isinstance(target_title, str) or not target_title.strip()
                or not str(proof.get('reviewer', '')).strip()
                or conn.execute('SELECT 1 FROM products WHERE shop=? AND product_id=? AND id!=?',
                                (row['shop'], row['product_id'], task_id)).fetchone()
                or batch._active_doudian_job_conflict(row['shop'], row['product_id'])):
            raise fail()
        miao, official = _load_dual_snapshots(
            proof, path.parent, row, now=now, max_age_seconds=7200,
            preflight=False, fail=fail)
        expected_mains = proof.get('expected_mains_count', 5)
        expected_details = proof.get('expected_details_count', 4)
        if (miao['title'] != target_title
                or len(official['mains']) != expected_mains
                or len(official['details']) != expected_details
                or any(not is_permanent_material_url(u) for u in [*official['mains'], *official['details']])):
            raise fail()
        observations, items = _bind_observations(conn, task_id, row, proof, path.parent, fail)
        unresolved_texts = []
        for item, history in items:
            stage = str(history.get('stage') if history.get('stage') is not None
                        else (history.get('phase') or '')).strip().lower()
            hist_status = history.get('statusFinal', history.get('status'))
            hist_title = _external_recorded_title(history)
            if (item.get('resolution') != 'prior_revision_confirmed'
                    or stage not in _COMPLETED_EXTERNAL_STAGES
                    or history.get('saved') is False
                    or not _save_block_ok(history)
                    or (hist_status is not None and hist_status not in (1, '1', '下架'))
                    or (hist_title is not None and hist_title != target_title)):
                raise fail()
            unresolved_texts.extend(_collect_unresolved_texts(history, fail))
        ack_list, visual_verif = _validate_acknowledged_unresolved(
            proof, unresolved_texts, official, expected_mains, expected_details, fail)
        readback_doc = {
            'reconciled_external': True, 'title': miao['title'],
            'mains': official['mains'], 'details': official['details'],
            'shop': row['shop'], 'product_id': row['product_id'],
        }
        readback_json = json.dumps(readback_doc, ensure_ascii=False, sort_keys=True)
        readback_hash = hashlib.sha256(readback_json.encode('utf-8')).hexdigest()
        source = json.loads(row['source'])
        source.update(source_title=miao['title'], name=miao['title'], stage='verified',
                      status='1', statusName='下架')
        detail = {
            'kind': 'external_verified_reconciliation', 'proof_path': str(path),
            'proof_sha256': batch._digest(path), 'target_version': row['target_version'],
            'reviewer': proof['reviewer'], 'readback_hash': readback_hash,
            'resolved_observation_sha256': sorted(x['evidence_sha256'] for x in observations),
        }
        if ack_list is not None:
            detail['acknowledged_unresolved'] = ack_list
            detail['visual_verification'] = visual_verif
        conn.execute(
            "UPDATE products SET state='verified',submission_state='verified_by_readback',"
            "submission_attempts=0,last_error=NULL,readback_json=?,readback_hash=?,"
            "source=?,lease_owner=NULL,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?",
            (readback_json, readback_hash, json.dumps(source, ensure_ascii=False), now, task_id))
        conn.execute('INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail) VALUES(?,?,?,?,?)',
                     (task_id, 'blocked', 'verified', now, json.dumps(detail, ensure_ascii=False)))
        conn.commit()
        return {'task_id': task_id, 'state': 'verified', 'submission_state': 'verified_by_readback',
                'target_version': row['target_version'], **detail}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_prewrite_source_collision(task_id, proof_path, *, db_path=None):
    """Reset stale pre-save preparation after live detail sources were deduplicated."""
    path = Path(proof_path).resolve()
    proof = batch.read_json(path)
    conn = batch._db(db_path)
    fail = lambda: DoudianError('collision_reset_unproven',
        '写前去重重置证据不完整或已有保存痕迹，拒绝清空准备记录。')
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        now = time.time()
        if (row is None or row['state'] != 'blocked'
                or row['last_error'] != 'writer_detail_source_collision'
                or row['submission_state'] != 'not_attempted' or row['submission_attempts'] != 0
                or row['readback_hash'] or row['submission_intent_json'] or row['writer_preparation_json']
                or any((row[key] or 0) >= now for key in ('lease_until', 'execution_until'))
                or conn.execute('SELECT 1 FROM external_observations WHERE task_id=?', (task_id,)).fetchone()):
            raise fail()
        if (not isinstance(proof, dict) or proof.get('read_only') is not True
                or any(proof.get(k) != row[k] for k in ('product_id', 'shop', 'target_version'))
                or proof.get('prior_error') != row['last_error']
                or (proof.get('prior_baseline_sha256') or '') != (row['baseline_hash'] or '')
                or not str(proof.get('reviewer', '')).strip()
                or conn.execute('SELECT 1 FROM products WHERE shop=? AND product_id=? AND id!=?',
                                (row['shop'], row['product_id'], task_id)).fetchone()
                or batch._active_doudian_job_conflict(row['shop'], row['product_id'])):
            raise fail()
        miao, official = _load_dual_snapshots(
            proof, path.parent, row, now=now, max_age_seconds=7200, preflight=False, fail=fail)
        slot_cap = min(4, len(official['details']))
        active_detail_keys = [resource_key(u) for u in official['details'][:slot_cap]]
        if slot_cap < 1 or len(set(active_detail_keys)) != slot_cap:
            raise fail()
        source = json.loads(row['source'])
        source.update(source_title=miao['title'], name=miao['title'], stage='prepared',
                      status='1', statusName='下架')
        detail = {
            'kind': 'prewrite_collision_reset', 'proof_path': str(path),
            'proof_sha256': batch._digest(path), 'target_version': row['target_version'],
            'reviewer': proof['reviewer'], 'prior_error': row['last_error'],
            'prior_baseline_sha256': row['baseline_hash'],
            'prior_artifacts_hash': row['artifacts_hash'],
            'active_detail_slots': slot_cap,
        }
        conn.execute(
            "UPDATE products SET state='needs_agent',last_error=NULL,baseline_json=NULL,baseline_hash=NULL,"
            "artifacts_path=NULL,artifacts_hash=NULL,upload_map_json='[]',source=?,"
            "lease_owner=NULL,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?",
            (json.dumps(source, ensure_ascii=False), now, task_id))
        conn.execute('INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail) VALUES(?,?,?,?,?)',
                     (task_id, 'blocked', 'needs_agent', now, json.dumps(detail, ensure_ascii=False)))
        conn.commit()
        return {'task_id': task_id, 'state': 'needs_agent', 'target_version': row['target_version'], **detail}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
