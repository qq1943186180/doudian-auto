"""核销一次「已被服务端明确判定失败」的提交，并把该行重新排为待素材任务。

背景：一次写入可能只拿到 HTTP 200、没有业务响应，队列因此停在 `unknown`。之后若从平台
自己的任务记录里取得「终结且零成功」的终态，并确认商品双端与基线完全一致，那么这次提交
在事实上没有产生任何变更，可以结清——但不能凭"看起来没变"就清，必须绑定可核验的证据。

本模块只做两件事，且都要求证据齐全：记录核销事件（保留历史），把行重置为可以重新预检的
形态。它不会、也不能把一个真正生效过的提交抹掉：`success_count` 必须为 0，且双端读回必须
逐项与基线相等。
"""

import hashlib
import json
import time
from pathlib import Path

from . import batch
from .errors import DoudianError

SCHEMA_VERSION = 1
# 证据只在这段时间内有效：终态与读回必须是刚刚观察到的，不能拿几天前的截图结案。
STALE_SECONDS = 30 * 60
REQUIRED_UNCHANGED = ('title', 'mains', 'details', 'protected')
FAILED_REQUEUE_PREFIX = batch.PRIOR_SAVE_FAILED_PREFIX + ' '


def _require(condition, message):
    if not condition:
        raise DoudianError('requeue_failed_unproven', message)


def requeue_failed_submission(task_id, proof_path, *, db_path=None):
    """结清一次零变更的失败提交，并把它放回可重新预检的状态。

    proof 必须同时证明：

    - 它属于这一行（product/shop/target_version/baseline_hash/artifacts_hash 全部相等）；
    - 平台任务**已经终结**（finished）、**成功数为 0**、**失败数 >= 1** 且给出了失败原因；
    - 双端只读读回的标题、主图、详情、受保护商业字段**全部与基线相同**；
    - 观察时间足够新。

    任一条不满足即抛 `requeue_failed_unproven`，行保持原样。成功时把原来的提交意图写入事件
    留档，再把 baseline/artifacts/upload_map/readback 清空、`submission_state` 归为
    `not_attempted`，并把 `last_error` 标成可重新预检的前缀。
    """
    proof = batch.read_json(Path(proof_path).resolve())
    conn = batch._db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        record = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        _require(record is not None, '队列中没有该任务。')
        row = dict(record)
        now = time.time()

        _require(row['state'] == 'blocked' and row['submission_state'] == 'unknown' and
                 int(row['submission_attempts'] or 0) == 1,
                 '只有 blocked/unknown/attempts=1 的提交可以按此路径结清。')
        _require(not any((row[key] or 0) >= now for key in ('lease_until', 'execution_until')),
                 '该任务仍被占用，不能结清。')
        _require(not conn.execute('SELECT 1 FROM products WHERE shop=? AND product_id=? AND id!=?',
                                  (row['shop'], row['product_id'], task_id)).fetchone(),
                 '该商品另有队列版本，先核对现有任务。')

        _require(isinstance(proof, dict) and proof.get('schema_version') == SCHEMA_VERSION,
                 '证据格式不可识别。')
        _require(proof.get('read_only') is True, '证据必须来自只读观察。')
        _require(str(proof.get('task_id')) == str(task_id) and
                 proof.get('product_id') == row['product_id'] and
                 proof.get('shop') == row['shop'] and
                 proof.get('target_version') == row['target_version'] and
                 proof.get('baseline_sha256') == row['baseline_hash'] and
                 proof.get('manifest_sha256') == row['artifacts_hash'],
                 '证据没有绑定到这一行的当前版本与基线。')

        observed = proof.get('observed_at')
        _require(type(observed) in (int, float) and 0 < observed and abs(now - observed) <= STALE_SECONDS,
                 '证据已过期，需要重新只读观察。')

        task = proof.get('miaoshou_task') if isinstance(proof.get('miaoshou_task'), dict) else {}
        reasons = task.get('reasons')
        # 平台任务必须能被指认，而且要指认到这个商品：只断言"某任务失败了"是不够的。
        _require(isinstance(task.get('task_id'), str) and task['task_id'].strip(),
                 '平台任务没有可指认的任务号。')
        _require(task.get('product_id_confirmed') == row['product_id'],
                 '平台任务详情没有确认属于该商品。')
        _require(task.get('finished') is True, '平台任务尚未终结。')
        _require(task.get('success_count') == 0, '平台任务有成功项，不能按零变更结清。')
        _require(type(task.get('fail_count')) is int and task['fail_count'] >= 1,
                 '平台任务没有失败项，证据与结论不符。')
        _require(isinstance(reasons, list) and any(isinstance(x, str) and x.strip() for x in reasons),
                 '平台任务没有给出失败原因。')

        unchanged = proof.get('unchanged') if isinstance(proof.get('unchanged'), dict) else {}
        for key in REQUIRED_UNCHANGED:
            _require(unchanged.get(key) is True, f'未证明 {key} 与基线一致。')

        reason = '; '.join(str(x).strip()[:120] for x in reasons if isinstance(x, str) and x.strip())[:300]
        prior_intent = row['submission_intent_json']
        # 清空基线前，把足以独立复核"零变更"的那部分留档：只留哈希无法再验证结论。
        prior_baseline = None
        if row['baseline_json']:
            try:
                saved = json.loads(row['baseline_json'])
            except ValueError:
                saved = {}
            if isinstance(saved, dict):
                prior_baseline = {
                    'title': saved.get('title'),
                    'mains': saved.get('mains'),
                    'details': saved.get('details'),
                    'protected': saved.get('protected'),
                    'slot_plan': saved.get('slot_plan'),
                    'baseline_sha256': row['baseline_hash'],
                }
        conn.execute(
            '''UPDATE products SET state='blocked', submission_state='not_attempted',
                    submission_attempts=0, baseline_json=NULL, baseline_hash=NULL,
                    artifacts_path=NULL, artifacts_hash=NULL, upload_map_json='[]',
                    readback_json=NULL, readback_hash=NULL,
                    last_error=?, updated_at=? WHERE id=?''',
            (FAILED_REQUEUE_PREFIX + ' ' + reason, now, task_id))
        conn.execute(
            '''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
               VALUES(?,?,?,?,?,?)''',
            (task_id, 'blocked', 'blocked', now, None, json.dumps({
                'action': 'requeue_failed_submission',
                'miaoshou_task': task,
                'prior_submission_intent_sha256':
                    hashlib.sha256(prior_intent.encode('utf-8')).hexdigest() if prior_intent else None,
                'prior_baseline': prior_baseline,
                'unchanged': {key: True for key in REQUIRED_UNCHANGED},
                'reason': reason,
            }, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return {'task_id': task_id, 'state': 'blocked', 'submission_state': 'not_attempted',
                'last_error': FAILED_REQUEUE_PREFIX + ' ' + reason}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
