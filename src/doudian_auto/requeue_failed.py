"""核销一次「已被服务端明确判定失败」的提交，并把该行重新排为待素材任务。

背景：一次写入可能只拿到 HTTP 200、没有业务响应，队列因此停在 `unknown`。之后若从平台
自己的任务记录里取得「终结且零成功」的终态，并确认商品双端与基线完全一致，那么这次提交
在事实上没有产生任何变更，可以结清——但不能凭"看起来没变"就清，必须绑定可核验的证据。

本模块只做两件事，且都要求证据齐全：记录核销事件（保留历史），把行重置为可以重新预检的
形态。它不会、也不能把一个真正生效过的提交抹掉：`success_count` 必须为 0，且双端读回必须
逐项与基线相等。
"""

from collections import Counter
import hashlib
import json
import math
import time
from pathlib import Path

from . import batch
from .errors import DoudianError
from .official_skus import compare_official_skus, verify_miaoshou_skus
from .visual_review import _bound_file
from .workflow import (
    _inactive_size_option_content,
    _normalize_images,
    _section_index,
    resource_key,
)

SCHEMA_VERSION = 1
# 证据只在这段时间内有效：终态与读回必须是刚刚观察到的，不能拿几天前的截图结案。
STALE_SECONDS = 30 * 60
REQUIRED_UNCHANGED = ('title', 'mains', 'details', 'protected')
FAILED_REQUEUE_PREFIX = batch.PRIOR_SAVE_FAILED_PREFIX + ' '


def _require(condition, message):
    if not condition:
        raise DoudianError('requeue_failed_unproven', message)


_EMPTY_MAIN_VIDEO_OLD = '主图视频 发布优质主图视频，介绍商品卖点，展示试穿试用效果，预计 转化率+0.5%'
_EMPTY_MAIN_VIDEO_NEW = _EMPTY_MAIN_VIDEO_OLD + ' 一键生成'


def _canonicalize_empty_main_video(section_name, block):
    if section_name != '图文信息' or not isinstance(block, dict):
        return block
    fields = block.get('static_fields')
    if not isinstance(fields, list):
        return block
    changed = False
    new_fields = []
    for entry in fields:
        if (isinstance(entry, dict)
                and entry.get('field') == '主图视频'
                and entry.get('text') == _EMPTY_MAIN_VIDEO_NEW):
            new_fields.append({**entry, 'text': _EMPTY_MAIN_VIDEO_OLD})
            changed = True
        else:
            new_fields.append(entry)
    return {**block, 'static_fields': new_fields} if changed else block


