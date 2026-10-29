const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const runtime = import(pathToFileURL(path.join(__dirname,'../src/doudian_auto/ego_runtime.mjs')).href);

function savePage() {
  const {JSDOM}=require('jsdom');
  const expected={shop:'销霁百货',product_id:'3848317832962113825',title:'目标商品标题',
    top_fields:['title','image_change','desc','price'],required_fields:['title','image_change','desc'],
    options:['new','onlyPreview','replaceImgsByImgUrls'],
    mains:Array.from({length:5},(_,i)=>`https://p3-aio.ecombdimg.com/obj/ecom-shop-material/main${i}`),
    pairs:Array.from({length:4},(_,i)=>[`https://p3-aio.ecombdimg.com/obj/ecom-shop-material/source${i}`,`https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-10-30/detail${i}.png?dy`])};
  const dom=new JSDOM(`<header>您好【${expected.shop}】</header><textarea placeholder="请输入商品ID">${expected.product_id}</textarea><textarea name="inputNewContent">${expected.title}</textarea>
    ${expected.required_fields.concat(expected.options).map(v=>`<input type="checkbox" value="${v}" checked>`).join('')}<input id="price" type="checkbox" value="price">
    <input type="radio" name="contentType" value="replaceImgByIndex" checked><input type="radio" name="overlengthType" value="fail" checked>
    ${expected.mains.map(u=>`<div class="replace-img-item"><div class="add-img-box"><img src="${u}"></div></div>`).join('')}
    ${expected.pairs.map(pair=>`<div class="base-edit-list">${pair.map(u=>`<div class="add-img-box"><img src="${u}"></div>`).join('')}</div>`).join('')}
    <button id="save" class="J_batchEditProduct">开始批量修改</button>`,{url:'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field',runScripts:'outside-only'});
  const w=dom.window;
  Object.defineProperty(w.HTMLElement.prototype,'innerText',{get(){return this.textContent;}});
  Object.defineProperty(w.HTMLElement.prototype,'offsetParent',{get(){return this.closest('[hidden]')?null:w.document.body;}});
  return {dom,w,expected,evaluate:async(fn,arg)=>typeof fn==='function'?w.eval('('+fn.toString()+')')(arg):w.eval(fn)};
}

async function fixture(t) {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'ego-transport-'));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const calls=[],buffer=[];
  const page={label:'p1',openedBy:'agent',
    info:async()=>({w:1462,h:795}),
    evaluate:async code => typeof code==='string'?{actual:true}:{count:1,x:40,y:80,actionable:true},
    cdp:async (method,args)=>{calls.push(method);if(method==='Network.getResponseBody')return {body:'{"result":"success"}',base64Encoded:false};return {};},
    events:async()=>buffer.splice(0),
    mouse:{click:async()=>{
      calls.push('click');
      buffer.push({method:'Network.requestWillBeSent',params:{requestId:'r1',request:{url:'https://v2-dd.chengji-inc.com/api/v2/product/product/getProductBaseEditInfo',method:'POST',postData:'productId=3850072653520044313&isDraft=0',headers:{Cookie:'do-not-store'}}}},
        {method:'Network.responseReceived',params:{requestId:'r1',response:{status:200}}},
        {method:'Network.loadingFinished',params:{requestId:'r1'}});
      return {};
    }},
    goto:async url=>{calls.push(url);}, url:async()=> 'https://v2-dd.chengji-inc.com/product/quick_edit'};
  const task={spaceId:8,page:()=>page,tabs:async()=>[{label:'p1',url:await page.url(),openedBy:'agent'}],
    finish:async()=>calls.push('finish'),pages:async()=>[page],newPage:async()=>{throw Error('should reuse page');}};
  global.taskSpace=async id=>{calls.push(['space',id]);return task;};
  global.listTaskSpaces=async()=>[];
  const {runEgo}=await runtime;
  const statePath=path.join(root,'state.json');
  return {run:(action,args={})=>runEgo({action,args,statePath,session:'test'}),calls,statePath,page};
}

