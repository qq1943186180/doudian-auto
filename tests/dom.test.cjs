const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(path.join(__dirname,'../src/doudian_auto/dom.js'),'utf8');
const pid = '3790019980637110699';
const image = name => `<img src="https://cdn.example/ecom-shop-material/${name}.jpg?resize=600">`;
// A 1x1 placeholder is what the current detail strip actually keeps in the visible cards.
const placeholder = () => `<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" data-nw="1" data-nh="1">`;

// jsdom never loads images, so `complete` and the natural dimensions are simulated
// explicitly. `data-nw`/`data-nh` drive the decoded size; without them the image is
// treated as a fully loaded 1024x1536 picture.
function boot(page) {
  Object.defineProperty(page.window.HTMLElement.prototype,'offsetWidth',{get(){return this.closest('[hidden],[style*="display:none"],[style*="display: none"]') ? 0 : 20;}});
  Object.defineProperty(page.window.HTMLElement.prototype,'innerText',{get(){return this.textContent;}});
  Object.defineProperty(page.window.HTMLImageElement.prototype,'complete',{get(){return this.getAttribute('data-loaded') !== '0';}});
  Object.defineProperty(page.window.HTMLImageElement.prototype,'naturalWidth',{get(){return Number(this.getAttribute('data-nw') || 1024);}});
  Object.defineProperty(page.window.HTMLImageElement.prototype,'naturalHeight',{get(){return Number(this.getAttribute('data-nh') || 1536);}});
  page.window.HTMLElement.prototype.scrollIntoView = function() {};
  page.window.document.querySelectorAll('[data-delete]').forEach(e=>e.addEventListener('click',()=>e.parentElement.parentElement.matches('[attr-field-id]') ? e.parentElement.remove() : e.parentElement.parentElement.remove()));
  const call = (op,p={})=>JSON.parse(JSON.stringify(page.window.eval(script + '('+JSON.stringify(op)+','+JSON.stringify({product_id:pid,shop:'样板店',...p})+')')));
  return {page,call};
}

// Legacy shape: real images sit in the visible detail field.
function fixture() {
  const page = new JSDOM(`<header><span>样板店</span></header>
    <div id="goodsEditScrollContainer-基础信息"><div attr-field-id="标题"><input id="pg-title-input" value="旧标题"></div>
    <div attr-field-id="类目">其他汽车防护用品</div>
    <div attr-field-id="主图">${[1,2,3,4,5].map(i=>`<div>${image('main'+i)}<div class="styles-module_hoverBottomWrapper__YPnf1"><div>编辑</div><div data-delete="main">删除</div></div></div>`).join('')}<label><input type="file" multiple></label><label><input type="file" multiple></label></div></div>
    <div id="goodsEditScrollContainer-图文信息"><div attr-field-id="商品详情">商详图片（2/50）${[1,2].map(i=>`<div class="styles_previewInstanceImgSortableItem__oPvoW">${image('detail'+i)}<i class="styles_iconDelete__y_88a" data-delete="detail"></i></div>`).join('')}<label><input type="file" multiple><div class="ecom-g-btn">上传图片</div></label></div></div>
    <div id="goodsEditScrollContainer-价格库存"><input name="price" value="20.88"><input type="checkbox" checked>${image('sku')}</div>
    <div id="goodsEditScrollContainer-服务与履约"><select><option selected>48小时</option></select></div>
    <button id="publish">发布商品</button><button>填写检查</button>`,{url:`https://fxg.jinritemai.com/ffa/g/create?product_id=${pid}`,runScripts:'outside-only'});
  return boot(page);
}

