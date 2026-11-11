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
from urllib.parse import urlparse

from .cli import process_alive
from .errors import DoudianError
from .jobs import DATA_ROOT, Lock, read_json, write_json

# 页面跳转后需要等待渲染完成再读，否则读到的是上一页的残留。
SETTLE_SECONDS = 12

# 铺货结果只有三种终态：明确成功、明确失败、未知。未知不是失败，也不许当成成功。
COPY_OUTCOMES = ('copied', 'failed', 'unknown')

# 搬家配置页的价格字段全集。目标配置必须覆盖全部，少一个就说明漏改了。
# 与 dropship_pages.PRICE_FIELDS 同源；放在这里是因为任务层要独立校验完整性，
# 而 dropship_pages 依赖任务层，复制一份常量比绕循环导入更清楚。
PRICE_FIELD_NAMES = (
    'pricePercent', 'priceAdd', 'priceSub', 'priceFinalPercent',
    'priceTail', 'priceDecimalDiyValue',
    'sourcePostFeePriceAddValue', 'postFeePrice1688AddValue',
)

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

    注意这只是**简化公式**的试算，不是页面最终售价：页面上还有运费、
    最终价倍数、尾数等项。实测源价 2 铺出 15.48（2×3+5=11，差 4.48 是运费），
    运费不在价格字段里。所以试算只作人工确认用的参考，核验一律读官方页实际价格。
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
        'page_price_percent': format(factor * 100, 'f'),
        'note': '简化公式试算，不含运费与尾数；页面 pricePercent 为百分比，倍数需 ×100。',
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


def _validate_offer_url(offer_url, source_product_id):
    """校验 offer URL 真的指向指定的那个 1688 商品，并规范成 HTTPS。

    只检查「是不是 https」是不够的：manifest 把来源 ID 和链接绑在一起，
    后面整个流程都相信这个绑定。链接与 ID 不匹配时，程序会去抓一个无关商品，
    而错误只在几天后的审核结果里才暴露出来。

    但也不能只收 https：仓库里现存的 42 条源链接**全部是 http**（实抓核对）。
    一刀切只收 https 会把全部现有关联都拒掉。所以 http 也接受，
    但写进 manifest 前统一规范成 https——页面访问用 https，保留可追溯的原链接。
    """
    parsed = urlparse(offer_url)
    match = re.fullmatch(r'/offer/(\d+)\.html', parsed.path)
    if (parsed.scheme not in ('http', 'https')
            or parsed.hostname != 'detail.1688.com'
            or not match
            or match.group(1) != str(source_product_id)):
        raise DoudianError(
            'dropship_offer_invalid',
            'offer URL 必须是 detail.1688.com 的 /offer/<来源商品ID>.html，且 ID 必须与来源一致。')
    return f'https://{parsed.hostname}{parsed.path}'


def _canonical_offer_url(offer_url, source_product_id):
    """返回规范化的 HTTPS 链接，同时保留原始链接供追溯。"""
    canonical = _validate_offer_url(offer_url, source_product_id)
    return canonical, offer_url


def resolve_job_dir(root, task_id):
    """把任务 ID 解析成任务目录，并确认它没有越出任务根目录。

    任务 ID 直接来自命令行。不校验的话，`..\\..\\` 或绝对路径能让流程在
    预期根目录之外读写 manifest/state，任务身份边界就没了。
    """
    if not re.fullmatch(r'dropship-\d{1,24}-[0-9a-f]{16}', str(task_id)):
        raise DoudianError('dropship_task_invalid', '铺货任务 ID 格式无效。')
    root = Path(root).resolve()
    job = (root / task_id).resolve()
    if job.parent != root:
        raise DoudianError('dropship_task_invalid', '铺货任务路径越出任务根目录。')
    return job


