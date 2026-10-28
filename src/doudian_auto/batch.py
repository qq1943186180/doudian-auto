"""Durable batch queue and agent hand-off for full listing revisions.

The queue stores only task metadata and local asset paths. It never stores browser
credentials or replays a site write request.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from .errors import DoudianError
from .jobs import DATA_ROOT, HOST, Lock, image_record, read_json, write_json
from .title import validate_title
from .workflow import (is_permanent_material_key, is_permanent_material_url,
                       is_temporary_upload_url, resource_key)

DB_PATH = DATA_ROOT / 'batch.sqlite3'
LEASE_SECONDS = 900
PREWRITE_RECOVERABLE_ERRORS = {
    'baseline_changed', 'miaoshou_tab_not_unique', 'miaoshou_slot_not_found',
    'miaoshou_slot_readback', 'miaoshou_timeout', 'miaoshou_read_timeout',
    'page_timeout', 'bridge_transport', 'bridge_error', 'bridge_action_failed',
}


def _db(path=None):
    db_path = Path(path or DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL REFERENCES batches(id),
            shop TEXT NOT NULL, product_id TEXT NOT NULL, source TEXT NOT NULL,
            target_version TEXT NOT NULL DEFAULT '',
            facts_json TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'needs_agent',
            lease_owner TEXT, lease_token TEXT, lease_until REAL,
            artifacts_path TEXT, artifacts_hash TEXT, submission_state TEXT NOT NULL DEFAULT 'not_attempted',
            execution_owner TEXT, execution_token TEXT, execution_until REAL,
            baseline_json TEXT, baseline_hash TEXT,
            upload_map_json TEXT NOT NULL DEFAULT '[]', submission_intent_json TEXT,
            submission_attempts INTEGER NOT NULL DEFAULT 0, readback_json TEXT, readback_hash TEXT,
            last_error TEXT, updated_at REAL NOT NULL,
            UNIQUE(batch_id, product_id)
        );
        CREATE INDEX IF NOT EXISTS products_claim ON products(state, lease_until, id);
        CREATE TABLE IF NOT EXISTS product_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES products(id),
            from_state TEXT, to_state TEXT NOT NULL, occurred_at REAL NOT NULL,
            elapsed_seconds REAL, detail TEXT
        );
    ''')
    # Existing local queues are durable user data. Add fields in place instead of
    # replacing the database, and derive stable legacy target versions once.
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(products)')}
    migrations = {
        'target_version': "TEXT NOT NULL DEFAULT ''",
        'execution_owner': 'TEXT', 'execution_token': 'TEXT', 'execution_until': 'REAL',
        'baseline_json': 'TEXT', 'baseline_hash': 'TEXT',
        'upload_map_json': "TEXT NOT NULL DEFAULT '[]'",
        'submission_intent_json': 'TEXT', 'submission_attempts': 'INTEGER NOT NULL DEFAULT 0',
        'readback_json': 'TEXT', 'readback_hash': 'TEXT',
    }
    for name, declaration in migrations.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE products ADD COLUMN {name} {declaration}')
    for row in conn.execute("SELECT id,batch_id,shop,product_id FROM products WHERE target_version='' ").fetchall():
        seed = f"{row['batch_id']}|{row['shop']}|{row['product_id']}".encode()
        version = 'legacy-' + hashlib.sha256(seed).hexdigest()[:20]
        conn.execute('UPDATE products SET target_version=? WHERE id=?', (version, row['id']))
    return conn


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _confirmed_upload_mapping(mapping):
    if not isinstance(mapping, dict) or mapping.get('confirmed') is not True:
        return False
    slot = mapping.get('slot')
    if not isinstance(slot, str) or not re.fullmatch(r'(?:mains:[1-5]|details:[1-4])', slot):
        return False
    source_hash = mapping.get('source_sha256')
    remote_key = mapping.get('remote_key')
    remote_url = mapping.get('remote_url')
    asset_state = mapping.get('asset_state')
    if not asset_state:
        # Compatibility with the pre-state-field records: temp URLs were observed in
        # actual successful Miao imports and are staged, not permanent material IDs.
        asset_state = 'permanent' if is_permanent_material_url(remote_url, expected_key=remote_key) else 'staged'
    common = (isinstance(source_hash, str) and
              bool(re.fullmatch(r'[0-9a-f]{64}', source_hash, re.I)))
    if asset_state == 'permanent':
        return common and is_permanent_material_key(remote_key) and is_permanent_material_url(
            remote_url, expected_key=remote_key)
    if asset_state == 'staged':
        return common and remote_key == remote_url and is_temporary_upload_url(remote_url)
    return False


def create_batch(input_path, *, shop=None, db_path=None):
    payload = read_json(Path(input_path))
    products = payload.get('products') if isinstance(payload, dict) else payload
    if not isinstance(products, list) or not products:
        raise DoudianError('invalid_batch_input', '商品清单必须是非空数组或含 products 数组的JSON。')
    batch_id = 'batch-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    now = time.time()
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT INTO batches(id,created_at,source) VALUES(?,?,?)',
                     (batch_id, now, str(Path(input_path).resolve())))
        seen = set()
        for product in products:
            if not isinstance(product, dict):
                raise DoudianError('invalid_batch_product', '每条商品记录都必须是JSON对象。')
            product_shop = str(product.get('shop') or shop or '').strip()
            pid = str(product.get('product_id') or product.get('productId') or '').strip()
            if not product_shop or not pid.isdigit() or not 16 <= len(pid) <= 22:
                raise DoudianError('invalid_batch_product', '每条记录都需要店铺名和16至22位字符串商品ID。')
            if pid in seen:
                raise DoudianError('duplicate_product', f'清单中商品ID重复：{pid}')
            seen.add(pid)
            conflict = None
            if conn.execute("SELECT 1 FROM products WHERE shop=? AND product_id=? AND state!='verified' LIMIT 1",
                            (product_shop, pid)).fetchone():
                conflict = f'店铺「{product_shop}」的商品 {pid} 已在另一个妙手批次中，需先核实或结案。'
            if Path(db_path or DB_PATH).resolve() == DB_PATH.resolve():
                conflict = conflict or _active_doudian_job_conflict(product_shop, pid)
            if product.get('submission_status') == 'unknown' or product.get('stage') in (
                    'editing', 'uploaded', 'submitting', 'submitted'):
                conflict = conflict or '导入记录显示存在未完成或结果未知的旧任务，先只读核查。'
            facts = {k: v for k, v in product.items() if k not in ('shop', 'product_id', 'productId')}
            if 'source_title' not in facts and product.get('name'):
                facts['source_title'] = product['name']
            target_version = 'v1-' + uuid.uuid4().hex
            conn.execute('''INSERT INTO products(batch_id,shop,product_id,source,target_version,
                            facts_json,state,last_error,updated_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                         (batch_id, product_shop, pid, json.dumps({**product, 'shop': product_shop,
                                                                  'product_id': pid,
                                                                  'source_title': facts.get('source_title')}, ensure_ascii=False),
                          target_version, json.dumps(facts, ensure_ascii=False), 'blocked' if conflict else 'needs_agent',
                          conflict, now))
        conn.commit()
        blocked = conn.execute("SELECT COUNT(*) n FROM products WHERE batch_id=? AND state='blocked'",
                               (batch_id,)).fetchone()['n']
        return {'batch_id': batch_id, 'count': len(products), 'blocked': blocked,
                'state': 'needs_agent'}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _active_doudian_job_conflict(shop, product_id):
    jobs_root = DATA_ROOT / 'jobs'
    if not jobs_root.exists():
        return None
    active = {'editing', 'uploaded', 'submitting', 'submitted', 'rejected'}
    for manifest_path in jobs_root.glob('*/manifest.json'):
        try:
            manifest = read_json(manifest_path)
            if str(manifest.get('product_id')) != str(product_id):
                continue
            if manifest.get('shop') and manifest.get('shop') != shop:
                continue
            state_path = manifest_path.parent / 'state.json'
            state = read_json(state_path) if state_path.exists() else {}
        except (OSError, ValueError, TypeError):
            return f'商品 {product_id} 存在无法读取的抖店任务记录，先人工核对。'
        if state.get('stage') in active or state.get('submission_status') == 'unknown':
            return f'商品 {product_id} 有未结案的抖店任务，需只读核查后再编辑。'
    return None


def claim_next(owner, *, batch_id=None, product_id=None, db_path=None, lease_seconds=LEASE_SECONDS):
    owner = str(owner).strip()
    if not owner:
        raise DoudianError('invalid_agent', 'agent 名不能为空。')
    conn = _db(db_path)
    now = time.time()
    try:
        conn.execute('BEGIN IMMEDIATE')
        active = conn.execute("SELECT COUNT(DISTINCT lease_owner) n FROM products "
                              "WHERE state='agent_claimed' AND lease_until>=?", (now,)).fetchone()['n']
        already_claimed = conn.execute("SELECT 1 FROM products WHERE state='agent_claimed' "
                                       "AND lease_owner=? AND lease_until>=? LIMIT 1",
                                       (owner, now)).fetchone()
        if active >= 3 or already_claimed:
            conn.commit()
            return None
        args = [now]
        where = "(state='needs_agent' OR (state='agent_claimed' AND lease_until < ?))"
        if batch_id:
            where += ' AND batch_id=?'
            args.append(batch_id)
        if product_id:
            where += ' AND product_id=?'
            args.append(str(product_id))
        row = conn.execute(f'SELECT * FROM products WHERE {where} ORDER BY id LIMIT 1', args).fetchone()
        if row is None:
            conn.commit()
            return None
        token = uuid.uuid4().hex
        conn.execute('''UPDATE products SET state='agent_claimed', lease_owner=?, lease_token=?,
                        lease_until=?, updated_at=? WHERE id=?''',
                     (owner, token, now + lease_seconds, now, row['id']))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail)
                        VALUES(?,?,?,?,?)''', (row['id'], row['state'], 'agent_claimed', now, owner))
        conn.commit()
        result = dict(row)
        result.update(state='agent_claimed', lease_owner=owner, lease_token=token,
                      lease_until=now + lease_seconds, facts=json.loads(row['source']))
        result.pop('facts_json', None)
        result['rag_context'] = search_knowledge(result['facts'])
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def search_knowledge(facts, *, timeout=5):
    """Cheap local course search; unavailable RAG never blocks preparation."""
    title = str(facts.get('source_title') or facts.get('title') or '')
    attrs = facts.get('attributes') or facts.get('confirmed') or {}
    query = ' '.join([title, json.dumps(attrs, ensure_ascii=False) if attrs else '']).strip()
    if not query:
        return {'available': False, 'items': [], 'reason': 'no_product_facts'}
    url = 'http://127.0.0.1:5001/api/rag/search?' + urlencode(
        {'q': query, 'limit': 5, 'platform': '抖店'})
    error = None
    for _ in range(2):
        try:
            with urlopen(url, timeout=timeout) as response:
                data = json.load(response)
            items = data.get('results', data.get('items', [])) if isinstance(data, dict) else []
            return {'available': True, 'items': items if isinstance(items, list) else []}
        except (OSError, ValueError) as exc:
            error = type(exc).__name__
    return {'available': False, 'items': [], 'reason': error or 'rag_unavailable'}


def validate_agent_artifacts(path, expected_product_id):
    path = Path(path).resolve()
    data = read_json(path)
    if not isinstance(data, dict) or str(data.get('product_id', '')) != str(expected_product_id):
        raise DoudianError('artifact_product_mismatch', '素材清单商品ID与领取任务不匹配。')
    title = str(data.get('title', '')).strip()
    _, errors = validate_title(title)
    if errors:
        raise DoudianError('invalid_title', '；'.join(errors))
    mains, details = data.get('mains'), data.get('details')
    if not isinstance(mains, list) or len(mains) != 5:
        raise DoudianError('invalid_mains', '必须提供按顺序排列的5张方主图。')
    if not isinstance(details, list) or len(details) != 4:
        raise DoudianError('invalid_details', '目标版本必须恰好提供4张新详情图；其余线上详情图由妙手逐槽保留。')
    records = []
    paths = set()
    for is_main, group in ((True, mains), (False, details)):
        for slot, raw in enumerate(group, 1):
            p = Path(raw).resolve()
            if p in paths or not p.is_file():
                raise DoudianError('asset_missing_or_duplicate', f'图片不存在或重复：{p}')
            paths.add(p)
            rec = image_record(p, is_main)
            if not is_main and not 620 <= rec['width'] <= 1290:
                raise DoudianError('image_dimensions', f'{p.name} 详情图宽度必须620至1290像素。')
            records.append({'kind': 'main' if is_main else 'detail', 'slot': slot,
                            'path': str(p), 'sha256': rec['sha256'],
                            'width': rec['width'], 'height': rec['height']})
    if len({item['sha256'] for item in records}) != len(records):
        raise DoudianError('duplicate_assets', '图片内容重复，已拒绝进入上传队列。')
    return {'product_id': str(expected_product_id), 'title': title, 'assets': records,
            'asset_set_sha256': hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()}


def complete_agent_task(task_id, owner, token, artifact_path, *, db_path=None):
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise DoudianError('task_not_found', 'agent 任务不存在。')
        if (row['state'] != 'agent_claimed' or row['lease_owner'] != owner or
                row['lease_token'] != token or row['lease_until'] < time.time()):
            raise DoudianError('stale_agent_lease', 'agent 领取已过期或被新任务替代，素材未接收。')
        artifact = read_json(Path(artifact_path))
        artifact_version = str(artifact.get('target_version') or '').strip()
        if artifact_version != row['target_version']:
            raise DoudianError('target_version_mismatch', '素材清单必须绑定 agent 领取时返回的目标版本。')
        manifest = validate_agent_artifacts(artifact_path, row['product_id'])
        now = time.time()
        conn.execute('''UPDATE products SET state='ready', artifacts_path=?, artifacts_hash=?,
                        lease_owner=NULL, lease_token=NULL, lease_until=NULL, last_error=NULL,
                        updated_at=? WHERE id=?''',
                     (str(Path(artifact_path).resolve()), _digest(artifact_path), now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, 'agent_claimed', 'ready', now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps({'artifacts_sha256': _digest(artifact_path)})))
        conn.commit()
        return {'task_id': task_id, 'state': 'ready', 'target_version': row['target_version'],
                'title': manifest['title'],
                'asset_count': len(manifest['assets']), 'asset_set_sha256': manifest['asset_set_sha256']}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def renew_agent_task(task_id, owner, token, *, db_path=None, lease_seconds=LEASE_SECONDS):
    if not 60 <= lease_seconds <= 7200:
        raise DoudianError('invalid_lease', '租约必须为60至7200秒。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        now = time.time()
        cursor = conn.execute('''UPDATE products SET lease_until=?,updated_at=?
                                 WHERE id=? AND state='agent_claimed' AND lease_owner=?
                                 AND lease_token=? AND lease_until>=?''',
                              (now + lease_seconds, now, task_id, owner, token, now))
        if cursor.rowcount != 1:
            raise DoudianError('stale_agent_lease', '领取已过期或属于另一个 agent，无法续租。')
        conn.commit()
        return {'task_id': task_id, 'lease_until': now + lease_seconds}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def batch_status(batch_id=None, *, db_path=None):
    conn = _db(db_path)
    try:
        where, args = ('', [])
        if batch_id:
            where, args = ('WHERE batch_id=?', [batch_id])
        counts = {row['state']: row['n'] for row in conn.execute(
            f'SELECT state,COUNT(*) n FROM products {where} GROUP BY state', args)}
        rows = [dict(r) for r in conn.execute(
            f'''SELECT id,batch_id,shop,product_id,target_version,state,submission_state,
                       submission_attempts,last_error,updated_at
                FROM products {where} ORDER BY id''', args)]
        elapsed = conn.execute(f'''SELECT to_state,COUNT(*) samples,AVG(elapsed_seconds) avg_seconds
                                   FROM product_events e JOIN products p ON p.id=e.task_id
                                   {where} AND elapsed_seconds IS NOT NULL GROUP BY to_state'''
                               if where else '''SELECT to_state,COUNT(*) samples,AVG(elapsed_seconds) avg_seconds
                                                FROM product_events WHERE elapsed_seconds IS NOT NULL GROUP BY to_state''',
                               args).fetchall()
        return {'counts': counts, 'products': rows,
                'phase_timing': [dict(r) for r in elapsed]}
    finally:
        conn.close()


def load_ready_artifacts(task_id, *, db_path=None):
    """Revalidate immutable output immediately before handing it to the page writer."""
    conn = _db(db_path)
    try:
        row = conn.execute('SELECT product_id,state,target_version,artifacts_path,artifacts_hash FROM products WHERE id=?',
                           (task_id,)).fetchone()
    finally:
        conn.close()
    if (row is None or row['state'] not in ('ready', 'editing', 'uploaded', 'submitted', 'blocked') or
            not row['artifacts_path']):
        raise DoudianError('artifacts_not_ready', '商品没有可续办的已校验素材。')
    path = Path(row['artifacts_path'])
    if not path.is_file() or _digest(path) != row['artifacts_hash']:
        raise DoudianError('artifact_manifest_changed', '素材清单在验收后发生变化，请重新提交校验。')
    raw = read_json(path)
    artifact_version = str(raw.get('target_version') or '').strip()
    target_version = row['target_version']
    if not artifact_version:
        raise DoudianError('target_version_mismatch', '素材清单缺少不可变目标版本。')
    if artifact_version and artifact_version != target_version:
        if (target_version.startswith('legacy-') and row['state'] == 'ready'):
            # One-time adoption for queues created before target_version was added.
            # Newer versions must bind their artifact to the version returned by agent next.
            conn = _db(db_path)
            try:
                conn.execute('BEGIN IMMEDIATE')
                current = conn.execute('SELECT state,target_version,baseline_hash FROM products WHERE id=?',
                                       (task_id,)).fetchone()
                if (current['state'] != 'ready' or current['baseline_hash'] is not None or
                        current['target_version'] != target_version or not artifact_version or
                        len(artifact_version) > 100):
                    raise DoudianError('target_version_conflict', '旧任务目标版本已开始执行或发生并发变更。')
                conn.execute('UPDATE products SET target_version=?,updated_at=? WHERE id=?',
                             (artifact_version, time.time(), task_id))
                conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,detail)
                                VALUES(?,?,?,?,?)''', (task_id, 'ready', 'ready', time.time(),
                                                       json.dumps({'adopted_legacy_target_version': artifact_version})))
                conn.commit()
                target_version = artifact_version
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            raise DoudianError('target_version_conflict', '素材清单不属于当前不可变目标版本。')
    manifest = validate_agent_artifacts(path, row['product_id'])
    return {'path': str(path), 'manifest': manifest, 'manifest_sha256': row['artifacts_hash'],
            'target_version': target_version}


def recover_legacy_target_version_mismatch(task_id, *, db_path=None):
    """Requeue only a legacy version mismatch proven to have stopped before editing."""
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        if (row is None or row['state'] != 'blocked' or row['last_error'] != 'target_version_mismatch' or
                row['target_version'] is None or not row['target_version'].startswith('legacy-') or
                row['submission_state'] != 'not_attempted' or int(row['submission_attempts'] or 0) != 0 or
                row['baseline_hash'] is not None or json.loads(row['upload_map_json'] or '[]') or
                row['submission_intent_json'] is not None or row['execution_token'] is not None or
                not row['artifacts_path']):
            conn.commit()
            return None
        path = Path(row['artifacts_path'])
        if not path.is_file() or _digest(path) != row['artifacts_hash']:
            raise DoudianError('artifact_manifest_changed', '素材清单哈希变化，旧版本任务不能自动重入。')
        raw = read_json(path)
        artifact_version = str(raw.get('target_version') or '').strip()
        if (not artifact_version or artifact_version == row['target_version'] or len(artifact_version) > 100 or
                str(raw.get('product_id')) != row['product_id']):
            raise DoudianError('target_version_conflict', '旧任务素材没有可安全采用的商品目标版本。')
        validate_agent_artifacts(path, row['product_id'])
        if _digest(path) != row['artifacts_hash']:
            raise DoudianError('artifact_manifest_changed', '素材清单在恢复时发生变化。')
        now = time.time()
        detail = {'recovered_before_write_version_binding': True,
                  'previous_target_version': row['target_version'],
                  'adopted_target_version': artifact_version,
                  'artifacts_sha256': row['artifacts_hash']}
        conn.execute('''UPDATE products SET state='ready',target_version=?,last_error=NULL,updated_at=?
                        WHERE id=? AND state='blocked' AND last_error='target_version_mismatch'
                          AND submission_state='not_attempted' AND submission_attempts=0
                          AND baseline_hash IS NULL AND execution_token IS NULL''',
                     (artifact_version, now, task_id))
        if conn.execute('SELECT changes()').fetchone()[0] != 1:
            raise DoudianError('execution_race', '任务在安全恢复过程中被其他操作变更。')
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, 'blocked', 'ready', now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps(detail, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return {'task_id': task_id, 'state': 'ready', 'target_version': artifact_version,
                'recovered_before_write': True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def recover_expired_claims(*, db_path=None):
    """Return only expired pre-write agent leases to the preparation queue."""
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        now = time.time()
        cursor = conn.execute('''UPDATE products SET state='needs_agent', lease_owner=NULL,
                                 lease_token=NULL, lease_until=NULL, updated_at=?
                                 WHERE state='agent_claimed' AND lease_until < ?''', (now, now))
        recovered = cursor.rowcount
        conn.commit()
        return {'recovered_agent_leases': recovered,
                'status': batch_status(db_path=db_path)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def quarantine_product(product_id, reason, *, db_path=None):
    reason = str(reason).strip()
    if not reason:
        raise DoudianError('reason_required', '隔离记录必须包含原因。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        now = time.time()
        rows = conn.execute("SELECT id,state,updated_at FROM products WHERE product_id=? AND state!='verified'",
                            (str(product_id),)).fetchall()
        for row in rows:
            conn.execute("UPDATE products SET state='blocked',last_error=?,updated_at=? WHERE id=?",
                         (reason, now, row['id']))
            conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                            VALUES(?,?,?,?,?,?)''', (row['id'], row['state'], 'blocked', now,
                                                     max(0, now-row['updated_at']), reason))
        conn.commit()
        return {'product_id': str(product_id), 'blocked_tasks': len(rows), 'reason': reason}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_execution(task_id, owner, *, db_path=None, lease_seconds=LEASE_SECONDS):
    """Atomically reserve the one browser writer and a ready product version."""
    owner = str(owner).strip()
    if not owner or not 60 <= lease_seconds <= 7200:
        raise DoudianError('invalid_execution_claim', '浏览器执行者名称或租约时长无效。')
    conn = _db(db_path)
    now = time.time()
    try:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('''SELECT * FROM products WHERE id=?''', (task_id,)).fetchone()
        if current is None:
            raise DoudianError('task_not_found', '批次商品不存在。')
        active = conn.execute('''SELECT id FROM products WHERE execution_until>=?
                                 AND execution_token IS NOT NULL LIMIT 1''', (now,)).fetchone()
        if active:
            conn.commit()
            return None
        writable = current['state'] in ('ready', 'editing', 'uploaded') and current['submission_state'] != 'unknown'
        prewrite_recovery = (current['state'] == 'blocked' and
                             current['submission_state'] == 'not_attempted' and
                             int(current['submission_attempts'] or 0) == 0 and
                             current['last_error'] in PREWRITE_RECOVERABLE_ERRORS and
                             bool(current['baseline_hash']) and bool(current['baseline_json']))
        readback_only = (current['state'] == 'submitted' or
                         (current['state'] == 'blocked' and current['submission_state'] in ('unknown', 'accepted')))
        if not writable and not readback_only and not prewrite_recovery:
            raise DoudianError('execution_not_ready', '仅可领取就绪任务、未提交中断任务或需只读核查任务。')
        token = uuid.uuid4().hex
        if writable:
            conn.execute('''UPDATE products SET execution_owner=?,execution_token=?,execution_until=?,updated_at=?
                            WHERE id=? AND state=? AND submission_state!='unknown' ''',
                         (owner, token, now + lease_seconds, now, task_id, current['state']))
        else:
            conn.execute('''UPDATE products SET execution_owner=?,execution_token=?,execution_until=?,updated_at=?
                            WHERE id=? AND state=? AND submission_state=? ''',
                         (owner, token, now + lease_seconds, now, task_id,
                          current['state'], current['submission_state']))
        if conn.execute('SELECT changes()').fetchone()[0] != 1:
            raise DoudianError('execution_race', '任务状态在领取期间发生变化，请刷新后重试。')
        conn.commit()
        result = dict(current)
        result.update(execution_owner=owner, execution_token=token,
                      execution_until=now + lease_seconds,
                      prewrite_recovery=prewrite_recovery)
        result['facts'] = json.loads(current['facts_json'])
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _execution_row(conn, task_id, owner, token, *, states=None):
    row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
    if row is None:
        raise DoudianError('task_not_found', '批次商品不存在。')
    if (row['execution_owner'] != owner or row['execution_token'] != token or
            not row['execution_until'] or row['execution_until'] < time.time()):
        raise DoudianError('stale_execution_lease', '浏览器执行租约已过期或属于其他进程。')
    if states and row['state'] not in states:
        raise DoudianError('invalid_transition', f"当前状态 {row['state']} 不允许此操作。")
    return row


def record_baseline(task_id, owner, token, baseline, *, db_path=None):
    """Persist a complete, target-bound read before changing any page field."""
    if not isinstance(baseline, dict):
        raise DoudianError('baseline_invalid', '妙手基线必须是结构化读取结果。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'ready'})
        expected_id = row['product_id']
        if (str(baseline.get('product_id')) != expected_id or baseline.get('shop') != row['shop'] or
                baseline.get('protected_complete') is not True or not baseline.get('protected') or
                len(baseline.get('mains') or []) != 5 or len(baseline.get('details') or []) < 4):
            raise DoudianError('baseline_incomplete', '店铺、商品ID、保护字段或图片基线未完整读回。')
        payload = json.dumps(baseline, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        now = time.time()
        conn.execute('''UPDATE products SET baseline_json=?,baseline_hash=?,state='editing',updated_at=?
                        WHERE id=?''', (payload, digest, now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, 'ready', 'editing', now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps({'baseline_sha256': digest})))
        conn.commit()
        return {'task_id': task_id, 'state': 'editing', 'baseline_sha256': digest}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_upload_mapping(task_id, owner, token, kind, slot, mapping, *, db_path=None,
                          allow_same_content_refresh=False):
    """Durably remember a read-back-confirmed permanent material replacement."""
    if kind not in ('mains', 'details') or not isinstance(mapping, dict):
        raise DoudianError('invalid_upload_mapping', '图片映射类型无效。')
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        raise DoudianError('invalid_upload_mapping', '图片槽位无效。')
    if not (1 <= slot <= (5 if kind == 'mains' else 4)):
        raise DoudianError('invalid_upload_mapping', '图片槽位超出本次改版范围。')
    key = f'{kind}:{slot}'
    source_hash = str(mapping.get('source_sha256') or '')
    remote_key = str(mapping.get('remote_key') or '')
    remote_url = str(mapping.get('remote_url') or '')
    asset_state = mapping.get('asset_state')
    if not asset_state:
        asset_state = ('permanent' if is_permanent_material_url(remote_url, expected_key=remote_key)
                       else 'staged')
    candidate = {'slot': key, 'source_sha256': source_hash, 'remote_key': remote_key,
                 'remote_url': remote_url, 'asset_state': asset_state,
                 'confirmed': mapping.get('confirmed')}
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'editing', 'uploaded'})
        if not _confirmed_upload_mapping(candidate):
            raise DoudianError('invalid_upload_mapping',
                               '只接受来源 SHA-256、精确槽位读回的妙手暂存地址或永久素材ID。')
        items = json.loads(row['upload_map_json'] or '[]')
        matching = [item for item in items if isinstance(item, dict) and item.get('slot') == key]
        existing = matching[0] if len(matching) == 1 else None
        item = {'slot': key, 'source_sha256': source_hash, 'remote_key': remote_key,
                'remote_url': remote_url, 'asset_state': asset_state,
                'confirmed': True, 'confirmed_at': time.time()}
        if len(matching) > 1:
            if any(_confirmed_upload_mapping(entry) for entry in matching):
                raise DoudianError('upload_mapping_conflict', '槽位存在多个素材映射，拒绝覆盖。')
            items = [entry for entry in items if not (isinstance(entry, dict) and entry.get('slot') == key)]
            existing = None
        if existing and not _confirmed_upload_mapping(existing):
            # Old builds incorrectly treated temporary upload URLs as confirmed IDs.
            # They are replaceable only after this call supplies a fully verified CDN mapping.
            items = [entry for entry in items if not (isinstance(entry, dict) and entry.get('slot') == key)]
            conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                            VALUES(?,?,?,?,?,?)''',
                         (task_id, row['state'], row['state'], time.time(), 0,
                          json.dumps({'event': 'legacy_untrusted_upload_mapping_replaced',
                                      'slot': key}, ensure_ascii=False)))
            existing = None
        if existing and existing != item:
            # Never overwrite a previous confirmed mapping: a changed asset set is a
            # different immutable target version and must start from fresh preparation.
            if (existing.get('source_sha256') != source_hash or
                    existing.get('remote_key') != remote_key or
                    existing.get('remote_url') != remote_url):
                safe_refresh = (allow_same_content_refresh is True and
                                existing.get('source_sha256') == source_hash and
                                row['state'] in ('editing', 'uploaded') and
                                row['submission_state'] == 'not_attempted' and
                                int(row['submission_attempts'] or 0) == 0 and
                                row['submission_intent_json'] is None)
                if not safe_refresh:
                    raise DoudianError('upload_mapping_conflict', '槽位已有不同的已确认素材，拒绝覆盖映射。')
                items = [entry for entry in items
                         if not (isinstance(entry, dict) and entry.get('slot') == key)]
                items.append(item)
                conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,
                                elapsed_seconds,detail) VALUES(?,?,?,?,?,?)''',
                             (task_id, row['state'], row['state'], time.time(), 0,
                              json.dumps({'event': 'equivalent_asset_url_refreshed', 'slot': key,
                                          'source_sha256': source_hash}, ensure_ascii=False, sort_keys=True)))
            else:
                existing.update(asset_state=asset_state)
        elif not existing:
            items.append(item)
        conn.execute('UPDATE products SET upload_map_json=?,updated_at=? WHERE id=?',
                     (json.dumps(items, ensure_ascii=False, sort_keys=True), time.time(), task_id))
        conn.commit()
        return {'task_id': task_id, 'slot': key, 'confirmed': True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def begin_submission(task_id, owner, token, *, db_path=None):
    """Persist the single-save intent before the only UI save click."""
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'uploaded'})
        mappings = json.loads(row['upload_map_json'] or '[]')
        expected = {*(f'mains:{slot}' for slot in range(1, 6)),
                    *(f'details:{slot}' for slot in range(1, 5))}
        found = [item.get('slot') for item in mappings if _confirmed_upload_mapping(item)]
        if len(mappings) != len(expected) or set(found) != expected or len(found) != len(expected):
            raise DoudianError('uploads_incomplete', '5张主图和前4张详情图的永久素材均未完整读回确认，未保存。')
        if row['submission_state'] == 'unknown':
            raise DoudianError('submission_unknown', '保存结果未知，只能只读核查。')
        if row['submission_attempts'] and row['submission_state'] != 'failed':
            raise DoudianError('submission_already_attempted', '已有保存尝试；未取得明确失败前不得重存。')
        baseline = row['baseline_hash']
        if not baseline:
            raise DoudianError('baseline_missing', '保存前没有持久化完整妙手基线。')
        now = time.time()
        map_hash = hashlib.sha256(json.dumps(mappings, sort_keys=True).encode()).hexdigest()
        intent = {'target_version': row['target_version'], 'manifest_sha256': row['artifacts_hash'],
                  'baseline_sha256': baseline, 'upload_map_sha256': map_hash,
                  'attempt': int(row['submission_attempts']) + 1,
                  'save_click_count': 1, 'created_at': now}
        conn.execute('''UPDATE products SET state='submitting',submission_state='unknown',
                        submission_attempts=submission_attempts+1,submission_intent_json=?,last_error=NULL,
                        updated_at=? WHERE id=?''',
                     (json.dumps(intent, sort_keys=True), now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, 'uploaded', 'submitting', now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps({'intent_sha256': hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()})))
        conn.commit()
        return intent
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def restore_proven_preclick_failure(task_id, owner, token, proof, *, db_path=None):
    """Return to uploaded only when an intent was persisted but its save click was not sent.

    This narrow recovery is for the observed control-lookup failure that is raised
    before Bridge.click is called. It requires a fresh dual-page baseline readback,
    and keeps an audit event for the discarded intent. Unknown results after a click
    remain permanently readback-only.
    """
    allowed_codes = {'miaoshou_batch_control_not_unique'}
    if (not isinstance(proof, dict) or proof.get('click_issued') is not False or
            proof.get('failure_code') not in allowed_codes or proof.get('read_only') is not True or
            proof.get('miaoshou_matches_baseline') is not True or
            proof.get('doudian_matches_baseline') is not True):
        raise DoudianError('preclick_recovery_not_proven', '未证明保存点击没有发出且双端仍等于原基线，保持隔离。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'blocked'})
        try:
            intent = json.loads(row['submission_intent_json'] or '')
            baseline = json.loads(row['baseline_json'] or '')
            prior_readback = json.loads(row['readback_json'] or '')
        except (TypeError, ValueError):
            raise DoudianError('preclick_recovery_not_proven', '保存意图或基线不完整，保持隔离。')
        intent_hash = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
        baseline_hash = hashlib.sha256(
            json.dumps(baseline, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        miao_readback = prior_readback.get('miaoshou') if isinstance(prior_readback, dict) else None
        doudian_readback = prior_readback.get('doudian') if isinstance(prior_readback, dict) else None
        if (row['state'] != 'blocked' or row['last_error'] != 'readback_mismatch' or
                row['submission_state'] != 'unknown' or int(row['submission_attempts'] or 0) != 1 or
                intent.get('save_click_count') != 1 or intent.get('attempt') != 1 or
                baseline_hash != row['baseline_hash'] or
                row['readback_hash'] is None or prior_readback.get('read_only') is not True or
                proof.get('readback_sha256') != row['readback_hash'] or
                not isinstance(miao_readback, dict) or not isinstance(doudian_readback, dict) or
                miao_readback.get('title') != baseline.get('title') or
                doudian_readback.get('title') != (baseline.get('doudian_baseline') or {}).get('title') or
                miao_readback.get('protected_match') is not True or
                doudian_readback.get('protected_match') is not True or
                miao_readback.get('shelf_mode_matches_original') is not True or
                proof.get('product_id') != row['product_id'] or
                proof.get('shop') != row['shop'] or
                proof.get('target_version') != row['target_version'] or
                proof.get('baseline_sha256') != row['baseline_hash'] or
                proof.get('submission_intent_sha256') != intent_hash or
                proof.get('miaoshou_title') != baseline.get('title') or
                proof.get('doudian_title') != (baseline.get('doudian_baseline') or {}).get('title')):
            raise DoudianError('preclick_recovery_state_changed', '任务、提交意图或读回证据与当前记录不一致。')
        now = time.time()
        detail = {'event': 'submission_preclick_aborted', 'click_issued': False,
                  'failure_code': proof['failure_code'], 'submission_intent_sha256': intent_hash,
                  'baseline_sha256': row['baseline_hash'], 'read_only': True,
                  'miaoshou_matches_baseline': True, 'doudian_matches_baseline': True}
        conn.execute('''UPDATE products SET state='uploaded',submission_state='not_attempted',
                        submission_attempts=0,submission_intent_json=NULL,last_error=?,updated_at=?
                        WHERE id=?''', ('save_button_precheck_failed', now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, 'blocked', 'uploaded', now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps(detail, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return {'task_id': task_id, 'state': 'uploaded', 'submission_state': 'not_attempted',
                'submission_attempts': 0, 'preclick_failure_recovered': True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def begin_title_repair_submission(task_id, owner, token, proof, *, db_path=None):
    """Allow one durable title-only correction after a known accepted mismatch.

    The old save must be accepted (never unknown), both pages must currently show the
    intended permanent images, and the official commercial fields must still match.
    This function cannot be used for general retries or a second repair.
    """
    if not isinstance(proof, dict):
        raise DoudianError('title_repair_proof_invalid', '标题修复必须先提供当前双端只读核验。')
    required_true = ('read_only', 'images_match', 'detail_tail_match',
                     'official_protected_match', 'miao_other_fields_match',
                     'shelf_status_matches', 'shelf_mode_matches_original')
    if any(proof.get(key) is not True for key in required_true):
        raise DoudianError('title_repair_unsafe', '标题修复前置核验未通过，拒绝再次保存。')
    if not proof.get('current_title') or proof.get('current_title') == proof.get('target_title'):
        raise DoudianError('title_repair_not_needed', '当前标题与目标相同或读取不完整。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'blocked'})
        if (row['submission_state'] != 'accepted' or row['last_error'] != 'readback_mismatch' or
                int(row['submission_attempts'] or 0) != 1 or not row['readback_hash'] or
                proof.get('previous_readback_sha256') != row['readback_hash'] or
                proof.get('product_id') != row['product_id'] or proof.get('shop') != row['shop'] or
                proof.get('target_version') != row['target_version'] or
                proof.get('manifest_sha256') != row['artifacts_hash']):
            raise DoudianError('title_repair_state_changed', '保存状态或上一轮读回证据已变化，拒绝修复。')
        prior_evidence = json.loads(row['readback_json'] or '{}')
        if prior_evidence.get('read_only') is not True:
            raise DoudianError('title_repair_evidence_missing', '上一轮缺少双端只读读回证据。')
        mappings = json.loads(row['upload_map_json'] or '[]')
        expected_slots = {*(f'mains:{slot}' for slot in range(1, 6)),
                          *(f'details:{slot}' for slot in range(1, 5))}
        if (len(mappings) != len(expected_slots) or
                any(not isinstance(item, dict) for item in mappings) or
                {item.get('slot') for item in mappings if _confirmed_upload_mapping(item)} != expected_slots or
                any(item.get('asset_state') != 'permanent' for item in mappings)):
            raise DoudianError('title_repair_images_incomplete', '标题修复要求9个槽位均已永久素材读回确认。')
        now = time.time()
        intent = {
            'target_version': row['target_version'], 'manifest_sha256': row['artifacts_hash'],
            'baseline_sha256': row['baseline_hash'], 'previous_readback_sha256': row['readback_hash'],
            'repair_kind': 'title-only', 'attempt': 2, 'save_click_count': 1,
            'images_match_before_repair': True,
            'shelf_mode_matches_original': proof.get('shelf_mode_matches_original') is True,
            'created_at': now,
        }
        conn.execute('''UPDATE products SET state='submitting',submission_state='unknown',
                        submission_attempts=2,submission_intent_json=?,last_error=NULL,updated_at=?
                        WHERE id=?''', (json.dumps(intent, sort_keys=True), now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''',
                     (task_id, 'blocked', 'submitting', now, max(0, now-row['updated_at']),
                      json.dumps({'repair_kind': 'title-only', 'previous_readback_sha256': row['readback_hash'],
                                  'shelf_mode_matches_original': intent['shelf_mode_matches_original']},
                                 ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return intent
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_submission_result(task_id, owner, token, result, *, db_path=None):
    """Record only a response observed after a save click; unknown stays blocked."""
    if not isinstance(result, dict) or result.get('state') not in ('accepted', 'failed', 'rejected', 'unknown'):
        raise DoudianError('invalid_submission_result', '妙手保存结果无法分类，保持只读核查。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'submitting'})
        state = {'accepted': 'submitted', 'failed': 'uploaded',
                 'rejected': 'rejected', 'unknown': 'blocked'}[result['state']]
        sub = {'accepted': 'accepted', 'failed': 'failed',
               'rejected': 'rejected', 'unknown': 'unknown'}[result['state']]
        now = time.time()
        conn.execute('UPDATE products SET state=?,submission_state=?,last_error=?,updated_at=? WHERE id=?',
                     (state, sub, result.get('error'), now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, 'submitting', state, now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps(result, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return {'task_id': task_id, 'state': state, 'submission_state': sub}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_execution_readback(task_id, owner, token, evidence, *, db_path=None):
    """Reconcile a response or unknown result using two independent readbacks."""
    if not isinstance(evidence, dict):
        raise DoudianError('readback_invalid', '读回证据必须是结构化对象。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'submitted', 'blocked'})
        if row['submission_state'] == 'unknown' and evidence.get('read_only') is not True:
            raise DoudianError('readback_required', '结果未知时只接受新开页面的只读核验。')
        expected = (row['product_id'], row['shop'])
        pages = (evidence.get('miaoshou'), evidence.get('doudian'))
        if any(not isinstance(page, dict) or (str(page.get('product_id')), page.get('shop')) != expected
               for page in pages):
            raise DoudianError('readback_identity', '妙手与抖店读回未同时匹配店铺和商品ID。')
        matched = all(page.get('matches_target') is True and page.get('protected_match') is True
                      for page in pages)
        miao_page = evidence['miaoshou']
        shelf_preserved = miao_page.get('shelf_mode_matches_original') is True
        if not shelf_preserved and miao_page.get('shelf_state_preservation'):
            baseline = json.loads(row['baseline_json'] or '{}')
            observed = {'status': miao_page.get('shelf_status'),
                        'startSaleType': miao_page.get('start_sale_type')}
            policy = _warehouse_shelf_preservation(observed, baseline.get('protected'))
            # Validate against the immutable baseline, not a caller-supplied claim.
            # The official page must independently preserve all original fields.
            shelf_preserved = (policy is not None and
                               miao_page['shelf_state_preservation'] == policy and
                               evidence['doudian'].get('protected_match') is True)
        matched = matched and shelf_preserved
        if not all(page.get('complete') is True for page in pages):
            raise DoudianError('readback_incomplete', '任一平台读取字段不完整，不能标为一致。')
        current_mappings = json.loads(row['upload_map_json'] or '[]')
        has_staged = any(
            item.get('asset_state') == 'staged' or
            (not item.get('asset_state') and is_temporary_upload_url(item.get('remote_url')))
            for item in current_mappings if isinstance(item, dict))
        final_mappings = evidence.get('final_asset_mappings')
        map_payload = None
        if matched and (has_staged or final_mappings is not None):
            expected_slots = {*(f'mains:{slot}' for slot in range(1, 6)),
                              *(f'details:{slot}' for slot in range(1, 5))}
            current_by_slot = {item.get('slot'): item for item in current_mappings
                               if isinstance(item, dict)}
            final_by_slot = {item.get('slot'): item for item in final_mappings or []
                             if isinstance(item, dict)}
            valid_final = (isinstance(final_mappings, list) and len(final_mappings) == len(expected_slots) and
                           set(final_by_slot) == expected_slots and
                           all(_confirmed_upload_mapping(item) and item.get('asset_state') == 'permanent'
                               for item in final_by_slot.values()) and
                           all(current_by_slot.get(slot, {}).get('source_sha256') ==
                               final_by_slot[slot].get('source_sha256') for slot in expected_slots))
            if valid_final:
                map_payload = json.dumps(final_mappings, ensure_ascii=False, sort_keys=True)
            else:
                # A staged tmp_upload link is not a post-save identity. Never mark the
                # batch verified until both independent pages yield permanent IDs.
                matched = False
        payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        now = time.time()
        state = 'verified' if matched else 'blocked'
        sub = 'verified_by_readback' if matched and row['submission_state'] == 'unknown' else row['submission_state']
        error = None if matched else 'readback_mismatch'
        conn.execute('''UPDATE products SET state=?,submission_state=?,readback_json=?,readback_hash=?,
                        upload_map_json=COALESCE(?,upload_map_json),
                        last_error=?,updated_at=? WHERE id=?''',
                     (state, sub, payload, digest, map_payload, error, now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, row['state'], state, now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps({'readback_sha256': digest, 'matches': matched})))
        conn.commit()
        return {'task_id': task_id, 'state': state, 'submission_state': sub,
                'readback_sha256': digest, 'matches': matched}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_execution(task_id, owner, token, *, db_path=None):
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        _execution_row(conn, task_id, owner, token)
        conn.execute('''UPDATE products SET execution_owner=NULL,execution_token=NULL,execution_until=NULL
                        WHERE id=?''', (task_id,))
        conn.commit()
        return {'task_id': task_id, 'released': True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def renew_execution(task_id, owner, token, *, db_path=None, lease_seconds=LEASE_SECONDS):
    if not 60 <= lease_seconds <= 7200:
        raise DoudianError('invalid_execution_claim', '浏览器执行租约时长无效。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        _execution_row(conn, task_id, owner, token)
        until = time.time() + lease_seconds
        conn.execute('UPDATE products SET execution_until=?,updated_at=? WHERE id=?',
                     (until, time.time(), task_id))
        conn.commit()
        return {'task_id': task_id, 'execution_until': until}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_writer_acceptance(results, *, db_path=None):
    """Store proof only after three independently verified live product revisions."""
    ids = {str(item.get('product_id')) for item in results if isinstance(item, dict) and item.get('state') == 'verified'}
    if len(ids) < 3:
        raise DoudianError('writer_acceptance_incomplete', '至少3件不同商品完成双端读回，才能启用正式 writer_ready。')
    proof = {'schema_version': 1, 'accepted_at': time.time(), 'verified_product_ids': sorted(ids),
             'readback_hashes': sorted(str(item.get('readback_sha256')) for item in results
                                       if item.get('state') == 'verified' and item.get('readback_sha256'))}
    write_path = Path(db_path or DB_PATH).parent / 'miaoshou-writer-acceptance.json'
    write_json(write_path, proof)
    return proof


def verified_acceptance_results(product_ids, *, db_path=None):
    """Return stored, independently read-back-verified products for acceptance."""
    ids = list(dict.fromkeys(str(pid) for pid in (product_ids or []) if str(pid)))
    if not ids:
        return []
    placeholders = ','.join('?' for _ in ids)
    conn = _db(db_path)
    try:
        rows = conn.execute(
            f'''SELECT product_id,state,readback_hash FROM products
                WHERE product_id IN ({placeholders}) AND state='verified'
                  AND readback_hash IS NOT NULL AND readback_hash != ''
                ORDER BY product_id''', ids).fetchall()
        return [{'product_id': row['product_id'], 'state': 'verified',
                 'readback_sha256': row['readback_hash']} for row in rows]
    finally:
        conn.close()


def execution_readiness(endpoint):
    """Probe the browser and the durable three-product writer acceptance record."""
    from .bridge import Bridge
    from .miaoshou_batch_editor import SHELF_MODE_BLOCK_MESSAGE, SHELF_MODE_PRESERVATION_VERIFIED

    status = Bridge(endpoint, session='miaoshou-batch-doctor').status()
    ready = bool(status.get('running') and status.get('extension_connected') and
                 not status.get('version_mismatch'))
    proof_path = DB_PATH.parent / 'miaoshou-writer-acceptance.json'
    proof = None
    try:
        proof = read_json(proof_path)
    except (OSError, ValueError):
        pass
    acceptance_verified = bool(proof and proof.get('schema_version') == 1 and
                               len(set(proof.get('verified_product_ids', []))) >= 3 and
                               len(proof.get('readback_hashes', [])) >= 3)
    writer_ready = bool(ready and acceptance_verified and SHELF_MODE_PRESERVATION_VERIFIED)
    reason = None if writer_ready else (
        '浏览器连接未就绪。' if not ready else
        SHELF_MODE_BLOCK_MESSAGE
        if not SHELF_MODE_PRESERVATION_VERIFIED else
        '需要3件商品的妙手与抖店独立读回验收后才开放全批量运行。')
    return {'browser_ready': ready, 'bridge': status, 'writer_ready': writer_ready,
            'shelf_mode_preservation_verified': SHELF_MODE_PRESERVATION_VERIFIED,
            'acceptance_products': proof.get('verified_product_ids', []) if writer_ready else [],
            'reason': reason}


def _stable_doudian_snapshot(editor, identity):
    """Read the official editor after its protected blocks stop mounting."""
    from .workflow import compare_protected

    focused = False
    try:
        # Hidden background tabs can retain the detail URL strings but render all image
        # cards at 0x0. Focus emulation lets the browser finish its normal page layout
        # without bringing the tab over the user's foreground app.
        editor.open(identity, fresh=True)
        editor.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled',
                                      'params': {'enabled': True}})
        focused = True
        editor.wait_details(identity, seconds=30)
        previous = None
        steady = 0
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            counts = editor.section_counts(identity)
            marker = json.dumps(counts, sort_keys=True, ensure_ascii=False)
            if marker == previous:
                steady += 1
                if steady >= 2:
                    break
            else:
                previous = marker
                steady = 0
            time.sleep(0.5)
        else:
            raise DoudianError('doudian_read_timeout', '抖店保护字段没有稳定挂载。')
        snapshot = editor.wait_details(identity, seconds=10)
        compare_protected(snapshot, snapshot)  # refuses missing or partially observed sections
        if snapshot.get('product_id') != identity['product_id'] or not snapshot.get('shop_confirmed'):
            raise DoudianError('wrong_identity', '抖店读回的店铺或商品ID不匹配。')
        return snapshot
    finally:
        if focused:
            try:
                editor.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled',
                                              'params': {'enabled': False}})
            except DoudianError:
                pass


def _image_keys(values):
    from .workflow import resource_key
    return [resource_key(value) for value in (values or [])]


def _target_asset_slots(assets):
    mains = [asset for asset in assets if asset.get('kind') == 'main']
    details = [asset for asset in assets if asset.get('kind') == 'detail'][:4]
    return ([('mains', slot, asset['path']) for slot, asset in enumerate(mains, 1)] +
            [('details', slot, asset['path']) for slot, asset in enumerate(details, 1)])


def _matches_miaoshou_target(before, after, title, mappings, *, preserve_warehouse=False):
    return (_matches_miaoshou_content(before, after, title, mappings) and
            _miaoshou_protected_matches(after.get('protected'), before.get('protected'),
                                        preserve_warehouse=preserve_warehouse))


def _matches_miaoshou_content(before, after, title, mappings):
    if after.get('title') != title or after.get('protected_complete') is not True:
        return False
    target_main = [item['remote_key'] for item in sorted(
        (m for m in mappings if m['slot'].startswith('mains:')),
        key=lambda item: int(item['slot'].split(':')[1]))]
    target_details = [item['remote_key'] for item in sorted(
        (m for m in mappings if m['slot'].startswith('details:')),
        key=lambda item: int(item['slot'].split(':')[1]))]
    before_details = _image_keys(before.get('details'))
    after_details = _image_keys(after.get('details'))
    return (_image_keys(after.get('mains')) == target_main and len(target_main) == 5 and
            len(target_details) == 4 and len(after_details) == len(before_details) and
            after_details[:4] == target_details and after_details[4:] == before_details[4:])


def _matches_doudian_target(before, after, title, mappings):
    from .workflow import compare_protected

    try:
        compare_protected(before, after)
    except DoudianError:
        return False
    if after.get('title') != title or after.get('draft_loaded') or after.get('rejected'):
        return False
    target_main = [item['remote_key'] for item in sorted(
        (m for m in mappings if m['slot'].startswith('mains:')),
        key=lambda item: int(item['slot'].split(':')[1]))]
    target_details = [item['remote_key'] for item in sorted(
        (m for m in mappings if m['slot'].startswith('details:')),
        key=lambda item: int(item['slot'].split(':')[1]))]
    before_details = _image_keys(before.get('details'))
    after_details = _image_keys(after.get('details'))
    return (_image_keys(after.get('mains')) == target_main and len(target_main) == 5 and
            len(target_details) == 4 and len(after_details) == len(before_details) and
            after_details[:4] == target_details and after_details[4:] == before_details[4:])


def _finalize_target_mappings(baseline, miaoshou_after, doudian_after, mappings):
    """Resolve pre-save temp URLs to permanent IDs only after dual server readback."""
    expected = {*(f'mains:{slot}' for slot in range(1, 6)),
                *(f'details:{slot}' for slot in range(1, 5))}
    if (not isinstance(mappings, list) or len(mappings) != len(expected) or
            any(not _confirmed_upload_mapping(item) for item in mappings) or
            {item['slot'] for item in mappings} != expected):
        raise DoudianError('final_asset_mapping_incomplete', '保存前没有完整的9个槽位素材证据。')
    miao_groups = {'mains': miaoshou_after.get('mains') or [],
                   'details': miaoshou_after.get('details') or []}
    official_groups = {'mains': doudian_after.get('mains') or [],
                       'details': doudian_after.get('details') or []}
    before_groups = {'mains': baseline.get('mains') or [],
                     'details': baseline.get('details') or []}
    by_slot = {item['slot']: item for item in mappings}
    finalized = []
    for group, count in (('mains', 5), ('details', 4)):
        if len(miao_groups[group]) < count or len(official_groups[group]) < count:
            raise DoudianError('final_asset_readback_incomplete', f'{group} 目标图片没有双端完整读回。')
        for slot in range(1, count + 1):
            slot_key = f'{group}:{slot}'
            miao_url = miao_groups[group][slot - 1]
            official_url = official_groups[group][slot - 1]
            final_key = resource_key(miao_url)
            if (not is_permanent_material_url(miao_url, expected_key=final_key) or
                    not is_permanent_material_url(official_url, expected_key=final_key)):
                raise DoudianError('final_asset_not_permanent', f'{slot_key} 保存后没有读回匹配的永久素材地址。')
            if resource_key(official_url) != final_key:
                raise DoudianError('final_asset_platform_mismatch', f'{slot_key} 妙手与抖店图片ID不同。')
            old_urls = before_groups[group]
            if slot <= len(old_urls) and resource_key(old_urls[slot - 1]) == final_key:
                raise DoudianError('final_asset_unchanged', f'{slot_key} 保存后仍是原图片，目标替换未读回。')
            prior = by_slot[slot_key]
            prior_is_permanent = (prior.get('asset_state') == 'permanent' or
                                  (not prior.get('asset_state') and is_permanent_material_url(
                                      prior.get('remote_url'), expected_key=prior.get('remote_key'))))
            if prior_is_permanent and prior.get('remote_key') != final_key:
                raise DoudianError('final_asset_key_changed', f'{slot_key} 保存后素材ID与保存前永久素材ID不同。')
            finalized.append({'slot': slot_key, 'source_sha256': prior['source_sha256'],
                              'remote_key': final_key, 'remote_url': miao_url,
                              'asset_state': 'permanent', 'confirmed': True})
    if len(miaoshou_after.get('details') or []) != len(before_groups['details']) or \
            len(doudian_after.get('details') or []) != len(before_groups['details']):
        raise DoudianError('final_detail_count_changed', '保存后详情图总数变化，拒绝确认目标映射。')
    if (_image_keys(miaoshou_after['details'][4:]) != _image_keys(before_groups['details'][4:]) or
            _image_keys(doudian_after['details'][4:]) != _image_keys(before_groups['details'][4:])):
        raise DoudianError('final_detail_tail_changed', '保存后非目标详情图发生变化。')
    return finalized


def _matches_saved_baseline(miaoshou, doudian, baseline):
    """A pre-save continuation is safe only while both server pages still equal baseline."""
    from .workflow import compare_protected

    official = baseline.get('doudian_baseline') if isinstance(baseline, dict) else None
    if not isinstance(official, dict):
        return False
    if (miaoshou.get('product_id') != baseline.get('product_id') or
            miaoshou.get('shop') != baseline.get('shop') or
            miaoshou.get('protected_complete') is not True or
            miaoshou.get('title') != baseline.get('title') or
            not _miaoshou_protected_matches(miaoshou.get('protected'), baseline.get('protected')) or
            _image_keys(miaoshou.get('mains')) != _image_keys(baseline.get('mains')) or
            _image_keys(miaoshou.get('details')) != _image_keys(baseline.get('details'))):
        return False
    if (doudian.get('product_id') != official.get('product_id') or
            doudian.get('shop_confirmed') is not True or doudian.get('draft_loaded') or
            doudian.get('rejected') or doudian.get('title') != official.get('title') or
            _image_keys(doudian.get('mains')) != _image_keys(official.get('mains')) or
            _image_keys(doudian.get('details')) != _image_keys(official.get('details'))):
        return False
    try:
        compare_protected(official, doudian)
    except DoudianError:
        return False
    return True


def _warehouse_shelf_preservation(current, expected):
    """Describe the one observed normalization that preserves an off-shelf product.

    startSaleType is the destination *after review*, not the current shelf state.
    The official product/edit docs define 0 as immediate listing and 1 as warehouse.
    A warehouse edit must retain status=1 and end in mode=1, even when its historical
    value was 0. Never apply this policy to listed products or unknown state values.
    """
    if not isinstance(current, dict) or not isinstance(expected, dict):
        return None
    values = (expected.get('status'), current.get('status'),
              expected.get('startSaleType'), current.get('startSaleType'))
    if (any(type(value) is not int for value in values) or
            values[0:2] != (1, 1) or values[2] not in (0, 1) or values[3] != 1):
        return None
    return {'policy': 'preserve_warehouse_v1', 'before_status': 1, 'after_status': 1,
            'before_mode': values[2], 'after_mode': 1, 'expected_after_mode': 1,
            'raw_mode_changed': values[2] != 1,
            'source': 'https://op.jinritemai.com/docs/api-docs/14/250?from=list'}


def _miaoshou_protected_matches(current, expected, *, preserve_warehouse=False):
    """Compare protected Miaoshou values, normalizing CDN renditions by asset identity."""
    if not isinstance(current, dict) or not isinstance(expected, dict):
        return False
    left, right = dict(current), dict(expected)
    if preserve_warehouse:
        if _warehouse_shelf_preservation(current, expected) is None:
            return False
        left.pop('startSaleType')
        right.pop('startSaleType')
    # Review status is a platform workflow state and is reported independently from
    # shelf status. Editing title/images can move it to "approved, waiting to list".
    left.pop('checkStatus', None)
    right.pop('checkStatus', None)
    for key in ('mainPic34', 'mainImageThreeToFour'):
        if _image_keys(left.pop(key, None)) != _image_keys(right.pop(key, None)):
            return False
    return left == right


def _miaoshou_title_repair_fields_match(current, expected):
    """Prove a corrective title-only save would not overwrite other Miao fields.

    The review and post-review shelf-mode fields are excluded from this *precondition*
    comparison only: they are reported separately and shelf-mode mismatch still blocks
    final verification. Every other commercial field, including current shelf status,
    must match the observed pre-repair state.
    """
    if not isinstance(current, dict) or not isinstance(expected, dict):
        return False
    left, right = dict(current), dict(expected)
    for key in ('checkStatus', 'startSaleType'):
        left.pop(key, None)
        right.pop(key, None)
    for key in ('mainPic34', 'mainImageThreeToFour'):
        if _image_keys(left.pop(key, None)) != _image_keys(right.pop(key, None)):
            return False
    return left == right


def record_execution_error(task_id, owner, token, error, *, db_path=None):
    """Save a pre-commit error while keeping the verified, resumable stage intact."""
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token,
                             states={'ready', 'editing', 'uploaded', 'submitted', 'blocked'})
        now = time.time()
        code = str(error)[:200]
        conn.execute('UPDATE products SET last_error=?,updated_at=? WHERE id=?', (code, now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, row['state'], row['state'], now,
                                                 max(0, now-row['updated_at']), code))
        conn.commit()
        return {'task_id': task_id, 'state': row['state'], 'last_error': code}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def requeue_blocked_prewrite(task_id, owner, token, proof, *, db_path=None):
    """Resume a blocked pre-save edit only after fresh dual reads match its baseline."""
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = _execution_row(conn, task_id, owner, token, states={'blocked'})
        if (row['submission_state'] != 'not_attempted' or int(row['submission_attempts'] or 0) != 0 or
                row['last_error'] not in PREWRITE_RECOVERABLE_ERRORS or
                not row['baseline_hash'] or not row['baseline_json'] or
                not isinstance(proof, dict) or proof.get('read_only') is not True or
                proof.get('product_id') != row['product_id'] or
                proof.get('baseline_sha256') != row['baseline_hash'] or
                proof.get('miaoshou_matches') is not True or proof.get('doudian_matches') is not True):
            raise DoudianError('prewrite_recovery_not_proven', '中断任务未通过双端只读基线核对，保持隔离。')
        now = time.time()
        detail = {'read_only_baseline_rechecked': True, 'baseline_sha256': row['baseline_hash'],
                  'product_id': row['product_id']}
        conn.execute("UPDATE products SET state='editing',last_error=NULL,updated_at=? WHERE id=? AND state='blocked'",
                     (now, task_id))
        if conn.execute('SELECT changes()').fetchone()[0] != 1:
            raise DoudianError('execution_race', '任务在基线核对期间发生变化。')
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, 'blocked', 'editing', now,
                                                 max(0, now-row['updated_at']),
                                                 json.dumps(detail, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return {'task_id': task_id, 'state': 'editing', 'recovered_after_readback': True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _stored_execution_baseline(claim, manifest_sha256):
    try:
        baseline = json.loads(claim.get('baseline_json') or '')
    except (TypeError, ValueError):
        raise DoudianError('baseline_missing', '已保存或中断任务没有可核验的原始基线。')
    digest = hashlib.sha256(json.dumps(baseline, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    if digest != claim.get('baseline_hash'):
        raise DoudianError('baseline_changed', '任务原始基线哈希不匹配。')
    if (baseline.get('product_id') != claim.get('product_id') or baseline.get('shop') != claim.get('shop') or
            baseline.get('target_version') != claim.get('target_version') or
            baseline.get('manifest_sha256') != manifest_sha256 or
            not isinstance(baseline.get('doudian_baseline'), dict)):
        raise DoudianError('baseline_changed', '持久化基线与商品、店铺或目标版本不匹配。')
    return baseline


def _close_batch_session(bridge):
    """Close only tabs created by this browser session; borrowed tabs stay open."""
    try:
        result = bridge.command('close_session')
        return {'attempted': True, 'closed': int((result or {}).get('closed', 0))}
    except Exception as exc:
        # Browser-tab cleanup must not rewrite the durable product outcome. A later
        # run can close session-owned leftovers after the queue state is persisted.
        return {'attempted': True, 'closed': 0,
                'error': getattr(exc, 'code', type(exc).__name__)}


def _close_task_miaoshou_batch_tab(bridge):
    """Close only the single Miaoshou multi-field task tab after queue persistence."""
    try:
        tabs = bridge.command('list_tabs') or {}
        matches = [tab for tab in tabs.get('tabs', [])
                   if urlparse(tab.get('url', '')).hostname == 'v2-dd.chengji-inc.com' and
                   urlparse(tab.get('url', '')).path == '/product/batch/edit']
        if not matches:
            return {'attempted': False, 'closed': 0}
        if len(matches) != 1:
            return {'attempted': True, 'closed': 0, 'reason': 'ambiguous_task_tabs'}
        bridge.command('attach_tab', {'tabId': matches[0]['tabId']})
        result = bridge.command('close_tab') or {}
        return {'attempted': True, 'closed': int(bool(result.get('closed')))}
    except Exception as exc:
        return {'attempted': True, 'closed': 0,
                'error': getattr(exc, 'code', type(exc).__name__)}


def run_batch(endpoint, *, batch_id=None, product_ids=None, limit=1, owner='codex-miaoshou-writer',
              db_path=None, session='miaoshou-auto-batch-20261028', resume_only=False,
              readback_only=False):
    """Run ready or safely resumable products serially through both merchant pages."""
    from .bridge import Bridge
    from .editor import Editor
    from .miaoshou_editor import MiaoshouEditor
    from .miaoshou_batch_editor import (MiaoshouBatchEditor, SHELF_MODE_BLOCK_MESSAGE,
                                        SHELF_MODE_PRESERVATION_VERIFIED)
    from .workflow import compare_protected

    if not 1 <= int(limit) <= 20:
        raise DoudianError('invalid_limit', '批次写入单次限制为1至20件。')
    requested_ids = [str(pid) for pid in (product_ids or [])]
    allowed = set(requested_ids)
    status = batch_status(batch_id, db_path=db_path)
    recovered_legacy = []
    for product in status['products']:
        if (product['state'] == 'blocked' and product.get('last_error') == 'target_version_mismatch' and
                (not allowed or product['product_id'] in allowed)):
            recovered = recover_legacy_target_version_mismatch(product['id'], db_path=db_path)
            if recovered:
                recovered_legacy.append(recovered)
    if recovered_legacy:
        status = batch_status(batch_id, db_path=db_path)
    runnable = {'editing', 'uploaded', 'submitted'} if resume_only else {'ready', 'editing', 'uploaded', 'submitted'}
    candidates = [p for p in status['products'] if p['state'] in runnable and
                  (p.get('submission_state') != 'unknown' or p['state'] == 'submitted') and
                  (not batch_id or p['batch_id'] == batch_id) and
                  (not allowed or p['product_id'] in allowed) and p['product_id']]
    candidates.extend(p for p in status['products'] if p['state'] == 'blocked' and
                      p.get('submission_state') in ('unknown', 'accepted') and
                      (not batch_id or p['batch_id'] == batch_id) and
                      (not allowed or p['product_id'] in allowed) and p['product_id'])
    if readback_only:
        candidates = [p for p in candidates if p['state'] == 'submitted' or
                      (p['state'] == 'blocked' and
                       p.get('submission_state') in ('unknown', 'accepted'))]
    candidates.extend(p for p in status['products'] if p['state'] == 'blocked' and
                      p.get('submission_state') == 'not_attempted' and
                      p.get('last_error') in PREWRITE_RECOVERABLE_ERRORS and
                      (not batch_id or p['batch_id'] == batch_id) and
                      (not allowed or p['product_id'] in allowed) and p['product_id'])
    if requested_ids:
        order = {pid: index for index, pid in enumerate(requested_ids)}
        candidates.sort(key=lambda item: order.get(item['product_id'], len(order)))
    if not candidates:
        return {'run': [], 'recovered_legacy_versions': recovered_legacy,
                'message': '没有符合筛选条件且素材已通过校验的商品。'}
    candidates = candidates[:int(limit)]
    write_candidates = [item for item in candidates
                        if item['state'] in ('ready', 'editing', 'uploaded') or
                        (item['state'] == 'blocked' and item.get('submission_state') == 'not_attempted')]
    if write_candidates and not SHELF_MODE_PRESERVATION_VERIFIED:
        raise DoudianError('shelf_mode_unpreservable', SHELF_MODE_BLOCK_MESSAGE)
    results = []
    with Lock(DATA_ROOT / 'browser.lock'):
        bridge = Bridge(endpoint, session=session, timeout=25)
        bridge.require_ready()
        # Preserve a prepared user-owned batch form through validation. The adapter
        # selects the unique exact route; task tabs are closed only after the result
        # has been durably recorded.
        for item in candidates:
            task_id = item['id']
            claim = claim_execution(task_id, owner, db_path=db_path, lease_seconds=7200)
            if claim is None:
                results.append({'task_id': task_id, 'product_id': item['product_id'],
                                'state': 'skipped', 'reason': 'another_browser_writer_active'})
                continue
            submission_intent = False
            try:
                ready = load_ready_artifacts(task_id, db_path=db_path)
                manifest = ready['manifest']
                claim['target_version'] = ready['target_version']
                if manifest['product_id'] != item['product_id']:
                    raise DoudianError('artifact_product_mismatch', '目标版本与队列商品ID不匹配。')
                if (claim['state'] in ('submitted', 'blocked') and
                        not claim.get('prewrite_recovery')):
                    baseline = _stored_execution_baseline(claim, ready['manifest_sha256'])
                    mappings = json.loads(claim.get('upload_map_json') or '[]')
                    official_before = baseline['doudian_baseline']
                    miao_read = MiaoshouEditor(bridge, item['shop'], session=session)
                    miao_read.open_product(item['product_id'], fresh=True)
                    miao_after = miao_read.read_product(item['product_id'])
                    official_after = _stable_doudian_snapshot(Editor(bridge), {
                        'product_id': item['product_id'], 'shop': item['shop'],
                        'edit_url': f'https://{HOST}/ffa/g/create?product_id={item["product_id"]}'})
                    try:
                        final_mappings = _finalize_target_mappings(baseline, miao_after,
                                                                   official_after, mappings)
                    except DoudianError:
                        final_mappings = None
                    shelf_policy = _warehouse_shelf_preservation(
                        miao_after.get('protected'), baseline.get('protected'))
                    miao_match = bool(final_mappings) and _matches_miaoshou_target(
                        baseline, miao_after, manifest['title'], final_mappings,
                        preserve_warehouse=shelf_policy is not None)
                    try:
                        compare_protected(official_before, official_after)
                        official_protected = True
                    except DoudianError:
                        official_protected = False
                    doudian_match = bool(final_mappings) and _matches_doudian_target(
                        official_before, official_after, manifest['title'], final_mappings)
                    evidence = {
                        'target_version': claim['target_version'],
                        'manifest_sha256': ready['manifest_sha256'], 'read_only': True,
                        'miaoshou': {'product_id': item['product_id'], 'shop': item['shop'],
                                     'complete': bool(miao_after.get('protected_complete') and
                                                      len(miao_after.get('mains') or []) == 5 and
                                                      len(miao_after.get('details') or []) >= 4),
                                     'matches_target': miao_match,
                                     'protected_match': _miaoshou_protected_matches(
                                         miao_after.get('protected'), baseline.get('protected'),
                                         preserve_warehouse=shelf_policy is not None),
                                     'shelf_state_preservation': shelf_policy,
                                     'title': miao_after.get('title'),
                                     'main_count': len(miao_after.get('mains') or []),
                                     'detail_count': len(miao_after.get('details') or []),
                                     'shelf_status': miao_after.get('protected', {}).get('status'),
                                     'review_status': miao_after.get('protected', {}).get('checkStatus'),
                                     'start_sale_type': miao_after.get('protected', {}).get('startSaleType'),
                                     'start_sale_type_before': baseline.get('protected', {}).get('startSaleType'),
                                     'shelf_mode_matches_original': (
                                         miao_after.get('protected', {}).get('startSaleType') ==
                                         baseline.get('protected', {}).get('startSaleType'))},
                        'doudian': {'product_id': item['product_id'], 'shop': item['shop'],
                                    'complete': bool(official_after.get('shop_confirmed') and
                                                     official_after.get('protected')),
                                    'matches_target': doudian_match,
                                    'protected_match': official_protected,
                                    'title': official_after.get('title'),
                                    'main_count': len(official_after.get('mains') or []),
                                    'detail_count': len(official_after.get('details') or []),
                                    'draft_loaded': bool(official_after.get('draft_loaded')),
                                    'rejected': bool(official_after.get('rejected'))},
                    }
                    if final_mappings:
                        evidence['final_asset_mappings'] = final_mappings
                    result_state = record_execution_readback(task_id, owner, claim['execution_token'],
                                                             evidence, db_path=db_path)
                    miao_read.stop_capture()
                    results.append({'task_id': task_id, 'product_id': item['product_id'],
                                    'state': result_state['state'],
                                    'submission_state': result_state['submission_state'],
                                    'readback_sha256': result_state['readback_sha256'],
                                    'miao_matches': miao_match, 'doudian_matches': doudian_match,
                                    'read_only_reconciliation': True})
                    continue
                doudian_identity = {'product_id': item['product_id'], 'shop': item['shop'],
                                    'edit_url': f'https://{HOST}/ffa/g/create?product_id={item["product_id"]}'}
                # Independent official-page baseline is captured before any Miaoshou
                # field or image is touched.
                official = Editor(bridge)
                official_before = _stable_doudian_snapshot(official, doudian_identity)
                if official_before.get('draft_loaded') or official_before.get('rejected'):
                    raise DoudianError('doudian_draft_or_rejected', '抖店页面存在草稿或驳回，未开始改版。')
                miao = MiaoshouEditor(bridge, item['shop'], session=session)
                miao.open_product(item['product_id'], fresh=True)
                miao_before = miao.read_product(item['product_id'])
                if miao_before.get('protected', {}).get('startSaleType') is None:
                    raise DoudianError('shelf_mode_unknown',
                                       '妙手基线没有读回审核后的上架模式，未开始批量编辑。')
                agent_facts = read_json(ready['path']).get('facts') or {}
                source_title = next((agent_facts.get(key) for key in
                                     ('current_title', 'old_title', 'product_name_from_snapshot')
                                     if agent_facts.get(key)), None)
                if source_title and source_title != miao_before['title']:
                    raise DoudianError('agent_facts_stale', '素材准备使用的旧标题与实时妙手商品不一致。')
                if (miao_before['title'] != official_before.get('title') or
                        _image_keys(miao_before['mains']) != _image_keys(official_before.get('mains')) or
                        _image_keys(miao_before['details']) != _image_keys(official_before.get('details'))):
                    raise DoudianError('baseline_disagreement', '妙手与抖店的标题或图片基线不一致。')
                expected_skus = agent_facts.get('sku_count')
                actual_skus = len(miao_before['protected'].get('specPrices') or [])
                if expected_skus and int(expected_skus) != actual_skus:
                    raise DoudianError('agent_facts_stale', '素材准备记录的SKU数量与实时妙手读取不一致。')
                if miao_before['protected'].get('status') is None:
                    raise DoudianError('shelf_state_unknown', '商品当前上下架状态无法确认。')
                if claim['state'] == 'ready':
                    baseline = {**miao_before, 'doudian_baseline': official_before,
                                'target_version': claim['target_version'],
                                'manifest_sha256': ready['manifest_sha256']}
                    record_baseline(task_id, owner, claim['execution_token'], baseline, db_path=db_path)
                else:
                    baseline = _stored_execution_baseline(claim, ready['manifest_sha256'])
                    if not _matches_saved_baseline(miao_before, official_before, baseline):
                        raise DoudianError('baseline_changed', '线上商品已不同于中断前基线；已停止续办。')
                    if claim.get('prewrite_recovery'):
                        requeue_blocked_prewrite(task_id, owner, claim['execution_token'], {
                            'read_only': True, 'product_id': item['product_id'],
                            'baseline_sha256': claim['baseline_hash'],
                            'miaoshou_matches': True, 'doudian_matches': True,
                        }, db_path=db_path)
                        claim['state'] = 'editing'
                    miao_before = baseline
                    official_before = baseline['doudian_baseline']
                target_assets = _target_asset_slots(manifest['assets'])
                if len([x for x in target_assets if x[0] == 'mains']) != 5 or len(target_assets) != 9:
                    raise DoudianError('asset_manifest_incomplete', '目标版本必须是5张主图和4张新详情图。')
                main_paths = [path for kind, _, path in target_assets if kind == 'mains']
                detail_paths = [path for kind, _, path in target_assets if kind == 'details']
                asset_paths = main_paths + detail_paths
                batch_editor = MiaoshouBatchEditor(bridge, item['shop'], session=session)
                try:
                    mappings = batch_editor.verify_prepared(
                        product_id=item['product_id'], title=manifest['title'],
                        baseline=miao_before, asset_paths=asset_paths)
                except DoudianError as form_error:
                    if form_error.code in {'wrong_shop', 'miaoshou_batch_wrong_page',
                                           'miaoshou_batch_tab_ambiguous'}:
                        raise
                    batch_editor.prepare(product_id=item['product_id'], title=manifest['title'],
                                          baseline=miao_before, main_paths=main_paths,
                                          detail_paths=detail_paths)
                    mappings = batch_editor.verify_prepared(
                        product_id=item['product_id'], title=manifest['title'],
                        baseline=miao_before, asset_paths=asset_paths)
                for mapping in mappings:
                    kind, raw_slot = mapping['slot'].split(':', 1)
                    record_upload_mapping(task_id, owner, claim['execution_token'], kind,
                                          int(raw_slot), mapping, db_path=db_path,
                                          allow_same_content_refresh=True)
                miao.stop_capture()
                set_execution_state(task_id, 'uploaded', db_path=db_path)
                # Build and validate the page-level result preview before recording
                # a save intent. The final button does not exist until this step.
                prepared_submission = batch_editor.prepare_submission(
                    product_id=item['product_id'], shop=item['shop'],
                    title=manifest['title'], mappings=mappings)
                begin_submission(task_id, owner, claim['execution_token'], db_path=db_path)
                submission_intent = True
                try:
                    result = batch_editor.click_start_once(
                        product_id=item['product_id'], title=manifest['title'],
                        baseline=miao_before, asset_paths=asset_paths,
                        validated_mappings=mappings,
                        prepared_submission=prepared_submission)
                except Exception as exc:
                    result = {'state': 'unknown', 'error': getattr(exc, 'code', type(exc).__name__)}
                result_state = record_submission_result(task_id, owner, claim['execution_token'],
                                                        result, db_path=db_path)
                submission_intent = False
                if result_state['submission_state'] == 'failed':
                    results.append({'task_id': task_id, 'product_id': item['product_id'],
                                    'state': result_state['state'], 'submission_state': result_state['submission_state'],
                                    'reason': result.get('error')})
                    continue
                if result_state['submission_state'] not in ('accepted', 'unknown'):
                    results.append({'task_id': task_id, 'product_id': item['product_id'],
                                    'state': result_state['state'], 'submission_state': result_state['submission_state'],
                                    'reason': result.get('error')})
                    continue

                # The two readbacks use newly opened pages; the edited form is never
                # used as proof that the server accepted the change.
                miao_read = MiaoshouEditor(bridge, item['shop'], session=session)
                miao_read.open_product(item['product_id'], fresh=True)
                miao_after = miao_read.read_product(item['product_id'])
                official_after = _stable_doudian_snapshot(official, doudian_identity)
                try:
                    final_mappings = _finalize_target_mappings(miao_before, miao_after,
                                                               official_after, mappings)
                except DoudianError:
                    final_mappings = None
                shelf_policy = _warehouse_shelf_preservation(
                    miao_after.get('protected'), miao_before.get('protected'))
                miao_match = bool(final_mappings) and _matches_miaoshou_target(
                    miao_before, miao_after, manifest['title'], final_mappings,
                    preserve_warehouse=shelf_policy is not None)
                try:
                    compare_protected(official_before, official_after)
                    official_protected = True
                except DoudianError:
                    official_protected = False
                doudian_match = bool(final_mappings) and _matches_doudian_target(
                    official_before, official_after, manifest['title'], final_mappings)
                evidence = {
                    'target_version': claim['target_version'], 'manifest_sha256': ready['manifest_sha256'],
                    'read_only': True,
                    'miaoshou': {'product_id': item['product_id'], 'shop': item['shop'],
                                 'complete': bool(miao_after.get('protected_complete') and miao_after.get('mains')
                                                  and len(miao_after.get('details') or []) >= 4),
                                 'matches_target': miao_match,
                                 'protected_match': _miaoshou_protected_matches(
                                     miao_after.get('protected'), miao_before.get('protected'),
                                     preserve_warehouse=shelf_policy is not None),
                                 'shelf_state_preservation': shelf_policy,
                                 'title': miao_after.get('title'),
                                 'main_count': len(miao_after.get('mains') or []),
                                 'detail_count': len(miao_after.get('details') or []),
                                 'shelf_status': miao_after.get('protected', {}).get('status'),
                                 'review_status': miao_after.get('protected', {}).get('checkStatus'),
                                 'start_sale_type': miao_after.get('protected', {}).get('startSaleType'),
                                 'start_sale_type_before': miao_before.get('protected', {}).get('startSaleType'),
                                 'shelf_mode_matches_original': (
                                     miao_after.get('protected', {}).get('startSaleType') ==
                                     miao_before.get('protected', {}).get('startSaleType'))},
                    'doudian': {'product_id': item['product_id'], 'shop': item['shop'],
                                'complete': bool(official_after.get('shop_confirmed') and
                                                 official_after.get('protected')),
                                'matches_target': doudian_match,
                                'protected_match': official_protected,
                                'title': official_after.get('title'),
                                'main_count': len(official_after.get('mains') or []),
                                'detail_count': len(official_after.get('details') or []),
                                'draft_loaded': bool(official_after.get('draft_loaded')),
                                'rejected': bool(official_after.get('rejected'))},
                }
                if final_mappings:
                    evidence['final_asset_mappings'] = final_mappings
                result_state = record_execution_readback(task_id, owner, claim['execution_token'],
                                                         evidence, db_path=db_path)
                miao.stop_capture()
                results.append({'task_id': task_id, 'product_id': item['product_id'],
                                'state': result_state['state'], 'submission_state': result_state['submission_state'],
                                'readback_sha256': result_state['readback_sha256'],
                                'miao_matches': miao_match, 'doudian_matches': doudian_match})
            except Exception as exc:
                code = exc.code if isinstance(exc, DoudianError) else type(exc).__name__
                conn = _db(db_path)
                try:
                    current = conn.execute('SELECT state,submission_state FROM products WHERE id=?',
                                           (task_id,)).fetchone()
                finally:
                    conn.close()
                if submission_intent and current and current['state'] == 'submitting':
                    try:
                        record_submission_result(task_id, owner, claim['execution_token'],
                                                 {'state': 'unknown', 'error': code}, db_path=db_path)
                    except DoudianError:
                        pass
                elif current and current['state'] in ('ready', 'editing', 'uploaded'):
                    try:
                        fatal = code in {'agent_facts_stale', 'baseline_disagreement', 'baseline_changed',
                                         'doudian_draft_or_rejected', 'shelf_state_unknown', 'wrong_identity',
                                         'target_version_conflict', 'target_version_mismatch',
                                         'artifact_product_mismatch', 'artifact_manifest_changed',
                                         'protected_incomplete', 'baseline_incomplete',
                                         'shelf_mode_unpreservable'}
                        if fatal:
                            set_execution_state(task_id, 'blocked', error=code, db_path=db_path)
                        else:
                            record_execution_error(task_id, owner, claim['execution_token'], code, db_path=db_path)
                    except DoudianError:
                        pass
                conn = _db(db_path)
                try:
                    updated = conn.execute('SELECT state FROM products WHERE id=?', (task_id,)).fetchone()
                finally:
                    conn.close()
                results.append({'task_id': task_id, 'product_id': item['product_id'],
                                'state': updated['state'] if updated else 'blocked',
                                'reason': code, 'resumable': bool(current and current['state'] in ('ready','editing','uploaded')),
                                'message': str(exc) if isinstance(exc, DoudianError) else '浏览器操作异常，需按任务状态只读核查。'})
            finally:
                try:
                    release_execution(task_id, owner, claim['execution_token'], db_path=db_path)
                except DoudianError:
                    pass
        session_cleanup = _close_batch_session(bridge)
        task_tab_cleanup = _close_task_miaoshou_batch_tab(bridge)
        return {'run': results, 'recovered_legacy_versions': recovered_legacy,
                'continue_after_item_error': True,
                'browser_session_cleanup': session_cleanup,
                'task_batch_tab_cleanup': task_tab_cleanup,
                'completed': sum(1 for item in results if item.get('state') == 'verified'),
                'blocked': sum(1 for item in results if item.get('state') == 'blocked')}


def repair_accepted_title_mismatches(endpoint, *, product_ids, owner='codex-miaoshou-title-repair',
                                     db_path=None, session='miaoshou-title-repair-20261028'):
    """Correct only the title after an accepted save whose two reads still show the old title.

    The task must have exactly one accepted save already. Before this one corrective save,
    the routine independently proves that all 9 target image slots and the detail tail are
    correct, official protected fields still match the original baseline, and Miao's other
    editable fields are unchanged. It never repairs an unknown result or attempts a second
    title repair.
    """
    from .bridge import Bridge
    from .editor import Editor
    from .miaoshou_editor import MiaoshouEditor
    from .workflow import compare_protected

    requested = [str(pid) for pid in (product_ids or [])]
    if not requested or len(set(requested)) != len(requested) or len(requested) > 10:
        raise DoudianError('title_repair_scope', '标题修复必须指定1至10个不同商品ID。')
    status = batch_status(db_path=db_path)
    by_id = {product['product_id']: product for product in status['products']}
    candidates = []
    for pid in requested:
        item = by_id.get(pid)
        if (item and item['state'] == 'blocked' and item.get('submission_state') == 'accepted' and
                item.get('last_error') == 'readback_mismatch'):
            candidates.append(item)
    if not candidates:
        return {'run': [], 'message': '没有符合条件的“保存已受理、标题仍是旧值”修复任务。'}

    results = []
    with Lock(DATA_ROOT / 'browser.lock'):
        bridge = Bridge(endpoint, session=session, timeout=25)
        bridge.require_ready()
        _close_batch_session(bridge)
        for item in candidates:
            task_id = item['id']
            claim = claim_execution(task_id, owner, db_path=db_path, lease_seconds=7200)
            if claim is None:
                results.append({'task_id': task_id, 'product_id': item['product_id'],
                                'state': 'skipped', 'reason': 'another_browser_writer_active'})
                continue
            miao = None
            miao_after = None
            save_intent = False
            try:
                ready = load_ready_artifacts(task_id, db_path=db_path)
                manifest = ready['manifest']
                baseline = _stored_execution_baseline(claim, ready['manifest_sha256'])
                if manifest.get('product_id') != item['product_id']:
                    raise DoudianError('artifact_product_mismatch', '标题修复目标与批次商品ID不匹配。')
                mappings = json.loads(claim.get('upload_map_json') or '[]')
                identity = {'product_id': item['product_id'], 'shop': item['shop'],
                            'edit_url': f'https://{HOST}/ffa/g/create?product_id={item["product_id"]}'}
                official_before = _stable_doudian_snapshot(Editor(bridge), identity)
                if official_before.get('draft_loaded') or official_before.get('rejected'):
                    raise DoudianError('title_repair_draft_or_rejected', '抖店存在草稿或驳回状态，标题修复已停止。')
                miao = MiaoshouEditor(bridge, item['shop'], session=session)
                miao.open_product(item['product_id'], fresh=True)
                miao_before = miao.read_product(item['product_id'])
                miao.require_shelf_mode_preservable(
                    baseline.get('protected', {}).get('startSaleType'))
                if (miao_before.get('title') != baseline.get('title') or
                        official_before.get('title') != baseline.get('title') or
                        manifest.get('title') == baseline.get('title')):
                    raise DoudianError('title_repair_title_changed', '当前标题不再是修复前旧值，拒绝再次保存。')
                if (not _miaoshou_title_repair_fields_match(
                            miao_before.get('protected'), baseline.get('protected')) or
                        miao_before.get('protected', {}).get('status') !=
                        baseline.get('protected', {}).get('status')):
                    raise DoudianError('title_repair_miaoshou_fields_changed',
                                       '妙手非标题商品字段或当前上下架状态已变化，拒绝修复。')
                compare_protected(baseline['doudian_baseline'], official_before)
                final_before = _finalize_target_mappings(baseline, miao_before, official_before, mappings)
                proof = {
                    'read_only': True, 'product_id': item['product_id'], 'shop': item['shop'],
                    'target_version': ready['target_version'],
                    'manifest_sha256': ready['manifest_sha256'],
                    'previous_readback_sha256': claim.get('readback_hash'),
                    'current_title': miao_before['title'], 'target_title': manifest['title'],
                    'images_match': len(final_before) == 9,
                    'detail_tail_match': True, 'official_protected_match': True,
                    'miao_other_fields_match': True, 'shelf_status_matches': True,
                    'shelf_mode_matches_original': (
                        miao_before.get('protected', {}).get('startSaleType') ==
                        baseline.get('protected', {}).get('startSaleType')),
                }
                if not proof['shelf_mode_matches_original']:
                    raise DoudianError(
                        'title_repair_shelf_mode_changed',
                        '审核通过后的上架模式与原值不同；先从妙手页面恢复并读回该字段，再修复标题。')
                miao.fill_title(item['product_id'], manifest['title'])
                begin_title_repair_submission(task_id, owner, claim['execution_token'], proof,
                                              db_path=db_path)
                save_intent = True
                try:
                    result = miao.click_save_once()
                except Exception as exc:
                    result = {'state': 'unknown', 'error': getattr(exc, 'code', type(exc).__name__)}
                result_state = record_submission_result(task_id, owner, claim['execution_token'],
                                                        result, db_path=db_path)
                save_intent = False
                if result_state['submission_state'] != 'accepted':
                    results.append({'task_id': task_id, 'product_id': item['product_id'],
                                    'state': result_state['state'],
                                    'submission_state': result_state['submission_state'],
                                    'reason': result.get('error'), 'repair_kind': 'title-only'})
                    continue

                miao.stop_capture()
                miao_after_reader = MiaoshouEditor(bridge, item['shop'], session=session)
                miao_after_reader.open_product(item['product_id'], fresh=True)
                miao_after = miao_after_reader.read_product(item['product_id'])
                official_after = _stable_doudian_snapshot(Editor(bridge), identity)
                try:
                    final_after = _finalize_target_mappings(baseline, miao_after,
                                                            official_after, mappings)
                except DoudianError:
                    final_after = None
                miao_content = bool(final_after) and _matches_miaoshou_content(
                    baseline, miao_after, manifest['title'], final_after)
                miao_repair_fields = _miaoshou_protected_matches(
                    miao_after.get('protected'), baseline.get('protected'))
                try:
                    compare_protected(official_before, official_after)
                    official_repair_fields = True
                except DoudianError:
                    official_repair_fields = False
                doudian_match = bool(final_after) and _matches_doudian_target(
                    official_before, official_after, manifest['title'], final_after)
                shelf_mode_matches = (miao_after.get('protected', {}).get('startSaleType') ==
                                      baseline.get('protected', {}).get('startSaleType'))
                evidence = {
                    'target_version': ready['target_version'],
                    'manifest_sha256': ready['manifest_sha256'], 'read_only': True,
                    'repair_kind': 'title-only',
                    'previous_readback_sha256': claim.get('readback_hash'),
                    'miaoshou': {
                        'product_id': item['product_id'], 'shop': item['shop'],
                        'complete': bool(miao_after.get('protected_complete') and
                                         len(miao_after.get('mains') or []) == 5 and
                                         len(miao_after.get('details') or []) >= 4),
                        'matches_target': miao_content,
                        'protected_match': miao_repair_fields,
                        'title': miao_after.get('title'),
                        'main_count': len(miao_after.get('mains') or []),
                        'detail_count': len(miao_after.get('details') or []),
                        'shelf_status': miao_after.get('protected', {}).get('status'),
                        'review_status': miao_after.get('protected', {}).get('checkStatus'),
                        'start_sale_type': miao_after.get('protected', {}).get('startSaleType'),
                        'start_sale_type_before': baseline.get('protected', {}).get('startSaleType'),
                        'shelf_mode_matches_original': shelf_mode_matches,
                    },
                    'doudian': {
                        'product_id': item['product_id'], 'shop': item['shop'],
                        'complete': bool(official_after.get('shop_confirmed') and
                                         official_after.get('protected')),
                        'matches_target': doudian_match,
                        'protected_match': official_repair_fields,
                        'title': official_after.get('title'),
                        'main_count': len(official_after.get('mains') or []),
                        'detail_count': len(official_after.get('details') or []),
                        'draft_loaded': bool(official_after.get('draft_loaded')),
                        'rejected': bool(official_after.get('rejected')),
                    },
                }
                if final_after:
                    evidence['final_asset_mappings'] = final_after
                result_state = record_execution_readback(task_id, owner, claim['execution_token'],
                                                         evidence, db_path=db_path)
                miao_after_reader.stop_capture()
                results.append({'task_id': task_id, 'product_id': item['product_id'],
                                'state': result_state['state'],
                                'submission_state': result_state['submission_state'],
                                'readback_sha256': result_state['readback_sha256'],
                                'repair_kind': 'title-only', 'miao_title_matches': miao_content,
                                'doudian_matches': doudian_match,
                                'shelf_mode_matches_original': shelf_mode_matches})
            except Exception as exc:
                code = exc.code if isinstance(exc, DoudianError) else type(exc).__name__
                if save_intent:
                    try:
                        record_submission_result(task_id, owner, claim['execution_token'],
                                                 {'state': 'unknown', 'error': code}, db_path=db_path)
                    except DoudianError:
                        pass
                results.append({'task_id': task_id, 'product_id': item['product_id'],
                                'state': 'blocked', 'reason': code,
                                'message': str(exc) if isinstance(exc, DoudianError)
                                else '修复过程异常；保存状态按队列证据只读核查。'})
            finally:
                if miao:
                    miao.stop_capture()
                if miao_after:
                    miao_after.stop_capture()
                try:
                    release_execution(task_id, owner, claim['execution_token'], db_path=db_path)
                except DoudianError:
                    pass
        cleanup = _close_batch_session(bridge)
    return {'run': results, 'repair_kind': 'title-only', 'browser_session_cleanup': cleanup,
            'completed': sum(1 for item in results if item.get('state') == 'verified')}


def set_execution_state(task_id, state, *, submission_state=None, error=None, db_path=None):
    """Guarded state update for the browser executor; never changes unknown to retryable."""
    transitions = {
        'ready': {'editing', 'blocked'},
        'editing': {'uploaded', 'blocked'},
        'uploaded': {'submitting', 'blocked'},
        'submitting': {'submitted', 'verified', 'blocked', 'rejected'},
        'submitted': {'verified', 'blocked', 'rejected'},
        'blocked': {'verified', 'rejected'},
        'rejected': set(),
        'verified': set(),
    }
    allowed = set(transitions)
    if state not in allowed:
        raise DoudianError('invalid_state', '不支持的批次执行状态。')
    if state in ('submitting', 'submitted', 'verified', 'rejected'):
        raise DoudianError('evidence_required', '提交、受理、核验和驳回状态必须通过有证据的专用方法记录。')
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT state,submission_state,updated_at FROM products WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise DoudianError('task_not_found', '批次商品不存在。')
        if row['submission_state'] == 'unknown' and state != 'blocked':
            raise DoudianError('submission_unknown', '保存结果未知，只能保持隔离并完成只读核查。')
        if row['state'] == state == 'uploaded':
            conn.commit()
            return {'task_id': task_id, 'state': state, 'submission_state': row['submission_state']}
        if state not in transitions.get(row['state'], set()):
            raise DoudianError('invalid_transition', f"不允许从 {row['state']} 转为 {state}。")
        sub = submission_state or row['submission_state']
        if row['submission_state'] == 'unknown' and sub != 'unknown':
            raise DoudianError('cannot_clear_unknown', '未知提交结果不得由状态更新清除。')
        now = time.time()
        conn.execute('UPDATE products SET state=?,submission_state=?,last_error=?,updated_at=? WHERE id=?',
                     (state, sub, error, now, task_id))
        conn.execute('''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
                        VALUES(?,?,?,?,?,?)''', (task_id, row['state'], state, now,
                                                 max(0, now-row['updated_at']), error))
        conn.commit()
        return {'task_id': task_id, 'state': state, 'submission_state': sub}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
