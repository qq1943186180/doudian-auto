"""Audited return of historical, resolved work to the existing preparation row."""

import json
import time
from pathlib import Path

from . import batch
from .errors import DoudianError
from .official_skus import verify_miaoshou_skus
from .preflight import _validate_snapshot
from .visual_review import _bound_file
from .workflow import resource_key


def rebaseline_external(task_id, proof_path, *, db_path=None):
    """Keep version/history intact; never recover an unknown queue submission."""
    path = Path(proof_path).resolve()
    proof = batch.read_json(path)
    conn = batch._db(db_path)
    fail = lambda: DoudianError('external_rebaseline_unproven',
        '旧任务未核清或双端基线不完整，保持隔离，不重新保存。')
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        now = time.time()
        if (row is None or row['state'] != 'blocked'
                or row['last_error'] != 'external_work_requires_rebaseline'
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
        snapshots = []
        for key in ('miaoshou', 'doudian'):
            file = _bound_file(proof.get(key), path.parent, 'external_rebaseline_unproven')
            if not 0 <= now - file.stat().st_mtime <= 7200:
                raise fail()
            snapshots.append(batch.read_json(file))
        miao, official = snapshots
        _validate_snapshot(official, dict(row))
        verify_miaoshou_skus(miao, official.get('sku_evidence'))
        if (miao.get('product_id') != row['product_id'] or miao.get('shop') != row['shop']
                or miao.get('protected_complete') is not True
                or miao.get('protected', {}).get('status') != 1
                or miao['title'] != official['title']
                or any([resource_key(x) for x in miao[k]] !=
                       [resource_key(x) for x in official[k]] for k in ('mains', 'details'))):
            raise fail()
        observations = conn.execute('SELECT * FROM external_observations WHERE task_id=?', (task_id,)).fetchall()
        resolutions = proof.get('resolved_observations', [])
        if not observations or len(resolutions) != len(observations):
            raise fail()
        remaining = {x['evidence_sha256'] for x in observations}
        for item in resolutions:
            file = _bound_file(item.get('evidence'), path.parent, 'external_rebaseline_unproven')
            digest = batch._digest(file)
            if digest not in remaining or not any(Path(x['evidence_path']).resolve() == file for x in observations):
                raise fail()
            history = batch.read_json(file)
            status = history.get('submission_status', history.get('submission_state'))
            stage = history.get('stage', history.get('phase'))
            resolved = ((status == 'not_attempted' and item.get('resolution') == 'no_save_attempted')
                        or (stage == 'verified' and status == 'accepted'
                            and item.get('resolution') == 'prior_revision_confirmed'))
            if (str(history.get('product_id', history.get('productId'))) != row['product_id']
                    or not resolved or not str(item.get('reason', '')).strip()):
                raise fail()
            remaining.remove(digest)
        if remaining:
            raise fail()
        source = json.loads(row['source'])
        source.update(source_title=miao['title'], name=miao['title'], stage='prepared',
                      status='1', statusName='下架')
        detail = {'kind': 'external_rebaseline', 'proof_path': str(path),
                  'proof_sha256': batch._digest(path), 'target_version': row['target_version'],
                  'reviewer': proof['reviewer'], 'resolved_observation_sha256': sorted(
                      x['evidence_sha256'] for x in observations)}
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
