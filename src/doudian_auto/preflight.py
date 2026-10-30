"""Read-only official-page eligibility checks before spending time on new assets.

A successful result is an observation, not a queue claim or permission to save.
The caller must still claim the same immutable target version before preparing it.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import batch
from .bridge import Bridge
from .editor import Editor
from .errors import DoudianError
from .jobs import HOST, Lock, write_json
from .official_skus import compare_official_skus
from .workflow import compare_protected


_COLUMNS = ('id', 'batch_id', 'shop', 'product_id', 'target_version', 'state',
            'submission_state', 'submission_attempts', 'lease_owner', 'lease_until',
            'execution_owner', 'execution_until', 'artifacts_path', 'artifacts_hash',
            'baseline_hash', 'upload_map_json', 'source')
_IDENTITY = ('id', 'batch_id', 'shop', 'product_id', 'target_version')
_SECRET = re.compile(r'cookie|authorization|password|secret|token|csrf|xsrf|session[_-]?id', re.I)
_SNAPSHOT_FIELDS = (
    'url', 'product_id', 'shop', 'shop_confirmed', 'success', 'draft_loaded', 'rejected',
    'rejection_count', 'rejection_reasons', 'title', 'mains', 'details', 'detail_status',
    'detail_source', 'detail_reason', 'detail_declared', 'detail_cards', 'detail_slots',
    'main_delete_count', 'detail_delete_count', 'canvas_count', 'protected',
    'required_attributes', 'sku_evidence', 'sku_coverage', 'coverage', 'errors',
)


def _safe_text(value):
    def safe_url(match):
        try:
            url = urlsplit(match[0])
            query = [(key, '[redacted]' if _SECRET.search(key) else item)
                     for key, item in parse_qsl(url.query, keep_blank_values=True)]
            return urlunsplit((url.scheme, url.netloc.rsplit('@', 1)[-1], url.path,
                               urlencode(query), ''))
        except ValueError:
            return '[invalid URL]'

    value = re.sub(r'https?://[^\s\"<>]+', safe_url, str(value))
    value = re.sub(r'\bBearer\s+[^\s\"\',;]+', 'Bearer [redacted]', value, flags=re.I)
    return re.sub(
        r'([\"\']?(?:[\w-]*(?:token|password|secret|cookie|authorization|csrf|xsrf)[\w-]*|session[_-]?id)'
        r'[\"\']?\s*[:=]\s*)(?:[\"\'][^\"\']*[\"\']|[^\s;,]+)',
        r'\1[redacted]', value, flags=re.I)


def _safe_value(value):
    if isinstance(value, dict):
        password_field = (value.get('type') == 'password' or
                          bool(_SECRET.search(str(value.get('name', '')))))
        return {key: '[redacted]' if _SECRET.search(str(key)) or
                (password_field and key in ('value', 'values')) else _safe_value(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or type(value) in (bool, int, float):
        return value
    return '[unsupported value]'


def _open_queue(db_path):
    path = Path(db_path or batch.DB_PATH).resolve()
    if not path.is_file():
        raise DoudianError('preflight_queue_missing', '只读预检需要已存在的商品队列。')
    try:
        conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15,
                               isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(products)')}
        if not set(_COLUMNS).issubset(columns):
            raise DoudianError('preflight_queue_schema', '商品队列缺少身份或状态字段；只读预检不会迁移队列。')
        return conn
    except (sqlite3.Error, DoudianError) as exc:
        if 'conn' in locals():
            conn.close()
        if isinstance(exc, DoudianError):
            raise
        raise DoudianError('preflight_queue_unreadable', '商品队列无法只读打开。') from exc


def _select_rows(conn, ids, batch_id):
    selected = []
    for pid in ids:
        where, args = 'product_id=?', [pid]
        if batch_id is not None:
            where += ' AND batch_id=?'
            args.append(batch_id)
        rows = conn.execute(f'SELECT {",".join(_COLUMNS)} FROM products WHERE {where}', args).fetchall()
        if not rows:
            raise DoudianError('unknown_product', f'商品 {pid} 不在指定的现有队列中。')
        if len(rows) != 1:
            raise DoudianError('ambiguous_product', f'商品 {pid} 存在多条队列记录，请明确 batch_id。')
        selected.append(dict(rows[0]))
    return selected


def _current_row(conn, original):
    row = conn.execute(f'SELECT {",".join(_COLUMNS)} FROM products WHERE id=?',
                       (original['id'],)).fetchone()
    if row is None or any(row[key] != original[key] for key in _IDENTITY):
        raise DoudianError('queue_identity_changed', '预检期间队列商品、店铺或目标版本改变，请重新预检。')
    if (not isinstance(row['shop'], str) or not row['shop'].strip() or
            not isinstance(row['target_version'], str) or not row['target_version'].strip()):
        raise DoudianError('queue_identity_incomplete', '现有队列缺少明确店铺或目标版本。')
    return dict(row)


def _skip_reason(conn, row):
    siblings = [dict(item) for item in conn.execute(
        'SELECT state,submission_state FROM products WHERE shop=? AND product_id=? AND id!=?',
        (row['shop'], row['product_id'], row['id']))]
    related = [row, *siblings]
    if any(item['state'] == 'verified' or item['submission_state'] == 'verified_by_readback'
           for item in related):
        return 'already_verified', '该商品已有核验完成的版本，不作为新素材候选。'
    if any(item['submission_state'] == 'unknown' or item['state'] == 'submitting' for item in related):
        return 'submission_unknown', '该商品存在结果未知的保存，只能另行只读核查。'
    if siblings:
        return 'product_queue_conflict', '该商品另有队列版本，先核对现有任务。'
    if row['submission_state'] != 'not_attempted' or row['submission_attempts'] != 0:
        return 'prior_submission', '该商品已有保存尝试，不作为新的素材生成任务。'
    if row['state'] != 'needs_agent':
        return 'queue_state_ineligible', f'队列状态为 {row["state"]}，不作为新素材候选。'
    now = time.time()
    for kind in ('lease', 'execution'):
        until = row[f'{kind}_until']
        if until is not None and (not isinstance(until, (int, float)) or until >= now):
            return 'product_in_use', '该商品仍有领取或执行占用，不作为新素材候选。'
    if row['artifacts_path'] or row['artifacts_hash'] or row['baseline_hash']:
        return 'existing_work', '该商品已有素材或编辑基线，需核对当前任务后续办。'
    try:
        if json.loads(row['upload_map_json'] or '[]') != []:
            return 'existing_work', '该商品已有图片上传记录，需核对当前任务后续办。'
        source = json.loads(row['source'])
        if not isinstance(source, dict):
            raise ValueError('source is not an object')
    except (TypeError, ValueError):
        return 'queue_source_unreadable', '队列原始记录或上传记录无法完整读取。'
    if batch._source_has_prior_work(source):
        return 'existing_work', '原始记录显示旧编辑或保存尚未核清，不作为新素材候选。'
    conflict = batch._active_doudian_job_conflict(row['shop'], row['product_id'])
    if conflict:
        return 'active_official_job', conflict
    return None


def _existing_ego_space(bridge, expected=None):
    """Refuse the runtime's create/reset fallback before any page operation."""
    try:
        state = json.loads((bridge.session_dir / 'state.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError) as exc:
        raise DoudianError('ego_session_missing', '指定 session 没有可续用的TaskSpace；未创建替代会话。') from exc
    if not isinstance(state, dict) or type(state.get('spaceId')) is not int or state['spaceId'] <= 0:
        raise DoudianError('ego_session_missing', '指定 session 未绑定现有TaskSpace；未创建替代会话。')
    if state.get('finished'):
        raise DoudianError('ego_session_finished', '指定TaskSpace已结束；只读预检不会重建。')
    if expected is not None and state['spaceId'] != expected:
        raise DoudianError('ego_session_changed', '指定 session 的TaskSpace改变，已停止本件读取。')
    return state['spaceId']


def _validate_snapshot(snapshot, identity):
    if (not isinstance(snapshot, dict) or snapshot.get('product_id') != identity['product_id'] or
            snapshot.get('shop_confirmed') is not True or
            snapshot.get('shop', identity['shop']) != identity['shop']):
        raise DoudianError('wrong_identity', '官方读回的商品或店铺与现有队列不匹配。')
    if any(type(snapshot.get(key)) is not bool for key in ('draft_loaded', 'rejected')):
        raise DoudianError('official_business_state_unobserved', '未完整读取官方草稿和驳回状态。')
    if snapshot['draft_loaded'] or snapshot['rejected']:
        raise DoudianError('doudian_draft_or_rejected', '官方页面存在草稿或驳回，不能作为新素材候选。')
    evidence = snapshot.get('sku_evidence')
    compare_official_skus(evidence, evidence)  # Missing full SKU evidence never means "equal".
    if evidence.get('product_id') != identity['product_id']:
        raise DoudianError('wrong_identity', '官方完整SKU证据属于其他商品。')
    compare_protected(snapshot, snapshot)
    if (not isinstance(snapshot.get('title'), str) or not snapshot['title'].strip() or
            any(not isinstance(snapshot.get(key), list) or
                any(not isinstance(value, str) or not value.strip() for value in snapshot[key])
                for key in ('mains', 'details')) or
            snapshot.get('detail_status') not in ('ready', 'empty') or
            (snapshot['detail_status'] == 'empty') != (not snapshot['details'])):
        raise DoudianError('official_content_incomplete', '官方标题、主图或详情数据未完整读取。')
    main_count, detail_count = len(snapshot['mains']), len(snapshot['details'])
    if main_count != 5 or detail_count < 4 or snapshot['detail_status'] != 'ready':
        raise DoudianError('writer_image_slots_incomplete',
            f'当前写入器需要正好5张主图和至少4张已就绪详情图；官方实读主图{main_count}张、'
            f'详情{detail_count}张（状态={snapshot["detail_status"]}），不作为新素材候选。')
    batch.require_official_attributes(snapshot)


def preflight_products(endpoint, *, product_ids, batch_id=None, limit=20,
                       session=None, db_path=None, report_dir=None):
    """Inspect 1–20 existing queue rows without claiming or changing any product.

    Explicit IDs are required, validated together, and processed in caller order.
    Every requested ID (including IDs beyond ``limit``) must resolve to one queue
    row. The optional batch ID disambiguates products with multiple revisions.
    Only unclaimed ``needs_agent``/``not_attempted`` rows with exactly five main
    images and at least four ready detail images can become candidates.
    Per-product failures are returned and do not stop the next product. A browser
    request for human action stops the round and leaves remaining IDs unprocessed.
    An Ego session must already have a live, locally bound TaskSpace. No task is
    finished and no page is closed. Optional reports contain redacted snapshots.
    """
    started = time.monotonic()
    if type(limit) is not int or not 1 <= limit <= 20:
        raise DoudianError('invalid_limit', '只读预检单次限制为1至20件整数。')
    if not isinstance(product_ids, (list, tuple)) or not product_ids:
        raise DoudianError('invalid_product_ids', '只读预检需要明确的非空商品ID列表。')
    ids = [str(pid) for pid in product_ids]
    if any(not re.fullmatch(r'\d{16,22}', pid, re.ASCII) for pid in ids):
        raise DoudianError('invalid_product_ids', '商品ID必须为16至22位数字。')
    if len(ids) != len(set(ids)):
        raise DoudianError('duplicate_product', '只读预检商品ID不能重复。')
    if not isinstance(session, str) or not session.strip():
        raise DoudianError('invalid_session', '只读预检必须明确指定要沿用的浏览器 session。')
    if batch_id is not None and (not isinstance(batch_id, str) or not batch_id.strip()):
        raise DoudianError('invalid_batch_id', 'batch_id 必须为已有批次的非空标识。')

    conn = _open_queue(db_path)
    try:
        rows = _select_rows(conn, ids, batch_id)[:limit]
        report = None
        result = {'schema_version': 1, 'read_only': True, 'session': session, 'waiting_human': False,
                  'batch_id': batch_id, 'requested_product_ids': ids,
                  'unprocessed_product_ids': ids[limit:], 'products': []}
        bridge, editor, space_id = None, None, None
        with Lock(batch.DATA_ROOT / 'browser.lock'):
            if report_dir is not None:
                report = Path(report_dir).resolve() / ('preflight-' +
                    time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
                report.mkdir(parents=True, exist_ok=False)
                result['report_path'] = str(report / 'summary.json')
            for index, original in enumerate(rows):
                item_started = time.monotonic()
                item = {'task_id': original['id'], **{key: original[key] for key in _IDENTITY[1:]},
                        'queue_state': original['state'], 'submission_state': original['submission_state'],
                        'read_only': True, 'eligible': False, 'state': 'blocked', 'waiting_human': False,
                        'reason': None, 'message': '', 'missing_fields': [], 'read_elapsed_seconds': 0.0,
                        'evidence': {'read_only': True, 'snapshot_read': False}}
                try:
                    current = _current_row(conn, original)
                    item['queue_state'], item['submission_state'] = current['state'], current['submission_state']
                    skip = _skip_reason(conn, current)
                    if skip:
                        item.update(state='skipped', reason=skip[0], message=skip[1])
                        continue
                    if bridge is None:
                        bridge = Bridge(endpoint, session=session, timeout=25)
                        editor = Editor(bridge)
                    if endpoint == 'ego':
                        space_id = _existing_ego_space(bridge, space_id)
                        item['evidence']['space_id'] = space_id
                    identity = {'product_id': current['product_id'], 'shop': current['shop'],
                                'edit_url': f'https://{HOST}/ffa/g/create?product_id={current["product_id"]}'}
                    read_started = time.monotonic()
                    try:
                        snapshot = batch._stable_doudian_snapshot(editor, identity)
                    finally:
                        item['read_elapsed_seconds'] = round(time.monotonic() - read_started, 6)
                    if not isinstance(snapshot, dict):
                        raise DoudianError('invalid_official_snapshot', '官方页面没有返回完整商品快照。')
                    safe = _safe_value({key: snapshot[key] for key in _SNAPSHOT_FIELDS if key in snapshot})
                    encoded = json.dumps(safe, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
                    attrs = safe.get('required_attributes')
                    missing = attrs.get('missing') if isinstance(attrs, dict) else None
                    item['missing_fields'] = missing if isinstance(missing, list) else []
                    sku = safe.get('sku_evidence')
                    sku = sku if isinstance(sku, dict) else {}
                    item['evidence'].update(snapshot_read=True, source='official_editor_ui', fresh=True,
                        observed_at=time.time(), product_id=safe.get('product_id'),
                        shop_confirmed=safe.get('shop_confirmed'), draft_loaded=safe.get('draft_loaded'),
                        rejected=safe.get('rejected'), required_attributes=attrs,
                        main_count=len(safe['mains']) if isinstance(safe.get('mains'), list) else None,
                        detail_count=len(safe['details']) if isinstance(safe.get('details'), list) else None,
                        sku_complete=sku.get('complete') is True, sku_count=sku.get('count'),
                        snapshot_sha256=hashlib.sha256(encoded).hexdigest())
                    if report is not None:
                        path = report / f'{original["id"]}-{original["product_id"]}-official.json'
                        write_json(path, {'read_only': True, 'task_id': original['id'],
                            **{key: original[key] for key in _IDENTITY[1:]}, 'session': session,
                            'observed_at': item['evidence']['observed_at'], 'snapshot': safe})
                        item['evidence']['snapshot_path'] = str(path)
                    _validate_snapshot(snapshot, identity)
                    current = _current_row(conn, original)
                    skip = _skip_reason(conn, current)
                    item['evidence']['queue_rechecked'] = True
                    if skip:
                        item.update(state='skipped', reason=skip[0], message=skip[1],
                                    queue_state=current['state'], submission_state=current['submission_state'])
                        continue
                    if endpoint == 'ego':
                        _existing_ego_space(bridge, space_id)
                    item.update(eligible=True, state='eligible', message='新鲜官方读取通过，可领取同一目标版本准备素材。')
                except Exception as exc:
                    item.update(reason=getattr(exc, 'code', 'preflight_read_failed'),
                                message=_safe_text(str(exc))[:2000] or type(exc).__name__,
                                waiting_human=bool(getattr(exc, 'waiting', False)))
                    if item['waiting_human']:
                        result['waiting_human'] = True
                        result['unprocessed_product_ids'] = ids[index + 1:]
                        break  # The finally block persists this result before leaving the browser lock.
                finally:
                    item['elapsed_seconds'] = round(time.monotonic() - item_started, 6)
                    result['products'].append(_safe_value(item))
                    result['counts'] = {state: sum(p['state'] == state for p in result['products'])
                                        for state in ('eligible', 'blocked', 'skipped')}
                    result['candidate_product_ids'] = [p['product_id'] for p in result['products'] if p['eligible']]
                    result['elapsed_seconds'] = round(time.monotonic() - started, 6)
                    if report is not None:
                        write_json(report / 'summary.json', result)
        return result
    finally:
        conn.close()
