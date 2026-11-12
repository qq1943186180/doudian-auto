"""Execute the adapter's generated JavaScript under Node with a stub DOM.

The Python tests use a FakeBridge, so they can pass while the embedded JS is broken:
a regex written as \\\\s in a Python triple-quoted string lands as two backslashes and
matches a literal backslash followed by 's' instead of whitespace. Nothing in-process
would catch that. This runs the real code path in Node against a stub page.

Every adapter method gets a happy path and a fail-closed path: a happy path alone
cannot show that an ambiguous match stops instead of widening.

Run: python tests/verify_adapter_js.py
"""

import inspect
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

from doudian_auto.dropship_pages import (  # noqa: E402
    PRICE_FIELDS, DropshipPages, _js,
)

PID = '3853454064050373417'
SOURCE_ID = '965251097615'
YEN = '¥'

# 每个 case 各自建一套 stub，避免共用数组导致「所有选择器都命中同一批元素」。
STUB_BASE = r"""
globalThis.URL = URL;
globalThis.setPage = (host, path, query) => {
  const q = new URLSearchParams(query);
  globalThis.location = {href: 'https://' + host + path + '?' + query,
                         hostname: host, pathname: path, searchParams: q};
};
globalThis.resetDoc = () => {
  globalThis.document = {querySelectorAll: () => [], body: {innerText: ''}};
};
globalThis.resetDoc();
"""

# 官方商品编辑页：SKU 行 + 价格填写进度
STUB_OFFICIAL = r"""
const YEN = String.fromCharCode(65509);
const makeInput = v => ({value: v, getAttribute: () => '请输入'});
const skuRows = [
  {innerText: '极氪车门限位器-4个装 ' + YEN + ' 888888 增 减 888888 清空 - 3392818512538149 去关联 已上架',
   querySelectorAll: () => [makeInput('27.48')]},
  {innerText: '极氪车门限位器-1个装 ' + YEN + ' 888888 增 减 888888 清空 - 3392818512538405 去关联 已上架',
   querySelectorAll: () => [makeInput('15.48')]},
];
globalThis.document = {
  querySelectorAll: sel => (sel === 'tr' ? skuRows : []),
  body: {innerText: '*价格与库存 价格填写进度 100% 区域库存 全部颜色'},
};
"""

# 复制历史页：真实结构是 vue-recycle-scroller 虚拟滚动表格，行容器是 div 不是 tr。
# 这段 DOM 是从实抓页面逐字抄下来的：之前 stub 自造了 tr 行，于是验证器自洽通过，
# 而真实页面上永远返回 0 行。stub 必须反映真实结构，否则验证器等于自证。
STUB_HISTORY = r"""
const mkRow = cells => ({
  innerText: cells.join(' '),
  querySelectorAll: sel => (sel === 'div.cell'
    ? cells.map(c => ({innerText: c}))
    : []),
});
const historyRows = [
  mkRow(['',
    '阿里巴巴适用极氪001/007车门限位器7X/009汽车门缓冲减震垫改装保护套 发布类目：汽车用品>汽车防护用品>其他汽车防护用品 1688分销',
    '华睿车品（华睿车品） 源ID： 965251097615 默认配置',
    '审核通过', '已成功复制',
    '2026-11-11 22:21 商品ID： 3853454064050373417 已下架 审核通过 销量：0',
    '', '商品快速编辑 去抖店编辑 更多']),
  mkRow(['',
    '阿里巴巴utookii行李箱轮子保护套一次性收纳防尘脚罩防脏旅行箱滚轮万向 发布类目：箱包>箱包配件>箱包配件 1688分销',
    '上海馨尚悦居贸易有限公司（馨尚悦居） 源ID： 872099955768 默认配置',
    '', '已成功复制',
    '2026-10-24 16:36 商品ID： 3850072322857894188 已下架 审核通过 销量：0',
    '', '商品快速编辑 去抖店编辑 更多']),
];
// 复制历史页的「来源ID」筛选框：适配器要求处在按本来源筛选的状态
const sourceFilter = {name: 'sourceItemId', value: '965251097615'};
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'div.pro-table-custom-body-row') return historyRows;
    if (sel === 'input[name="sourceItemId"]') return [sourceFilter];
    // tr 里只有日历残留——这正是旧实现返回 0 行的原因
    if (sel === 'tr') return [{innerText: '日一二三四五六'}];
    return [];
  },
  body: {innerText: '共 1 条'},
};
"""