test('official SKU evidence comes from one UI reload and drops context tokens and actions',async t=>{
  const f=await fixture(t);
  const url='https://fxg.jinritemai.com/ffa/g/create?product_id=3850072653520044313';
  f.page.url=async()=>url;
  const events=[];
  f.page.events=async()=>events.splice(0);
  f.page.reload=async()=>{
    f.calls.push('reload');
    events.push({method:'Network.requestWillBeSent',params:{requestId:'schema-1',request:{
      url:'https://fxg.jinritemai.com/product/tproduct/getSchema',method:'POST'}}},
      {method:'Network.responseReceived',params:{requestId:'schema-1',response:{status:200}}},
      {method:'Network.loadingFinished',params:{requestId:'schema-1'}});
  };
  const body=JSON.stringify({errno:0,code:0,data:{context:{product_id:'3850072653520044313',shop_id:'177970452',
    operation_type:'normal',model_type:'normal',token:'secret-auth',n_token:'secret-native'},
    model:{sku_detail:{value:[{sku_id:'3387918799208229'}],actions:[{url:'do-not-store'}]},
      spec_detail:{value:[]}},global:{not_evidence:true}}});
  f.page.cdp=async method=>method==='Network.getResponseBody'?{body,base64Encoded:false}:{};
  const result=await f.run('official_sku_read',{product_id:'3850072653520044313'});
  assert.equal(f.calls.filter(x=>x==='reload').length,1);
  assert.equal(result.completed,true);assert.equal(result.page_url,url);
  assert.equal(JSON.parse(result.body).data.context.product_id,'3850072653520044313');
  assert.equal(/secret-|do-not-store|not_evidence/.test(JSON.stringify(result)),false);
});

test('official schema redaction refuses unsafe numeric product IDs',async()=>{
  const {redactOfficialSchema}=await runtime;
  assert.throws(()=>redactOfficialSchema('{"data":{"context":{"product_id":3850072653520044313},"model":{}}}'),/Unsafe numeric ID/);
});

test('final native save guard requires exact shop, product, title, fields and all nine image slots',async()=>{
  const {inspectBatchSave}=await runtime;const p=savePage();
  const read=()=>p.evaluate(inspectBatchSave,p.expected);
  assert.equal((await read()).valid,true);
  p.w.document.querySelector('#price').checked=true;assert.equal((await read()).reason,'fields');
  p.w.document.querySelector('#price').checked=false;
  p.w.document.querySelector('textarea[name=inputNewContent]').value='another';assert.equal((await read()).reason,'identity');
  p.w.document.querySelector('textarea[name=inputNewContent]').value=p.expected.title;
  const image=p.w.document.querySelector('.base-edit-list .add-img-box img');const old=image.src;
  image.src='https://p3-aio.ecombdimg.com/obj/ecom-shop-material/changed';assert.equal((await read()).reason,'assets');image.src=old;
  p.w.document.body.insertAdjacentHTML('beforeend','<div class="select-product-filter-dialog">open picker</div>');
  assert.equal((await read()).reason,'modal');p.dom.window.close();
});

