const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(path.join(__dirname,'../src/doudian_auto/dom.js'),'utf8');
const pid = '3790019980637110699';

// The real shelf-life control pairs a number input with a unit dropdown inside the
// platform's measure wrapper (measured 2026-11-12 on the 家清 category page).
function measureFixture({numberValue = '', unit = '天', listId = 'rc_select_9_list'} = {}) {
  const page = new JSDOM(`<header><span>样板店</span></header>
    <div id="goodsEditScrollContainer-基础信息"><div attr-field-id="标题"><input id="pg-title-input" value="旧标题"></div>
    <div attr-field-id="主图"><label><input type="file" multiple></label></div>
    <div attr-field-id="商品详情">商详图片（0/50）</div></div>
    <div id="goodsEditScrollContainer-价格库存"><input name="price" value="20.88"></div>
    <div id="goodsEditScrollContainer-服务与履约"><select><option selected>48小时</option></select></div>
    <button>发布商品</button><button>填写检查</button>`, {url:`https://fxg.jinritemai.com/ffa/g/create?product_id=${pid}`, runScripts:'outside-only'});
  Object.defineProperty(page.window.HTMLElement.prototype,'offsetWidth',{get(){return this.closest('[hidden],[style*="display:none"],[style*="display: none"]') ? 0 : 20;}});
  Object.defineProperty(page.window.HTMLElement.prototype,'innerText',{get(){return this.textContent;}});
  page.window.HTMLElement.prototype.scrollIntoView = function() {};
  // jsdom has no layout, so the dropdown's measured width is simulated. It has to be a
  // method, not an accessor: the adapter calls e.getBoundingClientRect() directly.
  Object.defineProperty(page.window.Element.prototype,'getBoundingClientRect',{value:function(){
    return {width:20,height:20,x:0,y:0,top:0,left:0,right:20,bottom:20};
  }});
  const base = page.window.document.querySelector('#goodsEditScrollContainer-基础信息');
  base.insertAdjacentHTML('beforeend',`<div class="categoryPropertiesItem"><div attr-field-id="保质期">
    <span class="styles_required__jsVzS">*</span><span class="styles_label__x">保质期</span>
    <div class="styles_measureValue__BknXC"><div class="styles_measureContainer__AF_AJ"><div class="styles_measureTemplate__AfVoo">
      <input class="ecom-g-input styles_value__QXqGx" type="text" placeholder="请输入" value="${numberValue}">
      <div class="ecom-g-select ecom-g-select-single">
        <span class="ecom-g-select-selection-item" title="${unit}">${unit}</span>
        <span class="ecom-g-select-selection-search"><input type="search" role="combobox" aria-controls="${listId}" readonly value=""></span>
      </div></div></div></div></div></div>`);
  const call = (op,p={})=>JSON.parse(JSON.stringify(page.window.eval(script + '('+JSON.stringify(op)+','+JSON.stringify({product_id:pid,shop:'样板店',...p})+')')));
  return {page,call,base};
}

test('a number-plus-unit control is reported as a measure, not as an unknown control',()=>{
  const {page,call}=measureFixture();
  const control=call('attribute_control',{name:'保质期'});
  assert.equal(control.kind,'measure');
  assert.equal(control.current,'');
  assert.equal(control.number_value,'');
  assert.equal(control.unit_value,'天');
  assert.ok(control.marked.includes('data-doudian-attr-number'));
  assert.ok(control.unit_marked.includes('data-doudian-attr-unit'));
  page.window.close();
});

test('a measure control reads back the composed value and reports a filled number',()=>{
  const {page,call}=measureFixture({numberValue:'12', unit:'个月'});
  const control=call('attribute_control',{name:'保质期'});
  assert.equal(control.kind,'measure');
  assert.equal(control.current,'12个月');
  assert.equal(control.number_value,'12');
  assert.equal(control.unit_value,'个月');
  page.window.close();
});

