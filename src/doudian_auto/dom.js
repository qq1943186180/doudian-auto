((op, p) => {
  const visible = e => !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
  const all = (selector, root = document) => [...root.querySelectorAll(selector)];
  const text = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
  const body = document.body?.innerText || '';
  const url = new URL(location.href);
  const success = body.includes('商品提交成功');
  // Business state is read before the strict field parsing. A page that is not a plain
  // editable form (success page, rejected draft) must report *why* instead of being
  // collapsed into a generic layout error, and a draft-loaded editor must never be
  // mistaken for the live version during readback.
  const draftLoaded = /当前商品已存草稿|已自动载入最新草稿/.test(body);
  const rejectionMatch = body.match(/(\d+)\s*个驳回问题待处理/);
  const rejected = !!rejectionMatch || /驳回原因/.test(body);
  // Reasons live in unclassed spans, so class-based lookup only ever returned the
  // headline. Anchoring on the descriptive sentence and walking up to its rejection
  // container is the shape that actually holds the text.
  const rejectionReasons = rejected
    ? [...new Set(all('*')
        .filter(e => visible(e) && !e.children.length && e.textContent.trim().length > 20
          && /不符|驳回|违规|不一致/.test(e.textContent))
        .map(e => e.textContent.replace(/\s+/g, ' ').trim())
        .filter(t => t.length < 600))].slice(0, 6)
    : [];
  const errorsSeen = all('[class*="form-item-explain-error"],[role="alert"]').filter(visible).map(text).filter(Boolean).slice(0, 20);
  const business = {draft_loaded: draftLoaded, rejected,
    rejection_count: rejectionMatch ? Number(rejectionMatch[1]) : null,
    rejection_reasons: rejectionReasons};
  const identity = {url: location.href, product_id: url.searchParams.get('product_id'), success, ...business};
  if (url.hostname !== 'fxg.jinritemai.com') return {...identity, error: 'wrong_host'};
  // A dedicated, non-throwing read for the window right after "发布商品" is clicked. The
  // page passes through frames where the editor is gone but the result is not inked yet,
  // so this must classify instead of raising; only this poll is allowed to tolerate them.
  if (op === 'publish_state') {
    if (success) return {...identity, state: 'accepted'};
    if (rejected) return {...identity, state: 'rejected'};
    if (errorsSeen.length) return {...identity, state: 'validation_failed', errors: errorsSeen};
    if (!document.querySelector('#pg-title-input')) return {...identity, state: 'pending'};
    return {...identity, state: 'pending'};
  }
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
  const material = e => {const s = e.currentSrc || e.src; return /^https:\/\//.test(s) && s.includes('ecom-shop-material/') && !/\.svg(?:\?|$)/.test(s);};
  // `complete` alone is also true for a failed load, so require decoded dimensions too.
  const decoded = e => e.complete && e.naturalWidth > 1 && e.naturalHeight > 1;
  // The hidden decorate canvas is a page-load snapshot: measured live, it never syncs
  // with edits (neither delete nor upload re-renders it). It therefore stays a
  // diagnostic counter only and never feeds the authoritative detail read.
  const canvasCount = () => {
    const anchor = document.querySelector('#goods-decorate-wrapper');
    const previews = anchor ? all('[class*="previewContainer"]', anchor) : [];
    if (previews.length !== 1) return null;
    return all('img', previews[0]).filter(e => !e.closest('[class*="style_right__"]') && material(e) && decoded(e)).length;
  };
  // The right-hand phone preview is the only live-synced mirror of the detail field
  // (uploads and deletions appear/disappear immediately, in slot order). Lookup is
  // layered and uniqueness-checked: silently taking the first match could read an
  // unrelated panel after a class rename or layout change.
  const livePanel = () => {
    const panels = all('aside[class*="ecom-g-layout-sider"] [class*="_previewPanel__"]').filter(visible);
    if (panels.length !== 1) return {error: panels.length ? 'live_panel_not_unique' : 'live_panel_missing', panel:null, body:null, list:null};
    const bodies = all('[class*="_previewBodyWrap__"]', panels[0]).filter(visible);
    if (bodies.length !== 1) return {error: bodies.length ? 'live_panel_body_not_unique' : 'live_panel_body_missing', panel:panels[0], body:null, list:null};
    const lists = all('[class*="_detailImgList__"]', bodies[0]).filter(visible);
    if (lists.length > 1) return {error: 'live_list_not_unique', panel:panels[0], body:bodies[0], list:null};
    // A missing list is a genuine empty state, not an error: the panel drops the
    // whole list element once the last detail image is deleted.
    return {error:null, panel:panels[0], body:bodies[0], list:lists[0] || null};
  };
  // On current pages the visible detail strip keeps permanent 1x1 placeholders and the
  // card images render at zero size, so the standard branch stays empty and the live
  // panel is the read source. A future layout with real visible standard images is
  // still supported as long as it forms a complete, count-consistent source.
  const detailImages = () => {
    const declaredMatch = text(detail).match(/商详图片[（(](\d+)\s*\/\s*(\d+)[）)]/);
    const declared = declaredMatch ? Number(declaredMatch[1]) : null;
    const cards = all('[class*="previewInstanceImgSortableItem"]', detail).filter(visible).length;
    const standardSlots = all('img', detail).filter(e => visible(e) && material(e));
    let source = 'standard';
    let slots = standardSlots.length;
    let urls = standardSlots.filter(decoded).map(e => canonical(e.currentSrc || e.src));
    let panelError = null;
    if (!standardSlots.length) {
      const panel = livePanel();
      panelError = panel.error;
      if (panelError) {
        // No trusted live source: report nothing rather than fall back to the stale canvas.
        source = 'unavailable';
        slots = 0;
        urls = [];
      } else {
        source = 'live_panel';
        const listSlots = panel.list ? all('img', panel.list).filter(material) : [];
        slots = listSlots.length;
        urls = listSlots.filter(decoded).map(e => canonical(e.currentSrc || e.src));
      }
    }
    const count = urls.length;
    let status = 'pending';
    let reason = '未识别详情图数据源。';
    if (panelError === 'live_panel_not_unique' || panelError === 'live_panel_body_not_unique' || panelError === 'live_list_not_unique') {
      status = 'ambiguous'; reason = `实时预览面板结构不唯一（${panelError}），已停止。`;
    } else if (panelError) {
      status = 'pending'; reason = '实时预览面板尚未加载。';
    } else if (declared === null) {
      status = 'pending'; reason = '未识别商详图片声明。';
    } else if (declared !== slots || cards !== declared) {
      // Zero values participate in the check: cards=0 with slots>0 is a real conflict.
      status = 'ambiguous'; reason = `商详计数为${declared}张，槽位${slots}个，缩略卡片${cards}个，三者不一致。`;
    } else if (count < slots) {
      status = 'pending'; reason = `已识别${slots}个详情图槽位，仅${count}张完成解码。`;
    } else if (slots === 0) {
      status = 'empty'; reason = '标准区与实时预览均为 0 张详情图。';
    } else if (count > 0) {
      status = 'ready'; reason = '';
    }
    // Order is kept per slot on purpose: a product may legitimately reuse one image.
    return {details: urls, detail_status: status, detail_source: source, detail_declared: declared,
            detail_cards: cards, detail_slots: slots, canvas_count: canvasCount(), detail_reason: reason};
  };
  const deletes = kind => kind === 'mains'
    ? all('.styles-module_hoverBottomWrapper__YPnf1', main).filter(e=>visible(e.parentElement)).map(e => e.children[1]).filter(Boolean)
    : all('i.styles_iconDelete__y_88a', detail).filter(e => visible(e.parentElement));
  if (op === 'snapshot') {
    // Sections are enumerated from the DOM regardless of visibility. The platform hides
    // whole blocks lazily (`style_hidden__*` => visibility:hidden + height 0) and that
    // hidden state tracks *how far the page has been expanded*, not what the fields hold.
    // Filtering them out silently dropped sections between snapshots, so a baseline with
    // 8 blocks compared against a live read with 5 and every index misaligned. Observation
    // state is therefore recorded per section instead of inferred from absence.
    const sections = all('[id^="goodsEditScrollContainer-"]');
    const names = ['基础信息','价格库存','服务与履约'];
    if (!names.every(name=>sections.some(e=>e.id.endsWith('-'+name)))) return {...identity,error:'protected_sections_missing'};
    const protectedFields = sections.map(section => {
      const fields = {
        inputs: all('input,textarea,select,[role="switch"]', section).filter(e => !target(e) && visible(e) && !['file','button','submit','password'].includes(e.type)).map(e => ({
          type:e.type || e.getAttribute('role') || e.tagName, name:e.name || e.getAttribute('aria-label') || '',
          value:e.value ?? null, checked: ['checkbox','radio'].includes(e.type) ? e.checked : e.getAttribute('aria-checked'), disabled:!!e.disabled
        })),
        selections: all('[role="combobox"],[class*="select-selection-item"],[class*="Select_value"]', section).filter(e=>!target(e) && visible(e)).map(text),
        static_fields: all('[attr-field-id]',section).filter(e=>!target(e) && !e.contains(document.querySelector('#pg-title-input')) && !e.contains(main) && !e.contains(detail) && visible(e) && !e.querySelector('input,textarea,select,[role="switch"],[role="combobox"]')).map(e=>({field:e.getAttribute('attr-field-id'),text:text(e).slice(0,3000)})),
        images: [...new Set(all('img',section).filter(e=>!target(e) && visible(e)).map(e=>e.currentSrc||e.src).filter(s=>s.includes('ecom-shop-material/')).map(canonical))]
      };
      // A hidden section reports zero of everything, which is indistinguishable from
      // genuinely empty fields, so the observation state is recorded separately and never
      // inferred from absence. `innerText` of a hidden block is '' because layout never
      // happened, so emptiness is judged from textContent instead. A block qualifies as
      // `empty_block` only on positive evidence that it holds nothing this tool could
      // overwrite: no `[attr-field-id]`, no form control, no material image, and
      // textContent that is either empty or exactly its own heading. Measured after
      // forcing these blocks visible they stay at heading height with zero fields, so
      // they are empty rather than unloaded -- an unloaded block still carries its
      // controls in the DOM.
      const hasFields = !!section.querySelector('[attr-field-id]');
      const hasControl = !!section.querySelector('input,textarea,select,[role="switch"]');
      const hasImage = all('img', section).some(e => material(e));
      const bare = (section.textContent || '').replace(/\s+/g, '');
      const heading = section.querySelector('[class*="style_title"]');
      const headingBare = heading ? (heading.textContent || '').replace(/\s+/g, '') : null;
      const contentless = bare === '' || (headingBare !== null && bare === headingBare);
      const observation = visible(section) ? 'ready'
        : (!hasFields && !hasControl && !hasImage && contentless ? 'empty_block' : 'unobserved');
      return {section: section.id, observation, ...fields};
    });
    return {...identity, shop_confirmed:!!shopFound, title:document.querySelector('#pg-title-input').value,
      mains:images(main), ...detailImages(), main_delete_count:deletes('mains').length, detail_delete_count:deletes('details').length,
      protected:protectedFields, coverage:'仅DOM实际加载字段；虚拟SKU列表未逐行遍历。程序只写标题、方主图及标准详情。',
      errors:errorsSeen};
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
