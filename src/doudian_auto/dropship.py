"""单商品机会铺货任务编排。

把来源商品、价格人工确认、共享搬家配置的审计和目标商品读回绑定到一个持久任务。
铺货是一次外部写入，所以结果未知时任务只允许只读核查，绝不重放复制动作。

页面选择器不放在这里：所有 DOM 动作都由 DropshipPages 在一次 evaluate 内完成
「重识别 → 唯一性校验 → 执行 → 即时读回」，本模块只负责任务身份、阶段与边界。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import time

from .cli import process_alive
from .errors import DoudianError
from .jobs import DATA_ROOT, Lock, read_json, write_json

# 铺货结果只有三种终态：明确成功、明确失败、未知。未知不是失败，也不许当成成功。
COPY_OUTCOMES = ('copied', 'failed', 'unknown')

# 这些阶段一律禁止再触发写入（贴链接、抓取、写配置、点复制）。
# 注意 unknown 也在其中：它禁止的是写入，但**不禁止只读核查**——
# 读复制历史、读官方页正是 unknown 阶段唯一该做的事。
WRITE_FORBIDDEN_STAGES = frozenset({
    'unknown',
    'copying_after_intent',
    'verification_pending',
    'copied',
    'verified',
    'blocked',
})


def _decimal(value, label):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise DoudianError('dropship_price_invalid', f'{label}必须是有效金额。') from None
    if not result.is_finite() or result < 0:
        raise DoudianError('dropship_price_invalid', f'{label}必须是非负有限金额。')
    return result


def calculate_price(source_price, multiplier, addition):
    """按任务输入试算最终价，统一按分四舍五入。

    这一步只做算术，不写任何页面。它的存在是让人在 apply 之前看到
    「源价 / 公式 / 最终价」，因为价格是对外的商业承诺，不能由程序单方面决定。
    """
    source = _decimal(source_price, '源价')
    factor = _decimal(multiplier, '倍数')
    add = _decimal(addition, '加价')
    if factor <= 0:
        raise DoudianError('dropship_price_invalid', '倍数必须大于0。')
    final = (source * factor + add).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {
        'source_price': format(source, '.2f'),
        'formula': f'{factor} × 源价 + {add}',
        'final_price': format(final, '.2f'),
    }


def _canonical_hash(identity):
    """规范 JSON 摘要。

    不复用 jobs.content_hash：那个函数的入参形状是围绕标题任务的（product_id/title/mode），
    把价格输入硬塞进 title 字段只会让摘要含义含糊。
    """
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()[:16]


def _acquire_task_lock(path):
    """只删除经复核已退出进程持有的锁，再复用 jobs.Lock 的排他创建。"""
    path = Path(path)
    if path.exists():
        try:
            raw = path.read_text(encoding='ascii').strip()
            pid = int(raw)
        except (OSError, ValueError):
            raise DoudianError('invalid_lock', '铺货锁内容异常，未删除。') from None
        if process_alive(pid):
            raise DoudianError('busy', f'铺货锁所属进程 {pid} 仍在运行，拒绝操作。')
        # 再读一次，防止在判活期间锁被另一个进程替换过。
        try:
            if path.read_text(encoding='ascii').strip() == str(pid):
                path.unlink()
        except FileNotFoundError:
            pass
    return Lock(path)


def _task_id(source_product_id, offer_url, shop):
    identity = {'source_product_id': source_product_id, 'offer_url': offer_url, 'shop': shop}
    return f'dropship-{source_product_id}-{_canonical_hash(identity)}'


def prepare_task(*, source_product_id, offer_url, shop, source_price,
                 multiplier, addition, root=None):
    """创建或读取单商品计划。此操作不连浏览器，也不执行任何写入。"""
    if not re.fullmatch(r'\d{1,24}', str(source_product_id)):
        raise DoudianError('dropship_source_invalid', '来源商品 ID 必须是数字字符串。')
    if not offer_url.startswith('https://'):
        raise DoudianError('dropship_offer_invalid', '1688 商品链接必须使用 HTTPS。')
    if not shop.strip():
        raise DoudianError('dropship_shop_missing', '必须指定店铺。')

    price = calculate_price(source_price, multiplier, addition)
    root = Path(root or DATA_ROOT / 'dropship').resolve()
    task_id = _task_id(str(source_product_id), offer_url, shop.strip())
    job = root / task_id
    job.mkdir(parents=True, exist_ok=True)

    manifest = {
        'schema_version': 1,
        'task_id': task_id,
        'source_product_id': str(source_product_id),
        'offer_url': offer_url,
        'shop': shop.strip(),
        'price_input': {
            'source_price': price['source_price'],
            'multiplier': str(multiplier),
            'addition': str(addition),
        },
        'price_preview': price,
        'identity_hash': _canonical_hash({
            'source_product_id': str(source_product_id),
            'offer_url': offer_url,
            'shop': shop.strip(),
            'price_input': manifest_price_input(price, multiplier, addition),
        }),
        # 初版只允许放入仓库。「立即上架」涉及真实售卖，必须人工另行确认。
        'shelf_mode': '放入仓库',
    }
    manifest_path = job / 'manifest.json'
    state_path = job / 'state.json'

    if manifest_path.exists():
        existing = read_json(manifest_path)
        if existing != manifest:
            raise DoudianError('dropship_task_conflict', '已有任务计划与当前输入不一致。')
    else:
        write_json(manifest_path, manifest)
        write_json(state_path, {
            'stage': 'prepared',
            'submission_status': 'not_attempted',
            'created_at': time.time(),
            'updated_at': time.time(),
        })

    return {
        'task_id': task_id,
        'job_dir': str(job),
        'stage': read_json(state_path)['stage'],
        'dry_run': True,
        'price_confirmation': price,
        'shelf_mode': '放入仓库',
        'next': '核对源价、公式和最终价；确认后以同一任务执行 dropship apply --apply。',
    }


def manifest_price_input(price, multiplier, addition):
    """价格输入单独成函数，避免在 manifest 字典里自引用未定义变量。"""
    return {
        'source_price': price['source_price'],
        'multiplier': str(multiplier),
        'addition': str(addition),
    }


def record_configuration_audit(job, before, target, after):
    """持久记录共享搬家配置的前值、目标值、后值，读回不一致就停止。

    搬家配置是共享设置，改它会影响后续人工和其他自动任务，所以前后值都要留证；
    这也是恢复原值的唯一依据。
    """
    job = Path(job)
    if not all(isinstance(x, dict) for x in (before, target, after)):
        raise DoudianError('dropship_config_invalid', '配置审计必须是对象。')
    audit = {
        'recorded_at': time.time(),
        'before': before,
        'target': target,
        'after': after,
        'matches_target': after == target,
    }
    write_json(job / 'configuration-audit.json', audit)
    if after != target:
        state_path = job / 'state.json'
        state = read_json(state_path)
        state.update(stage='blocked', last_error='configuration_readback_mismatch',
                     updated_at=time.time())
        write_json(state_path, state)
        raise DoudianError('dropship_config_mismatch', '搬家配置读回不一致，停止并交人工处理。')
    return audit


def require_copy_write_allowed(state):
    """写入闸门：unknown 只禁写入，不禁只读核查。

    早期版本在 unknown 阶段直接 raise，把「读复制历史」这条唯一的恢复路径也堵死了，
    任务会永久卡死。写入和读回是两种不同权限，必须分开判断。
    """
    if state.get('stage') in WRITE_FORBIDDEN_STAGES or state.get('submission_status') == 'unknown':
        raise DoudianError(
            'dropship_readback_only',
            '复制状态未知或已进入只读阶段；禁止贴链接、抓取、写配置或再次点击复制。')
    if state.get('stage') != 'settings_verified':
        raise DoudianError('dropship_stage_invalid', '搬家配置尚未核验，不能开始复制。')


def mark_copy_intent(job):
    """写入前持久化 unknown，防止进程中断后重复触发复制。

    先落 unknown 再点按钮：哪怕进程在点击后被杀，重启后读到的也是 unknown，
    于是只能只读核查，不会重复铺一次货。
    """
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)
    require_copy_write_allowed(state)
    state.update(stage='unknown', submission_status='unknown',
                 copy_intent_at=time.time(), updated_at=time.time())
    write_json(state_path, state)


def record_copy_observation(job, *, outcome, evidence=None, target_product_id=None):
    """只接受明确读回；未知状态保持只读，不自动重试。

    三种终态分开处理：copied 前进到 copied；failed 是明确失败，停在 blocked 并保留证据；
    unknown 既不前进也不重试。把 failed 混进 unknown 会让人误以为还有机会重跑。
    """
    if outcome not in COPY_OUTCOMES:
        raise DoudianError('dropship_outcome_invalid', f'复制结果必须是 {COPY_OUTCOMES} 之一。')
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)

    if outcome == 'unknown':
        state.update(stage='unknown', submission_status='unknown',
                     last_readback=evidence, updated_at=time.time())
        write_json(state_path, state)
        return {'stage': 'unknown', 'readback_only': True}

    if outcome == 'failed':
        state.update(stage='blocked', submission_status='failed',
                     last_readback=evidence, last_error='copy_failed',
                     updated_at=time.time())
        write_json(state_path, state)
        return {'stage': 'blocked', 'failed': True, 'readback': evidence}

    if not re.fullmatch(r'\d{16,22}', str(target_product_id or '')):
        state.update(stage='blocked', last_readback=evidence,
                     last_error='copy_readback_invalid', updated_at=time.time())
        write_json(state_path, state)
        raise DoudianError('dropship_copy_unverified', '商品 ID 读回不完整，停止并交人工处理。')

    state.update(stage='copied', submission_status='accepted',
                 target_product_id=str(target_product_id),
                 copy_evidence=evidence, updated_at=time.time())
    write_json(state_path, state)
    return {'stage': 'copied', 'target_product_id': str(target_product_id)}


def verify_target_readback(job, *, sku_rows, review_status, sku_total_count=None):
    """报告官方页观察值；价格由页面适配器从 input.value 读回后传入。

    sku_total_count 是完整性依据：官方页表格可能虚拟滚动，读到的行数少于实际 SKU 数时，
    绝不能把部分行当成完整结果。没有可靠总数计数就停在 verification_pending。
    """
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)
    if state.get('stage') not in ('copied', 'warehouse_created', 'verification_pending'):
        raise DoudianError('dropship_stage_invalid', '没有可核验的铺货结果。')
    if not isinstance(sku_rows, list) or not sku_rows:
        raise DoudianError('dropship_sku_missing', '官方编辑页没有读到 SKU 行。')

    if sku_total_count is None or len(sku_rows) != sku_total_count:
        state.update(stage='verification_pending', sku_rows_observed=len(sku_rows),
                     sku_total_count=sku_total_count,
                     last_error='sku_total_count_unverified', updated_at=time.time())
        write_json(state_path, state)
        return {
            'stage': 'verification_pending',
            'sku_rows_observed': len(sku_rows),
            'sku_total_count': sku_total_count,
            'reason': 'SKU 行数与页面总数计数不一致或缺少总数计数，不标 verified。',
        }

    if not isinstance(review_status, str) or not review_status.strip():
        raise DoudianError('dropship_review_unknown', '审核状态无法读取；不作推断。')

    report = {
        'product_id': state.get('target_product_id'),
        'sku_rows': sku_rows,
        'sku_total_count': sku_total_count,
        'review_status_read_only': review_status,
        'verified_at': time.time(),
    }
    write_json(job / 'target-readback.json', report)
    # 初版不推断审核或消费者端状态：页面读到什么就报什么。
    state.update(stage='verified', target_readback='target-readback.json',
                 review_status_read_only=review_status, updated_at=time.time())
    write_json(state_path, state)
    return report


def _settings_observation(args):
    """只读搬家配置快照。不写共享设置，也不点保存。"""
    from .dropship_pages import DropshipPages
    from .ego_bridge import EgoBridge

    bridge = EgoBridge(session=args.session)
    bridge.require_ready()
    return DropshipPages(bridge).read_settings()


def run_task(args):
    """CLI 入口。页面写动作由 DropshipPages 完成，任务层不拼选择器。"""
    root = Path(args.data_root or DATA_ROOT / 'dropship').resolve()
    job = root / args.task_id
    manifest_path = job / 'manifest.json'
    state_path = job / 'state.json'
    if not manifest_path.is_file() or not state_path.is_file():
        raise DoudianError('dropship_task_missing', '找不到对应的铺货任务。')

    manifest = read_json(manifest_path)
    state = read_json(state_path)

    if not args.apply:
        return {
            'dry_run': True,
            'task_id': args.task_id,
            'stage': state.get('stage'),
            'price_confirmation': manifest['price_preview'],
            'shelf_mode': manifest['shelf_mode'],
            'next': '核对源价、公式和最终价；加 --apply 才继续。',
        }

    if state.get('stage') == 'unknown' or state.get('submission_status') == 'unknown':
        raise DoudianError('dropship_readback_only', '任务处于 unknown；apply 被禁止，只能只读核查。')

    with _acquire_task_lock(root / 'browser.lock'):
        # v1 只做到「读搬家配置」：写入配置、点复制、读历史都留给后续阶段，
        # 每个阶段都要先在真实页面验收即时读回再接进状态机。
        observation = _settings_observation(args)
        return {
            'task_id': args.task_id,
            'stage': read_json(state_path).get('stage'),
            'phase': 'settings_observation',
            'page_observation': observation,
            'next': '页面读回需由人确认；复制结果未知时仅使用只读核查。',
        }
