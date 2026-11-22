"""Audited read-only verification for legacy `readback_mismatch` caused solely by virtual SKU grid mount width."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import batch
from .errors import DoudianError
from .official_skus import compare_official_skus, verify_miaoshou_skus
from .visual_review import _bound_file
from .workflow import (
    _REQUIRED_SECTIONS,
    _content,
    _inactive_size_option_content,
    _normalize_images,
    _observations,
    _section_index,
    is_permanent_material_url,
    resource_key,
)

_MAX_AGE_SECONDS = 30 * 60
_HASH_RE = re.compile(r'[0-9a-f]{64}', re.I)


def _fail(code='legacy_readback_unproven', message='历史读回证据不足以排除商业字段变化，保持隔离。'):
    return DoudianError(code, message)


def _json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise _fail('legacy_readback_unproven', '证据或观测文件无法读取。') from exc


def _price_equal(left, right):
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return str(left) == str(right)


def _validate_virtual_sku_chunk(middle, by_code, *, offset=0, allow_empty=False):
    """Validate that `middle` consists strictly of 6-control SKU rows bound to `by_code`."""
    if not middle:
        if allow_empty:
            return []
        raise _fail(message='差异控件无法整组对应为 6 控件虚拟 SKU 行。')
    if len(middle) % 6 != 0:
        raise _fail(message='差异控件无法整组对应为 6 控件虚拟 SKU 行。')
    bound_rows = []
    seen_codes = set()
    for start in range(0, len(middle), 6):
        chunk = middle[start:start + 6]
        # Exact 6-control Doudian SKU row signature: [price, radio_on(1), radio_off(-1), step_stock, code, custom_note]
        price_el, r_on, r_off, step_el, code_el, extra_el = chunk
        code = code_el.get('value')
        price_val = price_el.get('value')
        if (price_el.get('type') != 'text'
                or r_on.get('type') != 'radio' or r_on.get('value') != '1'
                or r_off.get('type') != 'radio' or r_off.get('value') != '-1'
                or step_el.get('type') != 'number'
                or code_el.get('type') != 'text' or not isinstance(code, str) or code not in by_code
                or code in seen_codes
                or extra_el.get('type') != 'text'):
            raise _fail(message=f'虚拟 SKU 行结构或编码绑定失败（chunk index {offset + start}）。')
        auth = by_code[code]
        if not _price_equal(price_val, auth.get('price')) or bool(r_on.get('checked')) is not bool(auth.get('sku_status')):
            raise _fail(message=f'SKU 行 {code} 价格或启用状态与权威 SKU 证据不一致。')
        seen_codes.add(code)
        bound_rows.append({'sku_id': str(auth.get('sku_id')), 'code': code, 'price': str(price_val)})
    return bound_rows


def _strip_validated_legacy_sku_grid(legacy_inputs, target_inputs_without_grid, raw_rows,
                                     *, right_inputs=None):
    """Strip ONLY validated virtual SKU grid rows from legacy `价格库存.inputs`.

    Returns ``(grid_free_inputs, bound_sku_rows, diff_report)``. Raises if any
    difference exists outside virtual SKU rows explicitly bound by code & price
    to authoritative ``sku_evidence.raw_rows``. When ``inputs_without_sku_grid``
    also excludes a non-SKU ``tr[data-row-key]`` size table inside ``价格库存``,
    falls back to strict symmetric comparison against ``right_inputs`` where BOTH
    sides' diff spans must validate as pure 6-control virtual SKU rows.
    """
    if not isinstance(legacy_inputs, list) or not isinstance(target_inputs_without_grid, list):
        raise _fail(message='价格库存控件列表缺失，无法核对。')
    if not isinstance(raw_rows, list) or not raw_rows:
        raise _fail(message='缺少权威 SKU 明细，无法识别虚拟列表行。')

    by_code = {str(r.get('code') or ''): r for r in raw_rows if isinstance(r, dict) and r.get('code')}
    if len(by_code) != len(raw_rows):
        raise _fail(message='权威 SKU 商家编码不唯一，拒绝按网格推断。')

    def match_edges(left_list, right_list):
        p = 0
        while p < len(left_list) and p < len(right_list) and left_list[p] == right_list[p]:
            p += 1
        s = 0
        max_s = min(len(left_list) - p, len(right_list) - p)
        while s < max_s and left_list[-1 - s] == right_list[-1 - s]:
            s += 1
        return p, s

    prefix_len, suffix_len = match_edges(legacy_inputs, target_inputs_without_grid)
    if prefix_len + suffix_len == len(target_inputs_without_grid):
        middle_end = len(legacy_inputs) - suffix_len if suffix_len else len(legacy_inputs)
        bound_rows = _validate_virtual_sku_chunk(legacy_inputs[prefix_len:middle_end], by_code, offset=prefix_len)
        stripped = legacy_inputs[:prefix_len] + (legacy_inputs[middle_end:] if suffix_len else [])
        if stripped != target_inputs_without_grid:
            raise _fail(message='剔除已绑定 SKU 行后仍与最新非网格控件不一致。')
        diff_report = {
            'prefix_matched': prefix_len,
            'suffix_matched': suffix_len,
            'legacy_total_inputs': len(legacy_inputs),
            'live_inputs_without_sku_grid': len(target_inputs_without_grid),
            'stripped_virtual_sku_rows': len(bound_rows),
            'bound_sku_codes': [item['code'] for item in bound_rows],
        }
        return stripped, bound_rows, diff_report

    if not isinstance(right_inputs, list):
        raise _fail(message='剔除虚拟 SKU 网格后，价格库存非网格控件仍存在差异。')

    prefix_raw, suffix_raw = match_edges(legacy_inputs, right_inputs)
    # When both sides start with identical virtual SKU rows, `match_edges` may stop mid-row;
    # back up by at most 5 elements on prefix/suffix so both sides align cleanly to 6-control chunks.
    aligned = None
    for dp in range(6):
        p = prefix_raw - dp
        if p < 0:
            break
        for ds in range(6):
            s = suffix_raw - ds
            if s < 0 or p + s > min(len(legacy_inputs), len(right_inputs)):
                continue
            le = len(legacy_inputs) - s if s else len(legacy_inputs)
            re_ = len(right_inputs) - s if s else len(right_inputs)
            lm, rm = legacy_inputs[p:le], right_inputs[p:re_]
            if (lm or rm) and len(lm) % 6 == 0 and len(rm) % 6 == 0:
                try:
                    bl = _validate_virtual_sku_chunk(lm, by_code, offset=p, allow_empty=True)
                    br = _validate_virtual_sku_chunk(rm, by_code, offset=p, allow_empty=True)
                    aligned = (p, s, le, re_, bl, br)
                    break
                except DoudianError:
                    continue
        if aligned is not None:
            break
    if aligned is None:
        raise _fail(message='剔除虚拟 SKU 网格后，价格库存非网格控件仍存在差异。')

    prefix_len, suffix_len, left_end, right_end, bound_left, bound_right = aligned
    left_stripped = legacy_inputs[:prefix_len] + (legacy_inputs[left_end:] if suffix_len else [])
    right_stripped = right_inputs[:prefix_len] + (right_inputs[right_end:] if suffix_len else [])
    if left_stripped != right_stripped or not right_stripped:
        raise _fail(message='剔除虚拟 SKU 网格后，价格库存非网格控件仍存在差异。')
    diff_report = {
        'prefix_matched': prefix_len,
        'suffix_matched': suffix_len,
        'legacy_total_inputs': len(legacy_inputs),
        'live_total_inputs': len(right_inputs),
        'live_inputs_without_sku_grid': len(target_inputs_without_grid),
        'non_sku_inputs_matched': len(left_stripped),
        'stripped_legacy_virtual_sku_rows': len(bound_left),
        'stripped_live_virtual_sku_rows': len(bound_right),
        'bound_sku_codes': [item['code'] for item in bound_left],
        'live_bound_sku_codes': [item['code'] for item in bound_right],
    }
    return left_stripped, bound_left or bound_right, diff_report


def verify_legacy_sku_grid_readback(task_id, proof_path, *, db_path=None):
    """Independently verify and close a legacy `readback_mismatch` task with fresh dual reads."""
    proof_file = Path(proof_path).resolve()
    try:
        proof_bytes = proof_file.read_bytes()
        proof_sha256 = hashlib.sha256(proof_bytes).hexdigest()
        proof = json.loads(proof_bytes.decode('utf-8-sig'))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise _fail(message='结案证明文件无法读取。') from exc

    conn = batch._db(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        record = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        if record is None:
            raise DoudianError('unknown_task', '队列里没有这个任务。')
        row = dict(record)
        now = time.time()

        if (row['state'] != 'blocked' or row['submission_state'] != 'unknown'
                or int(row['submission_attempts'] or 0) != 1
                or row['last_error'] != 'readback_mismatch'
                or not row['baseline_json'] or not row['baseline_hash']
                or any((row[key] or 0) >= now for key in ('lease_until', 'execution_until'))
                or row['execution_owner'] is not None or row['execution_token'] is not None):
            raise _fail(message='仅允许对 blocked/unknown/attempts=1/readback_mismatch 且无并发租约的历史任务核销。')
        if conn.execute('SELECT 1 FROM products WHERE shop=? AND product_id=? AND id!=?',
                        (row['shop'], row['product_id'], task_id)).fetchone():
            raise _fail(message='同店同品存在其他队列版本，拒绝核销。')
        if batch._active_doudian_job_conflict(row['shop'], row['product_id']):
            raise _fail(message='同店同品存在未结案的官方任务，拒绝核销。')

        if (not isinstance(proof, dict) or proof.get('read_only') is not True
                or not str(proof.get('reviewer') or '').strip()
                or str(proof.get('task_id')) != str(task_id)
                or proof.get('product_id') != row['product_id'] or proof.get('shop') != row['shop']
                or proof.get('target_version') != row['target_version']
                or proof.get('baseline_sha256') != row['baseline_hash']
                or proof.get('manifest_sha256') != row['artifacts_hash']):
            raise _fail(message='证明未绑定本任务的店铺、商品、版本、基线或素材摘要。')

        observed = proof.get('observed_at')
        if (type(observed) not in (int, float) or not math.isfinite(observed)
                or not 0 <= now - observed <= _MAX_AGE_SECONDS
                or not 0 <= now - proof_file.stat().st_mtime <= _MAX_AGE_SECONDS):
            raise _fail(message='证明时间或文件修改时间不在 30 分钟有效期内。')

        miao_ref = proof.get('miaoshou')
        dd_ref = proof.get('doudian')
        miao_file = _bound_file(miao_ref, proof_file.parent, 'legacy_readback_unproven')
        dd_file = _bound_file(dd_ref, proof_file.parent, 'legacy_readback_unproven')
        for f, ref in ((miao_file, miao_ref), (dd_file, dd_ref)):
            if not 0 <= now - f.stat().st_mtime <= _MAX_AGE_SECONDS:
                raise _fail(message='实时观测文件不在 30 分钟有效期内。')
            if isinstance(ref, dict) and ref.get('sha256') and batch._digest(f) != ref['sha256']:
                raise _fail(message='实时观测文件哈希与证明不一致。')

        miao_after = _json_file(miao_file)
        official_after = _json_file(dd_file)
        baseline = json.loads(row['baseline_json'])
        official_before = baseline.get('doudian_baseline')
        if not isinstance(official_before, dict):
            raise _fail(message='历史 baseline 缺少官方完整基线快照。')

        # 1. Verify identity & draft/rejected status
        if (miao_after.get('product_id') != row['product_id'] or miao_after.get('shop') != row['shop']
                or miao_after.get('protected_complete') is not True):
            raise _fail(message='最新妙手读回未绑定当前商品或保护字段不完整。')
        if (official_after.get('product_id') != row['product_id']
                or official_after.get('shop_confirmed') is not True
                or official_after.get('shop', row['shop']) != row['shop']
                or official_after.get('draft_loaded') or official_after.get('rejected')):
            raise _fail(message='最新官方读回身份不匹配或存在草稿/驳回状态。')

        # 2. Authoritative full-SKU comparison on both platforms
        compare_official_skus(official_before.get('sku_evidence'), official_after.get('sku_evidence'))
        verify_miaoshou_skus(miao_after, official_after.get('sku_evidence'))

        # 3. Protected comparison across all 8 sections (strict equality on 7 sections;
        #    bound virtual-SKU-row strip on legacy 价格库存 ONLY).
        base_sec = _section_index(official_before)
        curr_sec = _section_index(official_after)
        missing = [n for n in _REQUIRED_SECTIONS if n not in base_sec or n not in curr_sec]
        if missing:
            raise _fail(message=f'官方页面缺少必需分区（{"、".join(missing)}）。')
        b_state = _observations(base_sec)
        c_state = _observations(curr_sec)
        exempt = lambda n: b_state.get(n) == 'empty_block' and c_state.get(n) == 'empty_block'
        usable = lambda st, n: st.get(n) in ('ready', 'empty_block') or (st is b_state and st.get(n) == 'legacy_ready')
        unobserved = sorted(n for n in set(base_sec) | set(curr_sec) if not exempt(n) and not (usable(b_state, n) and usable(c_state, n)))
        if unobserved or set(base_sec) ^ set(curr_sec):
            raise _fail(message='保护分区观测不完整或前后分区集合不一致。')
        if 'inputs_without_sku_grid' in base_sec.get('价格库存', {}):
            raise _fail(message='该基线已包含 inputs_without_sku_grid，请走常规 recheck。')

        grid_diff = None
        for name in sorted(curr_sec):
            if exempt(name):
                continue
            left_blk = _normalize_images(_inactive_size_option_content(base_sec[name], full_skus_compared=True))
            right_blk = _normalize_images(_inactive_size_option_content(curr_sec[name], full_skus_compared=True))
            if name != '价格库存':
                if left_blk != right_blk:
                    raise DoudianError('commercial_changed', f'非价格库存分区 {name} 存在未授权变更。')
            else:
                target_grid_free = curr_sec[name].get('inputs_without_sku_grid')
                if not isinstance(target_grid_free, list):
                    raise _fail(message='最新官方读回缺少 inputs_without_sku_grid。')
                for k in ('selections', 'static_fields', 'images'):
                    if left_blk.get(k) != right_blk.get(k):
                        raise DoudianError('commercial_changed', f'价格库存分区的 {k} 字段与基线不一致。')
                _, _, grid_diff = _strip_validated_legacy_sku_grid(
                    left_blk.get('inputs'), _normalize_images(target_grid_free),
                    (official_after.get('sku_evidence') or {}).get('raw_rows'),
                    right_inputs=right_blk.get('inputs'),
                )

        # 4. Target title + all permanent image slots match on BOTH Miaoshou and Doudian
        artifact_path = Path(row['artifacts_path']).resolve()
        if not artifact_path.is_file() or batch._digest(artifact_path) != row['artifacts_hash']:
            raise _fail(message='任务素材清单缺失或哈希不一致。')
        manifest = json.loads(artifact_path.read_text(encoding='utf-8-sig'))
        target_title = manifest.get('title')
        prior_rb = json.loads(row['readback_json']) if row['readback_json'] else {}
        final_mappings = proof.get('final_asset_mappings') or prior_rb.get('final_asset_mappings')
        plan = batch._slot_plan(baseline)
        expected_slots = batch._expected_slots(plan)
        if (not isinstance(final_mappings, list) or len(final_mappings) != len(expected_slots)
                or {m.get('slot') for m in final_mappings} != expected_slots):
            raise _fail(message='缺少全部槽位的永久素材映射证据。')
        # Re-verify current UploadMap hashes match final_mappings source_sha256
        upload_by_slot = {u.get('slot'): u for u in json.loads(row['upload_map_json'] or '[]') if isinstance(u, dict)}
        for m in final_mappings:
            slot = m.get('slot')
            if (not batch._confirmed_upload_mapping(m)
                    or not is_permanent_material_url(m.get('remote_url'), expected_key=m.get('remote_key'))
                    or upload_by_slot.get(slot, {}).get('source_sha256') != m.get('source_sha256')):
                raise _fail(message=f'槽位 {slot} 永久素材映射或本地上传哈希不匹配。')

        shelf_policy = batch._warehouse_shelf_preservation(miao_after.get('protected'), baseline.get('protected'))
        shelf_preserved = (miao_after.get('protected', {}).get('startSaleType') ==
                           baseline.get('protected', {}).get('startSaleType')) or (shelf_policy is not None)
        if not shelf_preserved or not batch._miaoshou_protected_matches(
                miao_after.get('protected'), baseline.get('protected'), preserve_warehouse=shelf_policy is not None):
            raise _fail(message='妙手受保护商业字段或仓库保底状态与基线不一致。')
        if not batch._matches_miaoshou_content(baseline, miao_after, target_title, final_mappings, plan):
            raise _fail(message='最新妙手标题、主图或详情映射与目标不一致。')

        # Check Doudian title, mains and details explicitly
        by_slot = {m['slot']: m['remote_key'] for m in final_mappings}
        want_mains = [by_slot[f'mains:{i}'] for i in range(1, plan['mains'] + 1)]
        want_details = [by_slot[f'details:{i}'] for i in range(1, plan['details'] + 1)]
        before_details = batch._image_keys(official_before.get('details'))
        after_details = batch._image_keys(official_after.get('details'))
        after_mains = batch._image_keys(official_after.get('mains'))
        if (official_after.get('title') != target_title
                or after_mains != want_mains
                or len(after_details) != len(before_details)
                or after_details[:plan['details']] != want_details
                or after_details[plan['details']:] != before_details[plan['details']:]):
            raise _fail(message='最新抖店官方标题、主图或详情映射与目标不一致。')

        evidence = {
            'target_version': row['target_version'],
            'manifest_sha256': row['artifacts_hash'],
            'read_only': True,
            'verification_kind': 'legacy_sku_grid_readback',
            'prior_error': row['last_error'],
            'proof_sha256': proof_sha256,
            'reviewer': str(proof['reviewer']).strip(),
            'sku_grid_diff': grid_diff,
            'final_asset_mappings': final_mappings,
            'miaoshou': {
                'product_id': row['product_id'],
                'shop': row['shop'],
                'complete': True,
                'matches_target': True,
                'protected_match': True,
                'shelf_state_preservation': shelf_policy,
                'title': miao_after.get('title'),
                'main_count': len(miao_after.get('mains') or []),
                'detail_count': len(miao_after.get('details') or []),
                'shelf_status': miao_after.get('protected', {}).get('status'),
                'review_status': miao_after.get('protected', {}).get('checkStatus'),
                'start_sale_type': miao_after.get('protected', {}).get('startSaleType'),
            },
            'doudian': {
                'product_id': row['product_id'],
                'shop': row['shop'],
                'complete': True,
                'matches_target': True,
                'protected_match': True,
                'sku_evidence': official_after.get('sku_evidence'),
                'title': official_after.get('title'),
                'main_count': len(after_mains),
                'detail_count': len(after_details),
                'draft_loaded': False,
                'rejected': False,
            },
        }
        payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        readback_sha256 = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        map_payload = json.dumps(final_mappings, ensure_ascii=False, sort_keys=True)
        conn.execute(
            '''UPDATE products SET state='verified', submission_state='verified_by_readback',
                    readback_json=?, readback_hash=?, upload_map_json=?, last_error=NULL, updated_at=?
               WHERE id=? AND state='blocked' AND submission_state='unknown' AND last_error='readback_mismatch' ''',
            (payload, readback_sha256, map_payload, now, task_id),
        )
        if conn.execute('SELECT changes()').fetchone()[0] != 1:
            raise _fail(message='核销期间任务状态发生变化。')
        conn.execute(
            '''INSERT INTO product_events(task_id,from_state,to_state,occurred_at,elapsed_seconds,detail)
               VALUES(?,?,?,?,?,?)''',
            (task_id, 'blocked', 'verified', now, max(0, now - row['updated_at']),
             json.dumps({'verification_kind': 'legacy_sku_grid_readback',
                         'proof_sha256': proof_sha256,
                         'readback_sha256': readback_sha256,
                         'sku_grid_diff': grid_diff,
                         'reviewer': str(proof['reviewer']).strip()}, ensure_ascii=False, sort_keys=True)),
        )
        conn.commit()
        return {'task_id': task_id, 'state': 'verified', 'submission_state': 'verified_by_readback',
                'readback_sha256': readback_sha256, 'sku_grid_diff': grid_diff}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