def prepare_task(*, source_product_id, offer_url, shop, source_price,
                 multiplier, addition, root=None):
    """创建或读取单商品计划。此操作不连浏览器，也不执行任何写入。"""
    if not re.fullmatch(r'\d{1,24}', str(source_product_id)):
        raise DoudianError('dropship_source_invalid', '来源商品 ID 必须是数字字符串。')
    canonical_url, original_url = _canonical_offer_url(offer_url, str(source_product_id))
    if not shop.strip():
        raise DoudianError('dropship_shop_missing', '必须指定店铺。')

    price = calculate_price(source_price, multiplier, addition)
    root = Path(root or DATA_ROOT / 'dropship').resolve()
    task_id = _task_id(str(source_product_id), canonical_url, shop.strip())
    job = root / task_id
    job.mkdir(parents=True, exist_ok=True)

    manifest = {
        'schema_version': 1,
        'task_id': task_id,
        'source_product_id': str(source_product_id),
        'offer_url': canonical_url,
        'offer_url_original': original_url,
        'shop': shop.strip(),
        'price_input': {
            'source_price': price['source_price'],
            'multiplier': str(multiplier),
            'addition': str(addition),
        },
        'price_preview': price,
        'identity_hash': _canonical_hash({
            'source_product_id': str(source_product_id),
            'offer_url': canonical_url,
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
            # 来源商品 ID 存进状态：复制历史里读到的行必须与它一致，
            # 否则无法证明读到的是本次任务的记录而不是别人的。
            'source_product_id': str(source_product_id),
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


def record_verified_configuration(job, *, before, target, persisted_after):
    """只有在「独立重新进入页面」读回完整目标配置后，才推进到 settings_verified。

    单次 evaluate 里写完再读同一份 DOM 只能证明输入框里的值变了，
    不能证明服务端存了。实测整页刷新后 8 个价格字段与「放入仓库」radio 都保持，
    说明这条独立读回路径可行。

    完整字段集合也是硬条件：目标配置必须覆盖全部价格字段，
    少写一个运费或尾数字段，读回仍然一致，那就说明漏改了。
    """
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)
    if state.get('stage') != 'prepared':
        raise DoudianError('dropship_stage_invalid', '任务不能进入配置已核验阶段。')
    missing = sorted(set(PRICE_FIELD_NAMES) - set(target or {}))
    if missing:
        raise DoudianError(
            'dropship_config_incomplete',
            f'目标配置缺少价格字段：{"、".join(missing)}。')
    # 货架模式同样要明确：只对齐了价格却没确认「放入仓库」，
    # 等于没确认商品会被放进仓库而不是直接开卖。
    if ((target or {}).get('shelf_mode') != '放入仓库'
            or (persisted_after or {}).get('shelf_mode') != '放入仓库'):
        raise DoudianError(
            'dropship_shelf_mode_unverified',
            '目标配置与独立读回都必须明确 shelf_mode 为「放入仓库」。')
    audit = record_configuration_audit(job, before, target, persisted_after)
    state.update(stage='settings_verified', configuration_audit='configuration-audit.json',
                 updated_at=time.time())
    write_json(state_path, state)
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


def require_no_pending_history(job, pending_rows):
    """同来源存在「有源ID、还没商品ID」的历史行时，不许开始新的复制。

    那种行是上一次复制卡在中间态的痕迹。这次再复制一遍，
    可能产生两个商品。所以先停下交人工核对。
    """
    if pending_rows:
        raise DoudianError(
            'dropship_history_pending',
            f'该来源有 {pending_rows} 条未完成的历史行（上一次复制可能卡住了），'
            '请先人工核对再继续。')


def mark_copy_intent(job, *, expected_skus=None, history_baseline=None):
    """写入前持久化 unknown，防止进程中断后重复触发复制。

    先落 unknown 再点按钮：哪怕进程在点击后被杀，重启后读到的也是 unknown，
    于是只能只读核查，不会重复铺一次货。

    同时落盘两样东西：
    - expected_skus：复制**前**从 1688 来源页读到的规格名与批发价。
      这是复制前唯一存在的先验（官方页上此时还没有这个商品），
      核验时拿官方页的 SKU 名与它比对，才能证明铺出去的是同一批规格。
      不落盘的话，核验就成了调用方自己给自己出标准。
    - history_baseline：点击复制前复制历史里的既有行。核验时只认基线之后
      新增的行——否则一条旧记录也会被当成本次复制成功。
    """
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)
    require_copy_write_allowed(state)
    state.update(stage='unknown', submission_status='unknown',
                 copy_intent_at=time.time(), updated_at=time.time())
    if expected_skus:
        state['expected_skus'] = dict(expected_skus)
    if history_baseline is not None:
        state['history_baseline'] = list(history_baseline)
    write_json(state_path, state)


def record_copy_observation(job, *, outcome, evidence=None, target_product_id=None):
    """只接受明确读回；未知状态保持只读，不自动重试。

    三种终态分开处理：copied 前进到 copied；failed 是明确失败，停在 blocked 并保留证据；
    unknown 既不前进也不重试。把 failed 混进 unknown 会让人误以为还有机会重跑。

    copied 还要求「确实点过复制」并且证据里带得回本次来源：
    之前只校验商品 ID 的位数，等于任何人拿一个 19 位数字就能把任务写成已复制。
    """
    if outcome not in COPY_OUTCOMES:
        raise DoudianError('dropship_outcome_invalid', f'复制结果必须是 {COPY_OUTCOMES} 之一。')
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)

    # 终态不可回退：verified / blocked 的任务不能再被改成 unknown。
    if state.get('stage') in ('verified', 'blocked'):
        raise DoudianError(
            'dropship_terminal_state',
            f"任务已处于终态 {state.get('stage')}，不接受新的复制观察结果。")

    if outcome == 'unknown':
        # unknown 也要求已落盘复制意图：没有意图就不该出现 unknown 观察
        if state.get('stage') != 'unknown' and state.get('submission_status') != 'unknown':
            if state.get('stage') != 'settings_verified':
                raise DoudianError('dropship_stage_invalid', '没有待核查的复制意图，不能记录未知结果。')
        state.update(stage='unknown', submission_status='unknown',
                     last_readback=evidence, updated_at=time.time())
        write_json(state_path, state)
        return {'stage': 'unknown', 'readback_only': True}

    if outcome == 'failed':
        if state.get('stage') not in ('unknown', 'settings_verified'):
            raise DoudianError('dropship_stage_invalid', '没有待核查的复制意图，不能记录失败结果。')
        state.update(stage='blocked', submission_status='failed',
                     last_readback=evidence, last_error='copy_failed',
                     updated_at=time.time())
        write_json(state_path, state)
        return {'stage': 'blocked', 'failed': True, 'readback': evidence}

    # copied：必须先有落盘的复制意图，否则说明有人凭空宣布成功。
    if state.get('stage') != 'unknown' or state.get('submission_status') != 'unknown':
        raise DoudianError('dropship_stage_invalid', '没有待核查的复制意图，不能标记为已复制。')
    if not isinstance(evidence, dict) or not evidence.get('history_row'):
        raise DoudianError('dropship_copy_unverified', '缺少复制历史行证据，不能标记为已复制。')
    if str(evidence.get('source_product_id') or '') != str(state.get('source_product_id') or ''):
        raise DoudianError('dropship_copy_unverified', '复制历史行的来源商品与本任务不一致。')
    # 基线校验：只认点击复制之后新增的历史行。
    # 没有基线就无法区分「本次新增」与「历史里本来就有的那条」。
    baseline = state.get('history_baseline')
    if baseline is None:
        raise DoudianError('dropship_copy_unverified', '缺少复制历史基线，无法区分新旧记录。')
    row_key = str(evidence.get('history_row_key') or '')
    if not row_key:
        raise DoudianError('dropship_copy_unverified', '缺少历史行的稳定标识，无法与基线比对。')
    if row_key in set(map(str, baseline)):
        raise DoudianError('dropship_copy_unverified', '该历史行在复制前就已存在，不是本次新增。')
    # 稳定键必须与读回的目标商品一致，否则说明键与行不是一回事
    if not row_key.endswith('@' + str(target_product_id or '')):
        raise DoudianError('dropship_copy_unverified', '历史行的稳定标识与目标商品 ID 不一致。')
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


