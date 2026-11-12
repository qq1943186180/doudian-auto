"""铺货策略：类目预检与人工补值清单。

这个模块不碰浏览器。它只做两件基于**已观测事实**的判断：

1. 铺货前按类目/标题预判「抖店必填属性 1688 源头没有」的风险，命中就别创建
   草稿箱垃圾，直接转人工队列。
2. 铺货后从妙手复制历史的失败原因里，把缺哪些属性解析成一张人工补值清单。

事实依据（都来自真实店铺观测，不是猜）：
- 2026-11-12：家清纸品>除臭用品>空气清新/净化/芳香剂 需要「保质期/生产企业名称」，
  1688 源头没有，妙手按配置自动放至草稿箱、未提审。
- 2026-11-11：汽车用品>汽车防护用品>其他汽车防护用品 无此问题，商品进仓库。
- 2026-11-11：安装方式/尺寸/厚度/硬度/适用年龄 是抖店类目特有，1688 属性区没有。

类目预检是**启发式**的：铺货前拿不到抖店最终类目（妙手抓取后才匹配），
所以标题关键词只能提示风险，不能证明类目。命中高风险时默认拦截并交人工，
需要显式 allow_risk 才放行——宁可少铺一件，也不制造一个提不了审的草稿。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .errors import DoudianError
from .jobs import read_json, write_json

# 实测：这些抖店类目要求的必填属性，1688 属性区里没有对应字段。
# key 用类目末级名（页面上的「发布类目：A>B>C」最后一段），便于模糊归属。
KNOWN_CATEGORY_ATTRIBUTES = {
    '空气清新/净化/芳香剂': {
        'attributes': ['保质期', '生产企业名称'],
        'evidence': '2026-11-12 复制历史：「保质期,生产企业名称」未填写，自动放至草稿箱',
    },
}

# 抖店类目特有、1688 属性区一概没有的属性（T-003 实抓 5 件不同类目确认）。
DOUYIN_ONLY_ATTRIBUTES = (
    '安装方式', '尺寸', '厚度', '硬度', '适用年龄',
    '保质期', '生产企业名称',
)

# 🔴 实测结论（2026-11-12，本店批量队列 61 件实读）：
# 同一个标题关键词会落到**不同**的类目必填属性上，所以「标题关键词 → 必填属性」
# 不可归纳，不要按关键词猜属性集合。
#   「浴室免打孔不锈钢吹风筒收纳架…」缺的是 安装方式
#   「轻奢风浴室吸盘置物架…免打孔壁挂塑料…」缺的是 尺寸（安装方式反而被填上了）
# 结论：属性集合由**抖店类目**决定，而铺货前拿不到最终类目。
# 因此这里只记「本店观测到缺过哪些属性」，供人工分诊；不据此自动推断或拦截。
OBSERVED_MISSING_ATTRIBUTES = (
    '安装方式', '尺寸', '厚度', '硬度', '适用年龄', '材质',
    '保质期', '生产企业名称', '承重', '适配基面类型',
)

# 复制历史行里出现过的渠道标记。下一行就是来源供应商（名称（店铺名））。
_CHANNEL_LINES = ('1688分销', '阿里巴巴', '淘宝', '天猫', '拼多多', '分销')

# 供应商段落的排除词：这些是行里的**字段**而不是供应商名，不能当供应商。
_NOT_SUPPLIER_LINES = (
    '默认配置', '已成功复制', '复制失败', '跳过复制', '已取消复制', '正在复制中',
    '审核通过', '审核不通过', '关联失败', '关联成功', '商品快速编辑', '去抖店编辑',
)

# 复制历史行里出现过的目标商品状态词。都是抖店官方用词，不是推测。
_TARGET_STATE_TOKENS = (
    '草稿箱', '未提审', '审核通过', '审核中', '审核未通过',
    '售卖中', '已下架', '待审核',
)

# 🔴 2026-11-12 全量 58 条实采后补的词汇表（证据：work/optimizer-20261111/history-all-rows.json）。
# 抖店侧「商品状态」与「审核状态」是两列，妙手侧还有第三列，词不一样：
#   抖店商品状态：草稿箱 / 已下架 / 上架中 / 售卖中 / 已售罄 / 已封禁
#   抖店审核状态：审核通过 / 审核不通过 / 审核驳回 / 未提审 / 审核中
#   妙手搬运审核：审核通过 / 审核不通过 / 关联失败 / 关联成功
# 三者混在一起统计会得出「未提审+审核通过+已下架」这种三词组合，无从判断谁是谁，
# 所以解析时按**位置**分开：商品ID 之后的属抖店侧，之前的属妙手侧。
PLATFORM_STATE_TOKENS = (
    '草稿箱', '已下架', '上架中', '售卖中', '已售罄', '已封禁', '待审核',
)
PLATFORM_AUDIT_TOKENS = (
    '审核通过', '审核不通过', '审核驳回', '未提审', '审核中',
)
MIAOSHOU_AUDIT_TOKENS = (
    '审核通过', '审核不通过', '关联失败', '关联成功',
)
COPY_STATE_TOKENS = (
    '已成功复制', '复制失败', '跳过复制', '已取消复制', '正在复制中',
)

# 复制历史行里，类目路径之后紧跟的「复制类型」标记。
# 实测 58 条里 57 条是「1688分销」，1 条是「翻新复制」（且那行没有供应商）。
COPY_TYPE_MARKERS = (
    '1688分销', '淘宝分销', '天猫分销', '拼多多分销', '京东分销',
    '翻新复制', '授权复制',
)


def extract_missing_attribute_names(text):
    """从一段失败原文里解析出「缺了哪些属性名」。

    实测有两种写法，都要认：
      preflight_exception: required_attributes_missing; 平台必填类目属性缺失：安装方式；
                            missing_fields=["安装方式"]
      妙手任务27418021已完成且失败：缺安装方式；官方另缺承重、适配基面类型，待真实参数。

    认不出就返回空列表——**不返回占位名**，免得把「原文没写」当成一个属性名
    混进人工清单。
    """
    raw = str(text or '')
    if not raw:
        return []
    names = []

    def push(value):
        value = value.strip().strip('「」『』“”"\'（）()【】[]')
        # 「缺失：安装方式」「缺少安装方式」都会多带前缀，先剥掉。
        value = value.lstrip('缺少少失').lstrip('：:，,、;； ')
        value = value.strip()
        if not value or len(value) > 12:
            return
        if any(bad in value for bad in ('资料', '参数', '真实', '字段', '以下',
                                        '未作为', '空值', '以下')):
            return
        if value not in names:
            names.append(value)

    m = re.search(r'missing_fields=\[([^\]]*)\]', raw)
    if m:
        for value in re.findall(r'"([^"]+)"', m.group(1)):
            push(value)
    m = re.search(r'平台必填类目属性缺失：([^；;]+)', raw)
    if m:
        for value in re.split(r'[、,，]', m.group(1)):
            push(value)
    for match in re.finditer(r'缺([^；;，,。\n]{2,12})', raw):
        for value in re.split(r'[、]', match.group(1)):
            push(value)
    return names


def parse_history_row_facts(row_text):
    """从复制历史行原文里抽出已经写在页面上的事实。

    实测行文（2026-11-12，商品 3853482303460343870，DOM innerText 原样）：

        阿里巴巴酒店生物酶除味剂…
        发布类目：家清纸品>除臭用品>空气清新/净化/芳香剂
        1688分销
        明丞生物科技有限公司（明丞生物科技有限公司）
        源ID：
        922368518409
        默认配置
        已成功复制
        "保质期,生产企业名称"未填写，导致复制失败，系统自动放至草稿箱
        2026-11-12 01:40
        商品ID：
        3853482303460343870
        草稿箱
        未提审
        销量：--

    这些字段以前采到了却没被利用，人工补值时还得自己翻页面。
    这里只做**读取**与透传：类目、来源供应商、目标状态、商品ID、源ID。
    供应商名只作参考，不当成「生产企业名称」的答案——那是另一回事。

    🔴 2026-11-12 全量 58 条实采后修了四处真实缺陷（都有真实行做反例）：
    1. 类目正则原来是 `([^\\n\\r]+)`，遇到被折叠成**单行**的文本会把整行
       （含供应商、源ID、时间、状态）都当成类目。现在止于下一行或复制类型标记。
    2. 供应商原来只认 `名称（店铺名）`，58 条里有 8 条供应商是**纯名称**
       （如 `瑞安市激濠五金商行`、`孕产批发`），现在也认。
    3. 源ID 原来只认 `源ID：`，漏了 `翻新复制` 行的 `新源ID：`。
    4. 状态词原来全表扫，妙手侧「审核通过」与抖店侧「审核通过」混在一起，
       统计出「未提审+审核通过+已下架」这种三词组合。现在按**位置**分开：
       商品ID 之后是抖店侧，之前是妙手侧。
    """
    raw = str(row_text or '')
    facts = {
        'category': None, 'source_supplier': None, 'source_shop': None,
        'copy_type': None, 'copy_state': None,
        'platform_states': [], 'platform_audit_state': None,
        'miaoshou_audit_state': None, 'failure_reason': None,
        'target_states': [], 'product_id': None, 'source_product_id': None,
    }
    if not raw.strip():
        return facts

    lines = [line.strip() for line in raw.split('\n') if line.strip()]

    # 类目：取「发布类目：」之后到行尾/复制类型标记为止的一段。
    match = re.search(r'发布类目[:：]([^\n\r]*)', raw)
    if match:
        segment = match.group(1)
        cut = len(segment)
        for marker in tuple(COPY_TYPE_MARKERS) + ('源ID：', '新源ID：', '源ID:', '新源ID:'):
            index = segment.find(marker)
            if 0 <= index < cut:
                cut = index
        facts['category'] = segment[:cut].strip() or None

    # 复制类型：必须两侧是空白，否则标题里出现同名词会误判。
    type_match = re.search(
        r'(?:^|\s)(' + '|'.join(re.escape(m) for m in COPY_TYPE_MARKERS) + r')(?=\s|$)',
        raw)
    if type_match:
        facts['copy_type'] = type_match.group(1)

    # 来源 ID：「源ID：」与「翻新复制」行的「新源ID：」都要认。
    match = re.search(r'(?:新?源ID)[:：]\s*(\d+)', raw)
    if match:
        facts['source_product_id'] = match.group(1)
    match = re.search(r'商品ID[:：]\s*(\d+)', raw)
    if match:
        facts['product_id'] = match.group(1)

    # 供应商：紧跟复制类型标记、在来源 ID 之前的那一段。
    if type_match:
        after = raw[type_match.end():]
        stop = re.search(r'新?源ID[:：]', after)
        segment = after[:stop.start()] if stop else after
        candidates = [line.strip() for line in segment.split('\n') if line.strip()]
        if candidates:
            candidate = candidates[0].strip()
            paired = re.match(r'^(.+?)[（(]([^）)]*)[）)]$', candidate)
            if paired:
                facts['source_supplier'] = paired.group(1).strip()
                facts['source_shop'] = paired.group(2).strip() or None
            elif (2 <= len(candidate) <= 40
                  and not re.search(r'[：:，,。、]', candidate)
                  and candidate not in _NOT_SUPPLIER_LINES):
                facts['source_supplier'] = candidate

    # 状态按位置分侧：商品ID 之后是抖店侧，之前是妙手侧。
    product_marker = re.search(r'商品ID[:：]', raw)
    if product_marker:
        head, tail = raw[:product_marker.start()], raw[product_marker.start():]
    else:
        head, tail = '', raw
    facts['platform_states'] = [t for t in PLATFORM_STATE_TOKENS if t in tail]
    for token in PLATFORM_AUDIT_TOKENS:
        if token in tail:
            facts['platform_audit_state'] = token
            break
    for token in MIAOSHOU_AUDIT_TOKENS:
        if token in head:
            facts['miaoshou_audit_state'] = token
            break
    for token in COPY_STATE_TOKENS:
        if token in raw:
            facts['copy_state'] = token
            break
    for line in lines:
        if '未填写' in line or '导致复制失败' in line:
            facts['failure_reason'] = line.strip()
            break

    # 兼容字段：target_states 只保留抖店侧（商品状态 + 审核状态）。
    states = list(facts['platform_states'])
    if facts['platform_audit_state']:
        states.append(facts['platform_audit_state'])
    facts['target_states'] = states
    return facts


# 标题里的风险词。只用于**预警**，不能当作类目证据。
# 每一条都对应一次真实观测或明确的类目语义，不堆砌泛词。
RISK_KEYWORDS = (
    '除味剂', '除臭', '空气清新', '芳香剂', '净化剂',
    '保鲜', '食品接触', '化妆品', '护肤品', '消毒液',
)


def precheck_category(*, title=None, category=None):
    """预判这个类目/商品会不会因必填属性缺失而落草稿箱。

    返回结构里 `basis` 明确写清判断依据：精确类目命中是「category」，
    标题关键词命中是「keyword_heuristic」，后者不能当成确定结论。
    """
    title = str(title or '').strip()
    category = str(category or '').strip()

    if category:
        for leaf, info in KNOWN_CATEGORY_ATTRIBUTES.items():
            if leaf in category or category in leaf:
                return {
                    'risk': 'high',
                    'basis': 'category',
                    'matched_category': category,
                    'missing_attributes': list(info['attributes']),
                    'evidence': info['evidence'],
                    'action': 'block',
                    'note': '该类目必填属性 1688 源头没有，自动铺货只会产生提不了审的草稿。',
                }

    hits = [w for w in RISK_KEYWORDS if w and w in title]
    if hits:
        known = set()
        for info in KNOWN_CATEGORY_ATTRIBUTES.values():
            known.update(info['attributes'])
        return {
            'risk': 'high',
            'basis': 'keyword_heuristic',
            'matched_keywords': hits,
            'possible_missing_attributes': sorted(known),
            'action': 'block',
            'note': ('标题命中强属性类目关键词，但铺货前拿不到抖店最终类目，'
                     '这只是风险预警。默认拦截转人工；确需继续请显式 allow_risk。'),
        }

    return {
        'risk': 'low',
        'basis': 'no_known_risk',
        'action': 'proceed',
        'note': '未命中已知强属性类目或风险词；不保证一定成功，只是没有被观测到的风险。',
    }


def require_precheck_allowed(precheck, *, allow_risk=False):
    """高风险任务必须显式放行；否则落到人工队列而不是草稿箱。"""
    if not precheck or precheck.get('risk') != 'high':
        return precheck
    if allow_risk:
        return dict(precheck, action='allowed_by_operator')
    raise DoudianError(
        'dropship_category_risk',
        '预检命中强属性类目风险（' + precheck.get('basis', '?') + '）：'
        + precheck.get('note', '')
        + ' 请先在抖店确认类目必填属性并人工补齐，或用 --allow-risk 显式放行。')


# 妙手复制历史里失败原因的真实形态：
#   「保质期,生产企业名称」未填写，导致复制失败，系统自动放至草稿箱
_MISSING_PATTERNS = (
    re.compile(r'[「“"]([^」”"]{2,80})[」”"]\s*未填写'),
    re.compile(r'([^\s，。；]{2,80})未填写[，,]?\s*导致复制失败'),
)


def extract_missing_attributes(row_text):
    """从复制历史行文本里解析「哪些必填属性没填」。读不到就返回空列表。"""
    text = str(row_text or '')
    found = []
    symbols = ('「', '」', '『', '』', '“', '”', chr(34), chr(39),
               '（', '）', '(', ')', '[', ']', '【', '】')
    for pattern in _MISSING_PATTERNS:
        for match in pattern.finditer(text):
            for part in re.split(r'[,，、;；\s]+', match.group(1)):
                for sym in symbols:
                    part = part.replace(sym, '')
                part = part.strip(' 	,，、;；')
                if part and part not in found and not part.startswith('导致'):
                    found.append(part)
    return found

def build_manual_attribute_list(job, *, source_product_id, target_product_id=None,
                                missing_attributes=None, row_text=None,
                                category=None):
    """把「缺哪些属性、去哪补」写成一张可交付的人工清单。

    只记录事实：从失败原因解析出的属性名、来源商品、目标商品、原始行文本。
    不替人猜属性值——这正是之前反复证明「源头没有、程序变不出来」的边界。
    """
    job = Path(job)
    missing = list(missing_attributes or [])
    if not missing and row_text:
        missing = extract_missing_attributes(row_text)
    if not missing:
        return None

    facts = parse_history_row_facts(row_text)
    row_category = facts.get('category') or category

    items = []
    for name in missing:
        item = {
            'attribute': name,
            'value': None,
            'source': '人工填写',
            'reason': '1688 属性区没有该字段；抖店类目必填',
            'is_douyin_only': name in DOUYIN_ONLY_ATTRIBUTES,
        }
        # 「生产企业名称」在复制历史行里能看到 1688 来源供应商名。
        # 它是**参考**，不是答案：抖店要的是实际生产方，供应商可能是贸易商。
        if name == '生产企业名称' and facts.get('source_supplier'):
            item['reference_supplier'] = facts['source_supplier']
            item['reference_note'] = (
                '复制历史行里打印的 1688 来源供应商名，仅作参考线索；'
                '抖店「生产企业名称」须按实际生产方填写，不能直接照抄。')
        items.append(item)

    checklist = {
        'created_at': time.time(),
        'source_product_id': str(source_product_id),
        'target_product_id': str(target_product_id) if target_product_id else None,
        'category': row_category,
        'target_states': facts.get('target_states') or [],
        'source_supplier': facts.get('source_supplier'),
        'source_shop': facts.get('source_shop'),
        'missing_count': len(items),
        'items': items,
        'instruction': ('在抖店商品编辑页补以上属性后提审。'
                        '这些值无法从 1688 源头或妙手搬运获得，必须人工提供。'),
        'evidence_row': str(row_text or '')[:600],
    }
    write_json(job / 'manual-attributes.json', checklist)
    return checklist


def load_manual_attribute_list(job):
    path = Path(job) / 'manual-attributes.json'
    return read_json(path) if path.is_file() else None

# 队列 blocked 的真实原因分类（2026-11-12 实读 batch.sqlite3 43 件）。
# 顺序有意义：先匹配到的先算。`handling` 说明这件事该谁做：
#   need_human_value 只能由人给值（属性、参数）
#   need_human_asset  只能由人给素材或判断
#   need_human_decision 只能由人决策
#   machine_retry     程序可重跑（重新基线、补读商家编码）
#   closed            这件已经结束，不要再动
BLOCKED_REASON_CLASSES = (
    ('missing_required_attributes',
     ('required_attributes_missing', '平台必填类目属性缺失'), 'need_human_value'),
    ('missing_real_parameters',
     ('待真实参数', '需真实资料补齐'), 'need_human_value'),
    ('needs_rebaseline',
     ('external_work_requires_rebaseline',), 'machine_retry'),
    ('image_slots_insufficient',
     ('writer_image_slots_incomplete',), 'need_human_asset'),
    ('draft_or_rejected',
     ('doudian_draft_or_rejected',), 'need_human_decision'),
    ('visual_quality_failed',
     ('visual_quality_failed_after_retry',
      'root_visual_review_failed_after_retry'), 'need_human_asset'),
    ('sku_code_incomplete',
     ('official_sku_code_incomplete',
      'official_sku_code_row_ambiguous'), 'machine_retry'),
    ('product_deleted',
     ('doudian_product_deleted',), 'closed'),
    ('detail_source_collision',
     ('writer_detail_source_collision',), 'need_human_decision'),
)


def classify_blocked_reason(last_error):
    """把一条 last_error 归到机器可读的类目；认不出就如实说认不出。"""
    text = str(last_error or '')
    for name, markers, handling in BLOCKED_REASON_CLASSES:
        if any(marker in text for marker in markers):
            return {'reason_class': name, 'handling': handling}
    return {'reason_class': 'unclassified', 'handling': 'need_human_decision'}


def build_manual_queue_report(*, data_root=None, limit=200):
    """把两条线的「等人工给值」汇总成一张只读清单。

    线 A：铺货任务目录里的 ``manual-attributes.json``（新商品的类目必填属性）。
    线 B：批量队列 ``batch.sqlite3`` 里因必填属性缺失 / missing_fields 而 blocked
          的历史商品。

    只读：不修改队列状态、不解锁任何任务、不写商品页面。
    目的是让人一眼看到「总共还欠哪些值、分别属于哪个商品」，而不是让两条线
    各说各话。属性名一律从页面原文/队列原文解析，不推断值。
    """
    import re
    import sqlite3
    from .jobs import DATA_ROOT

    root = Path(data_root or DATA_ROOT)
    items = []

    # 线 A：铺货任务。默认在 DATA_ROOT/dropship/任务/ 下，
    # 但真跑常用临时 --data-root，任务目录直接挂在 root 下，两种都要认。
    seen_files = set()
    for pattern in ('dropship/*/manual-attributes.json',
                    '*/manual-attributes.json'):
        for f in sorted(root.glob(pattern)):
            if f in seen_files:
                continue
            seen_files.add(f)
            try:
                data = read_json(f)
            except Exception:
                continue
            for entry in data.get('items') or []:
                items.append({
                    'line': 'dropship',
                    'product_id': data.get('target_product_id'),
                    'source_product_id': data.get('source_product_id'),
                    'attribute': entry.get('attribute'),
                    'category': data.get('category'),
                    'evidence': '复制历史行的失败原因',
                })

    # 线 B：批量队列（只读连接）。队列 db 常驻 DATA_ROOT，
    # 不会跟着 --data-root 搬到临时目录，所以两个位置都试。
    db = next((c for c in (root / 'batch.sqlite3', DATA_ROOT / 'batch.sqlite3')
               if c.is_file()), None)
    blocked_summary = {}
    observed_attributes = {}
    if db is not None:
        try:
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
            rows = con.execute(
                "select product_id, last_error, facts_json from products "
                "where state='blocked' limit ?", (limit,)).fetchall()
            con.close()
            for product_id, err, facts_json in rows:
                text = str(err or '')
                classified = classify_blocked_reason(text)
                bucket = blocked_summary.setdefault(
                    classified['reason_class'],
                    {'count': 0, 'handling': classified['handling'],
                     'product_ids': []})
                bucket['count'] += 1
                if len(bucket['product_ids']) < 8:
                    bucket['product_ids'].append(str(product_id))
                names = extract_missing_attribute_names(text)
                if not names:
                    continue
                title = ''
                try:
                    title = str((json.loads(facts_json or '{}') or {}).get('name') or '')
                except (ValueError, TypeError):
                    title = ''
                for n in names:
                    items.append({
                        'line': 'batch_queue',
                        'product_id': str(product_id),
                        'source_product_id': None,
                        'attribute': n,
                        'category': None,
                        'title': title[:80],
                        'reason_class': classified['reason_class'],
                        'evidence': text[:180],
                    })
                    stat = observed_attributes.setdefault(
                        n, {'count': 0, 'product_ids': [], 'example_titles': []})
                    stat['count'] += 1
                    if len(stat['product_ids']) < 8:
                        stat['product_ids'].append(str(product_id))
                    if title and len(stat['example_titles']) < 3:
                        stat['example_titles'].append(title[:60])
        except sqlite3.Error:
            pass

    return {
        'generated_at': time.time(),
        'total_items': len(items),
        'by_line': {
            'dropship': sum(1 for x in items if x['line'] == 'dropship'),
            'batch_queue': sum(1 for x in items if x['line'] == 'batch_queue'),
        },
        'items': items,
        'blocked_summary': {
            'total_blocked': sum(b['count'] for b in blocked_summary.values()),
            'by_reason': blocked_summary,
            'note': ('blocked 原因分布。handling 说明该谁处理：'
                     'need_human_value/need_human_asset/need_human_decision 只能由人做，'
                     'machine_retry 可由程序重跑，closed 表示这件已经结束。'),
        },
        'observed_missing_attributes': {
            'attributes': observed_attributes,
            'known_set': list(OBSERVED_MISSING_ATTRIBUTES),
            'note': ('本店真实观测到缺过的抖店类目必填属性。'
                     '属性集合由抖店类目决定，同一标题关键词会落到不同属性上，'
                     '所以这里只作人工分诊参考，不用于自动推断或拦截。'),
        },
        'note': '只读汇总。属性值必须由人按真实资料提供，程序不推断、不填写。',
    }
