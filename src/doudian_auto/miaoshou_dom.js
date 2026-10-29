((op, p = {}) => {
  // The list renders cached clones outside the viewport, sometimes at y=-9000.
  // offsetParent alone does not distinguish those from the real action row.
  const visible = el => {
    if (!el || !el.isConnected) return false;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    }
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.right <= 0 ||
        r.top >= innerHeight || r.left >= innerWidth) return false;
    const x = Math.max(0, r.left) + (Math.min(innerWidth, r.right) - Math.max(0, r.left)) / 2;
    const y = Math.max(0, r.top) + (Math.min(innerHeight, r.bottom) - Math.max(0, r.top)) / 2;
    const hit = document.elementFromPoint(x, y);
    return !!hit && (el === hit || el.contains(hit));
  };
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const all = selector => [...document.querySelectorAll(selector)].filter(visible);
  const mark = nodes => {
    if (nodes.length !== 1) return {count: nodes.length};
    nodes[0].setAttribute('data-codex-miao-target', p.marker);
    return {count: 1, selector: `[data-codex-miao-target="${p.marker}"]`};
  };
  const shop = (document.body.innerText || document.body.textContent || '').match(/您好【([^】]+)】/);
  if (p.shop && (!shop || shop[1] !== p.shop)) return {error: 'wrong_shop'};
  if (op === 'search_input') return mark(all('input[name="productId"]'));
  if (op === 'query_button') return mark(all('button.J_filterFormSearch'));
  if (op === 'save_button') return mark(all('button.J_editProductSaveXhsProduct')
    .filter(button => text(button) === '保存到抖店(F)'));
  if (op === 'edit_button') {
    const rows = [...document.querySelectorAll('.pro-table-custom-body-row')]
      .filter(row => (text(row).match(/\d{16,22}/g) || []).includes(String(p.product_id)));
    const buttons = rows.flatMap(row => [...row.querySelectorAll('button')]
      .filter(button => text(button) === '编辑商品' && visible(button)));
    return {...mark(buttons), rows: rows.length};
  }
  if (op === 'dialog') {
    const dialogs = all('.product-edit-dialog');
    // The wrapper itself can contain a scrollable area. Title visibility is checked
    // separately; zero or multiple actionable dialogs are never accepted.
    if (dialogs.length !== 1) return {count: dialogs.length};
    const d = dialogs[0];
    const ids = text(d).match(/(?:ID|商品ID)[：:\s]*(\d{16,22})/g) || [];
    const identity = ids.some(value => value.match(/\d{16,22}/)?.[0] === String(p.product_id));
    const titles = [...d.querySelectorAll('input[name="name"],.el-form-item input.el-input__inner')]
      .filter(input => visible(input) && (input.name === 'name' ||
        input.closest('.el-form-item')?.querySelector('.el-form-item__label')?.textContent.trim() === '商品标题：'));
    return {count: 1, identity, title: titles.length === 1 ? titles[0].value : null};
  }
  return {error: 'unsupported_operation'};
})