def verify_target_readback(job, *, product_id, sku_rows,
                           sku_total_count, price_progress, review_status):
    """核对官方页读回与预期是否一致；不一致一律停在 verification_pending。

    之前只检查「行数等于总数」，那只能证明读到的行数和传进来的数字相等，
    调用方传两条编造的行再传 sku_total_count=2 就能标成 verified。
    现在必须同时满足：商品 ID 与复制历史一致、页面价格填写进度是 100%、
    读到的 SKU 集合与预期完全一致、审核状态原文可读。

    expected_skus 来自复制时的页面读回并持久化，不是核验时临时指定的。
    """
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)
    if state.get('stage') not in ('copied', 'warehouse_created', 'verification_pending'):
        raise DoudianError('dropship_stage_invalid', '没有可核验的铺货结果。')
    if str(product_id) != str(state.get('target_product_id') or ''):
        raise DoudianError('dropship_product_mismatch', '官方页商品 ID 与复制历史不一致。')
    if not isinstance(sku_rows, list) or not sku_rows:
        raise DoudianError('dropship_sku_missing', '官方编辑页没有读到 SKU 行。')

    observed = {}
    for row in sku_rows:
        if not isinstance(row, dict) or not row.get('sku'):
            raise DoudianError('dropship_sku_missing', 'SKU 行缺少名称。')
        if row['sku'] in observed:
            raise DoudianError('dropship_sku_duplicate', f"SKU 名称重复：{row['sku']}。")
        observed[row['sku']] = str(row.get('price') or '')

    # 预期 SKU 只从状态里读，不接受调用方现传：调用方现传就等于自己给自己出标准。
    # 它的值是来源批发价，比对的是**规格名集合**：
    # 官方页的售价含运费与尾数，与来源批发价不相等是正常的，
    # 但规格名必须一一对应，少一个规格就说明没铺全。
    expected = dict(state.get('expected_skus') or {})
    reasons = []
    if not expected:
        reasons.append('缺少复制时记录的预期 SKU 集合')
    if sku_total_count is None:
        reasons.append('缺少页面 SKU 总数计数')
    elif len(sku_rows) != sku_total_count:
        reasons.append(f'读回行数 {len(sku_rows)} 与页面总数 {sku_total_count} 不一致')
    if price_progress != 100:
        reasons.append(f'页面价格填写进度为 {price_progress}%，不是 100%')
    if expected and set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        detail = []
        if missing:
            detail.append('缺少规格 ' + '、'.join(missing))
        if extra:
            detail.append('多出规格 ' + '、'.join(extra))
        reasons.append('读回的规格名与来源不一致：' + '；'.join(detail))

    if reasons:
        state.update(stage='verification_pending', sku_rows_observed=len(sku_rows),
                     sku_total_count=sku_total_count,
                     last_error='sku_readback_unverified', updated_at=time.time())
        write_json(state_path, state)
        return {
            'stage': 'verification_pending',
            'sku_rows_observed': len(sku_rows),
            'sku_total_count': sku_total_count,
            'reason': '；'.join(reasons) + '，不标 verified。',
        }

    if not isinstance(review_status, str) or not review_status.strip():
        raise DoudianError('dropship_review_unknown', '审核状态无法读取；不作推断。')

    report = {
        'stage': 'verified',
        'product_id': str(product_id),
        'sku_rows': sku_rows,
        'sku_total_count': sku_total_count,
        'price_progress': price_progress,
        'review_status': review_status,
        'verified_at': time.time(),
    }
    write_json(job / 'target-readback.json', report)
    # 初版不推断审核或消费者端状态：页面读到什么就报什么。
    state.update(stage='verified', target_readback='target-readback.json',
                 review_status=review_status, updated_at=time.time())
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
    job = resolve_job_dir(root, args.task_id)
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

    # unknown 阶段：写入被禁止，但只读核查必须放行——读复制历史正是唯一出路。
    if state.get('stage') == 'unknown' or state.get('submission_status') == 'unknown':
        with _acquire_task_lock(root / 'browser.lock'):
            return _readback_only(args, job, state, manifest)

    if getattr(args, 'readback_only', False):
        with _acquire_task_lock(root / 'browser.lock'):
            return _readback_only(args, job, state, manifest)

    with _acquire_task_lock(root / 'browser.lock'):
        return _advance(args, job, state, manifest)


