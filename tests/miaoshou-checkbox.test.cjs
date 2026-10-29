const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(path.join(__dirname,'../src/doudian_auto/miaoshou_checkbox.js'),'utf8');
function fixture(extra='') {
  const dom = new JSDOM(`<label id="method"><span class="el-checkbox__input"><input type="checkbox" value="new"><span class="el-checkbox__inner" id="box"></span></span><span>使用新内容<textarea disabled></textarea></span></label>${extra}`,{runScripts:'outside-only'});
  const w=dom.window;
  Object.defineProperty(w.HTMLElement.prototype,'offsetParent',{get(){return this.closest('[hidden]')?null:w.document.body;}});
  w.HTMLElement.prototype.getBoundingClientRect=function(){return {width:14,height:14};};
  return {w,call:(checked=true)=>JSON.parse(JSON.stringify(w.eval('('+script+')("new",'+JSON.stringify(checked)+',"test")')))};
}
test('clicks the small checkbox instead of the disabled editor at the label center',()=>{
  const {w,call}=fixture();
  const input=w.document.querySelector('input');
  w.document.querySelector('textarea').click();
  assert.equal(input.checked,false);
  assert.equal(call().count,1);
  const target=w.document.querySelector('[data-codex-miao-batch="test"]');
  assert.equal(target.id,'box');
  target.click();
  assert.equal(input.checked,true);
});
test('does not toggle an already correct checkbox',()=>{
  const {w,call}=fixture();w.document.querySelector('input').checked=true;
  assert.equal(call().unchanged,true);
  assert.equal(w.document.querySelector('[data-codex-miao-batch]'),null);
});
test('ignores hidden or disabled clones and refuses two enabled live values',()=>{
  const {w,call}=fixture('<label hidden><input type="checkbox" value="new"></label><input disabled type="checkbox" value="new">');
  assert.equal(call().count,1);
  w.document.querySelector('input[disabled]').disabled=false;
  assert.equal(call().count,2);
});
test('missing or zero-sized checkbox visual fails without falling back to its large label',()=>{
  const {w,call}=fixture();w.document.getElementById('box').getBoundingClientRect=()=>({width:0,height:0});
  assert.equal(call().count,0);
  w.document.getElementById('box').remove();assert.equal(call().count,0);
  assert.equal(w.document.getElementById('method').hasAttribute('data-codex-miao-batch'),false);
});
