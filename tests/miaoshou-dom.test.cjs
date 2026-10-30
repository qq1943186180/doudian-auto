const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(require('node:path').join(__dirname,'../src/doudian_auto/miaoshou_dom.js'),'utf8');
const pid = '3850072653520044313';
function fixture(extra='') {
  const page = new JSDOM(`<header>您好【销霁百货】</header>${extra}
    <div class="pro-table-custom-body-row" data-y="-9000">商品ID：${pid}<button>编辑商品</button></div>
    <div class="pro-table-custom-body-row" data-y="100">商品ID：${pid}<button id="live">编辑商品</button></div>`, {runScripts:'outside-only'});
  const w = page.window;
  Object.defineProperty(w.HTMLElement.prototype,'innerText',{get(){return this.textContent;}});
  w.HTMLElement.prototype.getBoundingClientRect = function() {
    const top = Number(this.closest('[data-y]')?.dataset.y || 20);
    return {left:10,right:110,top,bottom:top+30,width:100,height:30};
  };
  w.document.elementFromPoint = (x,y) => [...w.document.querySelectorAll('button,input')].find(el => {
    const r = el.getBoundingClientRect(); return y >= r.top && y <= r.bottom;
  });
  return {w,call:(op,p={})=>JSON.parse(JSON.stringify(w.eval(script+'('+JSON.stringify(op)+','+JSON.stringify({product_id:pid,shop:'销霁百货',marker:'test',...p})+')')))};
}
test('ignores offscreen cached rows even when they have dimensions', () => {
  const {w,call}=fixture();
  assert.equal(call('edit_button').count,1);
  assert.equal(w.document.querySelector('[data-codex-miao-target]').id,'live');
});
test('refuses two actionable rows and exact adjacent product ids', () => {
  const {call}=fixture(`<div class="pro-table-custom-body-row" data-y="200">商品ID：${pid}<button>编辑商品</button></div>`);
  assert.equal(call('edit_button').count,2);
  assert.equal(call('edit_button',{product_id:'3850072653520044314'}).count,0);
});
test('hidden ancestors and another shop cannot supply an action', () => {
  const {w,call}=fixture();
  w.document.querySelector('#live').parentElement.style.display='none';
  assert.equal(call('edit_button').count,0);
  assert.equal(call('edit_button',{shop:'另一店'}).error,'wrong_shop');
});

test('listing targets only the exact visible product and never its edit or delist button',()=>{
  const {w,call}=fixture();
  const rows=w.document.querySelectorAll('.pro-table-custom-body-row');
  for(const row of rows)row.insertAdjacentHTML('beforeend','<button class="list">上架</button>');
  const live=rows[1].querySelector('button.list');live.id='listing';
  w.document.elementFromPoint=()=>live;
  assert.equal(call('listing_button').count,1);
  assert.equal(w.document.querySelector('[data-codex-miao-target]').id,'listing');
  assert.equal(call('listing_button',{product_id:'3850072653520044314'}).count,0);
  live.textContent='下架';
  assert.equal(call('listing_button').count,0);
});

test('supplier provenance comes from the exact current row, excluding cached rows and other domains',()=>{
  const {w,call}=fixture();
  const rows=w.document.querySelectorAll('.pro-table-custom-body-row');
  rows[0].insertAdjacentHTML('beforeend','<a href="https://detail.1688.com/offer/111.html">旧货源</a>');
  rows[1].insertAdjacentHTML('beforeend','<a href="https://detail.1688.com/offer/222.html?source=own">阿里巴巴</a>');
  assert.deepEqual(call('supplier_link'),{count:1,url:'https://detail.1688.com/offer/222.html?source=own'});
  rows[1].querySelector('a').href='https://unrelated.example/offer/222.html';
  assert.deepEqual(call('supplier_link'),{count:0,url:null});
  assert.equal(call('supplier_link',{shop:'另一店'}).error,'wrong_shop');
});

test('scrolls an offscreen action column of the one visible exact-ID row', () => {
  const {w,call}=fixture();
  const live=w.document.getElementById('live');
  const original=live.getBoundingClientRect.bind(live);
  let scrolled=false;
  live.getBoundingClientRect=()=>scrolled?original():{left:1500,right:1600,top:100,bottom:130,width:100,height:30};
  w.document.elementFromPoint=(x,y)=>{
    if(y>=100&&y<=130)return x<1100?w.document.querySelector('#live').parentElement:null;
    return null;
  };
  live.scrollIntoView=()=>{scrolled=true;w.document.elementFromPoint=()=>live;};
  assert.equal(call('edit_button').count,1);
  assert.equal(scrolled,true);
  assert.equal(w.document.querySelector('[data-codex-miao-target]').id,'live');
});
test('title ignores the keyword selector inside the same labelled form item', () => {
  const {call}=fixture(`<div class="product-edit-dialog" data-y="20">ID：${pid}<div class="el-form-item"><label class="el-form-item__label">商品标题：</label><input name="name" class="el-input__inner" value="当前商品标题"><input class="el-input__inner" value="算法热词"></div></div>`);
  assert.deepEqual(call('dialog'),{count:1,identity:true,title:'当前商品标题'});
});
