const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(path.join(__dirname,'../src/doudian_auto/dom.js'),'utf8');
const pid = '3790019980637110699';
const image = name => `<img src="https://cdn.example/ecom-shop-material/${name}.jpg?resize=600">`;
function fixture() {
  const page = new JSDOM(`<header><span>样板店</span></header>
    <div id="goodsEditScrollContainer-基础信息"><div attr-field-id="标题"><input id="pg-title-input" value="旧标题"></div>
    <div attr-field-id="类目">其他汽车防护用品</div>
    <div attr-field-id="主图">${[1,2,3,4,5].map(i=>`<div>${image('main'+i)}<div class="styles-module_hoverBottomWrapper__YPnf1"><div>编辑</div><div data-delete="main">删除</div></div></div>`).join('')}<label><input type="file" multiple></label><label><input type="file" multiple></label></div></div>
    <div id="goodsEditScrollContainer-图文信息"><div attr-field-id="商品详情">${[1,2].map(i=>`<div>${image('detail'+i)}<i class="styles_iconDelete__y_88a" data-delete="detail"></i></div>`).join('')}<label><input type="file" multiple><div class="ecom-g-btn">上传图片</div></label></div></div>
    <div id="goodsEditScrollContainer-价格库存"><input name="price" value="20.88"><input type="checkbox" checked>${image('sku')}</div>
    <div id="goodsEditScrollContainer-服务与履约"><select><option selected>48小时</option></select></div>
    <button id="publish">发布商品</button><button>填写检查</button>`,{url:`https://fxg.jinritemai.com/ffa/g/create?product_id=${pid}`,runScripts:'outside-only'});
  Object.defineProperty(page.window.HTMLElement.prototype,'offsetWidth',{get(){return this.closest('[hidden],[style*="display:none"],[style*="display: none"]') ? 0 : 20;}});
  Object.defineProperty(page.window.HTMLElement.prototype,'innerText',{get(){return this.textContent;}});
  page.window.HTMLElement.prototype.scrollIntoView = function() {};
  page.window.document.querySelectorAll('[data-delete]').forEach(e=>e.addEventListener('click',()=>e.parentElement.parentElement.matches('[attr-field-id]') ? e.parentElement.remove() : e.parentElement.parentElement.remove()));
  const call = (op,p={})=>JSON.parse(JSON.stringify(page.window.eval(script + '('+JSON.stringify(op)+','+JSON.stringify({product_id:pid,shop:'样板店',...p})+')')));
  return {page,call};
}
test('reads canonical ordered URLs, inputs and checkbox without coupling to title/images',()=>{
  const {page,call} = fixture();
  const before = call('snapshot');
  assert.equal(before.mains.length,5);
  assert.equal(before.details.length,2);
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