// Current real page shape: the visible strip keeps permanent 1x1 placeholders, the
// hidden decorate canvas is a page-load snapshot that never syncs with edits, and the
// right-hand phone preview panel is the only live-synced mirror of the detail field.
// Canvas URLs use the /obj/ prefix, panel URLs the /img/ prefix plus a rendition
// suffix, exactly as observed on the live page.
function realistic({declared = '商详图片（2/50）', cards = 2, canvas = true, rightPanel = true, extraCanvasImages = false,
                    panel = true, list = true, panelImages = ['detail1','detail2'], extraPanelImages = false,
                    duplicatePanels = false} = {}) {
  const canvasImages = ['detail1','detail2'].concat(extraCanvasImages ? ['detail2'] : []);
  const listImages = panelImages.concat(extraPanelImages ? ['detail2'] : []);
  const panelList = list ? `<div class="styles_detailImgList__g8P0J">${listImages.map(n=>`<div><img src="https://cdn.example/img/ecom-shop-material/${n}.jpg~750x0_q90_b0.jpg"></div>`).join('')}</div>` : '';
  const onePanel = `<aside class="ecom-g-layout-sider"><div class="styles_previewPanel__ilAnO"><div class="styles_previewPanelBody__dpOu6"><div class="styles_scrollBody__KKYBa"><div class="styles_previewBodyWrap__pcVBF">${panelList}</div></div></div></div></aside>`;
  const page = new JSDOM(`<header><span>样板店</span></header>
    <div id="goodsEditScrollContainer-基础信息"><div attr-field-id="标题"><input id="pg-title-input" value="旧标题"></div>
    <div attr-field-id="类目">其他汽车防护用品</div>
    <div attr-field-id="主图">${[1,2,3,4,5].map(i=>`<div>${image('main'+i)}<div class="styles-module_hoverBottomWrapper__YPnf1"><div>编辑</div><div data-delete="main">删除</div></div></div>`).join('')}<label><input type="file" multiple></label><label><input type="file" multiple></label></div></div>
    <div id="goodsEditScrollContainer-图文信息"><div attr-field-id="商品详情">${declared}
      ${Array.from({length:cards},()=>`<div class="styles_previewInstanceImgSortableItem__oPvoW">${placeholder()}<i class="styles_iconDelete__y_88a" data-delete="detail"></i></div>`).join('')}
      <label><input type="file" multiple><div class="ecom-g-btn">上传图片</div></label>
      ${canvas ? `<div id="goods-decorate-wrapper" class="style_decorateWrapper__YYKiB" hidden>
        <div class="style_previewContainer__aWqx7">${canvasImages.map(n=>`<div><img src="https://cdn.example/obj/ecom-shop-material/${n}.jpg?resize=600"></div>`).join('')}</div>
        ${rightPanel ? `<div class="style_right__zErlp">${canvasImages.map(n=>`<div><img src="https://cdn.example/obj/ecom-shop-material/${n}.jpg?resize=600"></div>`).join('')}</div>` : ''}
      </div>` : ''}
    </div></div>
    <div id="goodsEditScrollContainer-价格库存"><input name="price" value="20.88"><input type="checkbox" checked>${image('sku')}</div>
    <div id="goodsEditScrollContainer-服务与履约"><select><option selected>48小时</option></select></div>
    <button id="publish">发布商品</button><button>填写检查</button>
    ${panel ? onePanel + (duplicatePanels ? onePanel : '') + '<aside class="ecom-g-layout-sider"><div class="styles_otherSider__abc">sibling</div></aside>' : ''}`,{url:`https://fxg.jinritemai.com/ffa/g/create?product_id=${pid}`,runScripts:'outside-only'});
  return boot(page);
}

test('reads canonical ordered URLs, inputs and checkbox without coupling to title/images',()=>{
  const {page,call} = fixture();
  const before = call('snapshot');
  assert.equal(before.mains.length,5);
  assert.equal(before.details.length,2);
  assert.equal(before.detail_status,'ready');
  assert.equal(before.detail_source,'standard');
  assert.equal(before.main_delete_count,5);
  assert.equal(before.detail_delete_count,2);
  assert.equal(before.mains[0],'https://cdn.example/ecom-shop-material/main1.jpg');
  page.window.document.querySelector('#pg-title-input').value = '新标题';
  call('delete',{kind:'mains'});
  const after = call('snapshot');
  assert.equal(after.mains.length,4);
  assert.deepEqual(after.protected,before.protected);
  const checkbox = after.protected.flatMap(s=>s.inputs).find(e=>e.type==='checkbox');
  assert.equal(checkbox.checked,true);
  page.window.close();
});