# 搬家设置页：8 个价格字段 + 放入仓库 radio + 保存按钮
STUB_SETTINGS = r"""
const FIELDS = ['pricePercent','priceAdd','priceSub','priceFinalPercent','priceTail',
                 'priceDecimalDiyValue','sourcePostFeePriceAddValue','postFeePrice1688AddValue'];
const initial = {pricePercent:'200', priceAdd:'3', priceSub:'', priceFinalPercent:'100',
                 priceTail:'', priceDecimalDiyValue:'88', sourcePostFeePriceAddValue:'',
                 postFeePrice1688AddValue:'5.00'};
class HTMLInputElement {
  constructor(name, value) { this.name = name; this._value = value; this.dispatchEvent = () => {}; }
}
Object.defineProperty(HTMLInputElement.prototype, 'value', {
  set(v) { this._value = v; }, get() { return this._value; },
});
globalThis.window = {HTMLInputElement};
globalThis.Event = class Event { constructor(t, o) { this.type = t; this.options = o; } };
const inputs = {};
for (const name of FIELDS) inputs[name] = new HTMLInputElement(name, initial[name]);

const radioInput = {checked: true};
const radio = {
  innerText: '放入仓库',
  querySelector: s => (s === 'input[type=radio]' ? radioInput : null),
  click: () => { radioInput.checked = true; },
};
const saveButton = {innerText: '保存', click: () => {}};
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'input[name]') return Object.values(inputs);
    if (sel === 'label.el-radio') return [radio];
    if (sel === 'button') return [saveButton];
    if (sel === '.el-message') return [];
    return [];
  },
  body: {innerText: ''},
};
"""

# 商品上货页：textarea + 三个同类按钮
STUB_MOVE = r"""
class HTMLTextAreaElement {
  constructor() { this.placeholder = '多条地址换行或逗号区分'; this._value = ''; this.dispatchEvent = () => {}; }
}
Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {
  set(v) { this._value = v; }, get() { return this._value; },
});
globalThis.window = {HTMLTextAreaElement};
globalThis.Event = class Event { constructor(t, o) { this.type = t; this.options = o; } };
const ta = new HTMLTextAreaElement();

const grabButton = {innerText: '开始批量抓取商品', disabled: false, click: () => {}};
const nextCopyButton = {innerText: '下一步: 开始复制', disabled: false, click: () => {}};
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'textarea') return [ta];
    if (sel === 'button') return [grabButton, nextCopyButton];
    return [];
  },
  body: {innerText: '商品列表 跳过： 1 详情 成功： 0 查看详情'},
};
"""

# 商品上货页：抓取成功的结果页（成功 1 / 跳过 0）
STUB_MOVE_OK = r"""
const ta = {
  placeholder: '多条地址换行或逗号区分', value: '',
  dispatchEvent: () => {},
};
class HTMLTextAreaElement {}
Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {
  set(v) { this._value = v; }, get() { return this._value; },
});
globalThis.window = {HTMLTextAreaElement};
globalThis.Event = class Event { constructor(t, o) { this.type = t; this.options = o; } };

const nextCopyButton = {innerText: '下一步: 开始复制', disabled: false, click: () => {}};
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'textarea') return [ta];
    if (sel === 'button') return [nextCopyButton];
    return [];
  },
  body: {innerText: '商品列表 跳过： 0 详情 成功： 1'},
};
"""

# 商品上货页：成功 2 / 跳过 0（成功数多于单商品任务的预期）
STUB_MOVE_TWO = STUB_MOVE_OK.replace('跳过： 0 详情 成功： 1', '跳过： 0 详情 成功： 2')

# 商品上货页：成功 1 / 跳过 1（成功数对但有跳过，仍不许复制）
STUB_MOVE_SKIPPED = STUB_MOVE_OK.replace('跳过： 0 详情 成功： 1', '跳过： 1 详情 成功： 1')

# 结果页：抓取成功、跳过为 0（此时页面把「跳过」计数器整个隐藏）
STUB_MOVE_CLEAN = STUB_MOVE_OK.replace(
    '跳过： 0 详情 成功： 1', '成功： 1')

# 复制历史页：筛选表单
STUB_HISTORY_FILTER = r"""
const rect = () => ({width: 200, height: 30});
class HTMLInputElement {
  constructor() {
    this.name = 'sourceItemId';
    this.dispatchEvent = () => {};
    this.getBoundingClientRect = rect;
  }
}
Object.defineProperty(HTMLInputElement.prototype, 'value', {
  set(v) { this._value = v; }, get() { return this._value; },
});
globalThis.window = {HTMLInputElement};
globalThis.Event = class Event { constructor(t, o) { this.type = t; this.options = o; } };
const filterInput = new HTMLInputElement();
const queryBtn = {innerText: '查询', click: () => {}, getBoundingClientRect: rect};
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'input[name="sourceItemId"]') return [filterInput];
    if (sel === 'button') return [queryBtn];
    return [];
  },
  body: {innerText: '共 0 条'},
};
"""

# 筛选后「共 0 条」、DOM 无行 —— 基线空但完整
STUB_HISTORY_EMPTY = STUB_HISTORY.replace(
    "if (sel === 'div.pro-table-custom-body-row') return historyRows;",
    "if (sel === 'div.pro-table-custom-body-row') return [];"
).replace("body: {innerText: '共 1 条'}", "body: {innerText: '共 0 条'}"
).replace("value: '965251097615'", "value: '922368518409'")

# 筛选框里是别的来源 —— 基线必须判无效
STUB_HISTORY_WRONG_FILTER = STUB_HISTORY.replace(
    "body: {innerText: '共 1 条'}", "body: {innerText: '共 1 条'}")

