"""Close one owned Ego page after a single timed-out read, without replaying it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .errors import DoudianError
from .jobs import TransportLock
from .miaoshou_editor import VISIBLE_DOM


_TOKEN_RE = re.compile(r'[a-f0-9]{32}')
_HASH_RE = re.compile(r'[a-f0-9]{64}')
_PRODUCT_RE = re.compile(r'[0-9]{16,22}')
_MARKER_RE = re.compile(r'[a-f0-9]{32}')
_ROUTE_KEY = 'v2-dd.chengji-inc.com/product/quick_edit'
_PAGE_URL = 'https://v2-dd.chengji-inc.com/product/quick_edit'


def _error(code, message):
    return DoudianError(code, message)


def _read_json(path, code='stalled_read_proof_invalid'):
    try:
        raw = Path(path).read_bytes()
        return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise _error(code, 'Ego恢复证据或会话状态无法完整读取。') from exc


def _sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise _error('stalled_read_proof_invalid', 'Ego恢复证据文件缺失或无法读取。') from exc


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _write_text_once(path, value):
    path = Path(path)
    try:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise _error('stalled_read_recovery_unknown', 'Ego恢复意图或收据已存在，禁止再次关闭页面。') from exc
    except OSError as exc:
        raise _error('stalled_read_recovery_unknown', '无法持久化Ego恢复意图；未尝试再次关闭页面。') from exc


def _write_json_once(path, value):
    _write_text_once(path, json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')


def _write_json_atomic(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise _error('stalled_read_recovery_unknown', 'Ego会话状态未能安全持久化；保留恢复意图。') from exc


def _validate_proof(proof, session):
    if not isinstance(proof, dict):
        raise _error('stalled_read_proof_invalid', '恢复证明必须是JSON对象。')
    required = ('reviewer', 'session', 'space_id', 'page', 'product_id', 'shop',
                'pending_token', 'request_sha256', 'result_sha256')
    if any(key not in proof for key in required):
        raise _error('stalled_read_proof_invalid', '恢复证明缺少会话、页面或请求结果绑定。')
    if (not isinstance(proof['reviewer'], str) or not proof['reviewer'].strip() or
            proof['session'] != session or not isinstance(session, str) or not session.strip() or
            type(proof['space_id']) is not int or proof['space_id'] <= 0 or
            not isinstance(proof['page'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', proof['page']) or
            not isinstance(proof['product_id'], str) or not _PRODUCT_RE.fullmatch(proof['product_id']) or
            not isinstance(proof['shop'], str) or not proof['shop'].strip() or
            not isinstance(proof['pending_token'], str) or not _TOKEN_RE.fullmatch(proof['pending_token']) or
            any(not isinstance(proof[key], str) or not _HASH_RE.fullmatch(proof[key])
                for key in ('request_sha256', 'result_sha256'))):
        raise _error('stalled_read_proof_invalid', '恢复证明的绑定字段格式无效或与当前会话不符。')


def _parse_navigation_code(code, proof):
    prefix = VISIBLE_DOM + '('
    name = json.dumps('navigation_toggle')
    if not isinstance(code, str) or not code.startswith(prefix) or not code.endswith(')'):
        raise _error('stalled_read_purpose_mismatch', '只允许原样核验的 navigation_toggle 只读调用。')
    tail = code[len(prefix):-1]
    if not tail.startswith(name + ','):
        raise _error('stalled_read_purpose_mismatch', '请求不是唯一允许的导航状态读取。')
    try:
        params = json.loads(tail[len(name) + 1:])
    except (TypeError, ValueError) as exc:
        raise _error('stalled_read_purpose_mismatch', 'navigation_toggle 参数无法解析。') from exc
    if (not isinstance(params, dict) or list(params) != ['shop', 'product_id', 'marker'] or
            not isinstance(params.get('marker'), str) or not _MARKER_RE.fullmatch(params['marker'])):
        raise _error('stalled_read_purpose_mismatch', 'navigation_toggle 参数不符合固定读取形态。')
    canonical = VISIBLE_DOM + '(' + name + ',' + json.dumps(params, ensure_ascii=True) + ')'
    if (code != canonical or params.get('shop') != proof['shop'] or
            params.get('product_id') != proof['product_id']):
        raise _error('stalled_read_identity_mismatch', '读取代码中的商品或店铺与恢复证明不一致。')
    return params


def _validate_result(result):
    error = result.get('error') if isinstance(result, dict) else None
    if (not isinstance(result, dict) or result.get('ok') is not False or
            not isinstance(error, dict) or error.get('code') != 'EGO_PAGE_EVALUATION_TIMED_OUT' or
            error.get('executionStopped') is not False or
            error.get('mayHaveLateEffects') is not True):
        raise _error('stalled_read_result_mismatch', '只接受本次明确的 evaluate 超时且仍可能迟到的结果。')


def _read_live_inputs(root, proof, state_path, *, require_pending=True):
    token = proof['pending_token']
    pending_path = root / 'pending-command.json'
    request_path = root / f'{token}.json'
    result_path = root / f'{token}.result.json'
    pending = None
    pending_hash = None
    if pending_path.is_file():
        pending, pending_hash = _read_json(pending_path)
        if (not isinstance(pending, dict) or pending.get('token') != token or
                pending.get('action') != 'evaluate' or not isinstance(pending.get('run_id'), str) or
                not pending['run_id']):
            raise _error('stalled_read_source_mismatch', '当前pending不是绑定的单次evaluate读取。')
    elif require_pending:
        raise _error('stalled_read_pending_missing', '原pending已不存在，不能推测或重建待核查操作。')

    request, request_hash = _read_json(request_path)
    result, result_hash = _read_json(result_path)
    if request_hash != proof['request_sha256'] or result_hash != proof['result_sha256']:
        raise _error('stalled_read_hash_mismatch', '请求或结果文件哈希与恢复证明不一致。')
    if (not isinstance(request, dict) or request.get('action') != 'evaluate' or
            request.get('session') != proof['session'] or
            not isinstance(request.get('runId'), str) or
            (pending is not None and pending.get('run_id') != request.get('runId'))):
        raise _error('stalled_read_source_mismatch', '请求来源不是当前会话的原生 evaluate 操作。')
    args = request.get('args')
    if not isinstance(args, dict) or set(args) != {'code'}:
        raise _error('stalled_read_purpose_mismatch', '请求包含额外参数，拒绝按浏览器读取失败恢复。')
    _parse_navigation_code(args.get('code'), proof)
    try:
        if Path(request.get('statePath', '')).resolve() != Path(state_path).resolve():
            raise _error('stalled_read_source_mismatch', '请求绑定了其他Ego会话状态文件。')
    except (OSError, TypeError, ValueError) as exc:
        raise _error('stalled_read_source_mismatch', '请求状态路径无效。') from exc
    _validate_result(result)
    return {
        'pending_path': pending_path, 'request_path': request_path, 'result_path': result_path,
        'pending': pending, 'pending_sha256': pending_hash,
        'request': request, 'request_sha256': request_hash,
        'result': result, 'result_sha256': result_hash,
    }


def _verify_inputs_unchanged(inputs, proof, *, allow_missing_pending=False):
    if _sha256(inputs['request_path']) != proof['request_sha256'] or \
            _sha256(inputs['result_path']) != proof['result_sha256']:
        raise _error('stalled_read_hash_mismatch', '请求或结果文件在页面恢复期间发生变化。')
    if inputs['pending_path'].is_file():
        if _sha256(inputs['pending_path']) != inputs['pending_sha256']:
            raise _error('stalled_read_hash_mismatch', 'pending记录在页面恢复期间发生变化。')
    elif not allow_missing_pending:
        raise _error('stalled_read_pending_missing', '页面恢复期间pending记录意外消失。')


def _state_projection(state):
    return {key: value for key, value in state.items() if key not in ('pages', 'active', 'capture')}


def _validate_state_base(state, proof, request):
    if (not isinstance(state, dict) or state.get('finished') is True or
            state.get('cleanup') is not None or type(state.get('spaceId')) is not int or
            state['spaceId'] != proof['space_id'] or not isinstance(state.get('pages'), dict) or
            not isinstance(state.get('requests'), dict) or type(state.get('capture')) is not bool):
        raise _error('stalled_read_state_mismatch', 'TaskSpace已结束、正清理或状态与恢复证明不一致。')
    return {
        'pages_before': dict(state['pages']), 'active_before': state.get('active'),
        'capture_before': state['capture'], 'requests_sha256': _json_hash(state['requests']),
        'other_state_sha256': _json_hash(_state_projection(state)),
    }


def _validate_initial_page_state(state, proof, state_snapshot):
    pages = state_snapshot['pages_before']
    route_keys = [key for key, label in pages.items() if label == proof['page']]
    if (state_snapshot['active_before'] != proof['page'] or
            pages.get(_ROUTE_KEY) != proof['page'] or route_keys != [_ROUTE_KEY]):
        raise _error('stalled_read_identity_mismatch', '当前active页或路由不是绑定的quick_edit页面。')


def _build_close_script(spec):
    encoded = json.dumps(spec, ensure_ascii=False, separators=(',', ':'))
    return '''const fs=await import("node:fs/promises");
const s=''' + encoded + ''';
let closeCalled=false;
let receipt={schema_version:1,ok:false,nonce:s.nonce,session:s.session,space_id:s.space_id,
  page:s.page,page_url:s.page_url,product_id:s.product_id,shop:s.shop,pending_token:s.pending_token,
  pending_sha256:s.pending_sha256,request_sha256:s.request_sha256,result_sha256:s.result_sha256,
  proof_sha256:s.proof_sha256,close_called:false};
try {
  if(typeof taskSpace!=='function')throw Object.assign(new Error('taskSpace unavailable'),{code:'taskSpace_missing'});
  const task=await taskSpace(s.space_id);
  if(!task||task.spaceId!==s.space_id)throw Object.assign(new Error('wrong TaskSpace'),{code:'space_mismatch'});
  const before=await task.tabs();
  const labels=before.map(t=>t?.label);
  if(labels.some(x=>typeof x!=='string'||!x)||new Set(labels).size!==labels.length)
    throw Object.assign(new Error('task page labels are incomplete'),{code:'page_labels_incomplete'});
  const matches=before.filter(t=>t.label===s.page);
  if(matches.length!==1||matches[0].openedBy!=='agent'||matches[0].url!==s.page_url)
    throw Object.assign(new Error('target page identity or ownership mismatch'),{code:'page_identity_mismatch'});
  const beforeLabels=[...labels];
  const page=task.page(s.page);
  if(!page||typeof page.close!=='function')throw Object.assign(new Error('Page.close unavailable'),{code:'page_close_unavailable'});
  closeCalled=true;
  await page.close();
  const after=await task.tabs();
  const afterLabels=after.map(t=>t?.label);
  const remaining=beforeLabels.filter(label=>label!==s.page);
  if(afterLabels.some(x=>typeof x!=='string'||!x)||new Set(afterLabels).size!==afterLabels.length||
     afterLabels.includes(s.page)||JSON.stringify(afterLabels)!==JSON.stringify(remaining))
    throw Object.assign(new Error('other task page labels changed'),{code:'remaining_pages_changed'});
  const owned=after.filter(t=>t.openedBy==='agent').map(t=>t.label);
  if(!owned.length)throw Object.assign(new Error('no remaining owned page'),{code:'remaining_owned_page_missing'});
  receipt={...receipt,ok:true,close_called:true,target_opened_by:'agent',
    closed_page:s.page,before_labels:beforeLabels,remaining_pages:afterLabels,remaining_owned_pages:owned,
    active_page:owned[0],closed_at:Date.now(),mayHaveLateEffects:false};
} catch(e) {
  receipt={...receipt,ok:false,close_called:closeCalled,
    error_code:e?.code||'stalled_read_close_failed'};
}
const handle=await fs.open(s.receipt_path,'wx');
await handle.writeFile(JSON.stringify(receipt),'utf8');
await handle.sync();
await handle.close();
'''


def _safe_intent_path(root, token):
    return root / f'stalled-read-recovery-{token}.intent.json'


def _paths_from_intent(root, intent, token):
    try:
        script = Path(intent['script_path']).resolve()
        receipt = Path(intent['receipt_path']).resolve()
    except (KeyError, TypeError, OSError, ValueError) as exc:
        raise _error('stalled_read_recovery_unknown', '恢复意图的脚本或收据路径无效，禁止再次关闭。') from exc
    if (script.parent != root or receipt.parent != root or
            not script.name.startswith(f'stalled-read-recovery-{token}-') or not script.name.endswith('.mjs') or
            not receipt.name.startswith(f'stalled-read-recovery-{token}-') or
            not receipt.name.endswith('.receipt.json')):
        raise _error('stalled_read_recovery_unknown', '恢复意图引用了非本会话的文件，禁止再次关闭。')
    return script, receipt


def _validate_intent(intent, proof, proof_hash, inputs, root):
    if not isinstance(intent, dict):
        raise _error('stalled_read_recovery_unknown', '既有恢复意图损坏，禁止再次关闭。')
    expected = {
        'schema_version': 1, 'phase': 'close_pending', 'proof_sha256': proof_hash,
        'session': proof['session'], 'space_id': proof['space_id'], 'page': proof['page'],
        'product_id': proof['product_id'], 'shop': proof['shop'],
        'pending_token': proof['pending_token'], 'pending_sha256': inputs['pending_sha256'],
        'request_sha256': proof['request_sha256'], 'result_sha256': proof['result_sha256'],
    }
    if any(intent.get(key) != value for key, value in expected.items()):
        raise _error('stalled_read_recovery_unknown', '既有恢复意图与当前proof或pending不匹配，禁止再次关闭。')
    script, receipt = _paths_from_intent(root, intent, proof['pending_token'])
    if (not isinstance(intent.get('nonce'), str) or not _TOKEN_RE.fullmatch(intent['nonce']) or
            not isinstance(intent.get('script_sha256'), str) or
            not _HASH_RE.fullmatch(intent['script_sha256']) or
            not isinstance(intent.get('pages_before'), dict) or
            intent.get('pages_before', {}).get(_ROUTE_KEY) != proof['page'] or
            intent.get('active_before') != proof['page'] or
            type(intent.get('capture_before')) is not bool or
            not isinstance(intent.get('requests_sha256'), str) or
            not _HASH_RE.fullmatch(intent['requests_sha256']) or
            not isinstance(intent.get('other_state_sha256'), str) or
            not _HASH_RE.fullmatch(intent['other_state_sha256']) or
            not script.is_file() or _sha256(script) != intent['script_sha256']):
        raise _error('stalled_read_recovery_unknown', '既有恢复意图或安全脚本已变化，禁止再次关闭。')
    return script, receipt


def _validate_receipt(receipt, intent, proof):
    if not isinstance(receipt, dict) or receipt.get('ok') is not True:
        raise _error('stalled_read_recovery_unknown', 'Ego没有返回成功的页面关闭收据；禁止再次关闭。')
    for key, expected in {
        'schema_version': 1, 'nonce': intent['nonce'], 'session': proof['session'],
        'space_id': proof['space_id'], 'page': proof['page'], 'page_url': _PAGE_URL,
        'product_id': proof['product_id'], 'shop': proof['shop'],
        'pending_token': proof['pending_token'], 'pending_sha256': intent['pending_sha256'],
        'request_sha256': proof['request_sha256'], 'result_sha256': proof['result_sha256'],
        'proof_sha256': intent['proof_sha256'], 'close_called': True,
        'target_opened_by': 'agent', 'closed_page': proof['page'],
        'mayHaveLateEffects': False,
    }.items():
        if receipt.get(key) != expected:
            raise _error('stalled_read_recovery_unknown', 'Ego关闭收据没有绑定原页面或恢复证据。')
    before = receipt.get('before_labels')
    remaining = receipt.get('remaining_pages')
    owned = receipt.get('remaining_owned_pages')
    active = receipt.get('active_page')
    if (not isinstance(before, list) or any(not isinstance(x, str) or not x for x in before) or
            len(set(before)) != len(before) or before.count(proof['page']) != 1 or
            not isinstance(remaining, list) or any(not isinstance(x, str) or not x for x in remaining) or
            remaining != [label for label in before if label != proof['page']] or
            not isinstance(owned, list) or not owned or any(label not in remaining for label in owned) or
            len(set(owned)) != len(owned) or active not in owned):
        raise _error('stalled_read_recovery_unknown', 'Ego关闭收据未证明仅目标页消失且其他页保留。')
    return receipt


def _state_phase(state, proof, intent, receipt):
    if (not isinstance(state, dict) or state.get('finished') is True or
            state.get('cleanup') is not None or type(state.get('spaceId')) is not int or
            state['spaceId'] != proof['space_id'] or not isinstance(state.get('pages'), dict) or
            not isinstance(state.get('requests'), dict) or
            _json_hash(state['requests']) != intent['requests_sha256'] or
            _json_hash(_state_projection(state)) != intent['other_state_sha256']):
        raise _error('stalled_read_state_mismatch', '页面关闭后TaskSpace状态或requests改变，未结案pending。')
    before_pages = intent['pages_before']
    expected_pages = {key: value for key, value in before_pages.items() if key != _ROUTE_KEY}
    if before_pages.get(_ROUTE_KEY) != proof['page']:
        raise _error('stalled_read_identity_mismatch', '持久化意图没有绑定目标quick_edit路由。')
    initial = (state['pages'] == before_pages and state.get('active') == proof['page'] and
               state.get('capture') is intent['capture_before'])
    finalized = (state['pages'] == expected_pages and state.get('active') == receipt['active_page'] and
                 state.get('capture') is False)
    if initial:
        return 'initial', expected_pages
    if finalized:
        return 'finalized', expected_pages
    raise _error('stalled_read_state_mismatch', '页面路由已发生其他变化，未结案pending。')


def _audit_path(root, token):
    return root / f'stalled-read-recovery-{token}.audit.json'


def _finalize(root, state_path, proof_path, proof, proof_hash, inputs, intent_path,
              intent, receipt_path, receipt, receipt_hash):
    state, _ = _read_json(state_path, 'stalled_read_state_mismatch')
    phase, expected_pages = _state_phase(state, proof, intent, receipt)
    _verify_inputs_unchanged(inputs, proof, allow_missing_pending=True)
    script_path, _ = _paths_from_intent(root, intent, proof['pending_token'])
    if (_sha256(proof_path) != proof_hash or _sha256(receipt_path) != receipt_hash or
            _sha256(script_path) != intent['script_sha256']):
        raise _error('stalled_read_hash_mismatch', '恢复证明在页面关闭期间发生变化。')
    audit_path = _audit_path(root, proof['pending_token'])
    audit = {
        'schema_version': 1, 'kind': 'stalled_read_page_closed',
        'reviewer': proof['reviewer'], 'session': proof['session'],
        'space_id': proof['space_id'], 'page': proof['page'],
        'product_id': proof['product_id'], 'shop': proof['shop'],
        'pending': inputs['pending'] if inputs['pending'] is not None else intent['pending'],
        'pending_sha256': intent['pending_sha256'],
        'request_sha256': proof['request_sha256'], 'result_sha256': proof['result_sha256'],
        'proof_sha256': proof_hash, 'script_sha256': intent['script_sha256'],
        'receipt_path': str(receipt_path), 'receipt_sha256': receipt_hash,
        'closed_page': proof['page'], 'remaining_pages': receipt['remaining_pages'],
        'finalized_at': time.time(),
    }
    if phase == 'initial':
        updated = dict(state)
        updated['pages'] = expected_pages
        updated['active'] = receipt['active_page']
        updated['capture'] = False
        _write_json_atomic(state_path, updated)
    if audit_path.exists():
        old_audit, _ = _read_json(audit_path, 'stalled_read_recovery_unknown')
        for key in ('kind', 'pending_sha256', 'request_sha256', 'result_sha256',
                    'proof_sha256', 'receipt_sha256', 'page'):
            if old_audit.get(key) != audit.get(key):
                raise _error('stalled_read_recovery_unknown', '已有结案审计与当前收据冲突。')
        audit = old_audit
    else:
        _write_json_once(audit_path, audit)
    pending_path = inputs['pending_path']
    if pending_path.is_file():
        _verify_inputs_unchanged(inputs, proof)
        pending_path.unlink()
    return {'recovered': True, 'closed_page': proof['page'],
            'remaining_pages': receipt['remaining_pages'], 'evidence_path': str(receipt_path)}


def recover_stalled_read(bridge, proof_path):
    """Close only the proven owned quick-edit page, then consume its late-read marker.

    Repeated calls never launch the SDK script again. A prior intent can only be
    completed from its matching, complete receipt written by that one SDK round.
    """
    session = getattr(bridge, 'session', None)
    session_dir = getattr(bridge, 'session_dir', None)
    if not session or not session_dir:
        raise _error('stalled_read_proof_invalid', '必须使用已有EgoBridge会话。')
    root = Path(session_dir).resolve()
    if not root.is_dir() or not (root / 'state.json').is_file():
        raise _error('stalled_read_state_mismatch', 'Ego会话目录不存在；不会创建替代TaskSpace。')
    state_path = root / 'state.json'
    proof_path = Path(proof_path).resolve()

    with TransportLock(root / 'transport.lock'):
        proof, proof_hash = _read_json(proof_path)
        _validate_proof(proof, session)
        inputs = _read_live_inputs(root, proof, state_path)
        state, _ = _read_json(state_path, 'stalled_read_state_mismatch')
        state_snapshot = _validate_state_base(state, proof, inputs['request'])

        intent_path = _safe_intent_path(root, proof['pending_token'])
        if intent_path.exists():
            intent, _ = _read_json(intent_path, 'stalled_read_recovery_unknown')
            script_path, receipt_path = _validate_intent(
                intent, proof, proof_hash, inputs, root)
            if not receipt_path.is_file():
                if (state_snapshot['pages_before'] != intent['pages_before'] or
                        state_snapshot['active_before'] != intent['active_before'] or
                        state_snapshot['capture_before'] is not intent['capture_before'] or
                        state_snapshot['requests_sha256'] != intent['requests_sha256'] or
                        state_snapshot['other_state_sha256'] != intent['other_state_sha256']):
                    raise _error('stalled_read_recovery_unknown',
                                 '页面状态与未完成恢复意图不符；禁止再次close。')
                raise _error('stalled_read_recovery_unknown',
                             '页面关闭尚无完整late receipt；不会再次运行SDK或重复close。')
            receipt, receipt_hash = _read_json(receipt_path, 'stalled_read_recovery_unknown')
            receipt = _validate_receipt(receipt, intent, proof)
            return _finalize(root, state_path, proof_path, proof, proof_hash, inputs,
                             intent_path, intent, receipt_path, receipt, receipt_hash)

        executable = shutil.which('ego-browser.cmd') or shutil.which('ego-browser')
        if not executable:
            raise _error('ego_not_installed', '未找到Ego原生浏览器工具；没有写入恢复意图或调用页面。')

        _validate_initial_page_state(state, proof, state_snapshot)
        nonce = uuid.uuid4().hex
        script_path = root / f'stalled-read-recovery-{proof["pending_token"]}-{nonce}.mjs'
        receipt_path = root / f'stalled-read-recovery-{proof["pending_token"]}-{nonce}.receipt.json'
        spec = {
            'nonce': nonce, 'receipt_path': str(receipt_path), 'session': proof['session'],
            'space_id': proof['space_id'], 'page': proof['page'], 'page_url': _PAGE_URL,
            'product_id': proof['product_id'], 'shop': proof['shop'],
            'pending_token': proof['pending_token'], 'pending_sha256': inputs['pending_sha256'],
            'request_sha256': proof['request_sha256'], 'result_sha256': proof['result_sha256'],
            'proof_sha256': proof_hash,
        }
        script_text = _build_close_script(spec)
        _write_text_once(script_path, script_text)
        intent = {
            'schema_version': 1, 'phase': 'close_pending', 'nonce': nonce,
            'proof_sha256': proof_hash, 'session': proof['session'],
            'space_id': proof['space_id'], 'page': proof['page'],
            'product_id': proof['product_id'], 'shop': proof['shop'],
            'pending_token': proof['pending_token'], 'pending': inputs['pending'],
            'pending_sha256': inputs['pending_sha256'],
            'request_sha256': proof['request_sha256'], 'result_sha256': proof['result_sha256'],
            'script_path': str(script_path), 'script_sha256': _sha256(script_path),
            'receipt_path': str(receipt_path), 'pages_before': state_snapshot['pages_before'],
            'active_before': state_snapshot['active_before'],
            'capture_before': state_snapshot['capture_before'],
            'requests_sha256': state_snapshot['requests_sha256'],
            'other_state_sha256': state_snapshot['other_state_sha256'],
            'started_at': time.time(),
        }
        _write_json_once(intent_path, intent)
        if _sha256(script_path) != intent['script_sha256']:
            raise _error('stalled_read_recovery_unknown', '安全恢复脚本在启动前发生变化；未再次关闭页面。')

        module_uri = script_path.as_uri()
        command = [executable, 'nodejs', '-e', "await import('" + module_uri + "')"]
        launch_error = None
        try:
            completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                       encoding='utf-8', errors='replace', timeout=35)
            if completed is not None and getattr(completed, 'returncode', 0) != 0:
                launch_error = _error('stalled_read_recovery_unknown',
                                      'Ego SDK脚本没有以成功状态结束；保留恢复意图。')
        except (OSError, subprocess.TimeoutExpired) as exc:
            launch_error = exc

        if not receipt_path.is_file():
            message = ('Ego关闭调用超时或未生成receipt；恢复意图已保存，禁止再次close。'
                       if launch_error else 'Ego没有生成receipt；恢复意图已保存，禁止再次close。')
            raise _error('stalled_read_recovery_unknown', message) from launch_error
        if launch_error and not isinstance(launch_error, subprocess.TimeoutExpired):
            intent['phase'] = 'failed'
            intent['failure'] = 'sdk_process_not_confirmed_success'
            _write_json_atomic(intent_path, intent)
            raise _error('stalled_read_recovery_unknown',
                         'Ego SDK未确认脚本成功结束；保留恢复意图，禁止再次close。') from launch_error
        receipt, receipt_hash = _read_json(receipt_path, 'stalled_read_recovery_unknown')
        receipt = _validate_receipt(receipt, intent, proof)
        inputs['pending'] = intent['pending']
        return _finalize(root, state_path, proof_path, proof, proof_hash, inputs,
                         intent_path, intent, receipt_path, receipt, receipt_hash)