def _advance(args, job, state, manifest):
    """按阶段推进任务。每个阶段的推进都由页面证据支撑，不靠推断。

    阶段：
      prepared → 写搬家配置 → 独立重新读回 → settings_verified
      settings_verified → 读来源 SKU → 采历史基线 → 贴链接 → 抓取 → 落复制意图 → 点复制
      unknown → 读复制历史 → copied
      copied → 读官方页 → verified / verification_pending
    """
    from .dropship_pages import DropshipPages
    from .ego_bridge import EgoBridge

    bridge = EgoBridge(session=args.session)
    bridge.require_ready()
    pages = DropshipPages(bridge)
    stage = state.get('stage')

    if stage == 'prepared':
        return _stage_settings(args, job, state, manifest, pages)
    if stage == 'settings_verified':
        return _stage_copy(args, job, state, manifest, pages)
    if stage in ('unknown', 'copied', 'verification_pending'):
        return _readback_only(args, job, state, manifest)
    raise DoudianError('dropship_stage_invalid', f'任务处于无法推进的阶段：{stage}。')


def _stage_settings(args, job, state, manifest, pages):
    """写搬家配置，然后**独立重新进入页面**读回，读回一致才推进。"""
    from .dropship_pages import PRICE_FIELDS, SETTING_PATH

    job_state_path = job / 'state.json'
    pages.navigate_miaoshou(SETTING_PATH)
    time.sleep(SETTLE_SECONDS)

    before = pages.read_settings()
    target = dict(before.get('values') or {})
    # 只改任务明确指定的字段。
    # ⚠️ 倍数与百分比差 100 倍：页面的 pricePercent 是 300 表示 300%，
    # 而任务的 multiplier 是 3 表示三倍。直接写 3 会把定价变成 3%。
    price_input = manifest.get('price_input') or {}
    percent = calculate_price(price_input.get('source_price'),
                              price_input.get('multiplier'),
                              price_input.get('addition')).get('page_price_percent')
    target['pricePercent'] = percent
    target['priceAdd'] = price_input.get('addition')
    target['shelf_mode'] = '放入仓库'

    written = pages.set_price_formula(
        before=before.get('values') or {},
        target={k: v for k, v in target.items() if k in PRICE_FIELDS})
    if written.get('persistence') != 'unverified':
        raise DoudianError('dropship_config_invalid', '写配置的即时读回语义不对。')

    # 独立读回：重新进入页面再读，不是同一次 evaluate 里的二次读取
    pages.navigate_miaoshou(SETTING_PATH)
    time.sleep(SETTLE_SECONDS)
    after = pages.read_settings()
    persisted = dict(after.get('values') or {})
    persisted['shelf_mode'] = after.get('shelf_mode')

    audit = record_verified_configuration(job, before=before.get('values') or {},
                                          target=target, persisted_after=persisted)
    return {
        'task_id': args.task_id,
        'stage': read_json(job_state_path).get('stage'),
        'phase': 'settings_verified',
        'configuration_audit': audit,
        'note': '配置已在重新进入页面后独立读回一致，货架模式为放入仓库。',
    }


