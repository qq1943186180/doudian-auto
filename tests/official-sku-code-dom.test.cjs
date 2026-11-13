const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(path.join(__dirname, '../src/doudian_auto/official_sku_code_dom.js'), 'utf8');
const pid = '3790019980637110699';
const sku1 = '3387918799208229', sku2 = '3387918799208230';

function fixture() {
  const page = new JSDOM('<header><span>样板店</span></header>' +
    '<div id="goodsEditScrollContainer-价格库存"><table><thead><tr>' +
    '<th class="attr-column-field_code">商家编码</th></tr></thead></table></div>', {
    url: `https://fxg.jinritemai.com/ffa/g/create?product_id=${pid}`, runScripts: 'outside-only'});
  const {window} = page, doc = window.document;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', {get() { return this.textContent; }});
  window.HTMLElement.prototype.getClientRects = function() {
    return this.closest('[hidden],[style*="display:none"],[style*="display: none"]') ? [] : [{}];
  };
  window.HTMLElement.prototype.getBoundingClientRect = () => ({top: 10, width: 100, height: 20});
  const scrolled = [];
  window.HTMLElement.prototype.scrollIntoView = function(options) {
    scrolled.push({row: this.dataset.rowKey, options: JSON.parse(JSON.stringify(options))});
  };
  const root = doc.getElementById('goodsEditScrollContainer-价格库存');
  function row(sku, code = '') {
    // Append standalone tr via the DOM; HTML parsing a tr inside a div strips the tag.
    const tr = doc.createElement('tr');
    tr.dataset.rowKey = sku || 'placeholder-' + root.querySelectorAll('tr[data-row-key]').length;
    const id = doc.createElement('td'), cell = doc.createElement('td');
    id.className = 'attr-column-field_sku_id'; id.textContent = sku;
    cell.className = 'attr-column-field_code';
    if (sku) {
      const input = doc.createElement('input');
      input.type = 'text'; input.placeholder = '请输入erp编码'; input.value = code;
      cell.append(input);
    }
    tr.append(id, cell); root.append(tr);
    return tr;
  }
  const call = (op = 'read', args = {}) => JSON.parse(JSON.stringify(window.eval(script + '(' +
    JSON.stringify(op) + ',' + JSON.stringify({product_id: pid, shop: '样板店', navigation_id: null, ...args}) + ')')));
  function holder(scrollHeight, clientHeight, top = 0) {
    // jsdom reports zero for scroll metrics, so model the measured virtual holder
    // explicitly, including the clamp a real element applies at either end.
    const el = doc.createElement('div');
    el.className = 'ecom-g-table-tbody-virtual-holder';
    let value = top;
    Object.defineProperty(el, 'scrollHeight', {get: () => scrollHeight});
    Object.defineProperty(el, 'clientHeight', {get: () => clientHeight});
    Object.defineProperty(el, 'scrollTop', {
      get: () => value,
      set: (next) => { value = Math.max(0, Math.min(next, scrollHeight - clientHeight)); },
    });
    root.append(el);
    return el;
  }
  return {page, doc, root, row, call, scrolled, holder};
}

test('reads actual empty and nonempty codes from standalone rows and leaves input values unchanged', () => {
  const f = fixture(); f.row(sku1, ''); f.row(sku2, 'ERP-2');
  const before = f.root.innerHTML;
  const result = f.call();
  assert.deepEqual(result.rows, [
    {sku_id: sku1, code: '', observed: true, input_count: 1},
    {sku_id: sku2, code: 'ERP-2', observed: true, input_count: 1}]);
  assert.equal(result.pending_count, 0);
  assert.equal(result.shop_confirmed, true);
  assert.equal(f.root.innerHTML, before);
  assert.deepEqual(f.scrolled, []);
});

test('an empty skeleton never becomes an empty code and only the last skeleton is scrolled', () => {
  const f = fixture(); f.row(sku1); f.row(''); const last = f.row('');
  const result = f.call('scroll_pending');
  assert.deepEqual(result.rows.map(row => row.sku_id), [sku1]);
  assert.equal(result.pending_count, 2);
  assert.deepEqual(f.scrolled, [{row: last.dataset.rowKey, options: {block: 'center'}}]);
});