test('a plain text box beside a dropdown is not mistaken for a measure control',()=>{
  const {page,call}=measureFixture();
  // Same two controls, but without the platform's measure wrapper.
  page.window.document.querySelector('[attr-field-id="保质期"]').innerHTML =
    '<input type="text" value=""><div class="ecom-g-select ecom-g-select-single">' +
    '<span class="ecom-g-select-selection-item">天</span></div>';
  assert.equal(call('attribute_control',{name:'保质期'}).kind,'unknown');
  page.window.close();
});

test('the unit dropdown is found through its own listbox id, not by taking the last open dropdown',()=>{
  const {page,call}=measureFixture();
  const doc=page.window.document;
  // Another attribute's dropdown is open and visible at the same time.
  doc.body.insertAdjacentHTML('beforeend',`<div class="ecom-g-select-dropdown">
    <div role="listbox" id="rc_select_other_list"><div role="option" aria-label="别的">99</div></div>
    <div class="ecom-g-select-item-option"><div class="ecom-g-select-item-option-content">别的</div></div>
  </div>`);
  doc.body.insertAdjacentHTML('beforeend',`<div class="ecom-g-select-dropdown">
    <div role="listbox" id="rc_select_9_list"><div role="option" aria-label="天">6</div></div>
    <div class="ecom-g-select-item-option"><div class="ecom-g-select-item-option-content">天</div></div>
    <div class="ecom-g-select-item-option"><div class="ecom-g-select-item-option-content">个月</div></div>
  </div>`);
  const listing=call('attribute_unit_options',{name:'保质期'});
  assert.deepEqual(listing.candidates,['天','个月']);
  const marked=call('attribute_unit_options',{name:'保质期',value:'个月'});
  assert.equal(marked.selector,'[data-doudian-unit-option="个月"]');
  page.window.close();
});

test('a unit that the platform does not offer is refused with the real candidate list',()=>{
  const {page,call}=measureFixture();
  page.window.document.body.insertAdjacentHTML('beforeend',`<div class="ecom-g-select-dropdown">
    <div role="listbox" id="rc_select_9_list"><div role="option" aria-label="天">6</div></div>
    <div class="ecom-g-select-item-option"><div class="ecom-g-select-item-option-content">天</div></div>
    <div class="ecom-g-select-item-option"><div class="ecom-g-select-item-option-content">个月</div></div>
  </div>`);
  const refused=call('attribute_unit_options',{name:'保质期',value:'星期'});
  assert.equal(refused.error,'option_not_unique');
  assert.deepEqual(refused.candidates,['天','个月']);
  page.window.close();
});

test('the unit label alone never makes an empty measure attribute look filled',()=>{
  // The platform pre-selects a unit, so counting that label as the field's value
  // made an empty shelf life look complete while the platform's own required
  // progress said otherwise. Only the number decides.
  const {page,call}=measureFixture();
  const base=page.window.document.querySelector('#goodsEditScrollContainer-基础信息');
  base.insertAdjacentHTML('beforeend','<div>必填项进度 50%</div>');
  base.insertAdjacentHTML('beforeend','<div class="categoryPropertiesItem"><div attr-field-id="生产企业名称">' +
    '<span class="styles_required__jsVzS">*</span><input type="text" value=""></div></div>');
  const attributes=call('snapshot').required_attributes;
  assert.deepEqual(attributes.missing,['保质期','生产企业名称']);
  assert.equal(attributes.completion_percent,50);
  page.window.close();
});

test('a filled measure attribute leaves the required list',()=>{
  const {page,call}=measureFixture({numberValue:'12', unit:'个月'});
  const base=page.window.document.querySelector('#goodsEditScrollContainer-基础信息');
  base.insertAdjacentHTML('beforeend','<div>必填项进度 100%</div>');
  const attributes=call('snapshot').required_attributes;
  assert.deepEqual(attributes.missing,[]);
  const field=attributes.fields.find(f=>f.name==='保质期');
  assert.deepEqual(field.values,['12个月']);
  page.window.close();
});