def _wait_for_fetch_result(pages, *, attempts=12, interval=4):
    """轮询等抓取结果出现。

    抓取是后台任务：点完「开始批量抓取商品」，结果页的计数器要过几秒才渲染出来。
    读一次就判断会把「还没好」误判成「失败」。
    超时上限到了就把最后一次读到的如实返回，让调用方按不干净处理。
    """
    last = {}
    for _ in range(attempts):
        last = pages.read_fetch_result()
        if last.get('success_count') is not None and last.get('skipped_count') is not None:
            return last
        time.sleep(interval)
    return last


def _stage_copy(args, job, state, manifest, pages):
    """贴链接 → 抓取 → 落复制意图 → 点复制。"""
    from .dropship_pages import HISTORY_PATH, MOVE_PATH

    job_state_path = job / 'state.json'
    offer_url = manifest['offer_url']
    source_id = manifest['source_product_id']

    # 1) 读来源商品的规格：复制前唯一的先验
    pages.navigate_source(offer_url)
    time.sleep(SETTLE_SECONDS)
    source_skus = pages.read_source_skus(offer_url=offer_url)
    expected = {row['sku']: row['source_price']
                for row in source_skus.get('sku_rows') or []}
    if not expected:
        raise DoudianError('dropship_source_sku_missing',
                           '来源商品没有读到规格，无法建立预期。')

    # 2) 采历史基线：点击复制前已有的行
    pages.navigate_miaoshou(HISTORY_PATH)
    time.sleep(SETTLE_SECONDS)
    baseline = pages.read_history_baseline(source_product_id=source_id)
    require_no_pending_history(job, baseline.get('pending_rows'))

    # 3) 贴链接并抓取。抓取是异步的：点完按钮后结果页要过一会儿才有计数器，
    #    所以要轮询等它出现，而不是读一次就下结论。
    pages.navigate_miaoshou(MOVE_PATH)
    time.sleep(SETTLE_SECONDS)
    pages.paste_offer_and_fetch(offer_url=offer_url)
    fetch = _wait_for_fetch_result(pages)
    if fetch.get('success_count') != '1' or fetch.get('skipped_count') != '0':
        raise DoudianError(
            'dropship_fetch_incomplete',
            f"抓取结果不干净（成功 {fetch.get('success_count')} / 跳过 "
            f"{fetch.get('skipped_count')}），未点复制。")

    # 4) 先落复制意图，再点按钮
    mark_copy_intent(job, expected_skus=expected,
                     history_baseline=baseline.get('baseline_keys'))
    pages.click_start_copy(expected_success=1)

    return {
        'task_id': args.task_id,
        'stage': read_json(job_state_path).get('stage'),
        'phase': 'copy_intent_clicked',
        'expected_skus': expected,
        'fetch': fetch,
        'note': '已点下一步开始复制；结果未知，只允许只读核查。',
    }