test('SKU display mirrors share one material identity across CDN hosts and renditions',()=>{
  const {page,call}=fixture();
  const price=page.window.document.getElementById('goodsEditScrollContainer-价格库存');
  price.insertAdjacentHTML('beforeend','<img src="https://another.example/obj/ecom-shop-material/sku.jpg~tplv-crop.image">');
  let fields=call('snapshot').protected.find(x=>x.section.endsWith('-价格库存'));
  assert.equal(fields.images.length,1);
  price.insertAdjacentHTML('beforeend','<img src="https://another.example/obj/ecom-shop-material/changed-sku.jpg">');
  fields=call('snapshot').protected.find(x=>x.section.endsWith('-价格库存'));
  assert.equal(fields.images.length,2);page.window.close();
});
test('wrong product and shop fail before any mutation',()=>{
  const {page,call} = fixture();
  assert.equal(call('delete',{kind:'mains',product_id:'3793430313384935495'}).error,'wrong_product');
  assert.equal(call('delete',{kind:'mains',shop:'另一家店'}).error,'shop_not_confirmed');
  assert.equal(call('snapshot').mains.length,5);
  page.window.close();
});
test('selects final multiple input and deletes only intended image',()=>{
  const {page,call} = fixture();
  const selector = call('upload_selector',{kind:'mains'}).selector;
  const mains = page.window.document.querySelector('[attr-field-id="主图"]');
  assert.equal(mains.querySelectorAll('input[type=file]')[1],page.window.document.querySelector(selector));
  call('delete',{kind:'details'});
  assert.equal(call('snapshot').detail_delete_count,1);
  assert.equal(call('snapshot').mains.length,5);
  page.window.close();
});
test('only exact unique publish button can be clicked',()=>{
  const {page,call} = fixture();
  let clicks = 0;
  page.window.document.querySelector('#publish').addEventListener('click',()=>clicks++);
  assert.equal(call('button',{name:'发布商品'}).ok,true);
  assert.equal(clicks,1);
  page.window.document.body.insertAdjacentHTML('beforeend','<button>发布商品</button>');
  assert.equal(call('button',{name:'发布商品'}).error,'button_not_unique');
  assert.equal(clicks,1);
  page.window.close();
});
test('hidden advanced editor is excluded and old upload markers are cleared',()=>{
  const {page,call} = fixture();
  const detail = page.window.document.querySelector('[attr-field-id="商品详情"]');
  detail.insertAdjacentHTML('beforeend',`<div hidden>${image('advanced')}<i class="styles_iconDelete__y_88a"></i><label><input type="file" multiple>上传图片</label></div>`);
  assert.equal(call('snapshot').details.length,2);
  assert.equal(call('snapshot').detail_delete_count,2);
  const mains = page.window.document.querySelector('[attr-field-id="主图"]');
  mains.querySelector('input').setAttribute('data-doudian-auto-input','mains');
  const selector = call('upload_selector',{kind:'mains'}).selector;
  assert.equal(page.window.document.querySelectorAll(selector).length,1);
  assert.equal(page.window.document.querySelector(selector),mains.querySelectorAll('input')[1]);
  const detailSelector = call('upload_selector',{kind:'details'}).selector;
  assert.equal(page.window.document.querySelector(detailSelector).closest('[hidden]'),null);
  page.window.close();
});
test('reads ordered detail slots from the live preview panel when the visible strip only has placeholders',()=>{
  const {page,call} = realistic();
  const snapshot = call('snapshot');
  assert.deepEqual(snapshot.details,['https://cdn.example/img/ecom-shop-material/detail1.jpg~750x0_q90_b0.jpg','https://cdn.example/img/ecom-shop-material/detail2.jpg~750x0_q90_b0.jpg']);
  assert.equal(snapshot.detail_status,'ready');
  assert.equal(snapshot.detail_source,'live_panel');
  assert.equal(snapshot.detail_declared,2);
  assert.equal(snapshot.detail_cards,2);
  assert.equal(snapshot.detail_slots,2);
  // The stale decorate canvas is kept as a diagnostic counter only.
  assert.equal(snapshot.canvas_count,2);
  page.window.close();
});
test('the live preview panel wins over a stale hidden canvas with different images',()=>{
  // Editing session reality: the canvas still shows the pre-edit images while the
  // panel already mirrors the freshly uploaded ones.
  const {page,call} = realistic({panelImages:['fresh1','fresh2']});
  const snapshot = call('snapshot');
  assert.deepEqual(snapshot.details,['https://cdn.example/img/ecom-shop-material/fresh1.jpg~750x0_q90_b0.jpg','https://cdn.example/img/ecom-shop-material/fresh2.jpg~750x0_q90_b0.jpg']);
  assert.equal(snapshot.detail_status,'ready');
  assert.equal(snapshot.canvas_count,2);
  page.window.close();
});
test('right-hand component editor copies are never counted as detail slots',()=>{
  const {page,call} = realistic();
  // Two canvas slots plus two right-panel mirrors: only the two ordered panel slots may be read.
  assert.equal(call('snapshot').details.length,2);
  page.window.close();
});
test('a legitimate repeated image keeps its own slot instead of being de-duplicated',()=>{
  const {page,call} = realistic({declared:'商详图片（3/50）',cards:3,extraPanelImages:true});
  assert.equal(call('snapshot').details.length,3);
  assert.equal(call('snapshot').details[1],call('snapshot').details[2]);
  page.window.close();
});
test('a missing live panel reports pending instead of an empty confirmed detail list',()=>{
  const {page,call} = realistic({panel:false});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'pending');
  assert.equal(snapshot.details.length,0);
  assert.match(snapshot.detail_reason,/尚未加载/);
  page.window.close();
});
test('a genuine empty detail reports empty and stays distinguishable from pending',()=>{
  // Three-zero standard area, live panel present without a list, stale canvas still there.
  const {page,call} = realistic({declared:'商详图片（0/50）',cards:0,list:false});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'empty');
  assert.equal(snapshot.details.length,0);
  assert.equal(snapshot.detail_slots,0);
  assert.equal(snapshot.canvas_count,2);
  page.window.close();
});
test('conflicting counts report ambiguous rather than silently trusting one source',()=>{
  const {page,call} = realistic({declared:'商详图片（5/50）'});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'ambiguous');
  assert.match(snapshot.detail_reason,/不一致/);
  page.window.close();
});
test('zero cards with loaded slots report ambiguous instead of ready',()=>{
  // Regression: the old `count && cards && cards !== count` check skipped cards=0.
  const {page,call} = realistic({cards:0});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'ambiguous');
  assert.match(snapshot.detail_reason,/不一致/);
  page.window.close();
});
test('a missing declaration keeps the detail source not ready',()=>{
  const {page,call} = realistic({declared:''});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'pending');
  assert.equal(snapshot.detail_declared,null);
  page.window.close();
});
test('an ambiguous live panel structure reports ambiguous instead of guessing',()=>{
  const {page,call} = realistic({duplicatePanels:true});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'ambiguous');
  assert.match(snapshot.detail_reason,/不唯一/);
  page.window.close();
});
test('an image that failed to decode is not treated as loaded',()=>{
  const {page,call} = realistic();
  page.window.document.querySelectorAll('[class*="detailImgList"] img').forEach(e=>e.setAttribute('data-nw','0'));
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'pending');
  assert.equal(snapshot.detail_slots,2);
  assert.equal(snapshot.details.length,0);
  page.window.close();
});

