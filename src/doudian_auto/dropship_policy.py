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

    items = []
    for name in missing:
        items.append({
            'attribute': name,
            'value': None,
            'source': '人工填写',
            'reason': '1688 属性区没有该字段；抖店类目必填',
            'is_douyin_only': name in DOUYIN_ONLY_ATTRIBUTES,
        })

    checklist = {
        'created_at': time.time(),
        'source_product_id': str(source_product_id),
        'target_product_id': str(target_product_id) if target_product_id else None,
        'category': category,
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
    if db is not None:
        try:
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
            rows = con.execute(
                "select product_id, last_error from products "
                "where state='blocked' limit ?", (limit,)).fetchall()
            con.close()
            for product_id, err in rows:
                text = str(err or '')
                if not any(k in text for k in (
                        'required_attributes_missing', 'missing_fields',
                        '待真实参数', '需真实资料补齐')):
                    continue
                names = []
                m = re.search(r'missing_fields=\[([^\]]*)\]', text)
                if m:
                    names += re.findall(r'"([^"]+)"', m.group(1))
                m2 = re.search(r'平台必填类目属性缺失：([^；;]+)', text)
                if m2:
                    names += re.split(r'[、,，]', m2.group(1).strip())
                uniq = []
                for n in names:
                    n = n.strip()
                    if n and n not in uniq:
                        uniq.append(n)
                if not uniq:
                    uniq = ['（原文未列出属性名，需查看 last_error）']
                for n in uniq:
                    items.append({
                        'line': 'batch_queue',
                        'product_id': str(product_id),
                        'source_product_id': None,
                        'attribute': n,
                        'category': None,
                        'evidence': text[:180],
                    })
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
        'note': '只读汇总。属性值必须由人按真实资料提供，程序不推断、不填写。',
    }
