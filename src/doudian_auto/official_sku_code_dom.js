((op, p) => {
  // Read only the measured official SKU layout. Scroll changes the view, never a field.
  const text = el => (el?.innerText || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    if (!el || !el.getClientRects().length) return false;
    for (let node = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || node.inert) return false;
    }
    return true;
  };
  const url = new URL(location.href);
  const identity = {product_id: url.searchParams.get('product_id'), page_url: location.href,
    navigation_id: performance.timeOrigin};
  const fail = error => ({...identity, error});
  if (!['read', 'scroll_pending', 'scroll_rows'].includes(op)) return fail('official_sku_code_operation');
  if (url.protocol !== 'https:' || url.hostname !== 'fxg.jinritemai.com' ||
      url.pathname !== '/ffa/g/create' || identity.product_id !== p.product_id)
    return fail('wrong_identity');
  if (p.navigation_id !== null && p.navigation_id !== undefined &&
      identity.navigation_id !== p.navigation_id) return fail('official_sku_code_navigation_changed');
  if ([...document.querySelectorAll('[role="dialog"],iframe')].some(el => visible(el) &&
      /验证码|安全验证|captcha/i.test(text(el) + (el.title || '') + (el.src || ''))))
    return fail('verification_required');
  const shop = typeof p.shop === 'string' && p.shop.trim() &&
    [...document.querySelectorAll('header,nav,aside,span,div')].some(el => visible(el) &&
      el.getBoundingClientRect().top < 300 && !el.children.length && text(el) === p.shop);
  if (!shop) return fail('shop_not_confirmed');
  const roots = [...document.querySelectorAll('[id="goodsEditScrollContainer-价格库存"]')].filter(visible);
  if (roots.length > 1) return fail('official_sku_code_layout_ambiguous');
  if (!roots.length) return {...identity, shop_confirmed: true, ready: false, rows: [], pending_count: 0};
  const root = roots[0];
  const headers = [...root.querySelectorAll('th.attr-column-field_code')].filter(visible);
  if (!headers.length) return {...identity, shop_confirmed: true, ready: false, rows: [], pending_count: 0};
  if (headers.length !== 1 || text(headers[0]) !== '商家编码')
    return fail('official_sku_code_header_ambiguous');
  // The measured page separates its header table from standalone virtual tr nodes.
  //
  // A price/stock section can also hold a second keyed table that is nothing to do with
  // SKUs. Measured on one listing: an 11-row size table (4 tds per row, no SKU or code
  // cell) sits in the same section as the SKU table, and because it is enumerated first
  // every read stopped at `official_sku_code_row_ambiguous`. A row that carries neither a
  // SKU cell nor a code cell cannot be a SKU row, so it is skipped. Placeholder rows are
  // unaffected: they do carry a code cell (empty), which is exactly how they are
  // recognised further down. When nothing qualifies the full set is used, so a page whose
  // rows have not rendered yet keeps reporting the shape it always did.
  const keyedRows = [...root.querySelectorAll('tr[data-row-key]')].filter(visible);
  const withSkuCells = keyedRows.filter(row =>
    row.querySelector('.attr-column-field_sku_id') || row.querySelector('.attr-column-field_code'));
  const nodes = withSkuCells.length ? withSkuCells : keyedRows;
  const rows = [], pending = [], seen = new Set();
  for (const row of nodes) {
    const cells = selector => [...row.querySelectorAll(selector)]
      .filter(el => el.closest('tr[data-row-key]') === row);
    const skuCells = cells('.attr-column-field_sku_id');
    const codeCells = cells('.attr-column-field_code');
    if (skuCells.length !== 1 || codeCells.length !== 1)
      return fail('official_sku_code_row_ambiguous');
    const sku = text(skuCells[0]);
    const inputs = [...codeCells[0].querySelectorAll('input')];
    // A measured placeholder has an empty SKU cell and a genuinely empty code cell.
    // No placeholder, absent input, or hidden input is ever reported as an empty code.
    if (!sku && !inputs.length && !text(codeCells[0]) && !codeCells[0].children.length) {
      pending.push(row);
      continue;
    }
    if (!/^\d{16}$/.test(sku)) return fail('official_sku_code_sku_identity');
    if (seen.has(sku)) return fail('official_sku_code_duplicate_row');
    seen.add(sku);
    if (inputs.length !== 1 || inputs[0].type !== 'text' ||
        inputs[0].getAttribute('placeholder') !== '请输入erp编码' || !visible(inputs[0]))
      return fail('official_sku_code_input_unobserved');
    rows.push({sku_id: sku, code: inputs[0].value, observed: true, input_count: 1});
  }
  // The measured table keeps every row in a virtual holder whose own scrollTop
  // decides which rows are mounted; the surrounding form scroller moves the whole
  // block without changing them. Advance this holder by half a page so consecutive
  // views overlap. Geometry is reported on every op (including `read`) so the Python
  // side can tell "still advancing / dynamically growing" from "genuinely at the end".
  //
  // Order matters. `scroll_pending` used to call `scrollIntoView` on the trailing empty
  // row *before* advancing the holder; that snap undid the advance and fifty-five rounds
  // re-read the same first screenful. Do not wrap back to the top when the holder cannot
  // advance either: measured on a 121-SKU listing the holder grows while lazy rows mount,
  // and an immediate jump to 0 hid the tail placeholder from the pending locator. Stay at
  // the bottom and give the next read a chance to see the mounted row.
  const holder = (withSkuCells.length &&
                  withSkuCells[0].closest('.ecom-g-table-tbody-virtual-holder')) ||
    root.querySelector('.ecom-g-table-tbody-virtual-holder');
  const geometry = holder ? (() => {
    const max = Math.max(0, Math.round(holder.scrollHeight - holder.clientHeight));
    return {scroll_top: Math.round(holder.scrollTop), max,
      scroll_height: Math.round(holder.scrollHeight), client_height: Math.round(holder.clientHeight),
      at_end: holder.scrollTop >= max - 2};
  })() : null;
  let topBefore = geometry ? geometry.scroll_top : null;
  let advancedDown = false;
  let rowScrolled = false;
  if ((op === 'scroll_pending' || op === 'scroll_rows') && holder &&
      geometry.max > 1) {
    holder.scrollTop = holder.scrollTop + Math.max(1, Math.floor(holder.clientHeight / 2));
    rowScrolled = holder.scrollTop !== topBefore;
    advancedDown = holder.scrollTop > topBefore + 1;
    geometry.scroll_top = Math.round(holder.scrollTop);
    geometry.max = Math.max(0, Math.round(holder.scrollHeight - holder.clientHeight));
    geometry.scroll_height = Math.round(holder.scrollHeight);
    geometry.at_end = holder.scrollTop >= geometry.max - 2;
  }
  if (op === 'scroll_pending' && pending.length && !advancedDown) {
    // Holder cannot advance; the placeholder may just be outside the viewport.
    // Locating it is not forward progress -- the geometry above says so honestly.
    pending[pending.length - 1].scrollIntoView({block: 'center'});
  }
  return {...identity, shop_confirmed: true, ready: nodes.length > 0,
    code_column: '商家编码', rows, row_count: nodes.length, pending_count: pending.length,
    geometry, advanced_down: advancedDown,
    scrolled: (op === 'scroll_pending' && pending.length > 0) || rowScrolled};
})