# 抖音官方机会商品页的卡片（结构与实抓一致）
def_opportunity_stub = r"""
const leaf = t => ({children: {length: 0}, innerText: t});
const mkCard = (title, tags, cipher, uuid, opportunity) => ({
  innerText: [title].concat(tags).join(' '),
  querySelector: s => {
    if (s === 'a.title' || s === '.title-text-box') return {innerText: title};
    if (s === '.price-number') return {innerText: '1.68 ~ 2.38'};
    if (s === '[data-custom-id]') return {getAttribute: () => uuid};
    if (s === 'img') return {src: 'https://cbu01.alicdn.com/img/x.jpg'};
    return null;
  },
  querySelectorAll: s => {
    if (s === '.tag-text') return tags.map(t => ({innerText: t}));
    if (s === '*') {
      const leaves = tags.map(leaf);
      if (cipher) leaves.push(leaf('支持密文'));
      if (opportunity) leaves.push(leaf('商机：' + opportunity));
      return leaves;
    }
    return [];
  },
});
globalThis.__mkCard = mkCard;
"""
STUB_OPPORTUNITY = def_opportunity_stub + r"""
const cards = [
  __mkCard('汽车倒车后视镜小圆镜', ['一件代发', '48小时发货'], true,
           'uuid-1', null),
];
globalThis.document = {
  querySelectorAll: s => (s === 'div.preview-item.hover-active' ? cards : []),
  body: {innerText: ''},
};
"""
STUB_OPPORTUNITY_MIXED = def_opportunity_stub + r"""
const cards = [
  __mkCard('汽车倒车后视镜小圆镜', ['一件代发'], true, 'uuid-1', null),
  __mkCard('普通无密文商品', ['一件代发'], false, 'uuid-2', null),
];
globalThis.document = {
  querySelectorAll: s => (s === 'div.preview-item.hover-active' ? cards : []),
  body: {innerText: ''},
};
"""

# 1688 来源页：规格选择区
# 这段结构是从实抓页面抄的：div.module-od-sku-selection > div.expand-view-item，
# 规格名在 span.item-label[title]，价格在第一个 span.item-price-stock，
# 第二个是「库存888888个」这种库存文本，不是钱。
STUB_SOURCE = r"""
const mkItem = (name, price) => ({
  innerText: name + ' ' + price + ' 库存888888个 ',
  querySelector: s => {
    if (s === 'span.item-label') return {getAttribute: () => name, innerText: name};
    return null;
  },
  querySelectorAll: s => {
    if (s === 'span.item-price-stock')
      return [{innerText: price}, {innerText: '库存888888个'}];
    return [];
  },
});
const skuItems = [
  mkItem('极氪车门限位器-4个装', '¥6'),
  mkItem('极氪车门限位器-1个装', '¥2'),
];
const skuSelection = {
  querySelectorAll: s => (s === 'div.expand-view-item' ? skuItems : []),
};
globalThis.document = {
  querySelector: s => (s === 'div.module-od-sku-selection' ? skuSelection : null),
  querySelectorAll: () => [],
  body: {innerText: ''},
};
"""

# 机会商品页：一张卡片 + 立即铺货
STUB_OPPORTUNITY = r"""
const action = {innerText: '立即铺货', click: () => {}};
const card = {
  innerText: '素材优化 汽车密封条 支持密文 一件代发',
  querySelector: s => (s === '.product-card.product-card__ms.product-card__orange' ? {} : null),
  querySelectorAll: s => (s === 'div.J_moveCommonPreviewProductBtn' ? [action] : []),
};
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'div.preview-item.hover-active') return [card];
    if (sel === 'button') return [{innerText: '下一步: 开始复制'}];
    // 抽屉里的来源商品链接：实抓确认这是 1688 offer ID 的来源
    if (sel === 'a') return [{href: 'http://detail.1688.com/offer/671243686759.html?amug_web_biz=fwmkt'}];
    return [];
  },
  body: {innerText: '商品列表 成功： 1'},
};
"""

# 机会商品页：抽屉开了但没有 1688 链接 —— 拿不到来源身份就不许算成功
STUB_OPPORTUNITY_NO_OFFER = STUB_OPPORTUNITY.replace(
    "    if (sel === 'a') return [{href: 'http://detail.1688.com/offer/671243686759.html?amug_web_biz=fwmkt'}];\n",
    "    if (sel === 'a') return [];\n")

# 抖店商品管理页：真实行文（2026-11-12 实抓逐字抄）
STUB_OFFICIAL_LIST = r"""
const row = {innerText: '黑色隐形BB夹大号小号两种规格含收纳盒 ID：3850071994200621373 '
  + '货号：A#1077401428037 现货模式 预览 复制链接 ￥10.88 ~ ￥11.88 1971417 0 暂无评价 88分 '
  + '2026/10/24 16:36:23 售卖中 编辑 下架 新建渠道品 发布相似品 更多'};
globalThis.document = {
  querySelectorAll: sel => (sel === 'tr' ? [row] : []),
  body: {innerText: '共 1 件商品 售卖中'},
};
"""

