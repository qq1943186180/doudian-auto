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

// Current real page shape: the visible strip keeps permanent 1x1 placeholders and the only
// loaded images live in the hidden decorate wrapper, mirrored by the right-hand editor.
function realistic({canvas = true, declared = '商详图片（2/50）', cards = 2, rightPanel = true, extraCanvasImages = false} = {}) {
  const canvasImages = ['detail1','detail2'].concat(extraCanvasImages ? ['detail2'] : []);
  const page = new JSDOM(`<header><span>样板店</span></header>
    <div id="goodsEditScrollContainer-基础信息"><div attr-field-id="标题"><input id="pg-title-input" value="旧标题"></div>
    <div attr-field-id="类目">其他汽车防护用品</div>
    <div attr-field-id="主图">${[1,2,3,4,5].map(i=>`<div>${image('main'+i)}<div class="styles-module_hoverBottomWrapper__YPnf1"><div>编辑</div><div data-delete="main">删除</div></div></div>`).join('')}<label><input type="file" multiple></label><label><input type="file" multiple></label></div></div>
    <div id="goodsEditScrollContainer-图文信息"><div attr-field-id="商品详情">${declared}
      ${Array.from({length:cards},()=>`<div class="styles_previewInstanceImgSortableItem__oPvoW">${placeholder()}<i class="styles_iconDelete__y_88a" data-delete="detail"></i></div>`).join('')}
      <label><input type="file" multiple><div class="ecom-g-btn">上传图片</div></label>
      ${canvas ? `<div id="goods-decorate-wrapper" class="style_decorateWrapper__YYKiB" hidden>
        <div class="style_previewContainer__aWqx7">${canvasImages.map(n=>`<div><img src="https://cdn.example/ecom-shop-material/${n}.jpg?resize=600"></div>`).join('')}</div>
        ${rightPanel ? `<div class="style_right__zErlp">${canvasImages.map(n=>`<div><img src="https://cdn.example/ecom-shop-material/${n}.jpg?resize=600"></div>`).join('')}</div>` : ''}
      </div>` : ''}
    </div></div>
    <div id="goodsEditScrollContainer-价格库存"><input name="price" value="20.88"><input type="checkbox" checked>${image('sku')}</div>
    <div id="goodsEditScrollContainer-服务与履约"><select><option selected>48小时</option></select></div>
    <button id="publish">发布商品</button><button>填写检查</button>`,{url:`https://fxg.jinritemai.com/ffa/g/create?product_id=${pid}`,runScripts:'outside-only'});
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
test('reads ordered detail slots from the hidden canvas when the visible strip only has placeholders',()=>{
  const {page,call} = realistic();
  const snapshot = call('snapshot');
  assert.deepEqual(snapshot.details,['https://cdn.example/ecom-shop-material/detail1.jpg','https://cdn.example/ecom-shop-material/detail2.jpg']);
  assert.equal(snapshot.detail_status,'ready');
  assert.equal(snapshot.detail_source,'canvas_preview');
  assert.equal(snapshot.detail_declared,2);
  assert.equal(snapshot.detail_cards,2);
  page.window.close();
});
test('right-hand component editor copies are never counted as detail slots',()=>{
  const {page,call} = realistic();
  // Two canvas slots plus two right-panel mirrors: only the two ordered slots may be read.
  assert.equal(call('snapshot').details.length,2);
  page.window.close();
});
test('a legitimate repeated image keeps its own slot instead of being de-duplicated',()=>{
  const {page,call} = realistic({declared:'商详图片（3/50）',cards:3,extraCanvasImages:true});
  assert.equal(call('snapshot').details.length,3);
  assert.equal(call('snapshot').details[1],call('snapshot').details[2]);
  page.window.close();
});
test('an uninitialised canvas reports pending instead of an empty confirmed detail list',()=>{
  const {page,call} = realistic({canvas:false});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'pending');
  assert.equal(snapshot.details.length,0);
  assert.match(snapshot.detail_reason,/未读到已加载地址|未识别/);
  page.window.close();
});
test('a genuine empty detail reports empty and stays distinguishable from pending',()=>{
  const {page,call} = realistic({canvas:false,declared:'商详图片（0/50）',cards:0});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'empty');
  assert.equal(snapshot.details.length,0);
  page.window.close();
});
test('conflicting counts report ambiguous rather than silently trusting one source',()=>{
  const {page,call} = realistic({declared:'商详图片（5/50）'});
  const snapshot = call('snapshot');
  assert.equal(snapshot.detail_status,'ambiguous');
  assert.match(snapshot.detail_reason,/不一致/);
  page.window.close();
});
test('an image that failed to decode is not treated as loaded',()=>{
  const {page,call} = realistic();
  page.window.document.querySelectorAll('#goods-decorate-wrapper img').forEach(e=>e.setAttribute('data-nw','0'));
  assert.equal(call('snapshot').detail_status,'pending');
  page.window.close();
});
