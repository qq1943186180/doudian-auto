"""Survey fresh preflight evidence and dispatch existing guarded queue operations.

Queue-only planning is labeled explicitly. Supplied missing attributes use their own
durable publication jobs; assets, historical resolutions and facts are never invented.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import batch
from .errors import DoudianError
from .jobs import read_json, write_json

# Outcomes a single product can end an auto run with.
SKIP_VERIFIED = 'skip_verified'          # already accepted, never re-save
READ_ONLY = 'read_only_ok'               # read cleanly, nothing to do now
WAIT_FACTS = 'wait_facts'                # needs real attribute values from the user
WAIT_DECISION = 'wait_decision'          # rejected / draft / conflict: user decides
WAIT_REBASELINE = 'wait_rebaseline'      # gatherable evidence, needs a human sign-off
WAIT_ASSETS = 'wait_assets'              # images cannot be sourced automatically
WAIT_WRITER = 'wait_writer_acceptance'   # three-product gate not yet satisfied
HOLD_ERROR = 'hold_error'                # evidence incomplete; do not guess
WROTE = 'wrote_and_verified'             # written and readback matched

# Reasons a product may be blocked on, mapped to the human-facing group they belong to.
FACT_ERRORS = ('required_attributes_missing',)
DECISION_ERRORS = ('doudian_draft_or_rejected', 'writer_detail_source_collision')
ASSET_ERRORS = ('writer_image_slots_incomplete', 'visual_quality_failed_after_retry',
                'root_visual_review_failed_after_retry')

GROUP_LABELS = {
    SKIP_VERIFIED: '已核验，跳过（不重存）',
    READ_ONLY: '待只读核查或预检结果（非完成）',
    WAIT_FACTS: '需要你提供资料',
    WAIT_DECISION: '需要你决定',
    WAIT_REBASELINE: '可自动取证，待你确认历史提交',
    WAIT_ASSETS: '需要补图片',
    WAIT_WRITER: '等写入器验收（三品门槛）',
    HOLD_ERROR: '程序遇到问题，需人工看',
    WROTE: '已写入并读回通过',
}


def _error_of(row):
    return (row.get('last_error') or '').lower()


def _matches(text, needles):
    return any(n in text for n in needles)


def decide(row):
    """Route one queue row to an outcome, using the queue plus its last error only.

    This is the cheap first pass. `survey()` refines it with a live read, because a
    recorded error may be stale: the page may already carry the attribute the queue says
    is missing.
    """
    state = row.get('state')
    submission = row.get('submission_state')

    if state == 'verified' or submission == 'verified_by_readback':
        return SKIP_VERIFIED, '队列记录已完成双端读回验收'

    # A submitted-but-unconfirmed result must never be re-sent; only read back.
    if submission in ('unknown', 'accepted'):
        return READ_ONLY, f'提交结果 {submission}，只读核查，不重复提交'

    error = _error_of(row)
    if _matches(error, FACT_ERRORS):
        return WAIT_FACTS, f'缺类目属性：{row.get("last_error", "")[:80]}'
    if _matches(error, DECISION_ERRORS):
        return WAIT_DECISION, f'草稿/驳回/来源冲突：{row.get("last_error", "")[:80]}'
    if _matches(error, ASSET_ERRORS):
        return WAIT_ASSETS, f'素材不足或视觉不合格：{row.get("last_error", "")[:80]}'
    if 'sku_code' in error:
        return WAIT_FACTS, f'SKU 码需确认：{row.get("last_error", "")[:80]}'
    if 'requires_rebaseline' in error:
        # Rebuilding needs a proof file that declares each external observation resolved.
        # The program can gather the dual-sided snapshots, but signing off "this past
        # submission ended in a known state" is a judgement about someone else's save.
        # Generating that itself would be the machine vouching for its own evidence, so
        # this stays a one-click human confirmation rather than silent automation.
        return WAIT_REBASELINE, '外部改动：可自动取证，待确认历史提交结论'
    return HOLD_ERROR, (row.get('last_error') or '未分类阻塞')[:100]


def _ensure_session(endpoint, session):
    """Initialize a genuinely new native session; never replace lost/finished state."""
    from .bridge import Bridge, is_native_endpoint
    from .jobs import DATA_ROOT, Lock
    if not is_native_endpoint(endpoint):
        return
    bridge = Bridge(endpoint, session=session)
    with Lock(DATA_ROOT / 'browser.lock'):
        root = bridge.session_dir
        if not root.exists():
            # Preflight intentionally cannot create sessions. This explicit initial
            # navigation does so once, before handing control to read-only preflight.
            bridge.command('navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/list'})
        # Existing directories, even without state.json, are never reset here.


def survey(*, endpoint='ego', session='doudian-auto', db_path=None, live=False, report_dir=None):
    """Classify the whole queue and return the per-outcome buckets plus a fact checklist."""
    status = batch.batch_status(db_path=db_path)
    products = status.get('products') or []
    # batch_status omits the fact blob; titles live there, and a checklist without a name
    # is unusable for someone who has to decide which product to go look at.
    titled = _titles_by_product(db_path)

    observations = {}
    if live:
        from .preflight import preflight_products
        ids = [p['product_id'] for p in products if decide(p)[0] != SKIP_VERIFIED]
        if ids:
            _ensure_session(endpoint, session)
        for offset in range(0, len(ids), 20):
            read = preflight_products(endpoint, product_ids=ids[offset:offset+20],
                                      session=session, db_path=db_path, report_dir=report_dir)
            observations.update({p['product_id']: p for p in read['products']})
            if any(p.get('waiting_human') for p in read['products']):
                break
    buckets: dict[str, list] = {}
    checklist = []
    sku_waiting = []
    for row in products:
        outcome, reason = decide(row)
        observation = observations.get(row['product_id'])
        if observation and observation.get('evidence', {}).get('snapshot_read'):
            if observation.get('eligible'):
                outcome, reason = READ_ONLY, '新鲜预检通过；是否可写仍由队列状态、素材和Writer决定'
            else:
                updated = dict(row, last_error=observation.get('reason'), submission_state=row.get('submission_state'))
                outcome, reason = decide(updated)
                reason = observation.get('message') or reason
        title = titled.get(row.get('product_id')) or _product_title(row)
        buckets.setdefault(outcome, []).append({
            'product_id': row.get('product_id'),
            'state': row.get('state'),
            'submission_state': row.get('submission_state'),
            'title': title,
            'reason': reason,
            'observation': 'fresh' if observation and observation.get('evidence', {}).get('snapshot_read') else 'queue_record',
        })
        if outcome == WAIT_FACTS:
            missing = (observation.get('missing_fields', []) if observation and observation.get('evidence', {}).get('snapshot_read')
                       else _missing_fields(row.get('last_error')))
            # SKU code problems carry no attribute names; asking for an empty attribute
            # block would be a dead line in the checklist, so they are listed separately.
            if missing:
                checklist.append({
                    'product_id': row.get('product_id'),
                    'title': title,
                    'fields': missing,
                    'queue_reason': (row.get('last_error') or '')[:160],
                    'observation': 'fresh' if observation and observation.get('evidence', {}).get('snapshot_read') else 'queue_record',
                })
            else:
                sku_waiting.append({
                    'product_id': row.get('product_id'),
                    'title': title,
                    'reason': (row.get('last_error') or '')[:160],
                })

    return {
        'observation_mode': 'live_preflight' if live else 'queue_only',
        'observations': list(observations.values()),
        'total': len(products),
        'buckets': {k: v for k, v in buckets.items() if v},
        'counts': {k: len(v) for k, v in buckets.items() if v},
        'facts_checklist': checklist,
        'sku_waiting': sku_waiting,
        'readiness': _readiness(endpoint, db_path=db_path),
    }


def _titles_by_product(db_path=None):
    """Map product_id -> a readable name, from the recorded source facts."""
    titles = {}
    try:
        conn = batch._db(db_path)
        rows = conn.execute('SELECT product_id, source FROM products').fetchall()
    except Exception:  # a missing or locked queue must not break a read-only survey
        return titles
    for row in rows:
        pid = row['product_id']
        raw = row['source']
        if not raw:
            continue
        try:
            source = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(source, dict):
            for key in ('source_title', 'name', 'title'):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    titles[pid] = value.strip()
                    break
    return titles


def _product_title(row):
    """The queue carries no title column; the recorded source facts do (name/source_title)."""
    for field in ('baseline_json', 'facts_json'):
        raw = row.get(field)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ('title', 'name', 'source_title'):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _missing_fields(error):
    """Pull the field names out of the preflight message, e.g. missing_fields=["尺寸"]."""
    if not error:
        return []
    marker = 'missing_fields='
    if marker not in error:
        return []
    raw = error.split(marker, 1)[1].strip()
    try:
        names = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(n) for n in names] if isinstance(names, list) else []


def _readiness(endpoint, *, db_path=None):
    try:
        info = batch.execution_readiness(endpoint, db_path=db_path)
    except DoudianError as exc:
        return {'writer_ready': False, 'reason': exc.code}
    if not isinstance(info, dict):
        return {'writer_ready': False, 'reason': 'unreadable'}
    return info


def render(report, *, as_markdown=False):
    """Turn a survey report into something a non-programmer can act on."""
    counts = report.get('counts') or {}
    lines = []
    if as_markdown:
        lines.append('# 自动巡检结果\n')
        lines.append(f"共 {report['total']} 件商品。\n")
        lines.append('以下分类为本轮开始时的观察；实际动作及最终队列另列。\n')
        lines.append('数据来源：' + report.get('observation_mode', 'queue_only') + '；未重新读取的条目只表示队列记录。\n')
        for outcome, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"- **{GROUP_LABELS.get(outcome, outcome)}**：{n} 件")
        checklist = report.get('facts_checklist') or []
        if checklist:
            lines.append('\n## 需要你提供的资料\n')
            lines.append('fresh为本轮实查缺项，queue_record仅旧队列待核实；不要把旧记录当当前缺项。只填有依据的真实值。\n')
            for item in checklist:
                fields = '、'.join(item['fields']) or '（见队列原因）'
                lines.append(f"- `{item['product_id']}` {item.get('title') or ''}"
                             f" → 待核实字段：{fields}（来源：{item.get('observation', 'queue_record')}）")
        sku = report.get('sku_waiting') or []
        if sku:
            lines.append('\n## 需要你确认的商家编码\n')
            for item in sku:
                lines.append(f"- `{item['product_id']}` {item.get('title') or ''}"
                             f" → 官方编码读取未通过，需人工确认")
        readiness = report.get('readiness') or {}
        lines.append('\n## 写入器状态\n')
        lines.append(f"- 就绪：{'是' if readiness.get('writer_ready') else '否'}")
        if readiness.get('reason'):
            lines.append(f"- 原因：{readiness['reason']}")
        if readiness.get('acceptance_products'):
            lines.append(f"- 已验收商品：{', '.join(readiness['acceptance_products'])}")
        if report.get('queue_after') is not None:
            lines.append('\n最终队列：' + json.dumps(report['queue_after'], ensure_ascii=False))
        if report.get('actions'):
            lines.append('\n## 本轮实际执行\n')
            for item in report['actions']:
                lines.append('- ' + json.dumps(item, ensure_ascii=False))
        return '\n'.join(lines)

    lines.append(f'共 {report["total"]} 件商品')
    for outcome, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f'  {GROUP_LABELS.get(outcome, outcome)}: {n}')
    for item in report.get('facts_checklist') or []:
        lines.append(f"  待填 {item['product_id']}: {'、'.join(item['fields']) or '见原因'}")
    return '\n'.join(lines)


def write_facts_template(report, path):
    """Emit the file the user (or the assistant) fills in, then `batch auto` reads back."""
    template = {
        'schema_version': 1,
        'note': '请只填真实资料。不知道的写 "待确认"，程序会跳过该商品而不是猜。',
        'items': [
            {
                'product_id': item['product_id'],
                'title': item.get('title'),
                'attributes': {field: '' for field in item['fields']},
                'confirmed_by': '',
                'confirmed_at': '',
            }
            for item in report.get('facts_checklist') or []
        ],
    }
    path = Path(path)
    if path.exists():
        previous = read_json(path)  # Malformed input must survive unchanged, not be replaced.
        if not isinstance(previous, dict) or not isinstance(previous.get('items'), list):
            raise DoudianError('invalid_facts', '已有资料文件格式错误，已保留原文件。')
        merged = {str(item.get('product_id')): item for item in previous['items']}
        for item in template['items']:
            pid = str(item['product_id'])
            if pid in merged:
                existing = merged[pid]
                existing.setdefault('attributes', {})
                for name in item['attributes']:
                    existing['attributes'].setdefault(name, '')
            else:
                merged[pid] = item
        template['items'] = list(merged.values())
    write_json(path, template)
    return template


def load_facts(path):
    """Read the filled-in facts file, dropping blanks and '待确认' placeholders."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise DoudianError('invalid_facts', '资料文件必须包含 items 数组。')
    usable = {}
    for item in data.get('items') or []:
        pid = str(item.get('product_id') or '')
        attrs = {k: v for k, v in (item.get('attributes') or {}).items()
                 if isinstance(v, str) and v.strip() and v.strip() != '待确认'}
        if pid and attrs:
            usable[pid] = attrs
    return usable


