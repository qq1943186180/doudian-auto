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
    'verified',          # 旧版终态，保留兼容
    'copy_confirmed',
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
                 multiplier, addition, root=None, source_title=None,
                 category=None, allow_risk=False):
    """创建或读取单商品计划。此操作不连浏览器，也不执行任何写入。"""
    if not re.fullmatch(r'\d{1,24}', str(source_product_id)):
        raise DoudianError('dropship_source_invalid', '来源商品 ID 必须是数字字符串。')
    canonical_url, original_url = _canonical_offer_url(offer_url, str(source_product_id))
    if not shop.strip():
        raise DoudianError('dropship_shop_missing', '必须指定店铺。')

    price = calculate_price(source_price, multiplier, addition)
    from .dropship_policy import precheck_category
    precheck = precheck_category(title=source_title, category=category)
    precheck['allow_risk'] = bool(allow_risk)
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
        'source_title': source_title,
        'category': category,
        'category_precheck': precheck,
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
        'category_precheck': precheck,
        'next': ('预检命中高风险，需人工确认类目必填属性后再继续。'
                 if precheck.get('risk') == 'high' and not allow_risk
                 else '核对源价、公式和最终价；确认后以同一任务执行 dropship apply --apply。'),
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
    if state.get('stage') in ('verified', 'copy_confirmed', 'blocked'):
        raise DoudianError(
            'dropship_terminal_state',
            f"任务已处于终态 {state.get('stage')}，不接受新的复制观察结果。")

    if outcome == 'unknown':
        # unknown 只能是对「已落盘复制意图」的补充说明，不能凭空创建。
        # 否则点击前的异常也会进 unknown，恢复路径会只读历史、
        # 永不继续，留下一个假 unknown 卡死任务。
        if (state.get('stage') != 'unknown'
                or state.get('submission_status') != 'unknown'
                or not state.get('copy_intent_at')):
            raise DoudianError(
                'dropship_stage_invalid',
                '没有已落盘的复制意图，不能把任务置为 unknown。')
        state.update(last_readback=evidence, updated_at=time.time())
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


def _require_shop_session(pages, *, page_name):
    """页面动作前先确认浏览器会话还登录着。

    实测（2026-11-12）：会话过期时抖店与妙手都会跳到
    ``https://fxg.jinritemai.com/login/common?...``。此时继续跑，
    适配器只会在几分钟后报「当前页面不是预期的XX页」，
    根因（掉线）被埋掉了。掉线只能由人重新登录，程序不能替人登录，
    也不能在登录页上重放写操作——所以这里失败关闭。
    """
    session = pages.check_session()
    if session.get('login_required'):
        raise DoudianError(
            'dropship_login_required',
            f'浏览器会话已过期：{page_name} 当前停在登录页'
            f'（{session.get("page_url")}，标记：{session.get("login_marker")}）。'
            f'请人工在浏览器里重新登录抖店，再重跑同一条命令；'
            f'程序不会代登录，也不会在登录页上重放任何写操作。')
    return session


def _normalize_spec(name):
    """规格名归一化：去掉空白与装饰符号，便于做包含关系比较。"""
    text = str(name or '').lower()
    for ch in ' \t\r\n-_/·*×x，,、.。()（）[]【】{}':
        text = text.replace(ch, '')
    return text


# 规格名里的「数量-单位」核心标记。妙手会改写规格展示名，但数量标记保留：
#   来源「4个装」                            → 官方「极氪车门限位器-4个装」
#   来源「生物酶除臭剂【2500ml】送喷壶」      → 官方「2500ml（生物酶除臭剂）」
# 两次真实铺货都如此，所以标记包含比规格名全等更可靠。
_SPEC_MARKER_RE = re.compile(r'(\d+(?:\.\d+)?)\s*([a-zA-Z]{1,4}|[一-龥]{1,2})')


def _spec_markers(name):
    """从规格名里提取数量标记；没有数量就没有标记（如「红色」）。"""
    text = _normalize_spec(name)
    markers = []
    for match in _SPEC_MARKER_RE.finditer(text):
        marker = match.group(1) + match.group(2)
        if marker not in markers:
            markers.append(marker)
    return markers


