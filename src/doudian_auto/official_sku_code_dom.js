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
  if (op === 'scroll_pending' && pending.length) {
    pending[pending.length - 1].scrollIntoView({block: 'center'});
  }
  // The measured table keeps every row in a virtual holder whose own scrollTop
  // decides which rows are mounted; the surrounding form scroller moves the whole
  // block without changing them. When no placeholder row is mounted there is
  // nothing to scrollIntoView, so advance this holder instead - by half a page so
  // consecutive views overlap - and wrap to the top once it cannot move further.
  let rowScrolled = false;
  if (op === 'scroll_pending' || op === 'scroll_rows') {
    // Both scrolling steps advance the holder. `scroll_pending` used to rely on
    // `scrollIntoView` alone, which a virtual holder ignores: measured on a 121-SKU
    // listing that keeps a placeholder mounted, thirty seconds of that moved nothing and
    // the read stopped at the ten rows already rendered. Bringing the placeholder into
    // view is still worth doing, so both happen.
    //
    // Prefer the holder the SKU rows actually live in. A section that also carries a size
    // table has its own virtual holder, and taking the first one in DOM order scrolled the
    // wrong table without ever moving the rows being read.
    const holder = (withSkuCells.length &&
                    withSkuCells[0].closest('.ecom-g-table-tbody-virtual-holder')) ||
      root.querySelector('.ecom-g-table-tbody-virtual-holder');
    if (holder && holder.scrollHeight - holder.clientHeight > 1) {
      const top = holder.scrollTop;
      holder.scrollTop = top + Math.max(1, Math.floor(holder.clientHeight / 2));
      rowScrolled = holder.scrollTop !== top;
      if (!rowScrolled) {
        holder.scrollTop = 0;
        rowScrolled = holder.scrollTop !== top;
      }
    }
  }
  return {...identity, shop_confirmed: true, ready: nodes.length > 0,
    code_column: '商家编码', rows, row_count: nodes.length, pending_count: pending.length,
    scrolled: (op === 'scroll_pending' && pending.length > 0) || rowScrolled};
})
