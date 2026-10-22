"""Title validation and diagnosis for Douyin Shop listings.

Scope is deliberately narrow: this module executes rules that are actually
implemented and reports what it cannot confirm. It never generates copy and never
claims platform compliance. "Local check passed" is not "the platform will accept
it" -- the ambiguous, semantic and word-list judgements all live behind the
platform's own review, and this module says so in its output.

The counting rule below is a local approximation. It matches the 15-60 unit limit
the editor enforces for the characters this shop uses, but it is not the platform's
own algorithm: emoji sequences and combining marks are not separately accounted for.
"""

import re
import unicodedata

# Platform limits, in the units computed below.
# Official sources (抖音电商学习中心, both checked 2026-10-22):
#   《"商品标题"如何填写?》  标题字数要求：8-30 个汉字（即 16-60 个字符）
#   《商品创建操作指南》     最多可支持输入 30 个字（60 字符）
# The previous bound was 15, which allows 7.5 characters worth of title -- below the
# 8-character floor the platform enforces, so such a title passed here and then failed
# on submit. The floor is 16 (8 汉字 * 2).
MIN_UNITS = 16
MAX_UNITS = 60

# Control characters have no legitimate place in a listing title. Full-width
# punctuation is allowed because Chinese titles use it.
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')

# Absolute or unverifiable marketing claims. The learning centre explicitly names
# 国家级 / 全网最低 / 极品 / 顶级 as prohibited; the rest are the same class of risk.
# Presence is a warning, not a rejection: wording may be legitimate when a real
# certificate exists, which this module cannot see.
_RISKY_CLAIMS = (
    '第一', '唯一', '最好', '最佳', '顶级', '国家级', '最高级', '绝无仅有', '极品',
    '百分百', '100%', '永久', '万能', '全效', '特效', '根治', '零甲醛',
    '环保', '防火', '阻燃', '防水', '抗菌', '除甲醛', '无甲醛', '全网最低',
    # Vague superlatives seen in real listings; none is verifiable and all invite review.
    '神器', '爆款', '网红', '超值', '史无前例', '黑科技',
)

# Vague quantity words. A title that says "a lot of options" without naming them
# spends characters without earning search coverage.
_VAGUE_SPEC = ('多厚度', '多规格', '多种', '多款', '各种', '任意', '若干', '等多', '等等')

# Generic basket words the learning centre lists as unacceptable substitutes for a
# real product subject ("不得通过百货/孤品/套装/链接/好物/秒杀专项等物品概述来描述商品主体").
_GENERIC_SUBJECT = ('百货', '孤品', '套装', '链接', '好物', '秒杀专项', '福利款', '盲盒')

# The platform blocks titles that advertise price at all ("禁止在标题中宣传价格").
_PRICE_CLAIM = re.compile(r'(?:[¥￥]\s*\d)|(?:\d+(?:\.\d+)?\s*(?:元|块钱|块|米))|(?:包邮|特价|低价|秒杀价|到手价|券后)')


class TitleFacts:
    """Confirmed facts a title may draw on.

    Built from a captured snapshot plus explicit human confirmation. Anything not in
    here is treated as unconfirmed: `diagnose` reports such words instead of assuming
    they are fine, because the original title can itself carry historical mistakes.

    Shape (all keys optional, JSON-friendly)::

        {
          "product_id": "3784643089604411407",
          "category": "家装建材 > 隔音保温 > 隔音材料",
          "confirmed": {
            "brand": "无品牌",
            "material": ["聚氨酯"],
            "scene": ["室内", "录音棚", "墙面"],
            "attributes": ["自粘背胶"],
            "specs": {"厚度": ["2cm", "2.5cm", "5cm"]}
          },
          "unconfirmed": ["防火", "防水"]
        }
    """

    def __init__(self, data=None):
        data = data or {}
        self.product_id = data.get('product_id')
        self.category = data.get('category') or ''
        confirmed = data.get('confirmed') or {}
        self.brand = confirmed.get('brand') or ''
        self.material = _as_list(confirmed.get('material'))
        self.scene = _as_list(confirmed.get('scene'))
        self.attributes = _as_list(confirmed.get('attributes'))
        self.specs = {k: _as_list(v) for k, v in (confirmed.get('specs') or {}).items()}
        self.unconfirmed = _as_list(data.get('unconfirmed'))

    @property
    def phrases(self):
        """Every phrase the title may legitimately claim, longest first.

        Longest first so that a longer confirmed phrase wins over a shorter substring
        of it when checking coverage.
        """
        pool = list(self.material) + list(self.scene) + list(self.attributes)
        pool += [v for values in self.specs.values() for v in values]
        if self.brand and self.brand != '无品牌':
            pool.append(self.brand)
        return sorted({p for p in pool if p}, key=len, reverse=True)

    @property
    def spec_values(self):
        return [v for values in self.specs.values() for v in values if v]


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in value if v]


def title_units(title):
    """Count title length in the units the editor enforces (CJK and full-width = 2)."""
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in title or '')


def _bigrams(text):
    """Adjacent two-character pairs, used to detect a phrase repeated verbatim."""
    stripped = re.sub(r'[^\u4e00-\u9fff]', '', text or '')
    return [stripped[i:i + 2] for i in range(len(stripped) - 1)]


def _spec_spans(text, spec_values):
    """Character ranges of `text` claimed by confirmed spec values.

    Plain substring matching is not enough here. With both 2件套 and 12件套 confirmed, the
    string "...12件套..." contains 2件套 only as a slice of 12件套; counting it separately would
    excuse an outright duplication of 12件套. Assigning longest-first and disallowing overlap
    makes every character belong to at most one value, which is what the check needs.
    """
    spans = []
    for value in sorted({v for v in spec_values if v}, key=len, reverse=True):
        start = 0
        while True:
            index = text.find(value, start)
            if index < 0:
                break
            end = index + len(value)
            if not any(index < other_end and other_start < end
                       for other_start, other_end in spans):
                spans.append((index, end))
            start = max(end, start + 1)
    return spans