test('a pending row that finishes before scrolling returns its observed value without guessing a scroll target', () => {
  const f = fixture(); f.row(sku1);
  assert.equal(f.call('scroll_pending').scrolled, false);
  assert.deepEqual(f.scrolled, []);
});

test('scroll_rows advances the measured virtual holder by half a page, without touching a row', () => {
  const f = fixture(); f.row(sku1, 'ERP-1');
  const holder = f.holder(2707, 523, 0);
  const result = f.call('scroll_rows');
  assert.equal(result.scrolled, true);
  assert.equal(result.pending_count, 0);
  assert.deepEqual(result.rows, [{sku_id: sku1, code: 'ERP-1', observed: true, input_count: 1}]);
  assert.equal(holder.scrollTop, 261);
  // The row scroll and the placeholder scroll are different mechanisms: only the
  // holder may move here, and no row may be scrolled into view.
  assert.deepEqual(f.scrolled, []);
});

test('scroll_rows wraps to the top once the virtual holder is already at its end', () => {
  const f = fixture(); f.row(sku1);
  const holder = f.holder(2707, 523, 2184);
  const result = f.call('scroll_rows');
  assert.equal(result.scrolled, true);
  assert.equal(holder.scrollTop, 0);
});

test('scroll_rows on a layout with no virtual holder reports no scroll and keeps the read', () => {
  const f = fixture(); f.row(sku1, 'ERP-1');
  const result = f.call('scroll_rows');
  assert.equal(result.scrolled, false);
  assert.equal(result.error, undefined);
  assert.deepEqual(result.rows.map((row) => row.sku_id), [sku1]);
  assert.deepEqual(f.scrolled, []);
});

for (const kind of ['absent', 'hidden', 'duplicate', 'wrong_type', 'wrong_placeholder']) {
  test(`rejects ${kind} code input instead of claiming an empty value`, () => {
    const f = fixture(), row = f.row(sku1), input = row.querySelector('input');
    if (kind === 'absent') input.remove();
    if (kind === 'hidden') input.hidden = true;
    if (kind === 'duplicate') input.parentElement.append(input.cloneNode());
    if (kind === 'wrong_type') input.type = 'search';
    if (kind === 'wrong_placeholder') input.placeholder = '请输入其他编码';
    assert.equal(f.call().error, 'official_sku_code_input_unobserved');
  });
}

test('rejects duplicate SKU rows even when their values match', () => {
  const f = fixture(); f.row(sku1); f.row(sku1);
  assert.equal(f.call().error, 'official_sku_code_duplicate_row');
});

test('requires the measured unique header and both unique row cells', () => {
  const f = fixture(); const row = f.row(sku1);
  row.querySelector('.attr-column-field_sku_id').remove();
  assert.equal(f.call().error, 'official_sku_code_row_ambiguous');
  const g = fixture(); g.row(sku1);
  g.root.querySelector('th').textContent = '另一编码';
  assert.equal(g.call().error, 'official_sku_code_header_ambiguous');
});

test('rejects changed product, shop, page navigation, and verification takeover', () => {
  const f = fixture(); f.row(sku1);
  assert.equal(f.call('read', {product_id: '3790019980637110698'}).error, 'wrong_identity');
  assert.equal(f.call('read', {shop: '另一家店'}).error, 'shop_not_confirmed');
  assert.equal(f.call('read', {navigation_id: f.page.window.performance.timeOrigin + 1}).error,
    'official_sku_code_navigation_changed');
  f.doc.body.insertAdjacentHTML('beforeend', '<div role="dialog">安全验证</div>');
  assert.equal(f.call().error, 'verification_required');
});

test('wrong host and route cannot provide official SKU evidence', () => {
  const f = fixture(); f.row(sku1);
  f.page.reconfigure({url: `https://other.example/ffa/g/create?product_id=${pid}`});
  assert.equal(f.call().error, 'wrong_identity');
  f.page.reconfigure({url: `https://fxg.jinritemai.com/other?product_id=${pid}`});
  assert.equal(f.call().error, 'wrong_identity');
});
