"""Durable, narrowly scoped publication of explicitly supplied missing attributes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from .attributes import apply_attributes, _control
from .errors import DoudianError
from .jobs import DATA_ROOT, Lock, read_json, write_json
from .workflow import compare_protected, guard_siblings


def _snapshot(editor, identity, values, *, fresh_skus=True):
    # Official SKU collection reloads the form: never invoke it on unsaved inputs.
    sku = editor.read_skus(identity) if fresh_skus else None
    editor.wait_details(identity)
    snap = editor.dom('snapshot', identity, attribute_names=list(values))
    if (snap.get('draft_loaded') or snap.get('rejected') or snap.get('success') or
            snap.get('product_id') != identity['product_id'] or not snap.get('shop_confirmed') or
            snap.get('detail_status') not in ('ready', 'empty')):
        raise DoudianError('attribute_baseline_unready', '属性任务需要身份确认、非草稿/驳回及完整图片的编辑页。')
    if sku is not None:
        snap['sku_evidence'] = sku
    return snap


def _compare(before, after, values, *, preview=False):
    left, right = deepcopy(before), deepcopy(after)
    if preview:
        left.pop("sku_evidence", None)
        right.pop("sku_evidence", None)
    compare_protected(left, right)
    for key in ('title', 'mains', 'details'):
        if before.get(key) != after.get(key):
            raise DoudianError('attribute_non_target_changed', '属性任务的标题或图片发生变化。')
    def others(snap):
        return [f for f in snap.get('required_attributes', {}).get('fields', [])
                if f.get('name') not in values]
    if others(before) != others(after):
        raise DoudianError('attribute_non_target_changed', '非目标类目属性发生变化。')


def abandon_attributes(editor, identity, values, *, reason, operator, root=None):
    """Release an attribute job that stopped before publishing, after checking the page.

    A job that died in `editing` holds the product against every later attempt, and the
    contract rightly forbids silently re-filling it. But if the values are still empty on a
    fresh page, nothing was saved and there is nothing to preserve. This releases that one
    job when, and only when, the page proves it: any target already carrying a different
    value, or any stage that reached submitting or beyond, refuses and keeps the hold.
    """
    root = Path(root or DATA_ROOT)
    values = {k: v.strip() for k, v in values.items() if isinstance(v, str) and v.strip()}
    plan = {'mode': 'attributes_only', **identity, 'attributes': values}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    job = root / 'jobs' / ('attributes-' + identity['product_id'] + '-' + digest[:12])
    state_path = job / 'state.json'
    if not state_path.exists():
        raise DoudianError('attribute_job_missing', '没有对应的属性任务。')
    with Lock(root / 'browser.lock'), Lock(job / 'job.lock'):
        state = read_json(state_path)
        stage = state.get('stage')
        if stage == 'saved':
            return {'product_id': identity['product_id'], 'abandoned': False, 'stage': stage,
                    'reason': '任务已完成，无需放弃。'}
        if stage in ('submitting', 'submitted'):
            raise DoudianError('attribute_abandon_refused',
                               '任务已进入提交，只能核查不能放弃。')
        editor.open(identity, fresh=True)
        unsafe = {}
        for name, want in values.items():
            got = (_control(editor, identity, name).get('current') or '').strip()
            if got not in ('', '请选择', want):
                unsafe[name] = got
        if unsafe:
            raise DoudianError('attribute_abandon_refused',
                               f'目标属性已有不同值 {unsafe}，保留现场，需人工判断。')
        state.update(stage='abandoned', abandoned_at=time.time(), abandon_reason=reason,
                     operator=operator, page_verified_empty=True)
        write_json(state_path, state)
        return {'product_id': identity['product_id'], 'job_dir': str(job), 'stage': 'abandoned',
                'abandoned': True, 'page_verified_empty': True, 'reason': reason}


def publish_attributes(editor, identity, values, *, root=None, queue_check=None):
    """Save once; later calls with the same facts only verify an uncertain submission.

    This path does not reuse the image writer's acceptance proof. Live acceptance of
    attribute publication is separate and its result must be reported as such.
    """
    root = Path(root or DATA_ROOT)
    values = {k: v.strip() for k, v in values.items() if isinstance(v, str) and v.strip() and v.strip() != '待确认'}
    if not values or not identity.get('shop'):
        raise DoudianError('attribute_scope_missing', '需要明确店铺及已确认的具体属性。')
    plan = {'mode': 'attributes_only', **identity, 'attributes': values}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    job = root / 'jobs' / ('attributes-' + identity['product_id'] + '-' + digest[:12])
    job.mkdir(parents=True, exist_ok=True)
    with Lock(root / 'browser.lock'), Lock(job / 'job.lock'):
        if queue_check:
            queue_check(identity['product_id'])
        guard_siblings(root / 'jobs', identity['product_id'], exclude=job)
        state_path = job / 'state.json'
        state = read_json(state_path) if state_path.exists() else {'stage': 'prepared'}
        if (job / 'manifest.json').exists() and read_json(job / 'manifest.json') != plan:
            raise DoudianError('attribute_plan_changed', '属性任务计划不一致。')
        write_json(job / 'manifest.json', plan)
        def save(stage, **kw):
            state.update(stage=stage, updated_at=time.time(), **kw)
            write_json(state_path, state)
        if state['stage'] == 'saved':
            return {'product_id': identity['product_id'], 'job_dir': str(job), 'persisted': True,
                    'stage': 'saved', 'skipped': True}
        recovering = state['stage'] in ('submitting', 'submitted')
        # `abandoned` means an operator already checked the page and confirmed nothing was
        # saved, so starting over cannot overwrite anything. Anything else unfinished keeps
        # the hold, because a half-finished edit must not be silently re-filled.
        if state['stage'] not in ('prepared', 'submitting', 'submitted', 'abandoned'):
            raise DoudianError('attribute_edit_incomplete', '原属性编辑尚未终结；保留页面与证据，不能自动重新填写。')
        editor.open(identity, fresh=True)
        current = _snapshot(editor, identity, values)
        if recovering:
            baseline = read_json(job / 'before.json')
            _compare(baseline, current, values)
            if not all((_control(editor, identity, k).get('current') or '').strip() == v for k, v in values.items()):
                return {'product_id': identity['product_id'], 'job_dir': str(job), 'stage': state['stage'],
                        'persisted': False, 'submission_status': state.get('submission_status'), 'readback_only': True}
            write_json(job / 'readback.json', current)
            save('saved', verified_by_readback=True)
            return {'product_id': identity['product_id'], 'job_dir': str(job), 'stage': 'saved',
                    'persisted': True, 'readback_only': True}
        before = deepcopy(current)
        controls = {name: _control(editor, identity, name) for name in values}
        for name, control in controls.items():
            existing = (control.get('current') or '').strip()
            if control.get('kind') not in ('text', 'single') or control.get('disabled') or (existing not in ('', '请选择', values[name])):
                raise DoudianError('attribute_control_unsupported', '目标属性已有不同值、被禁用或控件尚不支持，未填写。')
        if all((controls[k].get('current') or '').strip() == v for k, v in values.items()):
            save('saved', noop=True)
            return {'product_id': identity['product_id'], 'stage': 'saved', 'persisted': True, 'noop': True}
        write_json(job / 'before.json', before)
        save('editing', submission_status='not_submitted')
        fields = apply_attributes(editor, identity, values)
        write_json(job / 'fields.json', fields)
        if not all((_control(editor, identity, k).get('current') or '').strip() == v for k, v in values.items()):
            raise DoudianError('attribute_fill_incomplete', '属性填写不完整，未点击发布；保留原任务和页面。')
        editor.check(identity)
        preview = _snapshot(editor, identity, values, fresh_skus=False)
        _compare(before, preview, values, preview=True)
        write_json(job / 'preview.json', preview)
        save('submitting', submission_status='unknown', submitted_at=time.time())
        # Any exception from here leaves durable unknown; no automatic second click.
        result = editor.publish(identity)
        write_json(job / 'submission.json', result)
        if result.get('state') != 'accepted':
            # Keep the hold even for a known refusal until an operator resolves it.
            raise DoudianError('attribute_submission_unverified', '属性发布未确认受理；保留提交意图，仅核查不重发。')
        save('submitted', submission_status='accepted')
        editor.open(identity, fresh=True)
        after = _snapshot(editor, identity, values)
        _compare(before, after, values)
        if not all((_control(editor, identity, k).get('current') or '').strip() == v for k, v in values.items()):
            return {'product_id': identity['product_id'], 'stage': 'submitted', 'job_dir': str(job), 'persisted': False}
        write_json(job / 'readback.json', after)
        save('saved', verified_by_readback=True)
        return {'product_id': identity['product_id'], 'job_dir': str(job), 'stage': 'saved', 'persisted': True}
