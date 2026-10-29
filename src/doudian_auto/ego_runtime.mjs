// Runs inside the documented ego-browser Node runtime. No new browser/profile and
// no direct website writes: every mutation uses the page's ordinary controls.
export async function runEgo(request) {
  const fs = await import('node:fs/promises');
  const {action,args={},statePath,session,runId} = request;
  if (action === 'status') { await listTaskSpaces(); return {connected:true}; }
  let state;
  try { state=JSON.parse(await fs.readFile(statePath,'utf8')); }
  catch(e) { if(e.code!=='ENOENT')throw e; state={pages:{},requests:{},capture:false}; }
  const save=()=>fs.writeFile(statePath,JSON.stringify(state),'utf8');
  const fail=(code,message)=>{ const error=new Error(message);error.code=code;throw error; };
  if(state.finished){
    if(['list_tabs','list_browser_tabs'].includes(action))return {tabs:[]};
    if(action==='navigate'&&runId&&runId!==state.runId)
      state={pages:{},requests:{},capture:false};
    else fail('ego_session_finished','Use a new session after completing this TaskSpace.');
  }
  state.runId??=runId;
  const task=await taskSpace(state.spaceId??('doudian-auto '+session+' '+(state.runId??'')));
  state.spaceId=task.spaceId;
  state.active??='p1';
  await save();
  const ensureViewport=async page=>{
    let info=await page.info();
    let viewport=state.viewport;
    if(!viewport||viewport.width<=0||viewport.height<=0){
      viewport=info.w>0&&info.h>0?{width:info.w,height:info.h}:null;
      if(!viewport){
        for(const peer of await task.pages()){
          const observed=await peer.info();
          if(observed.w>0&&observed.h>0){viewport={width:observed.w,height:observed.h};break;}
        }
      }
    }
    if(!viewport)fail('ego_viewport_unavailable','No observed positive task viewport; restore the Ego window.');
    if(info.w===viewport.width&&info.h===viewport.height){state.viewport=viewport;await save();return;}
    // Newly created background Pages were observed at 0x0. Focus/bringToFront do
    // not repair them. Keep the task's measured viewport fixed across Pages and
    // window resizes so virtual SKU rows do not change between baseline/readback.
    await page.cdp('Emulation.setDeviceMetricsOverride',{...viewport,
      screenWidth:viewport.width,screenHeight:viewport.height,deviceScaleFactor:1,mobile:false});
    info=await page.info();
    if(info.w<=0||info.h<=0)fail('ego_viewport_unavailable','Background Page still has no actionable viewport.');
    state.viewport=viewport;await save();
  };
  if(action==='list_tabs'||action==='list_browser_tabs') {
    const tabs=await task.tabs();
    return {tabs:tabs.filter(t=>t.label).map(t=>({tabId:t.label,url:t.url,owned:t.openedBy==='agent'}))};
  }
  if(action==='attach_tab') {
    const tabs=await task.tabs(), tab=tabs.find(t=>t.label===args.tabId);
    if(!tab)fail('ego_tab_missing','No exact task page exists.');
    if(tab.openedBy!=='agent')fail('ego_user_page_protected','Cannot attach a user-owned page for batch writes.');
    state.active=tab.label;await save();return {success:true};
  }
  if(action==='close_session') {
    const tabs=await task.tabs(),count=tabs.filter(t=>t.openedBy==='agent').length;
    await task.finish({keep:[]});state.finished=true;await save();return {closed:count};
  }
  let page=task.page(state.active);
  if(action==='navigate') {
    const u=new URL(args.url);
    if(!['v2-dd.chengji-inc.com','fxg.jinritemai.com'].includes(u.hostname)||u.protocol!=='https:')
      fail('ego_navigation_scope','Only the current shop project sites are supported.');
    const key=u.hostname+u.pathname+(u.searchParams.has('batchType')?'?batchType='+u.searchParams.get('batchType'):'');
    if(state.pages[key]) page=task.page(state.pages[key]);
    else if(Object.keys(state.pages).length) page=await task.newPage();
    state.pages[key]=page.label;state.active=page.label;await save();
    await ensureViewport(page);
    await page.goto(args.url);
    return {success:true,tabId:page.label,url:await page.url()};
  }
  if(action==='close_tab') {
    const tabs=await task.tabs(),tab=tabs.find(t=>t.label===state.active);
    if(!tab||tab.openedBy!=='agent')fail('ego_user_page_protected','No task-owned page to close.');
    await page.close();
    for(const [key,label]of Object.entries(state.pages))if(label===state.active)delete state.pages[key];
    state.active=(await task.pages())[0]?.label;await save();return {closed:true};
  }
  if(action==='network') {
    if(args.cmd==='start'||args.cmd==='stop'){state.capture=args.cmd==='start';await save();return {success:true};}
    if(args.cmd==='list')return {requests:Object.values(state.requests).filter(r=>!args.filter||r.url.includes(args.filter)).map(({body,requestBody,...r})=>r)};
    if(args.cmd==='detail')return state.requests[args.requestId]??{};
    fail('ego_network_command','Unsupported network observation.');
  }
  await ensureViewport(page);
  if(action==='evaluate')return {value:await page.evaluate(args.code)};
  if(action==='snapshot') {
    // DOM text avoids Ego's snapshot-ref file-lock failure. No fabricated refs.
    return await page.evaluate(max=>({url:location.href,observation_kind:'dom_text',tree_text:
      ((document.body?.innerText||'')+'\n'+[...document.querySelectorAll('input,textarea')]
        .filter(x=>x.offsetParent!==null).map(x=>x.getAttribute('placeholder')||'').join('\n')).slice(0,max)}),args.max_chars??26000);
  }
  if(action==='screenshot')return {path:await page.screenshot({path:args.path})};
  const supported=['click','fill','upload','cdp'];
  if(!supported.includes(action))fail('ego_command_unsupported','Unsupported native command: '+action);
  // Capture and consume events in the same Node round as the action. Ego event
  // buffers cannot survive a subprocess boundary. Headers/cookies are never kept.
  const capture=state.capture&&(action!=='cdp'||args.method==='Input.insertText'||
    (args.method==='Input.dispatchMouseEvent'&&args.params?.type==='mouseReleased')||
    (args.method==='Input.dispatchKeyEvent'&&args.params?.type==='keyUp'));
  const local={};
  if(capture){await page.cdp('Network.enable',{});await page.events();}
  let result;
  const actionStarted=Date.now();
  try {
    if(action==='cdp') {
      if(!/^(Input\.(dispatchMouseEvent|dispatchKeyEvent|insertText)|Emulation\.setFocusEmulationEnabled)$/.test(args.method))
        fail('ego_cdp_scope','Unsupported browser input protocol.');
      result=await page.cdp(args.method,args.params??{});
    } else if(action==='upload') {
      result=await page.setInputFiles(args.selector,args.files??args.paths);
    } else {
      if(!args.selector||args.selector.startsWith('@'))fail('ego_refs_unsupported','Use freshly observed DOM selectors, not stale snapshot refs.');
      const target=await page.evaluate(selector=>{
        const nodes=[...document.querySelectorAll(selector)].filter(el=>{
          for(let p=el;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return false;}
          const r=el.getBoundingClientRect();return r.width>0&&r.height>0;
        });
        if(nodes.length!==1)return {count:nodes.length};
        const el=nodes[0];el.scrollIntoView({block:'center',inline:'center',behavior:'instant'});
        const r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
        return {count:1,x,y,actionable:!!hit&&(hit===el||el.contains(hit)),disabled:!!el.disabled,fieldName:el.name||null};
      },args.selector);
      if(target.count!==1||!target.actionable||target.disabled)fail('ego_target_not_unique','No unique actionable current DOM target.');
      await page.cdp('Emulation.setFocusEmulationEnabled',{enabled:true});
      try {
        result=await page.mouse.click(target.x,target.y,{label:action==='fill'?'enter verified product content':'activate verified page control'});
        if(action==='fill'){
          await page.keyboard.press('ControlOrMeta+A');await page.keyboard.insertText(String(args.value??''));
          // Miaoshou replaces the product-ID input with a textarea on focus. The
          // native typing target must keep the same observed logical field name.
          const field={selector:args.selector,name:target.fieldName,value:String(args.value??'')};
          const typed=await page.evaluate(p=>{
            const el=document.querySelector(p.selector),active=document.activeElement;
            return el?.value===p.value||!!p.name&&active?.name===p.name&&active.value===p.value;
          },field);
          if(typed!==true)fail('ego_fill_unconfirmed','Rendered input value differs after native typing.');
          await page.keyboard.press('Tab');
          const confirmed=await page.evaluate(p=>{
            const exact=document.querySelector(p.selector);
            if(exact?.value===p.value)return true;
            const fields=[...document.querySelectorAll('input,textarea')].filter(x=>x.name===p.name&&x.offsetParent!==null);
            return !!p.name&&fields.length===1&&fields[0].value===p.value;
          },field);
          if(confirmed!==true)fail('ego_fill_unconfirmed','Input did not retain the expected value after blur.');
        }
      } finally { await page.cdp('Emulation.setFocusEmulationEnabled',{enabled:false}); }
    }
  } finally {
    if(capture){
      const deadline=actionStarted+(action==='upload'?60000:30000),started=Date.now();
      while(Date.now()<deadline){
        for(const event of await page.events()){
          const p=event.params??{},id=p.requestId;
          if(event.method==='Network.requestWillBeSent'){
            const u=new URL(p.request.url);
            if(u.hostname==='v2-dd.chengji-inc.com'&&/^\/api\/v2\/(product|move)\//.test(u.pathname))
              local[id]={requestId:page.label+':'+actionStarted+':'+id,url:u.origin+u.pathname,method:p.request.method,requestBody:p.request.postData??'',completed:false};
          }
          const item=local[id];if(!item)continue;
          if(event.method==='Network.responseReceived')item.status=p.response.status;
          if(event.method==='Network.loadingFinished'||event.method==='Network.loadingFailed'){
            item.completed=true;
            if(event.method==='Network.loadingFinished')try{const b=await page.cdp('Network.getResponseBody',{requestId:id});if(!b.base64Encoded&&b.body.length<4000000)item.body=b.body;}catch{}
          }
        }
        const records=Object.values(local);
        if(Date.now()-started>=800&&records.every(r=>r.completed))break;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      for(const item of Object.values(local))state.requests[item.requestId]=item;
      const ids=Object.keys(state.requests);for(const id of ids.slice(0,-200))delete state.requests[id];
      await save();
    }
  }
  if(result?.dialog)fail('ego_dialog_required','A page confirmation dialog needs handling; action is not replayed.');
  return {success:true,...(result??{})};
}