# 同一页里出现两行同一个商品 ID —— 必须判结构变化，不能随便挑一行
STUB_OFFICIAL_LIST_DUP = STUB_OFFICIAL_LIST.replace(
    "querySelectorAll: sel => (sel === 'tr' ? [row] : []),",
    "querySelectorAll: sel => (sel === 'tr' ? [row, row] : []),")

# 抖店草稿箱：真实行文（状态词在 ID 之后、日期之前）
STUB_OFFICIAL_DRAFT = r"""
const row = {innerText: '酒店生物酶除味剂空气清新分解型去异味净味卫生间房间专用除臭剂 '
  + 'ID:3853482303460343870 待提交 2026/11/12 01:41:35 编辑删除'};
globalThis.document = {
  querySelectorAll: sel => (sel === 'tr' ? [row] : []),
  body: {innerText: '共 1 件商品 待提交'},
};
"""

# 复制历史页：虚拟滚动 + 分页器。
# 这段 stub 复刻真实行为：滚动容器 scrollTop 变化时，挂在 DOM 上的行会换掉，
# 所以只读一屏必然漏数据——采集必须边滚边累计。
STUB_HISTORY_PAGED = r"""
const mkView = text => ({
  querySelector: sel => (sel === 'div.pro-table-custom-body-row'
    ? {innerText: text} : null),
});
const rowText = i => '阿里巴巴商品' + i + '\n发布类目：居家日用>收纳整理工具>收纳筐/收纳篮\n'
  + '1688分销\n义乌市某某日用品（某某日用品）\n源ID：\n100000000000' + i
  + '\n默认配置\n已成功复制\n2026-10-24 16:35\n商品ID：\n38500700000000000' + i
  + '\n已下架\n审核通过\n销量：0';
const allRows = [0, 1, 2, 3, 4, 5].map(rowText);
let top = 0;
const scroller = {
  scrollTop: 0,
  scrollHeight: 600,
  clientHeight: 300,
};
Object.defineProperty(scroller, 'scrollTop', {
  get: () => globalThis.__scrollTop,
  set: v => {
    globalThis.__scrollTop = v;
    // 真实页面：滚动 → 虚拟列表换一批行挂载
    top = Math.max(0, Math.min(allRows.length - 2, Math.floor(v / 100)));
  },
});
globalThis.__scrollTop = 0;
const pagerLi = {
  innerText: '1',
  className: 'is-active number',
  click: () => {},
};
globalThis.document = {
  querySelector: sel => (sel === 'div.content-main' ? scroller : null),
  querySelectorAll: sel => {
    if (sel === '.el-pager li') return [pagerLi];
    if (sel === '.vue-recycle-scroller__item-view')
      return [mkView(allRows[top]), mkView(allRows[top + 1])];
    if (sel === 'tr') return [];
    return [];
  },
  body: {innerText: '共 6 条 1 20 条/页'},
};
"""


def extract(method, payload, fields=None):
    src = inspect.getsource(method)
    body = re.search(r'code = """(.*?)"""', src, re.S).group(1)
    body = body.replace('__PAYLOAD__', _js(payload))
    if '__FIELDS__' in body:
        body = body.replace('__FIELDS__', _js(fields or []))
    return body


def run(label, js, expect, page=None, stub=None):
    """在 Node 里真跑一段适配器 JS 并断言返回值。

    临时文件写系统临时目录而不是仓库：Node 超时或 Python 异常都可能让清理
    步骤来不及执行，留在仓库里就是污染。
    """
    # 异步适配器（轮询等待页面渲染）也要能真跑，所以两种 IIFE 都要接住，
    # 并且用 .mjs + 顶层 await 把 Promise 结算完再打印。
    js = js.replace('(async()=>{', 'globalThis.__r=(async()=>{', 1)
    js = js.replace('(()=>{', 'globalThis.__r=(()=>{', 1)
    js += '\nconsole.log(JSON.stringify(await globalThis.__r));\n'
    prefix = ''
    if page:
        prefix = f'setPage({page[0]!r}, {page[1]!r}, {page[2]!r});\n'
    script = STUB_BASE + (stub or '') + prefix + js
    with tempfile.TemporaryDirectory(prefix='dropship-js-') as tmp:
        path = Path(tmp) / 'case.mjs'
        path.write_text(script, encoding='utf-8')
        proc = subprocess.run(['node', str(path)], capture_output=True,
                              text=True, timeout=60)
    out = (proc.stdout or '').strip()
    if proc.returncode != 0:
        print(f'[FAIL] {label}: node 执行报错\n{proc.stderr.strip()[:400]}')
        return False
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        print(f'[FAIL] {label}: 输出不是 JSON -> {out[:200]}')
        return False
    ok = expect(data)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {json.dumps(data, ensure_ascii=False)[:200]}")
    return ok