def _check_spec_identity(expected, observed):
    """核对规格名：用「数量标记包含关系」，不用规格名全等。

    两次真实铺货都证明妙手会改写规格展示名，所以「集合相等」在真实页面上
    几乎从不成立——把它当判据等于永远不可达。这里只问一个可判定的子问题：
    来源规格里的数量标记，有没有出现在官方规格名里。

    返回三态：matched / partial / mismatch。partial 与 mismatch 都**不阻断**
    copy_confirmed（定价公式才是强证据），只如实写进核验报告。
    """
    if not expected or not observed:
        return {'status': 'not_checkable', 'reason': '缺少预期或读回的规格名'}
    if len(expected) != len(observed):
        return {'status': 'mismatch',
                'reason': f'SKU 数量不一致（来源 {len(expected)} / 官方 {len(observed)}）'}
    official_text = ' '.join(_normalize_spec(n) for n in observed)
    matched, partial, unmatched = [], [], []
    for name in expected:
        markers = _spec_markers(name)
        if not markers:
            partial.append({'source_spec': name, 'reason': '规格名里没有数量标记'})
            continue
        found = [m for m in markers if m in official_text]
        if found:
            matched.append({'source_spec': name, 'markers': markers, 'found': found})
        else:
            unmatched.append({'source_spec': name, 'markers': markers, 'found': []})
    result = {
        'status': 'matched',
        'matched': matched,
        'source_specs': sorted(expected),
        'official_specs': sorted(observed),
        'rule': '官方规格名包含来源规格的数量标记（妙手改写展示名时保留数量）',
    }
    if unmatched:
        result.update(status='mismatch', unmatched=unmatched,
                      reason='来源规格的数量标记没有出现在官方规格名里')
        return result
    if partial:
        result.update(status='partial', not_checkable=partial,
                      reason='部分来源规格没有数量标记，无法用标记核对')
    return result


