"""One-command commander: decide what each queue product needs, do the safe parts.

The point of this module is that the user stops reading dashboards. It walks the queue,
classifies every product from live evidence, performs the actions that are provably safe
and fully automatic, and returns one human-readable list of what still needs a person.

It deliberately never invents product facts. A missing 安装方式 or 尺寸 stops that product
and becomes a checklist line, because guessing a specification is a false advertisement to
the platform, not a shortcut.

Nothing here writes to a product unless the caller asks for it and every gate in
`WRITE_GATES` is satisfied; see `decide()` for the per-product routing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import batch
from .errors import DoudianError

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
    READ_ONLY: '只读确认，正常',
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


def survey(*, endpoint='ego', session='doudian-auto', db_path=None):
    """Classify the whole queue and return the per-outcome buckets plus a fact checklist."""
    status = batch.batch_status(db_path=db_path)
    products = status.get('products') or []
    # batch_status omits the fact blob; titles live there, and a checklist without a name
    # is unusable for someone who has to decide which product to go look at.
    titled = _titles_by_product(db_path)

    buckets: dict[str, list] = {}
    checklist = []
    sku_waiting = []
    for row in products:
        outcome, reason = decide(row)
        title = titled.get(row.get('product_id')) or _product_title(row)
        buckets.setdefault(outcome, []).append({
            'product_id': row.get('product_id'),
            'state': row.get('state'),
            'submission_state': row.get('submission_state'),
            'title': title,
            'reason': reason,
        })
        if outcome == WAIT_FACTS:
            missing = _missing_fields(row.get('last_error'))
            # SKU code problems carry no attribute names; asking for an empty attribute
            # block would be a dead line in the checklist, so they are listed separately.
            if missing:
                checklist.append({
                    'product_id': row.get('product_id'),
                    'title': title,
                    'fields': missing,
                    'queue_reason': (row.get('last_error') or '')[:160],
                })
            else:
                sku_waiting.append({
                    'product_id': row.get('product_id'),
                    'title': title,
                    'reason': (row.get('last_error') or '')[:160],
                })

    return {
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
        for outcome, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"- **{GROUP_LABELS.get(outcome, outcome)}**：{n} 件")
        checklist = report.get('facts_checklist') or []
        if checklist:
            lines.append('\n## 需要你提供的资料\n')
            lines.append('下表每件商品，请填上真实值。**不知道就写「待确认」，不要猜。**\n')
            for item in checklist:
                fields = '、'.join(item['fields']) or '（见队列原因）'
                lines.append(f"- `{item['product_id']}` {item.get('title') or ''}"
                             f" → 缺：{fields}")
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
    Path(path).write_text(json.dumps(template, ensure_ascii=False, indent=1), encoding='utf-8')
    return template


def load_facts(path):
    """Read the filled-in facts file, dropping blanks and '待确认' placeholders."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    usable = {}
    for item in data.get('items') or []:
        pid = str(item.get('product_id') or '')
        attrs = {k: v for k, v in (item.get('attributes') or {}).items()
                 if isinstance(v, str) and v.strip() and v.strip() != '待确认'}
        if pid and attrs:
            usable[pid] = attrs
    return usable