def main():
    pages = DropshipPages(None)
    results = []

    # ---------- read_sku_prices ----------
    def check_sku(d):
        rows = d.get('sku_rows') or []
        return (d.get('status') == 'ok' and len(rows) == 2
                and rows[0]['price'] == '27.48' and rows[1]['price'] == '15.48'
                and rows[0]['sku'].startswith('极氪车门限位器-4个装')
                and d.get('sku_total_count') is None
                and d.get('price_progress') == 100)

    results.append(run('read_sku_prices',
                       extract(pages.read_sku_prices, {'product_id': PID}), check_sku,
                       page=('fxg.jinritemai.com', '/ffa/g/create', f'product_id={PID}'),
                       stub=STUB_OFFICIAL))

    def check_sku_wrong_page(d):
        return d.get('status') == 'wrong_page'

    results.append(run('read_sku_prices_wrong_page',
                       extract(pages.read_sku_prices, {'product_id': PID}), check_sku_wrong_page,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_OFFICIAL))

    # ---------- read_history_product_id ----------
    def check_history(d):
        return d.get('status') == 'ok' and d.get('product_id') == PID

    results.append(run('read_history_product_id',
                       extract(pages.read_history_product_id,
                               {'source_product_id': SOURCE_ID}), check_history,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY))

    def check_history_prefix(d):
        """短 ID 不能命中长 ID 的前缀。"""
        return d.get('status') == 'layout_changed'

    results.append(run('read_history_prefix_collision',
                       extract(pages.read_history_product_id,
                               {'source_product_id': '96525109761'}), check_history_prefix,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY))

    def check_history_bad_id(d):
        """来源 ID 含正则字符时必须拒绝，而不是改变匹配含义。"""
        return d.get('status') == 'layout_changed' and d.get('reason') == 'source_id_invalid'

    results.append(run('read_history_non_numeric_id',
                       extract(pages.read_history_product_id,
                               {'source_product_id': '.*'}), check_history_bad_id,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY))

    # ---------- read_settings ----------
    def check_settings(d):
        v = d.get('values') or {}
        return (d.get('status') == 'ok' and v.get('pricePercent') == '200'
                and v.get('priceAdd') == '3' and d.get('shelf_mode') == '放入仓库')

    results.append(run('read_settings',
                       extract(pages.read_settings, {},
                               fields=list(PRICE_FIELDS)), check_settings,
                       page=('v2-dd.chengji-inc.com', '/move/move_setting', ''),
                       stub=STUB_SETTINGS))

    # ---------- set_price_formula ----------
    def check_set(d):
        v = d.get('values') or {}
        return (d.get('status') == 'ok' and v.get('pricePercent') == '300'
                and v.get('priceAdd') == '5'
                and d.get('shelf_mode') == '放入仓库'
                and d.get('persistence') == 'unverified')

    results.append(run('set_price_formula',
                       extract(pages.set_price_formula,
                               {'before': {'pricePercent': '200', 'priceAdd': '3'},
                                'target': {'pricePercent': '300', 'priceAdd': '5'}}),
                       check_set,
                       page=('v2-dd.chengji-inc.com', '/move/move_setting', ''),
                       stub=STUB_SETTINGS))

    def check_set_stale(d):
        """旧值已被别人改过时必须停，不能覆盖。"""
        return (d.get('status') == 'readback_mismatch'
                and d.get('reason') == 'old_value_changed')

    results.append(run('set_price_formula_stale_before',
                       extract(pages.set_price_formula,
                               {'before': {'pricePercent': '999', 'priceAdd': '3'},
                                'target': {'pricePercent': '300', 'priceAdd': '5'}}),
                       check_set_stale,
                       page=('v2-dd.chengji-inc.com', '/move/move_setting', ''),
                       stub=STUB_SETTINGS))

    # ---------- paste_offer_and_fetch ----------
    def check_paste(d):
        return (d.get('status') == 'ok'
                and d.get('textarea_value') == 'https://detail.1688.com/offer/1.html')

    results.append(run('paste_offer_and_fetch',
                       extract(pages.paste_offer_and_fetch,
                               {'offer_url': 'https://detail.1688.com/offer/1.html'}),
                       check_paste,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_MOVE))

    # ---------- read_fetch_result ----------
    def check_fetch(d):
        return (d.get('status') == 'ok' and d.get('skipped_count') == '1'
                and d.get('success_count') == '0' and d.get('next_step_count') == 1)

    results.append(run('read_fetch_result',
                       extract(pages.read_fetch_result, {}), check_fetch,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_MOVE))

    # ---------- click_start_copy ----------
    # 点击复制是整条链里最不可逆的一步，所以它自带前置闸门。
    # 下面几个用例逐条钉住闸门：抓取不干净就不许点。

    def check_next(d):
        return (d.get('status') == 'ok'
                and d.get('clicked') == '下一步: 开始复制'
                and d.get('success_count') == '1')

    results.append(run('click_start_copy',
                       extract(pages.click_start_copy, {'expected_success': 1}), check_next,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_MOVE_OK))

    def check_next_skipped(d):
        """有跳过就不许复制：被跳过的商品根本没抓回来。"""
        return (d.get('status') == 'layout_changed'
                and d.get('reason') == 'fetch_skipped'
                and d.get('skipped_count') == '1')

    results.append(run('click_start_copy_refuses_skipped',
                       extract(pages.click_start_copy, {'expected_success': 1}),
                       check_next_skipped,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_MOVE_SKIPPED))

    def check_next_mismatch(d):
        """成功数与预期不符就不许复制。"""
        return (d.get('status') == 'layout_changed'
                and d.get('reason') == 'fetch_success_mismatch')

    results.append(run('click_start_copy_refuses_success_mismatch',
                       extract(pages.click_start_copy, {'expected_success': 1}),
                       check_next_mismatch,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_MOVE_TWO))

    def check_next_no_list(d):
        """结果页都没出现就不许复制。"""
        return (d.get('status') == 'layout_changed'
                and d.get('reason') == 'result_list_missing')

    results.append(run('click_start_copy_refuses_missing_list',
                       extract(pages.click_start_copy, {'expected_success': 1}),
                       check_next_no_list,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=r"""
const ta = {placeholder: '多条地址换行或逗号区分', value: '', dispatchEvent: () => {}};
globalThis.document = {
  querySelectorAll: sel => (sel === 'textarea' ? [ta] : []),
  body: {innerText: '还没有抓取结果'},
};
"""))

    # ---------- click_single_opportunity ----------
    def check_card(d):
        """点开抽屉后必须同时拿到「下一步」和精确的 1688 offer ID。"""
        return (d.get('status') == 'ok' and d.get('result_visible') is True
                and d.get('next_step') is True
                and d.get('source_offer_id') == '671243686759'
                and 'detail.1688.com/offer/671243686759.html' in (d.get('source_offer_url') or ''))

    results.append(run('click_single_opportunity',
                       extract(pages.click_single_opportunity,
                               {'card_text': '汽车密封条'}), check_card,
                       page=('v2-dd.chengji-inc.com', '/selection/opportunity_product', ''),
                       stub=STUB_OPPORTUNITY))

    def check_card_ambiguous(d):
        """子串命中多张卡片时必须停。"""
        return d.get('status') == 'layout_changed' and d.get('reason') == 'card'

    results.append(run('click_single_opportunity_ambiguous',
                       extract(pages.click_single_opportunity,
                               {'card_text': '不存在的标题'}), check_card_ambiguous,
                       page=('v2-dd.chengji-inc.com', '/selection/opportunity_product', ''),
                       stub=STUB_OPPORTUNITY))

    def check_card_no_offer(d):
        """抽屉开了却拿不到 1688 offer ID —— 来源身份不成立，不许算成功。"""
        return d.get('status') == 'layout_changed' and d.get('reason') == 'offer_identity_not_found'

    results.append(run('click_single_opportunity_without_offer_identity',
                       extract(pages.click_single_opportunity,
                               {'card_text': '汽车密封条'}), check_card_no_offer,
                       page=('v2-dd.chengji-inc.com', '/selection/opportunity_product', ''),
                       stub=STUB_OPPORTUNITY_NO_OFFER))

    # ---------- read_opportunity_source_identity ----------
    def check_source_identity(d):
        return (d.get('status') == 'ok'
                and d.get('source_offer_id') == '671243686759'
                and d.get('source_offer_ids') == ['671243686759'])

    results.append(run('read_opportunity_source_identity',
                       extract(pages.read_opportunity_source_identity, {}),
                       check_source_identity,
                       page=('v2-dd.chengji-inc.com', '/selection/opportunity_product', ''),
                       stub=STUB_OPPORTUNITY))

    def check_source_identity_missing(d):
        """读不到就是读不到，不许拿别的东西顶上。"""
        return d.get('status') == 'not_found' and d.get('source_offer_id') is None

    results.append(run('read_opportunity_source_identity_missing',
                       extract(pages.read_opportunity_source_identity, {}),
                       check_source_identity_missing,
                       page=('v2-dd.chengji-inc.com', '/selection/opportunity_product', ''),
                       stub=STUB_OPPORTUNITY_NO_OFFER))

    # ---------- 抖店商品管理页：平台状态 ----------
    def check_official_state(d):
        return (d.get('status') == 'ok'
                and d.get('platform_state') == '售卖中'
                and d.get('product_id') == '3850071994200621373')

    results.append(run('read_official_product_status',
                       extract(pages.read_official_product_status,
                               {'product_id': '3850071994200621373'}),
                       check_official_state,
                       page=('fxg.jinritemai.com', '/ffa/g/list',
                             'product_id=3850071994200621373&sov_goodsType=0&tab=all'),
                       stub=STUB_OFFICIAL_LIST))

    def check_official_state_dup(d):
        """同一个 ID 出现两行时必须停，不能随便挑一行当状态。"""
        return d.get('status') == 'layout_changed' and d.get('reason') == 'product_id_rows'

    results.append(run('read_official_product_status_ambiguous',
                       extract(pages.read_official_product_status,
                               {'product_id': '3850071994200621373'}),
                       check_official_state_dup,
                       page=('fxg.jinritemai.com', '/ffa/g/list',
                             'product_id=3850071994200621373&sov_goodsType=0&tab=all'),
                       stub=STUB_OFFICIAL_LIST_DUP))

    def check_official_state_wrong_page(d):
        return d.get('status') == 'wrong_page'

    results.append(run('read_official_product_status_wrong_page',
                       extract(pages.read_official_product_status,
                               {'product_id': '3850071994200621373'}),
                       check_official_state_wrong_page,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_OFFICIAL_LIST))

    # ---------- 抖店草稿箱：草稿状态 ----------
    def check_draft_state(d):
        return (d.get('status') == 'ok'
                and d.get('platform_state') == '待提交'
                and d.get('product_id') == '3853482303460343870')

    results.append(run('read_draft_box_status',
                       extract(pages.read_draft_box_status,
                               {'product_id': '3853482303460343870'}),
                       check_draft_state,
                       page=('fxg.jinritemai.com', '/ffa/g/draft',
                             'product_id=3853482303460343870'),
                       stub=STUB_OFFICIAL_DRAFT))

    def check_draft_state_wrong_page(d):
        """草稿箱状态不能在商品管理页上读——路径写错必须报 wrong_page。"""
        return d.get('status') == 'wrong_page'

    results.append(run('read_draft_box_status_wrong_page',
                       extract(pages.read_draft_box_status,
                               {'product_id': '3853482303460343870'}),
                       check_draft_state_wrong_page,
                       page=('fxg.jinritemai.com', '/ffa/g/list', 'product_id=1'),
                       stub=STUB_OFFICIAL_DRAFT))

    # ---------- 复制历史：翻页 + 细步滚动采全量 ----------
    def check_history_all(d):
        """虚拟滚动只挂载 2 行，但必须靠累计采满 6 条（页面写「共 6 条」）。"""
        return (d.get('status') == 'ok' and d.get('total') == 6
                and d.get('collected') == 6 and d.get('complete') is True
                and len(d.get('rows') or []) == 6)

    results.append(run('collect_history_rows_all_pages',
                       extract(pages.collect_history_rows_all_pages,
                               {'max_pages': 10}),
                       check_history_all,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY_PAGED))

    # ---------- read_source_skus ----------
    def check_source(d):
        rows = d.get('sku_rows') or []
        return (d.get('status') == 'ok' and len(rows) == 2
                and rows[0]['sku'] == '极氪车门限位器-4个装'
                and rows[0]['source_price'] == '6'
                and rows[1]['sku'] == '极氪车门限位器-1个装'
                and rows[1]['source_price'] == '2')

    results.append(run('read_source_skus',
                       extract(pages.read_source_skus,
                               {'offer_url': 'https://detail.1688.com/offer/965251097615.html',
                                'source_product_id': '965251097615'}),
                       check_source,
                       page=('detail.1688.com', '/offer/965251097615.html', ''),
                       stub=STUB_SOURCE))

    def check_source_wrong_offer(d):
        """页面上的 offer ID 与任务指定的不一致时必须拒绝，不能读成别人的规格。"""
        return d.get('status') == 'wrong_page'

    results.append(run('read_source_skus_wrong_offer',
                       extract(pages.read_source_skus,
                               {'offer_url': 'https://detail.1688.com/offer/965251097615.html',
                                'source_product_id': '999999'}),
                       check_source_wrong_offer,
                       page=('detail.1688.com', '/offer/965251097615.html', ''),
                       stub=STUB_SOURCE))

    # ---------- 筛选态历史：基线可证明完整 ----------
    def check_filter(d):
        return d.get('status') == 'ok' and d.get('value') == '922368518409'

    results.append(run('filter_history_by_source',
                       extract(pages.filter_history_by_source,
                               {'source_product_id': '922368518409'}),
                       check_filter,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY_FILTER))

    def check_baseline(d):
        """筛选后 total==matched 才承认基线完整。"""
        return (d.get('status') == 'ok' and d.get('baseline_complete') is True
                and d.get('total_records') == 0 and d.get('matched_rows') == 0
                and d.get('baseline_keys') == [])

    results.append(run('read_history_baseline_filtered_empty',
                       extract(pages.read_history_baseline,
                               {'source_product_id': '922368518409'}),
                       check_baseline,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY_EMPTY))

    def check_baseline_incomplete(d):
        """筛选框不是本任务来源时必须判无效，不能拿别人的结果当基线。"""
        return (d.get('status') == 'ok' and d.get('baseline_complete') is False
                and '筛选框' in (d.get('completeness_reason') or ''))

    results.append(run('read_history_baseline_wrong_filter',
                       extract(pages.read_history_baseline,
                               {'source_product_id': '922368518409'}),
                       check_baseline_incomplete,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY_WRONG_FILTER))

    # ---------- 结果页：跳过为 0 时计数器被隐藏 ----------
    def check_skip_inferred(d):
        return (d.get('status') == 'ok' and d.get('success_count') == '1'
                and d.get('skipped_count') == '0'
                and d.get('skipped_inferred') is True)

    results.append(run('read_fetch_result_skip_counter_hidden',
                       extract(pages.read_fetch_result, {}), check_skip_inferred,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_MOVE_CLEAN))

    def check_next_clean(d):
        """跳过计数器隐藏、但成功 1 时应允许点复制。"""
        return d.get('status') == 'ok' and d.get('clicked') == '下一步: 开始复制'

    results.append(run('click_start_copy_allows_hidden_zero_skip',
                       extract(pages.click_start_copy, {'expected_success': 1}),
                       check_next_clean,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=STUB_MOVE_CLEAN))

    # ---------- 历史读取：必须处在筛选态、且只认基线之后的新行 ----------
    def check_history_baseline_excluded(d):
        return d.get('status') == 'ok' and d.get('product_id') == PID

    results.append(run('read_history_product_id_excludes_baseline',
                       extract(pages.read_history_product_id,
                               {'source_product_id': SOURCE_ID,
                                'baseline_keys': [SOURCE_ID + '@3850072322857894188']}),
                       check_history_baseline_excluded,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY))

    def check_history_not_filtered(d):
        return (d.get('status') == 'layout_changed'
                and d.get('reason') == 'history_not_filtered_for_source')

    results.append(run('read_history_product_id_requires_source_filter',
                       extract(pages.read_history_product_id,
                               {'source_product_id': '999999999999',
                                'baseline_keys': []}),
                       check_history_not_filtered,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', ''),
                       stub=STUB_HISTORY))

    # ---------- 选品候选：只读，不点按钮 ----------
    def check_opportunity(d):
        """字段完整 + 过滤生效 + 身份边界如实声明。"""
        rows = d.get('candidates') or []
        return (d.get('status') == 'ok'
                and d.get('candidate_count') == 1
                and rows[0]['title'] == '汽车倒车后视镜小圆镜'
                and rows[0]['supports_cipher'] is True
                and rows[0]['dropship'] is True
                and rows[0]['price_range'] == '1.68 ~ 2.38'
                and 'offer ID' in (d.get('identity_note') or ''))

    results.append(run('read_opportunity_candidates_filters_and_fields',
                       extract(pages.read_opportunity_candidates,
                               {'require_cipher': True, 'require_dropship': True,
                                'limit': 30}),
                       check_opportunity,
                       page=('v2-dd.chengji-inc.com', '/selection/opportunity_product', ''),
                       stub=STUB_OPPORTUNITY_MIXED))

    # ---------- read_review_status ----------
    def check_review(d):
        # 实测：编辑页没有商品审核状态。「已上架」是 SKU 状态，不能当审核状态。
        return (d.get('status') == 'ok'
                and d.get('review_status') is None
                and d.get('sku_status_tokens') == ['已上架']
                and set(d.get('product_state_options') or []) == {'上架', '下架'})

    results.append(run('read_review_status',
                       extract(pages.read_review_status, {'product_id': PID}), check_review,
                       page=('fxg.jinritemai.com', '/ffa/g/create', f'product_id={PID}'),
                       stub=r"""
const YEN = String.fromCharCode(65509);
const skuRows = [
  {innerText: '极氪车门限位器-4个装 ' + YEN + ' 888888 增 减 888888 清空 - 3392818512538149 去关联 已上架'},
];
const stateSpans = [{innerText: '上架'}, {innerText: '下架'}];
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'tr') return skuRows;
    if (sel === 'span') return stateSpans;
    return [];
  },
  body: {innerText: '*商品状态 上架 下架'},
};
"""))

    # ---------- check_session ----------
    # 实测（2026-11-12）：抖店与妙手会话过期后都会落到
    # https://fxg.jinritemai.com/login/common?...，适配器若不先判登录态，
    # 只会在几分钟后报「当前页面不是预期的XX页」，把根因埋掉。
    def check_login(d):
        return (d.get('status') == 'ok'
                and d.get('login_required') is True
                and d.get('login_marker') == '验证码登录'
                and d.get('host') == 'fxg.jinritemai.com')

    results.append(run('check_session',
                       extract(pages.check_session, {}), check_login,
                       page=('fxg.jinritemai.com', '/login/common', 'next=x'),
                       stub=r"""
globalThis.document = {
  querySelectorAll: () => [],
  body: {innerText: '优质流量 自主经营 手机登录 邮箱登录 发送验证码 登录 收不到验证码'},
};
"""))

    def check_alive(d):
        return (d.get('status') == 'ok'
                and d.get('login_required') is False
                and d.get('channel') == 'miaoshou')

    results.append(run('check_session_alive',
                       extract(pages.check_session, {}), check_alive,
                       page=('v2-dd.chengji-inc.com', '/move/move', ''),
                       stub=r"""
globalThis.document = {
  querySelectorAll: () => [],
  body: {innerText: '商品上货 立即上架 放入仓库 放至草稿箱 开始批量抓取商品'},
};
"""))

    print(f'\n{sum(results)}/{len(results)} 段 JS 真跑通过')
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
