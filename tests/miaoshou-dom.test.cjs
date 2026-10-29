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
test('title ignores the keyword selector inside the same labelled form item', () => {
  const {call}=fixture(`<div class="product-edit-dialog" data-y="20">ID：${pid}<div class="el-form-item"><label class="el-form-item__label">商品标题：</label><input name="name" class="el-input__inner" value="当前商品标题"><input class="el-input__inner" value="算法热词"></div></div>`);
  assert.deepEqual(call('dialog'),{count:1,identity:true,title:'当前商品标题'});
});