def _readback_only(args, job, state, manifest):
    """只读核查：读复制历史与官方页，绝不触发任何写入。

    用于 unknown 阶段——那时复制已经点过但结果不明，重来一次就可能铺两个商品。
    """
    from .dropship_pages import HISTORY_PATH, DropshipPages
    from .ego_bridge import EgoBridge

    bridge = EgoBridge(session=args.session)
    bridge.require_ready()
    pages = DropshipPages(bridge)
    result = {'task_id': args.task_id, 'readback_only': True, 'stage': state.get('stage')}

    target_id = state.get('target_product_id')
    if not target_id:
        # 还没有目标商品 ID：读复制历史，看这次复制是否其实已经落地
        pages.navigate_miaoshou(HISTORY_PATH)
        history = pages.read_history_product_id(
            source_product_id=manifest['source_product_id'])
        result['history'] = history
        # 必须传稳定键 history_row_key：基线里存的是 <源ID>@<商品ID>，
        # 拿整段行文本去比永远对不上，基线检查会被静默绕过。
        record_copy_observation(
            job, outcome='copied',
            evidence={'history_row': history.get('row_text'),
                      'history_row_key': history.get('row_key'),
                      'source_product_id': manifest['source_product_id']},
            target_product_id=history.get('product_id'))
        result['stage'] = 'copied'
        result['target_product_id'] = history.get('product_id')
        return result

    # 已有目标商品 ID：读官方页 SKU 与审核状态，原样报告
    pages.navigate_official(target_id)
    skus = pages.read_sku_prices(product_id=target_id)
    review = pages.read_review_status(product_id=target_id)
    result['sku_rows'] = skus.get('sku_rows')
    result['price_progress'] = skus.get('price_progress')
    result['sku_completeness'] = skus.get('completeness')
    # 审核状态在编辑页上读不到（那里只有 SKU 状态和上架/下架选项），
    # 所以如实报 unavailable，不拿 SKU 状态冒充审核状态。
    result['review_status'] = review.get('review_status')
    result['review_status_reason'] = review.get('review_status_reason')
    result['sku_status_tokens'] = review.get('sku_status_tokens')
    result['next'] = '只读核查完成；SKU 完整性未证实，是否推进到 verified 由人工判断。'
    return result