def _check_price_formula(observed, expected, price_input):
    """验证「售价 = 源价 × 倍数 + 加价 + 统一运费」。

    妙手会改写规格名（实测「生物酶除臭剂【2500ml】送喷壶」→「2500ml（生物酶除臭剂）」），
    所以按名字匹配不可靠。改用价格排序做位置对应：源价与售价都单调，
    最小的源价对应最小的售价。

    真正的证据不是「售价等于某个数」，而是**所有 SKU 的差额相同且非负**——
    那个共同差额就是运费。两次真实铺货都得到 3.48，说明公式确实被执行了。
    """
    if not expected or not observed:
        return {'ok': False, 'reason': '缺少预期或读回的 SKU 价格，无法核对公式'}
    if len(expected) != len(observed):
        return {'ok': False,
                'reason': f'SKU 数量不一致（来源 {len(expected)} / 官方 {len(observed)}）'}
    try:
        factor = Decimal(str(price_input.get('multiplier')))
        add = Decimal(str(price_input.get('addition')))
        sources = sorted(Decimal(str(v)) for v in expected.values())
        prices = sorted(Decimal(str(v)) for v in observed.values())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return {'ok': False, 'reason': '价格公式输入或读回值不是有效金额'}

    deltas = []
    for source, price in zip(sources, prices):
        base = (source * factor + add).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        deltas.append(price - base)
    if any(d < 0 for d in deltas):
        return {'ok': False, 'reason': '有 SKU 售价低于任务公式价'}
    spread = max(deltas) - min(deltas)
    if spread > Decimal('0.01'):
        return {'ok': False,
                'reason': f'各 SKU 的运费差额不一致（最大差 {spread}）'}
    return {
        'ok': True,
        'formula': f'{factor} × 源价 + {add}',
        'shipping_delta': format(deltas[0], '.2f'),
        'pairs': [{'source_price': format(s, '.2f'),
                   'formula_price': format((s * factor + add).quantize(
                       Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f'),
                   'shop_price': format(pr, '.2f')}
                  for s, pr in zip(sources, prices)],
    }


def verify_target_readback(job, *, product_id, sku_rows,
                           sku_total_count, price_progress, review_status,
                           platform_review_status=None, platform_review_source=None):
    """确认复制动作的结果，只声明能被证据证明的事。

    终态叫 ``copy_confirmed`` 而不是 ``verified``：官方编辑页**结构上**没有
    独立 SKU 总数计数，也没有商品审核状态（那里只有 SKU 角标和上架/下架表单
    选项），规格名还常被妙手改写。这三项不是「暂时没抓到」，是「这里根本没有」。
    拿它们当阻断条件，终态就永远不可达——之前停在 verification_pending
    一整轮正是这个原因。

    能自动证明的三件事：
    1. 商品 ID 与复制历史一致；
    2. 官方页能打开、读到 SKU 行、价格填写进度 100%；
    3. 价格符合任务公式（所有 SKU 的运费差额一致且非负）。

    拿不到的证据一律进 ``unverified_aspects``，如实交人工，不假装已验证。

    ``platform_review_status`` 是**审核状态的权威来源**（2026-11-12 实抓）：
    抖店商品管理页 ``/ffa/g/list?product_id=<ID>`` 与草稿箱
    ``/ffa/g/draft?product_id=<ID>`` 两页互斥——已提交商品只在前者，
    草稿商品只在后者（草稿箱状态词是「待提交」）。两页都查不到就如实说
    查不到，**不能**当成「未提审」——那是妙手侧用词，含义是「从没提交过审核」。
    """
    job = Path(job)
    state_path = job / 'state.json'
    state = read_json(state_path)
    if state.get('stage') not in (
            'copied', 'warehouse_created', 'verification_pending', 'copy_confirmed'):
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

    expected = dict(state.get('expected_skus') or {})
    manifest_path = job / 'manifest.json'
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    price_check = _check_price_formula(
        observed, expected, manifest.get('price_input') or {})

    verified_aspects = [
        '复制历史里出现本来源的新行，商品 ID 与官方页一致',
        '官方编辑页可打开并读到 SKU 行',
    ]
    unverified_aspects = []
    blockers = []

    if not expected:
        blockers.append('缺少复制时记录的预期 SKU 集合')
    if price_check.get('ok'):
        verified_aspects.append(
            '价格符合任务公式，各 SKU 运费差额一致（' + price_check['shipping_delta'] + '）')
    else:
        blockers.append('价格公式核对未通过：' + price_check.get('reason', ''))
    if price_progress != 100:
        blockers.append(f'页面价格填写进度为 {price_progress}%，不是 100%')
    else:
        verified_aspects.append('页面价格填写进度 100%')

    if sku_total_count is None:
        unverified_aspects.append('官方编辑页无独立 SKU 总数计数（结构上不存在）')
    elif len(sku_rows) != sku_total_count:
        blockers.append(f'读回行数 {len(sku_rows)} 与页面总数 {sku_total_count} 不一致')
    if not isinstance(review_status, str) or not review_status.strip():
        # 审核状态在编辑页上读不到，但**不**就此放弃：抖店商品管理页与草稿箱
        # 才是权威来源（两页互斥：已提交在商品管理页，草稿在草稿箱）。
        if isinstance(platform_review_status, str) and platform_review_status.strip():
            verified_aspects.append(
                '抖店官方读到平台状态：' + platform_review_status.strip()
                + '（来源：' + str(platform_review_source) + '）')
        else:
            unverified_aspects.append(
                '抖店商品管理页与草稿箱都没有这个商品 ID，'
                '无法确认审核状态（可能是从未提审，也可能是商品已被删除）')
    # 规格名：不用全等，用数量标记包含关系。
    # 妙手会改写展示名，所以全等在真实页面上几乎从不成立；
    # 但「数量标记还在」是可判定的，而且两次真实铺货都成立。
    spec_identity = _check_spec_identity(expected, observed)
    if spec_identity.get('status') == 'matched':
        verified_aspects.append('规格名数量标记与来源一致（妙手只改写了展示名）')
    elif spec_identity.get('status') == 'partial':
        unverified_aspects.append(
            '部分来源规格名没有数量标记，无法用标记核对规格名：'
            + '、'.join(x.get('source_spec', '') for x in spec_identity.get('not_checkable') or []))
    elif spec_identity.get('status') == 'mismatch':
        unverified_aspects.append('规格名核对未通过：' + spec_identity.get('reason', ''))
    elif expected:
        unverified_aspects.append('缺少规格名对照依据，无法核对')

    if blockers:
        state.update(stage='verification_pending', sku_rows_observed=len(sku_rows),
                     sku_total_count=sku_total_count,
                     last_error='readback_blockers', updated_at=time.time())
        write_json(state_path, state)
        return {
            'stage': 'verification_pending',
            'sku_rows_observed': len(sku_rows),
            'verified_aspects': verified_aspects,
            'unverified_aspects': unverified_aspects,
            'blockers': blockers,
            'reason': '；'.join(blockers),
        }

    report = {
        'stage': 'copy_confirmed',
        'product_id': str(product_id),
        'sku_rows': sku_rows,
        'price_check': price_check,
        'spec_identity': spec_identity,
        'verified_aspects': verified_aspects,
        'unverified_aspects': unverified_aspects,
        'sku_total_count': sku_total_count,
        'price_progress': price_progress,
        'review_status': review_status,
        'confirmed_at': time.time(),
        'note': '只确认「复制动作产生了这个商品且定价符合公式」；'
                '审核与上架状态不在本页，需人工到商品列表页确认。',
    }
    write_json(job / 'target-readback.json', report)
    state.update(stage='copy_confirmed', target_readback='target-readback.json',
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
      copied → 读官方页 → copy_confirmed / verification_pending
    """
    from .dropship_pages import DropshipPages
    from .ego_bridge import EgoBridge

    bridge = EgoBridge(session=args.session)
    bridge.require_ready()
    pages = DropshipPages(bridge)
    stage = state.get('stage')

    # 掉线早失败：会话过期时页面会跳登录页，继续跑只会得到
    # 「当前页面不是预期的XX页」，把根因埋掉。
    _require_shop_session(pages, page_name='当前标签页')

    if stage == 'prepared':
        return _stage_settings(args, job, state, manifest, pages)
    if stage == 'settings_verified':
        return _stage_copy(args, job, state, manifest, pages)
    if stage in ('unknown', 'copied', 'verification_pending'):
        return _readback_only(args, job, state, manifest)
    if stage in ('copy_confirmed', 'verified'):
        return {'task_id': args.task_id, 'stage': stage,
                'note': '任务已完成，终态不可回退。'}
    raise DoudianError('dropship_stage_invalid', f'任务处于无法推进的阶段：{stage}。')


def _stage_settings(args, job, state, manifest, pages):
    """写搬家配置，然后**独立重新进入页面**读回，读回一致才推进。"""
    from .dropship_pages import PRICE_FIELDS, SETTING_PATH

    job_state_path = job / 'state.json'
    pages.navigate_miaoshou(SETTING_PATH)
    time.sleep(SETTLE_SECONDS)
    _require_shop_session(pages, page_name='搬家设置页')

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
    """轮询等抓取结果出现，并绑住页面身份。

    抓取是后台任务：点完「开始批量抓取商品」，结果页的计数器要过几秒才渲染出来。
    读一次就判断会把「还没好」误判成「失败」。

    但如果轮询期间 session 切到别的页面，或者结果区被重新加载成上一次的
    旧计数，就可能把陈旧数据当成本次结果放行。所以每次都记录页面身份，
    身份一变就停；超时显式标 timed_out，绝不静默当成一次有效观测。
    """
    last = {}
    first_url = None
    for _ in range(attempts):
        last = pages.read_fetch_result()
        url = last.get('page_url')
        if first_url is None:
            first_url = url
        elif url != first_url:
            last['timed_out'] = True
            last['reason'] = '轮询期间页面身份变化，停止并交人工核查'
            return last
        if last.get('success_count') is not None and last.get('skipped_count') is not None:
            return last
        time.sleep(interval)
    last['timed_out'] = True
    last['reason'] = '等待抓取结果超时，未取得完整计数'
    return last


def _filtered_history_baseline(pages, source_id, *, attempts=6, interval=3):
    """按来源 ID 筛选历史，再轮询等筛选结果稳定，取可证明完整的基线。

    不筛选时页面「共 59 条」而虚拟滚动只挂载 8 行，基线无法证明完整。
    筛选后通常只有 0～2 条，DOM 与分页总数能对齐。
    """
    from .dropship_pages import HISTORY_PATH

    pages.navigate_miaoshou(HISTORY_PATH)
    time.sleep(SETTLE_SECONDS)
    pages.filter_history_by_source(source_product_id=source_id)
    last = {}
    for _ in range(attempts):
        time.sleep(interval)
        last = pages.read_history_baseline(source_product_id=source_id)
        if last.get('baseline_complete'):
            return last
    return last


def _stage_copy(args, job, state, manifest, pages):
    """贴链接 → 抓取 → 落复制意图 → 点复制。"""
    from .dropship_pages import HISTORY_PATH, MOVE_PATH

    job_state_path = job / 'state.json'
    offer_url = manifest['offer_url']
    source_id = manifest['source_product_id']

    # 0) 类目预检：命中强属性类目就别创建提不了审的草稿箱商品
    from .dropship_policy import require_precheck_allowed
    require_precheck_allowed(
        manifest.get('category_precheck'),
        allow_risk=bool((manifest.get('category_precheck') or {}).get('allow_risk')))

    # 1) 读来源商品的规格：复制前唯一的先验
    pages.navigate_source(offer_url)
    time.sleep(SETTLE_SECONDS)
    _require_shop_session(pages, page_name='1688来源商品页')
    source_skus = pages.read_source_skus(offer_url=offer_url)
    expected = {row['sku']: row['source_price']
                for row in source_skus.get('sku_rows') or []}
    if not expected:
        raise DoudianError('dropship_source_sku_missing',
                           '来源商品没有读到规格，无法建立预期。')

    # 2) 采历史基线：先按来源筛选，让本来源的行全部进视口，
    #    再用「共 N 条」与匹配行数证明基线完整
    baseline = _filtered_history_baseline(pages, source_id)
    require_no_pending_history(job, baseline.get('pending_rows'))
    # 虚拟滚动只渲染当前视口的行。页面写「共 N 条」而 DOM 只有少数行时，
    # 不能把这几行当完整基线——没看到的那 51 条里可能就有本来源的旧记录，
    # 那样复制后会把旧行误认成「本次新增」。
    if not baseline.get('baseline_complete'):
        raise DoudianError(
            'dropship_baseline_incomplete',
            f"按来源筛选后共 {baseline.get('total_records')} 条，匹配 "
            f"{baseline.get('matched_rows')} 行；"
            f"{baseline.get('completeness_reason')}，拒绝复制。")

    # 3) 贴链接并抓取。抓取是异步的：点完按钮后结果页要过一会儿才有计数器，
    #    所以要轮询等它出现，而不是读一次就下结论。
    pages.navigate_miaoshou(MOVE_PATH)
    time.sleep(SETTLE_SECONDS)
    _require_shop_session(pages, page_name='商品上货页')
    pages.paste_offer_and_fetch(offer_url=offer_url)
    fetch = _wait_for_fetch_result(pages)
    if fetch.get('timed_out'):
        raise DoudianError('dropship_fetch_incomplete',
                           f"抓取结果不可用：{fetch.get('reason')}。未点复制。")
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
    _require_shop_session(pages, page_name='当前标签页')

    target_id = state.get('target_product_id')
    if not target_id:
        # 还没有目标商品 ID：先按来源筛选历史，再找基线之后新增的那一行
        pages.navigate_miaoshou(HISTORY_PATH)
        time.sleep(SETTLE_SECONDS)
        _require_shop_session(pages, page_name='复制历史页')
        pages.filter_history_by_source(source_product_id=manifest['source_product_id'])
        time.sleep(4)
        history = pages.read_history_product_id(
            source_product_id=manifest['source_product_id'],
            baseline_keys=state.get('history_baseline') or [])
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

        # 复制历史行里若写着「XX未填写，导致复制失败，自动放至草稿箱」，
        # 就把缺的属性解析成一张人工补值清单，随结果一起交付。
        from .dropship_policy import build_manual_attribute_list
        checklist = build_manual_attribute_list(
            job,
            source_product_id=manifest['source_product_id'],
            target_product_id=history.get('product_id'),
            row_text=history.get('row_text'),
            category=manifest.get('category'))
        if checklist:
            result['manual_attributes'] = checklist
            result['next'] = ('商品已创建，但有必填属性缺失需人工补齐；'
                              '清单见 manual-attributes.json。')
        return result

    # 已有目标商品 ID：读官方页 SKU 与审核状态，原样报告
    pages.navigate_official(target_id)
    # 编辑页是重前端页面：导航返回后 DOM 还没渲染出 SKU 表，
    # 立刻读会得到「0 行」并被误报成 layout_changed。实测这个页面需要十几秒。
    time.sleep(SETTLE_SECONDS)
    _require_shop_session(pages, page_name='抖店官方商品编辑页')
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

    # 审核状态的权威来源：抖店商品管理页 / 草稿箱（两页互斥）。
    # 编辑页结构上读不到审核状态，但不代表读不到——之前那句
    # 「需到商品列表页人工确认」是事实，只是当时没做这一步。
    platform_review = pages.read_target_review_status(target_id)
    result['platform_review_status'] = platform_review.get('platform_state')
    result['platform_review_source'] = platform_review.get('source')
    result['platform_review_row'] = platform_review.get('row_text')

    verification = verify_target_readback(
        job, product_id=target_id,
        sku_rows=skus.get('sku_rows') or [],
        sku_total_count=skus.get('sku_total_count'),
        price_progress=skus.get('price_progress'),
        review_status=review.get('review_status'),
        platform_review_status=platform_review.get('platform_state'),
        platform_review_source=platform_review.get('source'))
    result['verification'] = verification
    result['stage'] = verification.get('stage', state.get('stage'))
    result['next'] = ('已按页面证据确认复制结果；官方编辑页拿不到的证据'
                      '列在 unverified_aspects 中，交人工确认。')
    return result