test('preserves an intentionally stored decoded 1x1 tail image in exact slot order',()=>{
  const {page,call}=fixture();
  const last=page.window.document.querySelectorAll('[attr-field-id="商品详情"] img')[1];
  last.src='https://p3-aio.ecombdimg.com/ecom-shop-material/jpeg_m_blank_sx_690_www1-1~tplv-fxg.image';
  last.setAttribute('data-nw','1');last.setAttribute('data-nh','1');
  const actual=call('snapshot');
  assert.equal(actual.detail_status,'ready');assert.equal(actual.details.length,2);
  assert.equal(actual.details[1],last.src);
  last.setAttribute('data-nw','0');assert.equal(call('snapshot').detail_status,'pending');
  page.window.close();
});

test('a one-pixel placeholder for a larger material remains pending',()=>{
  const {page,call}=fixture();
  const last=page.window.document.querySelectorAll('[attr-field-id="商品详情"] img')[1];
  last.src='https://p3-aio.ecombdimg.com/ecom-shop-material/jpeg_m_pending_sx_690_www800-1200';
  last.setAttribute('data-nw','1');last.setAttribute('data-nh','1');
  assert.equal(call('snapshot').detail_status,'pending');
  assert.equal(call('snapshot').details.length,1);page.window.close();
});