for(const mode of ['success','changed_on_focus','lost_after_enter'])test(`one native final-button Enter with ${mode}`,async t=>{
  const f=await fixture(t),p=savePage(),events=[];let inputs=0;
  f.page.evaluate=p.evaluate;f.page.events=async()=>events.splice(0);
  f.page.cdp=async(method,args)=>{
    if(method==='DOM.getDocument')return {root:{nodeId:1}};
    if(method==='DOM.querySelector')return {nodeId:2};
    if(method==='DOM.focus'){
      p.w.document.querySelector('#save').focus();
      if(mode==='changed_on_focus')p.w.document.querySelector('textarea[name=inputNewContent]').value='changed';
    }
    if(method==='Network.getResponseBody')return {body:'{"result":"success"}',base64Encoded:false};
    return {};
  };
  f.page.keyboard={press:async key=>{
    assert.equal(key,'Enter');inputs++;
    events.push({method:'Network.requestWillBeSent',params:{requestId:'save-one',request:{url:'https://v2-dd.chengji-inc.com/api/v2/product/product/saveProduct',method:'POST',postData:'productId='+p.expected.product_id}}},
      {method:'Network.responseReceived',params:{requestId:'save-one',response:{status:200}}},
      {method:'Network.loadingFinished',params:{requestId:'save-one'}});
    if(mode==='lost_after_enter')throw Error('receipt lost');
    return {};
  }};
  await f.run('network',{cmd:'start'});
  const action=()=>f.run('activate_batch_save',{guard:p.expected});
  if(mode==='changed_on_focus'){
    await assert.rejects(action(),e=>e.code==='ego_save_precheck_failed'&&e.inputDispatched===false);
    assert.equal(inputs,0);
  }else if(mode==='lost_after_enter'){
    await assert.rejects(action(),e=>e.message==='receipt lost'&&e.inputDispatched!==false);
    assert.equal(inputs,1);
  }else{await action();assert.equal(inputs,1);}
  const records=await f.run('network',{cmd:'list'});
  assert.equal(records.requests.length,mode==='changed_on_focus'?0:1);
  assert.equal(f.calls.includes('click'),false);p.dom.window.close();
});

test('repairs a zero-sized background Page from an observed peer viewport',async t=>{
  const f=await fixture(t);
  let repaired=false;
  const task=await global.taskSpace();
  const peer={info:async()=>({w:2036,h:1015})};
  task.pages=async()=>[f.page,peer];
  f.page.info=async()=>repaired?{w:2036,h:1015}:{w:0,h:0};
  const original=f.page.cdp;
  f.page.cdp=async(method,args)=>{
    if(method==='Emulation.setDeviceMetricsOverride'){
      assert.equal(args.width,2036);assert.equal(args.height,1015);repaired=true;
    }
    return original(method,args);
  };
  assert.deepEqual((await f.run('evaluate',{code:'observed DOM'})).value,{actual:true});
  assert.equal(repaired,true);
});

test('keeps the first measured task viewport when the browser window is resized',async t=>{
  const f=await fixture(t);
  await f.run('evaluate',{code:'baseline viewport'});
  let width=2514,height=1253;
  f.page.info=async()=>({w:width,h:height});
  const original=f.page.cdp;
  f.page.cdp=async(method,args)=>{
    if(method==='Emulation.setDeviceMetricsOverride'){
      width=args.width;height=args.height;
    }
    return original(method,args);
  };
  await f.run('evaluate',{code:'readback viewport'});
  assert.deepEqual([width,height],[1462,795]);
});

test('fills a named input replaced by a textarea on focus and confirms after blur',async t=>{
  const f=await fixture(t);
  const {JSDOM}=require('jsdom');
  const dom=new JSDOM('<input name="productId" data-observed="yes"><button>查询</button>',{runScripts:'outside-only'});
  const w=dom.window;
  Object.defineProperty(w.HTMLElement.prototype,'offsetParent',{get(){return w.document.body;}});
  w.HTMLElement.prototype.getBoundingClientRect=()=>({x:10,y:10,width:100,height:30});
  w.HTMLElement.prototype.scrollIntoView=()=>{};
  w.document.elementFromPoint=()=>w.document.querySelector('input,textarea');
  f.page.evaluate=async(fn,arg)=>typeof fn==='function'?w.eval('('+fn.toString()+')')(arg):w.eval(fn);
  f.page.mouse.click=async()=>{
    const replacement=w.document.createElement('textarea');replacement.name='productId';
    w.document.querySelector('input').replaceWith(replacement);replacement.focus();return {};
  };
  f.page.keyboard={insertText:async text=>{w.document.activeElement.value=text;},press:async key=>{
    if(key==='Tab'){
      const old=w.document.activeElement,input=w.document.createElement('input');
      input.name='productId';input.value=old.value;old.replaceWith(input);w.document.querySelector('button').focus();
    }
  }};
  const result=await f.run('fill',{selector:'[data-observed="yes"]',value:'3850072653520044313'});
  assert.equal(result.success,true);
  assert.equal(w.document.querySelector('input[name=productId]').value,'3850072653520044313');
});