def validate_title(title):
    """Return (units, errors) for the deterministic rules only.

    Errors are things that are wrong regardless of product facts: an empty title, an
    out-of-range length, a control character, or surrounding whitespace that would be
    sent literally. Nothing here tries to judge whether the wording is sellable.
    """
    text = title or ''
    errors = []
    if not text.strip():
        errors.append('标题为空。')
        return 0, errors
    if text != text.strip():
        # Not normalised silently: the exact bytes go into the manifest hash, so a
        # trimmed title would otherwise produce a job that differs from what was typed.
        errors.append('标题首尾含空白字符，请去掉后重试（不会自动修改）。')
    if _CONTROL.search(text):
        errors.append('标题含控制字符。')
    units = title_units(text)
    if units < MIN_UNITS:
        errors.append('标题为{0}个平台字符，少于{1}。'.format(units, MIN_UNITS))
    elif units > MAX_UNITS:
        errors.append('标题为{0}个平台字符，超过{1}。'.format(units, MAX_UNITS))
    return units, errors


def diagnose_title(title, facts=None):
    """Report warnings that a human should look at before the title is frozen.

    Every finding is a warning. The output never asserts the title is compliant or
    that a claim is false -- only that this module cannot confirm it from the facts
    it was given.
    """
    text = title or ''
    facts = facts or TitleFacts()
    units, errors = validate_title(text)
    warnings = []

    # Verbatim phrase repetition, e.g. "吸音棉...吸音棉". A bigram that spans two
    # *different* confirmed spec values is not repetition: "2件套3件套" repeats "件套"
    # only because both variants are being listed, which is desirable.
    #
    # The excuse is granted per distinct spec value that the title actually contains --
    # not per value the facts happen to list. Counting the facts alone would excuse
    # "2件套2件套" whenever 3件套 is also a confirmed value, which is exactly the
    # duplication this check exists to catch. A bigram that repeats inside a single
    # value still counts, and so does any occurrence beyond the distinct values present.
    seen = {}
    for gram in _bigrams(text):
        seen[gram] = seen.get(gram, 0) + 1
    spans = _spec_spans(text, facts.spec_values)

    def explained(gram):
        # One exemption per *distinct* confirmed value, however many times the value is
        # written. A value written twice must leave one occurrence unexplained, or this
        # check would wave through the very duplication it exists to report.
        claimed = {text[start:end] for start, end in spans}
        return sum(1 for value in claimed if gram in _bigrams(value))

    repeated = sorted(g for g, n in seen.items() if n > 1 and n > explained(g))
    if repeated:
        warnings.append('疑似重复用词：{0}。请确认不是堆砌。'.format('、'.join(repeated)))

    # Absolute or unverifiable claims. Rejected explicitly when the facts mark them
    # unconfirmed; otherwise flagged as needing evidence.
    for word in _RISKY_CLAIMS:
        if word not in text:
            continue
        if word in facts.unconfirmed:
            warnings.append('「{0}」已被标记为未经证实，不应出现在标题中。'.format(word))
        else:
            warnings.append('「{0}」属绝对化或需资质证明的表述，本工具无法核实，请自备依据。'.format(word))

    # Vague quantity words: they spend characters without naming a searchable value.
    for word in _VAGUE_SPEC:
        if word in text:
            warnings.append('「{0}」未给出具体规格值，搜索覆盖有限；如确有规格请写具体值。'.format(word))

    # Price in the title is blocked outright by the platform, not merely discouraged.
    price_hits = _PRICE_CLAIM.findall(text)
    if price_hits:
        warnings.append('标题疑似宣传价格：{0}。平台禁止在标题中宣传价格，带价格会被拦截。'.format(
            '、'.join(sorted(set(price_hits))[:5])))

    # Basket words that do not describe a real product subject.
    for word in _GENERIC_SUBJECT:
        if word in text:
            warnings.append('「{0}」属物品概述词，平台明确不可用来描述商品主体。'.format(word))

    # Numeric specifications in the title that no confirmed fact backs. The check runs
    # even when the confirmed set is empty: an unlisted dimension is still unconfirmed,
    # and treating "no confirmed specs" as "nothing to check" is how a made-up thickness
    # slips through.
    numbers = re.findall(r'\d+(?:\.\d+)?\s*(?:cm|mm|m|寸|厘米|毫米|米)', text)
    if numbers:
        confirmed_values = {v.replace(' ', '') for v in facts.spec_values}
        unbacked = [n for n in numbers if n.replace(' ', '') not in confirmed_values]
        if unbacked:
            warnings.append('标题含未在已确认规格中的数值：{0}。请确认规格真实且已核价。'.format(
                '、'.join(sorted(set(unbacked)))))

    # Facts that exist but are not used anywhere in the title.
    unused = [p for p in facts.phrases if p not in text]
    if unused:
        warnings.append('已确认但未使用：{0}。'.format('、'.join(unused[:8])))

    return {
        'title': text,
        'units': units,
        'errors': errors,
        'warnings': warnings,
        'ok': not errors,
        'coverage': '仅执行本地已实现的规则。未命中的词不代表平台通过；违禁词、类目适配与最终审核以平台发布检查为准。',
        'counting_note': '本地计数把汉字与全角字符按 2 计，emoji 与组合字符未单列，与平台算法不保证完全一致。',
    }
