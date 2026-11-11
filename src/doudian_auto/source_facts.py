"""Read category-attribute facts from a product's 1688 supplier page.

The shop is stocked from 1688 through Miaoshou. So when Douyin's category form asks for
材质/型号/是否进口/产地, the answer already exists on the supplier's own page. Asking the
user to retype it is the wrong ask, and inventing it is worse.

This module only reads. It never writes a product, and it refuses to borrow a spec from a
similar-looking product: values are keyed to facts the supplier page states outright.
"""

from __future__ import annotations

import json
import re

# Key names as the 1688 offer page prints them, mapped to what Douyin's form calls them.
DOUYIN_FROM_SOURCE = {
    '是否进口': '是否进口',
    '货号': '型号',
    '型号': '型号',
    '材质': '材质',
}

DUMP_SPEC = """(()=>{
  const txt = document.body.innerText || '';
  const out = {title:'', pairs:{}, supplier:'', location:''};
  const h1 = document.querySelector('h1');
  if (h1) out.title = (h1.innerText||'').replace(/\\s+/g,' ').trim().slice(0,120);
  // 1688 prints specs as "键\\n\\n值" in the 参数/商品属性 band.
  const keys = ['材质','品牌','贸易属性','是否进口','箱装数量','加工定制','专利','货号',
                '颜色','产地','生产企业','型号','规格','是否跨境出口专供货源'];
  for (const k of keys) {
    const m = txt.match(new RegExp(k + '[\\\\s\\\\t]*\\\\n+\\\\s*([^\\\\n]{1,40})'));
    if (m) { const v = m[1].trim(); if (v && v.length < 40) out.pairs[k] = v; }
  }
  // Supplier name and shipping origin, used only for 产地 when the page states it.
  const comp = txt.match(/([\\u4e00-\\u9fa5]{2,12}(?:市|省)[\\u4e00-\\u9fa5]{0,8}(?:贸易|实业|科技|电子商务|制品|百货)?有限公司)/);
  if (comp) out.supplier = comp[1];
  const loc = txt.match(/(?:送至|发货地|所在地)[\\s:：]*([\\u4e00-\\u9fa5]{2,10}(?:省|市))/);
  if (loc) out.location = loc[1];
  return out;
})()"""


def read_supplier_spec(bridge, url):
    """Open a 1688 offer and return the spec pairs it states. Read-only."""
    bridge.command('navigate', {'url': url, 'newTab': True, 'group_title': '源头规格'})
    import time
    time.sleep(11)
    for _ in range(3):
        bridge.evaluate("(()=>{window.scrollBy(0,700);return {y:window.scrollY};})()")
        time.sleep(1.5)
    return bridge.evaluate(DUMP_SPEC)


def facts_for_douyin(spec):
    """Map supplier spec pairs onto Douyin attribute names, keeping only direct statements.

    Anything the supplier page does not say is left out rather than inferred, so the
    caller sees a shorter result instead of a plausible guess.
    """
    pairs = (spec or {}).get('pairs') or {}
    out = {}
    for source_key, douyin_key in DOUYIN_FROM_SOURCE.items():
        value = (pairs.get(source_key) or '').strip()
        if value and value not in ('咨询客服', '其他', '-', '无'):
            out.setdefault(douyin_key, value)
    # 产地 is only usable when the page names a place; a company name alone is not an address.
    # The page states origin as either "浙江金华" or "浙江省金华市", so accept both shapes.
    location = (spec or {}).get('location') or ''
    if re.fullmatch(r'[\u4e00-\u9fa5]{2,12}(?:省|市)?', location) and len(location) >= 2:
        out.setdefault('产地', location)
    return out


def unsupported_but_asked(spec):
    """Attributes Douyin asks for that the supplier page genuinely does not answer."""
    pairs = (spec or {}).get('pairs') or {}
    missing = {}
    if '是否可接触食品' not in pairs:
        missing['是否可接触食品'] = '源页面无此字段'
    if '材质类型' not in pairs:
        missing['材质类型'] = '源页面只有材质名称，平台多选需选归类'
    if not (spec or {}).get('location') or '生产企业' not in pairs:
        missing['生产企业地址'] = '源页面仅有店铺公司与发货地，无详细厂址'
    return missing
