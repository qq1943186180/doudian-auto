const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const runtime = import(pathToFileURL(path.join(__dirname,'../src/doudian_auto/ego_runtime.mjs')).href);

async function fixture(t) {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'ego-transport-'));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const calls=[],buffer=[];
  const page={label:'p1',openedBy:'agent',
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
    finish:async()=>calls.push('finish'),newPage:async()=>{throw Error('should reuse page');}};
  global.taskSpace=async id=>{calls.push(['space',id]);return task;};
  global.listTaskSpaces=async()=>[];
  const {runEgo}=await runtime;
  const statePath=path.join(root,'state.json');
  return {run:(action,args={})=>runEgo({action,args,statePath,session:'test'}),calls,statePath,page};
}

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

test('reuses the task page across fresh navigations and finishes exactly once',async t=>{
  const f=await fixture(t);
  await f.run('navigate',{url:'https://v2-dd.chengji-inc.com/product/quick_edit',newTab:true});
  await f.run('navigate',{url:'https://v2-dd.chengji-inc.com/product/quick_edit',newTab:true});
  assert.equal((await f.run('close_session')).closed,1);
  assert.equal((await f.run('list_tabs')).tabs.length,0);
  await assert.rejects(f.run('close_session'),{code:'ego_session_finished'});
  assert.equal(f.calls.filter(x=>x==='finish').length,1);
});
