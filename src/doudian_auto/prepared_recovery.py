"""Audited recovery of an immutable prepared task after repeated read-only checks."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

from . import batch
from .errors import DoudianError
from .official_skus import verify_miaoshou_skus
from .preflight import _validate_snapshot
from .visual_review import _bound_file
from .workflow import compare_protected


_ERROR_PREFIX = 'official_repeat_snapshot_unstable:'
_MAX_AGE_SECONDS = 30 * 60
_HASH_RE = re.compile(r'[0-9a-f]{64}')
_REQUIRED_MIAOSHOU_PROTECTED = {
    'root.categoryId', 'root.brandName', 'specPrices', 'freightId', 'status',
    'draftStatus', 'specPics', 'mainImageThreeToFour', 'whiteBackGroundPicUrl',
    'afterSaleService', 'checkStatus',
}


def _fail(message='准备任务的双端只读恢复证明不完整或不一致。'):
    return DoudianError('prepared_recovery_unproven', message)


def _json_file(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise _fail('恢复证明或观测文件无法读取。') from exc


def _digest(path):
    try:
        return batch._digest(path)
    except OSError as exc:
        raise _fail('恢复证明引用的文件无法读取。') from exc


def _fresh_timestamp(value, path, now):
    if type(value) not in (int, float):
        raise _fail('每份只读观测都必须绑定有效的 Unix 时间。')
    try:
        if not math.isfinite(value):
            raise _fail('每份只读观测都必须绑定有效的 Unix 时间。')
    except (OverflowError, ValueError) as exc:
        raise _fail('每份只读观测都必须绑定有效的 Unix 时间。') from exc
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        raise _fail('只读观测文件已不存在。') from exc
    if not (0 <= now - value <= _MAX_AGE_SECONDS and
            0 <= now - mtime <= _MAX_AGE_SECONDS):
        raise _fail('只读观测的时间或文件修改时间超过30分钟。')


def _image_keys(values):
    if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
        raise _fail('双端图片列表缺失或格式不完整。')
    try:
        return batch._image_keys(values)
    except (TypeError, ValueError, AttributeError) as exc:
        raise _fail('双端图片地址无法核对。') from exc


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _validate_miaoshou(snapshot, official, row):
    if (not isinstance(snapshot, dict) or
            snapshot.get('product_id') != row['product_id'] or
            snapshot.get('shop') != row['shop'] or
            snapshot.get('protected_complete') is not True or
            not isinstance(snapshot.get('protected'), dict)):
        raise _fail('妙手观测没有绑定当前商品、店铺和完整保护字段。')
    protected = snapshot['protected']
    if not _REQUIRED_MIAOSHOU_PROTECTED.issubset(protected):
        raise _fail('妙手保护资料缺项，不能作为恢复证明。')
    if type(protected.get('status')) is not int or protected['status'] != 1:
        raise _fail('妙手商品状态不是已下架状态1。')
    if type(protected.get('checkStatus')) not in (int, str):
        raise _fail('妙手审核状态没有原始可比值。')
    if not isinstance(snapshot.get('title'), str) or snapshot['title'] != official.get('title'):
        raise _fail('妙手标题与对应官方观测不一致。')
    for key in ('mains', 'details'):
        if _image_keys(snapshot.get(key)) != _image_keys(official.get(key)):
            raise _fail('妙手图片与对应官方观测的素材顺序不一致。')
    verify_miaoshou_skus(snapshot, official.get('sku_evidence'))


def _review_asset_history(conn, task_id):
    rows = conn.execute('SELECT decision,attempt FROM asset_reviews WHERE task_id=?',
                        (task_id,)).fetchall()
    if any(row['decision'] != 'pass' or type(row['attempt']) is not int or row['attempt'] > 2
           for row in rows):
        raise _fail('任务已有目视失败或超过两次的隔离记录。')


def _prior_proof(conn, task_id, proof_sha256):
    for event in conn.execute('SELECT detail FROM product_events WHERE task_id=?', (task_id,)):
        try:
            detail = json.loads(event['detail'] or '{}')
        except (TypeError, ValueError):
            continue
        if isinstance(detail, dict) and detail.get('proof_sha256') == proof_sha256:
            return True
    return False


def recover_prepared_after_reads(task_id, proof_path, *, db_path=None):
    """Return an untouched prepared version to ``ready`` after two recent read pairs.

    The proof file schema is ``{read_only, reviewer, product_id, shop,
    target_version, manifest_sha256, observations}``. ``observations`` must contain
    exactly two entries; each entry has ``observed_at`` plus ``miaoshou`` and
    ``doudian`` objects containing only ``path`` and ``sha256``. Paths may be
    absolute or relative to the proof file.
    """
    proof_file = Path(proof_path).resolve()
    conn = batch._db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise DoudianError('task_not_found', '批次商品不存在。')

        try:
            proof_bytes = proof_file.read_bytes()
            proof_sha256 = hashlib.sha256(proof_bytes).hexdigest()
            proof = json.loads(proof_bytes.decode('utf-8-sig'))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise _fail('恢复证明文件无法读取。') from exc

        now = time.time()
        try:
            upload_map = json.loads(row['upload_map_json'] or '[]')
        except (TypeError, ValueError):
            upload_map = None
        agent_lease_until = row['lease_until']
        execution_until = row['execution_until']
        attempts = row['submission_attempts']
        if ((row['state'] != 'blocked' or not isinstance(row['last_error'], str) or
             not row['last_error'].startswith(_ERROR_PREFIX)) or
                row['submission_state'] != 'not_attempted' or type(attempts) is not int or attempts != 0 or
                row['baseline_json'] not in (None, '') or row['baseline_hash'] not in (None, '') or
                upload_map != [] or row['submission_intent_json'] not in (None, '') or
                row['readback_json'] not in (None, '') or row['readback_hash'] not in (None, '') or
                row['writer_preparation_json'] not in (None, '') or
                not row['artifacts_path'] or not row['artifacts_hash'] or
                row['execution_owner'] is not None or row['execution_token'] is not None or
                (execution_until is not None and (type(execution_until) not in (int, float) or
                                                   not math.isfinite(execution_until) or
                                                   execution_until >= now)) or
                (agent_lease_until is not None and (type(agent_lease_until) not in (int, float) or
                                                    not math.isfinite(agent_lease_until) or
                                                    agent_lease_until >= now)) or
                (agent_lease_until is None and (row['lease_owner'] is not None or
                                                row['lease_token'] is not None))):
            raise _fail('任务存在未知写入、基线、准备记录或未过期租约，保持隔离。')

        if (not isinstance(proof, dict) or proof.get('read_only') is not True or
                not isinstance(proof.get('reviewer'), str) or not proof['reviewer'].strip() or
                proof.get('product_id') != row['product_id'] or proof.get('shop') != row['shop'] or
                proof.get('target_version') != row['target_version'] or
                not isinstance(proof.get('manifest_sha256'), str) or
                not _HASH_RE.fullmatch(proof['manifest_sha256']) or
                proof['manifest_sha256'] != row['artifacts_hash'] or
                not isinstance(proof.get('observations'), list) or len(proof['observations']) != 2):
            raise _fail('恢复证明未绑定当前商品、店铺、版本和不可变素材清单。')
        if _prior_proof(conn, task_id, proof_sha256):
            raise _fail('同一份恢复证明已经使用过。')
        if conn.execute('SELECT 1 FROM products WHERE shop=? AND product_id=? AND id!=? LIMIT 1',
                        (row['shop'], row['product_id'], task_id)).fetchone():
            raise _fail('同店同品存在其他队列版本，不能自动恢复。')
        if batch._active_doudian_job_conflict(row['shop'], row['product_id']):
            raise _fail('同店同品存在未结案的官方任务，不能自动恢复。')

        _review_asset_history(conn, task_id)
        artifact_path = Path(row['artifacts_path']).resolve()
        if not artifact_path.is_file() or _digest(artifact_path) != row['artifacts_hash']:
            raise DoudianError('artifact_manifest_changed', '已准备素材清单哈希变化，不能恢复。')
        artifact_data = _json_file(artifact_path)
        if (not isinstance(artifact_data, dict) or
                artifact_data.get('target_version') != row['target_version']):
            raise _fail('素材清单没有绑定当前不可变目标版本。')
        artifact_report = batch.validate_agent_artifacts(
            artifact_path, row['product_id'], expected_shop=row['shop'],
            require_visual_review=True, allow_failed_review=False)
        if not artifact_report['visual_review'] or not artifact_report['visual_review'].get('approved'):
            raise DoudianError('visual_review_failed', '素材的完整目视审核未通过。')
        if _digest(artifact_path) != row['artifacts_hash']:
            raise DoudianError('artifact_manifest_changed', '素材清单在验证期间发生变化。')

        observations = []
        paths_by_kind = {'miaoshou': [], 'doudian': []}
        evidence_files = []
        for item in proof['observations']:
            if not isinstance(item, dict) or set(item) != {'miaoshou', 'doudian', 'observed_at'}:
                raise _fail('每份观测必须包含妙手、抖店文件和 Unix 时间。')
            snapshots = {}
            for kind in ('miaoshou', 'doudian'):
                record = item[kind]
                if (not isinstance(record, dict) or set(record) != {'path', 'sha256'} or
                        not isinstance(record.get('path'), str) or not record['path'].strip()):
                    raise _fail('观测文件记录必须只包含 path 和 sha256。')
                file = _bound_file(record, proof_file.parent, 'prepared_recovery_unproven')
                paths_by_kind[kind].append(file)
                evidence_files.append((file, record['sha256'], item['observed_at']))
                snapshots[kind] = _json_file(file)
            _fresh_timestamp(item['observed_at'], paths_by_kind['miaoshou'][-1], now)
            _fresh_timestamp(item['observed_at'], paths_by_kind['doudian'][-1], now)
            if not isinstance(snapshots['doudian'], dict):
                raise _fail('官方观测不是完整商品对象。')
            _validate_snapshot(snapshots['doudian'], dict(row))
            _validate_miaoshou(snapshots['miaoshou'], snapshots['doudian'], row)
            observations.append(snapshots)

        all_paths = [*paths_by_kind['miaoshou'], *paths_by_kind['doudian']]
        if len({str(path).casefold() for path in all_paths}) != 4:
            raise _fail('两轮观测必须使用四份互不重复的证据文件。')

        first, second = observations
        compare_protected(first['doudian'], second['doudian'])
        for key in ('title', 'mains', 'details'):
            if key == 'title':
                same = first['doudian'].get(key) == second['doudian'].get(key)
            else:
                same = _image_keys(first['doudian'].get(key)) == _image_keys(second['doudian'].get(key))
            if not same:
                raise _fail('两份官方观测的标题或图片顺序不一致。')

        miao_first, miao_second = first['miaoshou'], second['miaoshou']
        if not batch._miaoshou_protected_matches(miao_first['protected'], miao_second['protected']):
            raise _fail('两份妙手观测的受保护字段不一致。')
        if (type(miao_first['protected']['checkStatus']) is not type(miao_second['protected']['checkStatus']) or
                miao_first['protected']['checkStatus'] != miao_second['protected']['checkStatus']):
            raise _fail('两份妙手观测的审核状态原值不一致。')
        for snapshot in (miao_first, miao_second):
            comparable = {key: value for key, value in snapshot.items()
                          if key not in ('mains', 'details', 'protected')}
            other = {key: value for key, value in miao_first.items()
                     if key not in ('mains', 'details', 'protected')}
            if _canonical(comparable) != _canonical(other):
                raise _fail('两份妙手观测的非图片商品字段不一致。')
        for key in ('mains', 'details'):
            if _image_keys(miao_first.get(key)) != _image_keys(miao_second.get(key)):
                raise _fail('两份妙手观测的图片或顺序不一致。')

        # Re-run the full validator and hash every file used by the proof before the
        # atomic state transition. No manifest, image, or historical evidence is rewritten.
        artifact_report_again = batch.validate_agent_artifacts(
            artifact_path, row['product_id'], expected_shop=row['shop'],
            require_visual_review=True, allow_failed_review=False)
        if (artifact_report_again['asset_set_sha256'] != artifact_report['asset_set_sha256'] or
                artifact_report_again['visual_review']['review_sha256'] !=
                artifact_report['visual_review']['review_sha256']):
            raise DoudianError('artifact_manifest_changed', '素材或目视审核在恢复期间发生变化。')
        if _digest(artifact_path) != row['artifacts_hash']:
            raise DoudianError('artifact_manifest_changed', '素材清单在恢复期间发生变化。')
        final_check_at = time.time()
        for file, expected_hash, observed_at in evidence_files:
            _fresh_timestamp(observed_at, file, final_check_at)
            if _digest(file) != expected_hash:
                raise _fail('只读观测文件在恢复期间发生变化。')
        if _digest(proof_file) != proof_sha256:
            raise _fail('恢复证明在读取期间发生变化。')

        now = time.time()
        if batch._active_doudian_job_conflict(row['shop'], row['product_id']):
            raise _fail('同店同品出现未结案的官方任务，不能自动恢复。')
        expired_agent_lease = row['lease_until'] is not None
        fields = 'lease_owner=NULL,lease_token=NULL,lease_until=NULL,' if expired_agent_lease else ''
        conn.execute(f'''UPDATE products SET state='ready',last_error=NULL,{fields}updated_at=?
                         WHERE id=? AND state='blocked' AND last_error=?
                           AND submission_state='not_attempted' AND submission_attempts=0
                           AND target_version=? AND artifacts_hash=?''',
                     (now, task_id, row['last_error'], row['target_version'], row['artifacts_hash']))
        if conn.execute('SELECT changes()').fetchone()[0] != 1:
            raise DoudianError('prepared_recovery_race', '任务状态在恢复期间发生变化。')
        detail = {
            'kind': 'prepared_after_reads', 'proof_sha256': proof_sha256,
            'artifact_sha256': row['artifacts_hash'], 'reviewer': proof['reviewer'],
            'target_version': row['target_version'],
        }
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,
                        elapsed_seconds,detail) VALUES(?,?,?,?,?,?)''',
                     (task_id, 'blocked', 'ready', now, max(0, now - row['updated_at']),
                      json.dumps(detail, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return {'task_id': task_id, 'state': 'ready', 'target_version': row['target_version'],
                'proof_sha256': proof_sha256, 'artifact_sha256': row['artifacts_hash'],
                'reviewer': proof['reviewer']}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