// --- protected section observation state ------------------------------------
// The platform hides whole blocks with `visibility:hidden` + height 0. That state tracks
// how far the page has been expanded, so the visible block set differs between reads and
// positional comparison misaligns. Each block therefore reports its own observation state.

// jsdom computes no layout, so visibility and offsetHeight are simulated per block.
function blocks(page, specs) {
  const doc = page.window.document;
  for (const [name, spec] of Object.entries(specs)) {
    const section = doc.createElement('div');
    section.id = 'goodsEditScrollContainer-' + name;
    section.innerHTML = spec.html || '';
    if (spec.hidden) {
      section.style.visibility = 'hidden';
      // boot() reads offsetWidth only, so height 0 is expressed through the same hook.
      Object.defineProperty(section, 'offsetWidth', {get(){ return 0; }});
    }
    doc.body.appendChild(section);
  }
}

test('a hidden block with no fields reports empty_block, not ready',()=>{
  const {page,call} = realistic();
  blocks(page, {
    '权益': {hidden:true, html:'<div class="style_title__NHRpS"><div>权益</div></div><div></div>'},
    '尺码表': {hidden:true, html:'<div></div>'},
  });
  const snapshot = call('snapshot');
  const byName = Object.fromEntries(snapshot.protected.map(s=>[s.section.replace('goodsEditScrollContainer-',''), s.observation]));
  assert.equal(byName['权益'],'empty_block');
  assert.equal(byName['尺码表'],'empty_block');
  assert.equal(byName['基础信息'],'ready');
  page.window.close();
});

test('a hidden block that still carries fields is unobserved, never empty_block',()=>{
  const {page,call} = realistic();
  blocks(page, {
    // Fields exist but rendering was skipped: there is data here, so it must not be exempt.
    '尺码信息': {hidden:true, html:'<div class="style_title__NHRpS"><div>尺码信息</div></div><div attr-field-id="尺码表"><input value="L"></div>'},
  });
  const snapshot = call('snapshot');
  const section = snapshot.protected.find(s=>s.section.endsWith('-尺码信息'));
  assert.equal(section.observation,'unobserved');
  page.window.close();
});

