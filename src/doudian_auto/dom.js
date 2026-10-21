((op, p) => {
  const visible = e => !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
  const all = (selector, root = document) => [...root.querySelectorAll(selector)];
  const text = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
  const body = document.body?.innerText || '';
  const url = new URL(location.href);
  const success = body.includes('商品提交成功');
  const identity = {url: location.href, product_id: url.searchParams.get('product_id'), success};
  if (url.hostname !== 'fxg.jinritemai.com') return {...identity, error: 'wrong_host'};
  if (all('[role="dialog"],iframe').some(e => visible(e) && /验证码|安全验证|captcha/i.test(text(e) + (e.title || '') + (e.src || '')))) return {...identity, error: 'verification_required'};
  if (op === 'list') {
    const links = all('a[href*="product_id="]').filter(visible).map(e => ({url: e.href, text: text(e).slice(0,160)}));
    const rows = all('tr,[role="row"]').filter(visible).map(e=>({product_id:text(e).match(/\b\d{16,22}\b/)?.[0], text:text(e).slice(0,1000)})).filter(e=>e.product_id);
    return {...identity, items: links.slice(0, p.limit), rows:rows.slice(0,p.limit), coverage: '当前页面已渲染链接及表格行；不自动翻页、不猜编辑链接'};
  }
  const shopFound = p.shop && all('header,nav,aside,span,div').some(e => visible(e) && e.getBoundingClientRect().top < 300 && e.children.length === 0 && text(e) === p.shop);
  if (op === 'inspect') return {...identity, elements: all(p.selector).filter(visible).slice(0,50).map(e => ({tag:e.tagName, text:text(e).slice(0,1000), value:e.type === 'password' ? '[redacted]' : (e.value ?? null)}))};
  if (success) {
    if (op === 'snapshot') return {...identity, shop_confirmed: !!shopFound};
    return {...identity, error:'success_page'};
  }
  if (!document.querySelector('#pg-title-input')) return {...identity, error:'editor_not_ready'};
  if (p.product_id && identity.product_id !== p.product_id) return {...identity, error:'wrong_product'};
  if (p.shop && !shopFound) return {...identity, error:'shop_not_confirmed'};
  const field = name => {
    const found = all('[attr-field-id]').filter(e => e.getAttribute('attr-field-id') === name && visible(e));
    return found.length === 1 ? found[0] : null;
  };
  const main = field('主图');
  const detail = field('商品详情');
  if (!main || !detail) return {...identity, error:'editor_layout_changed'};
  const target = e => e.id === 'pg-title-input' || main.contains(e) || detail.contains(e);
  const canonical = value => {try {const u = new URL(value); return u.origin + u.pathname;} catch {return value;}};
  const images = root => [...new Set(all('img', root).filter(visible).map(e => e.currentSrc || e.src).filter(s => /^https:\/\//.test(s) && s.includes('ecom-shop-material/') && !/\.svg(?:\?|$)/.test(s)).map(canonical))];
  const deletes = kind => kind === 'mains'
    ? all('.styles-module_hoverBottomWrapper__YPnf1', main).filter(e=>visible(e.parentElement)).map(e => e.children[1]).filter(Boolean)
    : all('i.styles_iconDelete__y_88a', detail).filter(e => visible(e.parentElement));
  if (op === 'snapshot') {
    const sections = all('[id^="goodsEditScrollContainer-"]').filter(visible);
    if (!['基础信息','价格库存','服务与履约'].every(name=>sections.some(e=>e.id.endsWith('-'+name)))) return {...identity,error:'protected_sections_missing'};
    const protectedFields = sections.map(section => ({
      section: section.id,
      inputs: all('input,textarea,select,[role="switch"]', section).filter(e => !target(e) && visible(e) && !['file','button','submit','password'].includes(e.type)).map(e => ({
        type:e.type || e.getAttribute('role') || e.tagName, name:e.name || e.getAttribute('aria-label') || '',
        value:e.value ?? null, checked: ['checkbox','radio'].includes(e.type) ? e.checked : e.getAttribute('aria-checked'), disabled:!!e.disabled
      })),
      selections: all('[role="combobox"],[class*="select-selection-item"],[class*="Select_value"]', section).filter(e=>!target(e) && visible(e)).map(text),
      static_fields: all('[attr-field-id]',section).filter(e=>!target(e) && !e.contains(document.querySelector('#pg-title-input')) && !e.contains(main) && !e.contains(detail) && visible(e) && !e.querySelector('input,textarea,select,[role="switch"],[role="combobox"]')).map(e=>({field:e.getAttribute('attr-field-id'),text:text(e).slice(0,3000)})),
      images: [...new Set(all('img',section).filter(e=>!target(e) && visible(e)).map(e=>e.currentSrc||e.src).filter(s=>s.includes('ecom-shop-material/')).map(canonical))]
    }));
    return {...identity, shop_confirmed:!!shopFound, title:document.querySelector('#pg-title-input').value,
      mains:images(main), details:images(detail), main_delete_count:deletes('mains').length, detail_delete_count:deletes('details').length,
      protected:protectedFields, coverage:'仅DOM实际加载字段；虚拟SKU列表未逐行遍历。程序只写标题、方主图及标准详情。',
      errors:all('[class*="form-item-explain-error"],[role="alert"]').filter(visible).map(text).filter(Boolean).slice(0,20)};
  }
  if (op === 'scroll') { (p.kind === 'mains' ? main : detail).scrollIntoView({block:'center'}); return {ok:true}; }
  if (op === 'delete') {
    const elements = deletes(p.kind);
    if (!elements.length) return {ok:true,empty:true};
    elements[0].click(); return {ok:true};
  }
  if (op === 'upload_selector') {
    const root = p.kind === 'mains' ? main : detail;
    const candidates = all('label',root).filter(e => visible(e) && (p.kind === 'mains' || text(e).includes('上传图片'))).flatMap(e=>all('input[type="file"][multiple]',e));
    const input = candidates.at(-1);
    if (!input) return {error:'upload_input_missing'};
    all('input[data-doudian-auto-input]',root).forEach(e=>e.removeAttribute('data-doudian-auto-input'));
    input.setAttribute('data-doudian-auto-input',p.kind);
    return {selector:`input[data-doudian-auto-input="${p.kind}"]`};
  }
  if (op === 'button') {
    const buttons = all('button,[role="button"],.ecom-g-btn').filter(e=>visible(e) && text(e) === p.name && !e.disabled && e.getAttribute('aria-disabled') !== 'true');
    if (buttons.length !== 1) return {error:'button_not_unique',count:buttons.length};
    buttons[0].click(); return {ok:true};
  }
  return {error:'unknown_operation'};
})