test('captures response in the action round and retains it in the next round without headers',async t=>{
  const f=await fixture(t);
  await f.run('network',{cmd:'start'});
  await f.run('click',{selector:'[data-observed="yes"]'});
  const records=await f.run('network',{cmd:'list'});
  assert.equal(records.requests[0].completed,true);
  const detail=await f.run('network',{cmd:'detail',requestId:records.requests[0].requestId});
  assert.equal(detail.body,'{"result":"success"}');
  assert.equal(detail.requestBody,'productId=3850072653520044313&isDraft=0');
  assert.equal(JSON.stringify(detail).includes('Cookie'),false);
  assert.equal(f.calls.filter(x=>x==='click').length,1);
});

test('does not replay a failed native action or create another space',async t=>{
  const f=await fixture(t);
  f.page.mouse.click=async()=>{f.calls.push('click');throw Error('EPERM refs.json');};
  await assert.rejects(f.run('click',{selector:'button'}),/EPERM/);
  assert.equal(f.calls.filter(x=>x==='click').length,1);
  assert.equal(f.calls.filter(x=>Array.isArray(x)&&x[0]==='space').length,1);
});

for(const type of ['checkbox','radio'])test(`selects a zero-sized accessible ${type} with one trusted Space and never replays it`,async t=>{
  const f=await fixture(t);const {JSDOM}=require('jsdom');
  const dom=new JSDOM(`<label><span><input type="${type}" id="method"><span class="el-${type}__inner"></span></span><textarea disabled></textarea></label>`,{runScripts:'outside-only'});
  const w=dom.window;const input=w.document.querySelector('input');
  Object.defineProperty(w.HTMLElement.prototype,'offsetParent',{get(){return w.document.body;}});
  w.HTMLElement.prototype.getBoundingClientRect=function(){return this===input?{width:0,height:0}:{width:14,height:14};};
  f.page.evaluate=async(fn,arg)=>typeof fn==='function'?w.eval('('+fn.toString()+')')(arg):w.eval(fn);
  f.page.cdp=async(method,args)=>{
    f.calls.push(method);
    if(method==='DOM.getDocument')return {root:{nodeId:1}};
    if(method==='DOM.querySelector')return {nodeId:w.document.querySelector(args.selector)?2:0};
    if(method==='DOM.focus')input.focus();
    return {};
  };
  let presses=0;
  f.page.keyboard={press:async key=>{assert.equal(key,'Space');presses++;input.click();}};
  assert.equal((await f.run('checkbox',{selector:'#method',checked:true})).checked,true);
  assert.equal(input.checked,true);assert.equal(presses,1);
  assert.equal((await f.run('checkbox',{selector:'#method',checked:true})).unchanged,true);
  assert.equal(presses,1);assert.equal(f.calls.includes('click'),false);
  f.page.keyboard.press=async()=>{presses++;throw Error('input transport failed');};
  if(type==='checkbox'){
    await assert.rejects(f.run('checkbox',{selector:'#method',checked:false}),/transport failed/);
    assert.equal(presses,2);
  }else{
    input.checked=false;
    await assert.rejects(f.run('checkbox',{selector:'#method',checked:true}),/transport failed/);
    assert.equal(presses,2);
    await assert.rejects(f.run('checkbox',{selector:'#method',checked:false}),{code:'ego_checkbox_not_unique'});
  }
  assert.equal(f.calls.filter(x=>typeof x==='string').at(-1),'Emulation.setFocusEmulationEnabled');
  dom.window.close();
});

test('reuses the task page across fresh navigations and finishes exactly once',async t=>{
  const f=await fixture(t);
  await f.run('navigate',{url:'https://v2-dd.chengji-inc.com/product/quick_edit',newTab:true});
  await f.run('navigate',{url:'https://v2-dd.chengji-inc.com/product/quick_edit',newTab:true});
  assert.equal((await f.run('close_session')).closed,1);
  assert.equal((await f.run('list_tabs')).tabs.length,0);
  await assert.rejects(f.run('close_session'),{code:'ego_session_finished'});
  assert.equal(f.calls.filter(x=>x==='finish').length,1);
});
