"""Execute the adapter's generated JavaScript under Node with a stub DOM.

The Python tests use a FakeBridge, so they can pass while the embedded JS is broken:
a regex written as \\\\s in a Python triple-quoted string lands as two backslashes and
matches a literal backslash followed by 's' instead of whitespace. Nothing in-process
would catch that. This runs the real code path in Node against a stub page.

Run: python work/optimizer-20261111/verify-adapter-js.py
"""

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))

from doudian_auto.dropship_pages import DropshipPages, _js  # noqa: E402

PID = '3853454064050373417'

STUB_DOM = r"""
const YEN = String.fromCharCode(65509);
const makeInput = v => ({value: v, getAttribute: () => '请输入'});
const skuRows = [
  {innerText: '极氪车门限位器-4个装 ' + YEN + ' 888888 增 减 888888 清空 - 3392818512538149 去关联 已上架',
   querySelectorAll: () => [makeInput('27.48')]},
  {innerText: '极氪车门限位器-1个装 ' + YEN + ' 888888 增 减 888888 清空 - 3392818512538405 去关联 已上架',
   querySelectorAll: () => [makeInput('15.48')]},
];
const historyRows = [
  {innerText: '阿里巴巴utookii行李箱轮子保护套 1688分销 源ID： 872099955768 商品ID： 3850072322857894188'},
  {innerText: '阿里巴巴适用极氪001/007车门限位器 1688分销 源ID： 965251097615 商品ID： ' + '3853454064050373417'},
];
globalThis.document = {
  querySelectorAll: sel => {
    if (sel === 'tr') return skuRows.concat(historyRows);
    return [];
  },
  body: {innerText: ''},
};
globalThis.location = {
  href: 'https://fxg.jinritemai.com/ffa/g/create?product_id=__PID__',
  hostname: 'fxg.jinritemai.com', pathname: '/ffa/g/create',
  searchParams: new URLSearchParams('product_id=__PID__'),
};
// 每个 case 可覆盖 location 来伪装所在页面
globalThis.setPage = (host, path, query) => {
  const q = new URLSearchParams(query);
  globalThis.location = {href: 'https://' + host + path + '?' + query,
                         hostname: host, pathname: path, searchParams: q};
};
globalThis.URL = URL;
"""


def extract(method, payload):
    src = inspect.getsource(method)
    body = re.search(r'code = """(.*?)"""', src, re.S).group(1)
    return body.replace('__PAYLOAD__', _js(payload))


def run(label, js, expect, page=None):
    # 适配器是一段 IIFE，Node 不会打印它的返回值；接到全局再输出才能断言
    js = js.replace('(()=>{', 'globalThis.__r=(()=>{', 1)
    js += '\nconsole.log(JSON.stringify(globalThis.__r));\n'
    prefix = ''
    if page:
        prefix = f'setPage({page[0]!r}, {page[1]!r}, {page[2]!r});\n'
    path = Path(__file__).with_name(f'_js_{label}.js')
    path.write_text(STUB_DOM.replace('__PID__', PID) + '\n' + prefix + js + '\n',
                    encoding='utf-8')
    proc = subprocess.run(['node', str(path)], capture_output=True, text=True, timeout=30)
    path.unlink(missing_ok=True)
    out = (proc.stdout or '').strip()
    if proc.returncode != 0:
        print(f'[FAIL] {label}: node 执行报错\n{proc.stderr.strip()[:300]}')
        return False
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        print(f'[FAIL] {label}: 输出不是 JSON -> {out[:200]}')
        return False
    ok = expect(data)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {json.dumps(data, ensure_ascii=False)[:220]}")
    return ok


def main():
    pages = DropshipPages(None)
    results = []

    def check_sku(d):
        rows = d.get('sku_rows') or []
        return (d.get('status') == 'ok' and len(rows) == 2
                and rows[0]['price'] == '27.48' and rows[1]['price'] == '15.48'
                and rows[0]['sku'].startswith('极氪车门限位器-4个装')
                and d.get('sku_total_count') is None)

    results.append(run('read_sku_prices',
                       extract(pages.read_sku_prices, {'product_id': PID}), check_sku))

    def check_history(d):
        return d.get('status') == 'ok' and d.get('product_id') == PID

    results.append(run('read_history_product_id',
                       extract(pages.read_history_product_id,
                               {'source_product_id': '965251097615'}), check_history,
                       page=('v2-dd.chengji-inc.com', '/move/move_history', '')))

    print(f'\n{sum(results)}/{len(results)} 段 JS 真跑通过')
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