def auto(args):
    """Survey fresh evidence and dispatch only existing, explicitly authorized paths."""
    confirmed = load_facts(args.facts) if args.facts else {}  # before any template write
    report = survey(endpoint=args.endpoint, session=args.session, live=not args.plan,
                    report_dir=args.report_dir)
    report['facts_loaded'] = len(confirmed)
    report['actions'] = []
    def checkpoint():
        if args.report_dir:
            write_json(Path(args.report_dir) / 'auto-result.json', report)
    checkpoint()
    budget = args.limit
    halted = False
    if args.apply:
        if not args.shop:
            raise DoudianError('shop_required', '自动写入必须明确 --shop；不会默认选择店铺。')
        from .bridge import Bridge
        from .editor import Editor
        from .attribute_workflow import publish_attributes
        def queue_check(pid):
            rows = [p for p in batch.batch_status()['products'] if p['product_id'] == pid]
            if len(rows) != 1 or rows[0]['shop'] != args.shop:
                raise DoudianError('auto_identity_conflict', '资料商品必须唯一且属于明确店铺。')
            row = rows[0]
            if (row['state'] in ('verified', 'ready', 'editing', 'uploaded', 'submitting', 'submitted', 'agent_claimed') or
                    row.get('submission_state') not in (None, 'not_attempted') or row.get('submission_attempts', 0)):
                raise DoudianError('auto_product_occupied', '已有编辑/提交/已完成任务，自动补属性不得覆盖。')
        if confirmed:
            editor = Editor(Bridge(args.endpoint, session=args.session))
            for pid, values in confirmed.items():
                if budget <= 0:
                    break
                budget -= 1
                try:
                    queue_check(pid)
                    identity = {'product_id': pid, 'shop': args.shop,
                                'edit_url': f'https://fxg.jinritemai.com/ffa/g/create?product_id={pid}'}
                    result = publish_attributes(editor, identity, values, queue_check=queue_check)
                    report['actions'].append({'kind': 'attributes', **result})
                    checkpoint()
                except DoudianError as exc:
                    report['actions'].append({'kind': 'attributes', 'product_id': pid,
                                              'error': exc.code, 'persisted': False})
                    checkpoint()
                    if exc.waiting or exc.code.startswith(('ego_', 'transport_', 'attribute_fill_', 'attribute_submission_')):
                        halted = True
                        break
        # Queue execution is already durable and enforces images, full SKU and unknown guards.
        products = batch.batch_status()['products']
        uncertain = [p['product_id'] for p in products if p['shop'] == args.shop and
                     p.get('submission_state') in ('unknown', 'accepted') and p['state'] != 'verified']
        def dispatch(kind, **kwargs):
            nonlocal halted
            try:
                report['actions'].append({'kind': kind, 'result': batch.run_batch(
                    args.endpoint, session=args.session, **kwargs)})
            except DoudianError as exc:
                report['actions'].append({'kind': kind, 'error': exc.code})
                halted = True  # No further browser actions after an unsettled failure.
            checkpoint()
        if uncertain and not halted:
            dispatch('readback', product_ids=uncertain[:args.limit], limit=args.limit,
                     readback_only=True, resume_only=True)
        if not halted:
            readiness = batch.execution_readiness(args.endpoint)
            ready = [p['product_id'] for p in batch.batch_status()['products']
                     if p['shop'] == args.shop and p['state'] == 'ready']
            if ready and budget > 0 and readiness.get('writer_ready'):
                dispatch('batch_write', product_ids=ready[:budget], limit=budget)
            elif ready and not readiness.get('writer_ready'):
                report['actions'].append({'kind': 'batch_write', 'blocked': 'writer_not_accepted'})
    report['queue_after'] = batch.batch_status().get('counts')
    persisted = {a['product_id'] for a in report['actions'] if a.get('kind') == 'attributes' and a.get('persisted')}
    report['facts_checklist'] = [item for item in report['facts_checklist'] if item['product_id'] not in persisted]
    if args.report_dir:
        out = Path(args.report_dir)
        out.mkdir(parents=True, exist_ok=True)
        if report['facts_checklist']:
            write_facts_template(report, out / 'facts-needed.json')
        (out / 'auto-report.md').write_text(render(report, as_markdown=True), encoding='utf-8')
        write_json(out / 'auto-result.json', report)
    report['summary'] = render(report)
    return report