def _validate_attribute_backfill(row, proof, proof_dir, saved_baseline, now):
    """Validate an audited post-failure required-attribute completion for `requeue_failed`."""
    additions = proof.get('expected_attribute_additions')
    _require(isinstance(additions, list) and len(additions) >= 1,
             '缺少经审核的 expected_attribute_additions 属性补齐明细。')
    expected_map = {}
    expected_values = set()
    for entry in additions:
        _require(isinstance(entry, dict), '属性补齐条目格式无效。')
        field = str(entry.get('field') or '').strip()
        vals = entry.get('values')
        _require(field and isinstance(vals, list) and vals and all(isinstance(v, str) and v.strip() for v in vals),
                 f'属性补齐条目 {field!r} 缺少非空合法值。')
        _require(field not in expected_map, f'属性 {field} 重复声明。')
        clean_vals = [v.strip() for v in vals]
        expected_map[field] = clean_vals
        expected_values.update(clean_vals)

    interventions = proof.get('interventions')
    _require(isinstance(interventions, list) and len(interventions) >= 1
             and all(isinstance(x, dict) and str(x.get('action') or '').strip() for x in interventions),
             '缺少人工修复与下架核验介入留档（interventions）。')

    snapshots = proof.get('snapshots') if isinstance(proof.get('snapshots'), dict) else {}
    miao_ref = snapshots.get('miaoshou')
    dd_ref = snapshots.get('doudian')
    miao_file = _bound_file(miao_ref, proof_dir, 'requeue_failed_unproven')
    dd_file = _bound_file(dd_ref, proof_dir, 'requeue_failed_unproven')
    for f, ref in ((miao_file, miao_ref), (dd_file, dd_ref)):
        _require(0 <= now - f.stat().st_mtime <= STALE_SECONDS, '实时双端快照已过期。')
        if isinstance(ref, dict) and ref.get('sha256'):
            _require(batch._digest(f) == ref['sha256'], '实时双端快照哈希与证明不一致。')
    miao = batch.read_json(miao_file)
    official = batch.read_json(dd_file)

    _require(official.get('product_id') == row['product_id']
             and official.get('shop_confirmed') is True
             and official.get('shop', row['shop']) == row['shop']
             and not official.get('draft_loaded') and not official.get('rejected'),
             '官方最新快照身份异常或仍存在草稿/驳回状态。')
    _require(miao.get('product_id') == row['product_id']
             and miao.get('shop') == row['shop']
             and miao.get('protected_complete') is True
             and miao.get('protected', {}).get('status') == 1,
             '妙手最新快照未绑定本品或未处于下架状态（status=1）。')

    orig_dd = saved_baseline.get('doudian_baseline')
    _require(isinstance(orig_dd, dict), '原队列基线缺少 doudian_baseline，不能按属性差异核清。')
    _require(official.get('title') == saved_baseline.get('title') == miao.get('title'),
             '补齐属性期间商品标题发生变化，禁止走零变更重置。')
    orig_main_keys = [resource_key(x) for x in (saved_baseline.get('mains') or [])]
    orig_detail_keys = [resource_key(x) for x in (saved_baseline.get('details') or [])]
    _require([resource_key(x) for x in (official.get('mains') or [])] == orig_main_keys
             and [resource_key(x) for x in (miao.get('mains') or [])] == orig_main_keys,
             '补齐属性期间主图发生变化，禁止重置。')
    _require([resource_key(x) for x in (official.get('details') or [])] == orig_detail_keys
             and [resource_key(x) for x in (miao.get('details') or [])] == orig_detail_keys,
             '补齐属性期间详情图发生变化，禁止重置。')

    compare_official_skus(orig_dd.get('sku_evidence'), official.get('sku_evidence'))
    verify_miaoshou_skus(miao, official.get('sku_evidence'))

    req = official.get('required_attributes') if isinstance(official.get('required_attributes'), dict) else {}
    _require(req.get('observed') is True and req.get('completion_percent') == 100 and req.get('missing') == [],
             '最新官方必填类目属性仍未达到 100% 完成。')
    by_name = {f.get('name'): f.get('values') for f in (req.get('fields') or []) if isinstance(f, dict)}
    for field, clean_vals in expected_map.items():
        actual_vals = [str(v).strip() for v in (by_name.get(field) or [])]
        _require(sorted(actual_vals) == sorted(clean_vals),
                 f'官方最新属性 {field} 值 {actual_vals} 与声明的补齐值 {clean_vals} 不一致。')

    base_sec = _section_index(orig_dd)
    curr_sec = _section_index(official)
    _require(set(base_sec) == set(curr_sec) and '基础信息' in curr_sec,
             '官方受保护分区集合与原基线不一致。')
    actual_added_selections = []
    for name in sorted(curr_sec):
        left_blk = _canonicalize_empty_main_video(
            name, _normalize_images(_inactive_size_option_content(base_sec[name], full_skus_compared=True)))
        right_blk = _canonicalize_empty_main_video(
            name, _normalize_images(_inactive_size_option_content(curr_sec[name], full_skus_compared=True)))
        if name != '基础信息':
            _require(left_blk == right_blk, f'非基础信息受保护分区 {name} 存在差异，拒绝重置。')
        else:
            for key in ('images', 'static_fields', 'inputs'):
                _require(left_blk.get(key) == right_blk.get(key),
                         f'基础信息分区字段 {key} 与原基线不一致，拒绝重置。')
            b_sel = [x for x in (left_blk.get('selections') or []) if x]
            c_sel = [x for x in (right_blk.get('selections') or []) if x]
            b_counts, c_counts = Counter(b_sel), Counter(c_sel)
            _require(not (b_counts - c_counts),
                     f'基础信息原已选属性值被修改或删除：{dict(b_counts - c_counts)}。')
            added_counts = c_counts - b_counts
            _require(bool(added_counts), '基础信息未观测到新增属性选择项。')
            _require(set(added_counts).issubset(expected_values) and expected_values.issubset(set(added_counts)),
                     f'基础信息新增选项 {sorted(added_counts)} 与预期补齐值 {sorted(expected_values)} 不一致。')
            actual_added_selections = sorted(added_counts)

    orig_prot = saved_baseline.get('protected') or {}
    curr_prot = miao.get('protected') or {}
    shelf_policy = None
    for key in ('categoryId', 'brandId', 'freightId', 'deliveryMethod', 'deliveryDelayDay',
                'afterSaleService', 'reduceType', 'minimumPerOrder', 'maximumPerOrder',
                'limitPerBuyer', 'startSaleType', 'status'):
        if key in orig_prot or key in curr_prot:
            if key == 'startSaleType' and orig_prot.get(key) != curr_prot.get(key):
                _require(type(orig_prot.get('status')) is int and orig_prot.get('status') == 1
                         and type(curr_prot.get('status')) is int and curr_prot.get('status') == 1
                         and type(orig_prot.get('startSaleType')) is int and orig_prot.get('startSaleType') == 0
                         and type(curr_prot.get('startSaleType')) is int and curr_prot.get('startSaleType') == 1,
                         '妙手受保护商业字段 startSaleType 仅允许下架商品（status=1）从 0 转为 1（保留仓库），拒绝重置。')
                shelf_policy = batch._warehouse_shelf_preservation(curr_prot, orig_prot)
                _require(shelf_policy is not None,
                         '妙手仓库保留策略校验未通过，拒绝重置。')
                _require(any(isinstance(x, dict) and x.get('preserves_warehouse_shelf') is True for x in interventions),
                         '缺少显式仓库保留介入声明（preserves_warehouse_shelf: true），拒绝重置。')
            else:
                _require(orig_prot.get(key) == curr_prot.get(key),
                         f'妙手受保护商业字段 {key} 发生变化，拒绝重置。')

    result = {
        'expected_attribute_additions': expected_map,
        'actual_added_selections': actual_added_selections,
        'interventions': interventions,
        'doudian_snapshot_sha256': batch._digest(dd_file),
        'miaoshou_snapshot_sha256': batch._digest(miao_file),
        'doudian_status': 1,
        'miaoshou_status': curr_prot.get('status'),
    }
    if shelf_policy is not None:
        result['warehouse_shelf_preservation'] = shelf_policy
    return result


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
    proof_file = Path(proof_path).resolve()
    proof = batch.read_json(proof_file)
    proof_sha256 = batch._digest(proof_file)
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
        _require(type(observed) in (int, float) and math.isfinite(observed) and 0 < observed and abs(now - observed) <= STALE_SECONDS,
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

        saved = {}
        if row['baseline_json']:
            try:
                loaded = json.loads(row['baseline_json'])
                if isinstance(loaded, dict):
                    saved = loaded
            except ValueError:
                saved = {}

        unchanged = proof.get('unchanged') if isinstance(proof.get('unchanged'), dict) else {}
        has_attr_backfill = 'expected_attribute_additions' in proof
        attr_audit = None
        if has_attr_backfill:
            for key in ('title', 'mains', 'details'):
                _require(unchanged.get(key) is True, f'未证明 {key} 与基线一致。')
            attr_audit = _validate_attribute_backfill(row, proof, proof_file.parent, saved, now)
        else:
            for key in REQUIRED_UNCHANGED:
                _require(unchanged.get(key) is True, f'未证明 {key} 与基线一致。')

        reason = '; '.join(str(x).strip()[:120] for x in reasons if isinstance(x, str) and x.strip())[:300]
        prior_intent = row['submission_intent_json']
        # 清空基线前，把足以独立复核"零变更"的那部分留档：只留哈希无法再验证结论。
        prior_baseline = None
        if saved:
            prior_baseline = {
                'title': saved.get('title'),
                'mains': saved.get('mains'),
                'details': saved.get('details'),
                'protected': saved.get('protected'),
                'doudian_baseline': saved.get('doudian_baseline'),
                'slot_plan': saved.get('slot_plan'),
                'baseline_sha256': row['baseline_hash'],
            }
        conn.execute(
            '''UPDATE products SET state='blocked', submission_state='not_attempted',
                    submission_attempts=0, baseline_json=NULL, baseline_hash=NULL,
                    artifacts_path=NULL, artifacts_hash=NULL, upload_map_json='[]',
                    submission_intent_json=NULL, writer_preparation_json=NULL,
                    readback_json=NULL, readback_hash=NULL,
                    last_error=?, updated_at=? WHERE id=?''',
            (FAILED_REQUEUE_PREFIX + ' ' + reason, now, task_id))
        event_detail = {
            'action': 'requeue_failed_submission',
            'proof_sha256': proof_sha256,
            'miaoshou_task': task,
            'prior_submission_intent_sha256':
                hashlib.sha256(prior_intent.encode('utf-8')).hexdigest() if prior_intent else None,
            'prior_baseline': prior_baseline,
            'unchanged': ({key: True for key in ('title', 'mains', 'details')}
                          if has_attr_backfill else {key: True for key in REQUIRED_UNCHANGED}),
            'reason': reason,
        }
        if attr_audit is not None:
            event_detail['conclusion'] = 'original attempt failed with zero successes; subsequent manual repairs audited'
            event_detail['attribute_backfill'] = attr_audit
        conn.execute(
            '''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
               VALUES(?,?,?,?,?,?)''',
            (task_id, 'blocked', 'blocked', now, None,
             json.dumps(event_detail, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        return {'task_id': task_id, 'state': 'blocked', 'submission_state': 'not_attempted',
                'last_error': FAILED_REQUEUE_PREFIX + ' ' + reason,
                **({'attribute_backfill': attr_audit} if attr_audit is not None else {})}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