test('every protected block is enumerated even when hidden',()=>{
  const {page,call} = realistic();
  blocks(page, {
    '权益': {hidden:true, html:'<div class="style_title__NHRpS"><div>权益</div></div><div></div>'},
    '尺码表': {hidden:true, html:'<div></div>'},
    '尺码信息': {hidden:true, html:'<div class="style_title__NHRpS"><div>尺码信息</div></div><div></div>'},
  });
  const snapshot = call('snapshot');
  const names = snapshot.protected.map(s=>s.section.replace('goodsEditScrollContainer-',''));
  // Document order is preserved, so the hidden tail follows the four rendered blocks.
  assert.deepEqual(names, ['基础信息','图文信息','价格库存','服务与履约','权益','尺码表','尺码信息']);
  page.window.close();
});

test('a populated size table is read once beside its positively empty hideModule placeholder',()=>{
  const {page,call} = realistic();
  blocks(page, {'尺码表': {html:'<div attr-field-id="尺码信息"><input value="155/70(M)"></div>'}});
  const empty = page.window.document.createElement('div');
  empty.id = 'goodsEditScrollContainer-尺码表';
  empty.className = 'style_formBlockNewUI__x style_hideModule__x';
  empty.innerHTML = '<div></div>';
  page.window.document.body.appendChild(empty);
  const sections = call('snapshot').protected.filter(s=>s.section.endsWith('-尺码表'));
  assert.equal(sections.length,1);
  assert.equal(sections[0].inputs[0].value,'155/70(M)');
  empty.innerHTML = '<input value="XL">';
  assert.equal(call('snapshot').protected.filter(s=>s.section.endsWith('-尺码表')).length,2);
  page.window.close();
});

// --- publish outcome classification -----------------------------------------
// The window right after "发布商品" is clicked passes through frames where the editor is
// gone but the outcome is not rendered yet. `publish_state` must classify those frames
// instead of raising, because an exception would abort the poll before its predicate runs
// -- which is how a real successful submit was mistaken for a stall.

function publishPage(bodyHtml, {titleInput = true} = {}) {
  const page = new JSDOM(`<header><span>样板店</span></header>
    ${titleInput ? '<input id="pg-title-input" value="标题">' : ''}
    <div class="page-body">${bodyHtml}</div>`, {url:`https://fxg.jinritemai.com/ffa/g/create?product_id=${pid}`, runScripts:'outside-only'});
  const booted = boot(page);
  return booted;
}

test('a success page is classified as accepted',()=>{
  const {page,call} = publishPage('<div>商品提交成功，变更商品信息需审核通过后生效</div>', {titleInput:false});
  const result = call('publish_state');
  assert.equal(result.state,'accepted');
  assert.equal(result.success,true);
  page.window.close();
});

test('a rejected page is classified as rejected with its reasons',()=>{
  const {page,call} = publishPage(`<div>1个驳回问题待处理</div>
    <div class="rejectReason">您选择的商品类目与商品实际类目不符</div>`);
  const result = call('publish_state');
  assert.equal(result.state,'rejected');
  assert.equal(result.rejected,true);
  assert.equal(result.rejection_count,1);
  page.window.close();
});

test('a frame with no title input and no outcome is pending, not an error',()=>{
  // This is the transition frame that previously raised editor_not_ready and aborted the
  // publish poll before the success text had a chance to render.
  const {page,call} = publishPage('<div>处理中</div>', {titleInput:false});
  const result = call('publish_state');
  assert.equal(result.state,'pending');
  assert.equal(result.error,undefined);
  page.window.close();
});

test('a page with validation errors is classified as validation_failed',()=>{
  const {page,call} = publishPage('<div class="form-item-explain-error">该项为必填项，请上传图片</div>');
  const result = call('publish_state');
  assert.equal(result.state,'validation_failed');
  page.window.close();
});

test('the draft banner is reported so a draft readback is never taken for the live listing',()=>{
  const {page,call} = publishPage('<div>当前商品已存草稿，本次编辑已自动载入最新草稿信息</div>');
  const result = call('publish_state');
  assert.equal(result.draft_loaded,true);
  page.window.close();
});
