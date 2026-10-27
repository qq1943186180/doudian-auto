"""Durable batch queue and agent hand-off for full listing revisions.

The queue stores only task metadata and local asset paths. It never stores browser
credentials or replays a site write request.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from .errors import DoudianError
from .jobs import DATA_ROOT, image_record, read_json
from .title import validate_title

DB_PATH = DATA_ROOT / 'batch.sqlite3'
LEASE_SECONDS = 900


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
            facts_json TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'needs_agent',
            lease_owner TEXT, lease_token TEXT, lease_until REAL,
            artifacts_path TEXT, artifacts_hash TEXT, submission_state TEXT NOT NULL DEFAULT 'not_attempted',
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
    return conn


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


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
            if conn.execute("SELECT 1 FROM products WHERE product_id=? AND state!='verified' LIMIT 1",
                            (pid,)).fetchone():
                conflict = f'商品 {pid} 已在另一个妙手批次中，需先核实或结案。'
            if Path(db_path or DB_PATH).resolve() == DB_PATH.resolve():
                conflict = conflict or _active_doudian_job_conflict(pid)
            if product.get('submission_status') == 'unknown' or product.get('stage') in (
                    'editing', 'uploaded', 'submitting', 'submitted'):
                conflict = conflict or '导入记录显示存在未完成或结果未知的旧任务，先只读核查。'
            facts = {k: v for k, v in product.items() if k not in ('shop', 'product_id', 'productId')}
            if 'source_title' not in facts and product.get('name'):
                facts['source_title'] = product['name']
            conn.execute('''INSERT INTO products(batch_id,shop,product_id,source,facts_json,state,last_error,updated_at)
                            VALUES(?,?,?,?,?,?,?,?)''',
                         (batch_id, product_shop, pid, json.dumps({**product, 'shop': product_shop,
                                                                  'product_id': pid,
                                                                  'source_title': facts.get('source_title')}, ensure_ascii=False),
                          json.dumps(facts, ensure_ascii=False), 'blocked' if conflict else 'needs_agent',
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


def _active_doudian_job_conflict(product_id):
    jobs_root = DATA_ROOT / 'jobs'
    if not jobs_root.exists():
        return None
    active = {'editing', 'uploaded', 'submitting', 'submitted', 'rejected'}
    for manifest_path in jobs_root.glob('*/manifest.json'):
        try:
            manifest = read_json(manifest_path)
            if str(manifest.get('product_id')) != str(product_id):
                continue
            state_path = manifest_path.parent / 'state.json'
            state = read_json(state_path) if state_path.exists() else {}
        except (OSError, ValueError, TypeError):
            return f'商品 {product_id} 存在无法读取的抖店任务记录，先人工核对。'
        if state.get('stage') in active or state.get('submission_status') == 'unknown':
            return f'商品 {product_id} 有未结案的抖店任务，需只读核查后再编辑。'
    return None


def claim_next(owner, *, batch_id=None, db_path=None, lease_seconds=LEASE_SECONDS):
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
    if not isinstance(details, list) or len(details) < 4:
        raise DoudianError('invalid_details', '必须提供至少4张详情图。')
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
        return {'task_id': task_id, 'state': 'ready', 'title': manifest['title'],
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
            f'''SELECT id,batch_id,shop,product_id,state,submission_state,last_error,updated_at
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
        row = conn.execute('SELECT product_id,state,artifacts_path,artifacts_hash FROM products WHERE id=?',
                           (task_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row['state'] != 'ready' or not row['artifacts_path']:
        raise DoudianError('artifacts_not_ready', '商品没有通过素材准备阶段。')
    path = Path(row['artifacts_path'])
    if not path.is_file() or _digest(path) != row['artifacts_hash']:
        raise DoudianError('artifact_manifest_changed', '素材清单在验收后发生变化，请重新提交校验。')
    manifest = validate_agent_artifacts(path, row['product_id'])
    return {'path': str(path), 'manifest': manifest, 'manifest_sha256': row['artifacts_hash']}


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


def execution_readiness(endpoint):
    """Probe the browser only; refuse mutations until the Miaoshou writer is verified."""
    from .bridge import Bridge

    status = Bridge(endpoint, session='miaoshou-batch-doctor').status()
    ready = bool(status.get('running') and status.get('extension_connected') and
                 not status.get('version_mismatch'))
    return {'browser_ready': ready, 'bridge': status, 'writer_ready': False,
            'reason': '妙手批量写入器尚未通过当前登录页面的真实控件与保存响应验收；此命令未操作商品。'}


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
    conn = _db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT state,submission_state,updated_at FROM products WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise DoudianError('task_not_found', '批次商品不存在。')
        if row['submission_state'] == 'unknown' and state != 'blocked':
            raise DoudianError('submission_unknown', '保存结果未知，只能保持隔离并完成只读核查。')
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
