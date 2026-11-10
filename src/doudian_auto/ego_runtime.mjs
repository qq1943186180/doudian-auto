// Runs inside the documented ego-browser Node runtime. No new browser/profile and
// no direct website writes: every mutation uses the page's ordinary controls.
export function redactOfficialSchema(body) {
  const data=JSON.parse(body,(_key,value)=>{
    if(typeof value==='number'&&Number.isInteger(value)&&!Number.isSafeInteger(value))
      throw new Error('Unsafe numeric ID in official response');
    return value;
  });
  const context=data.data?.context,model=data.data?.model;
  if(!context||!model)throw new Error('Official product schema missing');
  // Keep only product identity and field values. Schema context also contains
  // tokens; component actions and capability metadata are not readback evidence.
  return JSON.stringify({errno:data.errno,code:data.code,data:{context:{
    product_id:context.product_id,shop_id:context.shop_id,
    operation_type:context.operation_type,model_type:context.model_type},model:{
    sku_detail:{value:model.sku_detail?.value},spec_detail:{value:model.spec_detail?.value}}}});
}

export function inspectBatchSave(expected) {
  const visible=el=>{
    if(!el||el.offsetParent===null)return false;
    for(let node=el;node;node=node.parentElement){const s=getComputedStyle(node);if(s.display==='none'||s.visibility==='hidden'||node.inert)return false;}
    return true;
  };
  const buttons=[...document.querySelectorAll('button.J_batchEditProduct')].filter(visible);
  const refusal=reason=>({valid:false,count:buttons.length,reason});
  const url=new URL(location.href);
  if(url.hostname!=='v2-dd.chengji-inc.com'||url.pathname!=='/product/batch/edit'||url.searchParams.get('batchType')!=='multi_field')return refusal('route');
  if(buttons.length!==1||buttons[0].disabled||buttons[0].getAttribute('aria-disabled')==='true'||buttons[0].innerText.replace(/\s+/g,' ').trim()!=='开始批量修改')return refusal('button');
  if([...document.querySelectorAll('.replace-image-dialog,.select-product-filter-dialog,.preview-detail-dialog')].some(visible))return refusal('modal');
  const shop=(document.body.innerText.match(/您好【([^】]+)】/)||[])[1];
  const ids=[...document.querySelectorAll('textarea')].filter(x=>visible(x)&&(x.placeholder||'').includes('请输入商品ID'));
  const titles=[...document.querySelectorAll('textarea[name=inputNewContent]')].filter(visible);
  if(shop!==expected.shop||ids.length!==1||ids[0].value.trim()!==expected.product_id||titles.length!==1||titles[0].value!==expected.title)return refusal('identity');
  const checks=[...document.querySelectorAll('input[type=checkbox]')].filter(x=>visible(x)&&!x.disabled&&x.checked).map(x=>x.value);
  const same=(a,b)=>JSON.stringify([...a].sort())===JSON.stringify([...b].sort());
  if(!same(checks.filter(x=>expected.top_fields.includes(x)),expected.required_fields)||!same(checks.filter(x=>!expected.top_fields.includes(x)),expected.options))return refusal('fields');
  const radios=[...document.querySelectorAll('input[type=radio]:checked')].filter(visible);
  if(!radios.some(x=>x.name==='contentType'&&x.value==='replaceImgByIndex')||!radios.some(x=>x.name==='overlengthType'&&x.value==='fail'))return refusal('method');
  const key=value=>{try{const u=new URL(value);return u.pathname.includes('ecom-shop-material/')?'material:'+u.pathname.split('ecom-shop-material/')[1].split(/[~?]/)[0]:u.origin+u.pathname;}catch{return null;}};
  const read=box=>{const img=box?.querySelector('img');return img?key(img.currentSrc||img.src):null;};
  const mains=[...document.querySelectorAll('.replace-img-item .add-img-box')].filter(visible).map(read);
  const pairs=[...document.querySelectorAll('.base-edit-list')].filter(x=>visible(x)&&x.querySelectorAll('.add-img-box').length===2).map(x=>[...x.querySelectorAll('.add-img-box')].map(read));
  if(mains.length!==5||pairs.length!==4||JSON.stringify(mains)!==JSON.stringify(expected.mains.map(key))||JSON.stringify(pairs)!==JSON.stringify(expected.pairs.map(p=>p.map(key))))return refusal('assets');
  return {valid:true,count:1};
}

export async function runEgo(request) {
  const fs = await import('node:fs/promises');
  const {action,args={},statePath,session,runId} = request;
  if (action === 'status') { await listTaskSpaces(); return {connected:true}; }
  let state;
  try { state=JSON.parse(await fs.readFile(statePath,'utf8')); }
  catch(e) { if(e.code!=='ENOENT')throw e; state={pages:{},requests:{},capture:false}; }
  const save=()=>fs.writeFile(statePath,JSON.stringify(state),'utf8');
  const fail=(code,message)=>{ const error=new Error(message);error.code=code;throw error; };
  if(!state.finished&&state.cleanup?.phase==='finishing')
    fail('ego_cleanup_unknown','Task-page cleanup outcome is unknown; do not repeat finish or reopen pages.');
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
  const native=state.interaction_mode==='native';
  const ensureViewport=async page=>{
    if(native)return; // Let Ego handle background layout and scrolling itself.
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
    state.cleanup={phase:'finishing',scope:'task_pages',browser_exit_requested:false,
      owned_labels:tabs.filter(t=>t.openedBy==='agent').map(t=>t.label),started_at:Date.now()};
    await save();
    await task.finish({keep:[]});state.finished=true;
    state.cleanup.phase='finished';state.cleanup.finished_at=Date.now();await save();
    return {closed:count,scope:'task_pages',browser_exit_requested:false};
  }
  // A Page handle can outlive its actual tab. Never retarget a write after loss.
  const liveTabs=await task.tabs();
  const owned=new Set(liveTabs.filter(t=>t.openedBy==='agent').map(t=>t.label));
  const lostRoutes=new Set();
  for(const [key,label] of Object.entries(state.pages))if(!owned.has(label)){lostRoutes.add(key);delete state.pages[key];}
  let page=owned.has(state.active)?task.page(state.active):null;
  if(action==='navigate') {
    const u=new URL(args.url);
    if(!['v2-dd.chengji-inc.com','fxg.jinritemai.com'].includes(u.hostname)||u.protocol!=='https:')
      fail('ego_navigation_scope','Only the current shop project sites are supported.');
    const key=u.hostname+u.pathname+(u.searchParams.has('batchType')?'?batchType='+u.searchParams.get('batchType'):'');
    if(state.pages[key]) page=task.page(state.pages[key]);
    else if(lostRoutes.has(key)||!page||Object.keys(state.pages).length) page=await task.newPage();
    state.pages[key]=page.label;state.active=page.label;await save();
    await ensureViewport(page);
    // The official editor can stay interactive while unrelated resources keep
    // the load event pending. Field/identity readiness is checked by the caller.
    await page.goto(args.url,{waitUntil:'domcontentloaded',timeout:15000});
    return {success:true,tabId:page.label,url:await page.url()};
  }
  if(action==='close_tab') {
    const tabs=await task.tabs(),tab=tabs.find(t=>t.label===state.active);
    if(!tab||tab.openedBy!=='agent')fail('ego_user_page_protected','No task-owned page to close.');
    await page.close();
    for(const [key,label]of Object.entries(state.pages))if(label===state.active)delete state.pages[key];
    state.active=(await task.pages())[0]?.label;await save();return {closed:true};
  }
  if(!page) { await save(); fail('ego_active_page_missing','Owned active Page closed; only an explicit navigation may create a replacement.'); }
  if(action==='network') {
    if(args.cmd==='start'||args.cmd==='stop'){state.capture=args.cmd==='start';await save();return {success:true};}
    if(args.cmd==='list')return {requests:Object.values(state.requests).filter(r=>!args.filter||r.url.includes(args.filter)).map(({body,requestBody,...r})=>r)};
    if(args.cmd==='detail')return state.requests[args.requestId]??{};
    fail('ego_network_command','Unsupported network observation.');
  }
  await ensureViewport(page);
  if(action==='batch_save_probe')return await page.evaluate(inspectBatchSave,args.guard);
  if(action==='checkbox') {
    const current=await page.evaluate(selector=>{
      const xs=[...document.querySelectorAll(selector)].filter(x=>{
        if(x.tagName!=='INPUT'||!['checkbox','radio'].includes(x.type)||x.disabled||x.offsetParent===null)return false;
        const visual=x.parentElement?.querySelector(x.type==='radio'?'.el-radio__inner':'.el-checkbox__inner');
        const rect=visual?.getBoundingClientRect();
        return !!rect&&rect.width>0&&rect.height>0&&visual.closest('label')===x.closest('label');
      });
      return {count:xs.length,checked:xs.length===1?xs[0].checked:null,type:xs[0]?.type};
    },args.selector);
    if(current.count!==1||typeof args.checked!=='boolean'||(current.type==='radio'&&!args.checked))fail('ego_checkbox_not_unique','No unique observed enabled check control.');
    if(current.checked===args.checked)return {unchanged:true,checked:current.checked};
    if(native){
      // A method label can wrap its whole textarea/image form. Its center is
      // not the switch. Use the observed visual box beside this exact input.
      const selector='span:has(> '+args.selector+') > '+(current.type==='radio'?'.el-radio__inner':'.el-checkbox__inner');
      const labels=await page.evaluate(s=>{
        const xs=[...document.querySelectorAll(s)].filter(x=>x.offsetParent!==null);
        const r=xs.length===1?xs[0].getBoundingClientRect():null;
        const onBatch=location.hostname==='v2-dd.chengji-inc.com'&&location.pathname==='/product/batch/edit';
        const hit=onBatch&&r?document.elementFromPoint(r.x+r.width/2,r.y+r.height/2):null;
        return {count:xs.length,footerOccluded:!!hit?.closest('.batch-edit-footer-ms')};
      },selector);
      if(labels.count!==1)fail('ego_checkbox_not_unique','No unique native control label.');
      // A measured native click on the unselected detail switch hit the fixed
      // footer. Center only this observed obstruction before one ordinary click.
      if(labels.footerOccluded)await page.evaluate(s=>document.querySelector(s)?.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'}),selector);
      await page.click(selector,{label:'select verified modification option'});
      await page.waitForFunction(p=>document.querySelector(p.selector)?.checked===p.checked,args,{timeout:3000});
      const checked=await page.evaluate(s=>document.querySelector(s)?.checked,args.selector);
      if(checked!==args.checked)fail('ego_checkbox_unconfirmed','Native control did not retain expected state.');
      return {changed:true,checked};
    }
    // Element Plus keeps the accessible input at zero size. The documented focus
    // wrapper rejects it, while DOM.focus + one trusted Space works even when the
    // Ego window is minimized. Never assign checked or dispatch synthetic events.
    await page.cdp('Emulation.setFocusEmulationEnabled',{enabled:true});
    try {
      const doc=await page.cdp('DOM.getDocument',{depth:0});
      const node=await page.cdp('DOM.querySelector',{nodeId:doc.root.nodeId,selector:args.selector});
      if(!node.nodeId)fail('ego_checkbox_not_unique','Checkbox disappeared before focus.');
      await page.cdp('DOM.focus',{nodeId:node.nodeId});
      const focused=await page.evaluate(selector=>document.activeElement===document.querySelector(selector),args.selector);
      if(!focused)fail('ego_checkbox_focus_failed','Checkbox focus was not confirmed.');
      await page.keyboard.press('Space');
      return {changed:true,checked:await page.evaluate(selector=>document.querySelector(selector)?.checked,args.selector)};
    }finally{await page.cdp('Emulation.setFocusEmulationEnabled',{enabled:false});}
  }
  if(action==='official_sku_read') {
    const url=new URL(await page.url());
    if(url.hostname!=='fxg.jinritemai.com'||url.pathname!=='/ffa/g/create'||
       url.searchParams.get('product_id')!==String(args.product_id))
      fail('wrong_identity','Official SKU read requires the exact current product editor.');
    await page.cdp('Network.enable',{});await page.events();
    const started=Date.now(),requests=new Map();
    await page.reload({waitUntil:'domcontentloaded',timeout:15000}); // UI reload only; no business API replay.
    while(Date.now()-started<30000){
      for(const event of await page.events()){
        const p=event.params??{},id=p.requestId;
        if(event.method==='Network.requestWillBeSent'){
          const u=new URL(p.request.url);
          if(u.origin==='https://fxg.jinritemai.com'&&u.pathname==='/product/tproduct/getSchema'&&p.request.method==='POST')
            requests.set(id,{requestId:page.label+':'+started+':'+id,url:u.origin+u.pathname,status:null});
        }
        const item=requests.get(id);if(!item)continue;
        if(event.method==='Network.responseReceived')item.status=p.response.status;
        if(event.method==='Network.loadingFinished'&&item.status===200){
          const response=await page.cdp('Network.getResponseBody',{requestId:id});
          if(response.base64Encoded||response.body.length>4000000)
            fail('official_sku_schema_invalid','Official schema encoding or size changed.');
          let body;
          try{body=redactOfficialSchema(response.body);}
          catch{fail('official_sku_schema_invalid','Official schema cannot be read without losing identity.');}
          return {...item,completed:true,page_url:await page.url(),body};
        }
      }
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    fail('official_sku_read_timeout','No fresh official product schema was observed; no reload retry.');
  }
  if(action==='evaluate')return {value:await page.evaluate(args.code)};
  if(action==='snapshot') {
    if(native){
      const page_identity=await page.evaluate(()=>({
        shop:(document.body.innerText.match(/您好【([^】]+)】/)||[])[1]??null,
        batch_id_fields:[...document.querySelectorAll('textarea')].filter(x=>x.offsetParent!==null&&(x.placeholder||'').includes('请输入商品ID')).length,
        batch_title_fields:[...document.querySelectorAll('textarea[name=inputNewContent]')].filter(x=>x.offsetParent!==null).length,
        batch_title_options:[...document.querySelectorAll('input[type=checkbox][value=title]')].filter(x=>x.offsetParent!==null).length,
        batch_scope_tabs:[...document.querySelectorAll('[role=tab]')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='按商品ID修改').length
      }));
      try {
        return {url:await page.url(),observation_kind:'native_snapshot',page_identity,
          tree_text:String(await page.snapshot()).slice(0,args.max_chars??26000)};
      } catch(error) {
        // Live p4: identity evaluation succeeded, but Snapshot's frame-tree query
        // timed out. A text read is sufficient for readiness, never for ref clicks.
        if(error?.code!=='EGO_CDP_REQUEST_TIMEOUT'||!String(error.message).includes('Page.getFrameTree')||
           error.mayHaveLateEffects===true||error.executionStopped===false)throw error;
        const observed=await page.evaluate(max=>({url:location.href,tree_text:
          ((document.body?.innerText||'')+'\n'+[...document.querySelectorAll('input,textarea')]
            .filter(x=>x.offsetParent!==null).map(x=>x.getAttribute('placeholder')||'').join('\n')).slice(0,max)}),args.max_chars??26000);
        return {...observed,observation_kind:'dom_text_after_frame_tree_timeout',page_identity,
          native_snapshot_error:'EGO_CDP_REQUEST_TIMEOUT: Page.getFrameTree'};
      }
    }
    // DOM text avoids Ego's snapshot-ref file-lock failure. No fabricated refs.
    return await page.evaluate(max=>({url:location.href,observation_kind:'dom_text',tree_text:
      ((document.body?.innerText||'')+'\n'+[...document.querySelectorAll('input,textarea')]
        .filter(x=>x.offsetParent!==null).map(x=>x.getAttribute('placeholder')||'').join('\n')).slice(0,max)}),args.max_chars??26000);
  }
  if(action==='screenshot')return {path:await page.screenshot({path:args.path})};
  const supported=['click','fill','upload','cdp','activate_batch_save'];
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
      if(native){
        if(args.method!=='Emulation.setFocusEmulationEnabled')fail('ego_native_input_required','Native pilot requires Page input controls.');
        result={skipped:true};
      }else result=await page.cdp(args.method,args.params??{});
    } else if(action==='activate_batch_save') {
      const observed=await page.evaluate(inspectBatchSave,args.guard);
      const precheck=message=>{const e=new Error(message);e.code='ego_save_precheck_failed';e.inputDispatched=false;throw e;};
      if(!observed.valid)precheck('Batch save control or bound product content changed: '+observed.reason);
      if(native){
        // The durable caller already persisted intent; dispatch exactly once.
        result=await page.click('button.J_batchEditProduct',{label:'save verified single product revision'});
      }else{
      await page.cdp('Emulation.setFocusEmulationEnabled',{enabled:true});
      try {
        const doc=await page.cdp('DOM.getDocument',{depth:0});
        const node=await page.cdp('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'button.J_batchEditProduct'});
        if(!node.nodeId)precheck('Batch save button disappeared before focus.');
        await page.cdp('DOM.focus',{nodeId:node.nodeId});
        const focused=await page.evaluate(()=>document.activeElement?.matches('button.J_batchEditProduct'));
        const current=await page.evaluate(inspectBatchSave,args.guard);
        if(!focused||!current.valid)precheck('Batch save focus or bound content was not confirmed.');
        // Exactly one ordinary keyboard activation; errors after this point stay unknown.
        result=await page.keyboard.press('Enter');
      }finally{await page.cdp('Emulation.setFocusEmulationEnabled',{enabled:false});}
      }
    } else if(action==='upload') {
      result=await page.setInputFiles(args.selector,args.files??args.paths);
    } else {
      if(!args.selector||args.selector.startsWith('@'))fail('ego_refs_unsupported','Use freshly observed DOM selectors, not stale snapshot refs.');
      if(native){
        const observed=await page.evaluate(selector=>{
          const xs=[...document.querySelectorAll(selector)].filter(el=>{
            for(let n=el;n;n=n.parentElement){const s=getComputedStyle(n);if(s.display==='none'||s.visibility==='hidden')return false;}
            const r=el.getBoundingClientRect();return r.width>0&&r.height>0;
          });return {count:xs.length,disabled:!!xs[0]?.disabled,name:xs[0]?.name,
            imageFooter:xs.length===1&&xs[0].matches('.replace-img-item .add-img-box,.base-edit-list .add-img-box')&&
              location.hostname==='v2-dd.chengji-inc.com'&&location.pathname==='/product/batch/edit'&&
              !!document.querySelector('.batch-edit-footer-ms')};
        },args.selector);
        if(observed.count!==1||observed.disabled)fail('ego_target_not_unique','No unique enabled native control.');
        if(action==='click'){
          // Live task5: native nearest-scroll left detail4's center underneath
          // Miaoshou's fixed footer. Center only image slots on this proven route;
          // native click still resolves/hit-checks the element and dispatches once.
          if(observed.imageFooter)await page.evaluate(s=>document.querySelector(s)?.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'}),args.selector);
          result=await page.click(args.selector,{label:'activate verified product control'});
        }
        else {
          await page.fill(args.selector,String(args.value??''));
          const field={selector:args.selector,name:observed.name,value:String(args.value??'')};
          const confirmed=await page.evaluate(p=>{
            const xs=[...document.querySelectorAll('input,textarea')].filter(x=>x.offsetParent!==null&&(x.matches(p.selector)||p.name&&x.name===p.name));
            return xs.length===1&&xs[0].value===p.value;
          },field);
          if(!confirmed)fail('ego_fill_unconfirmed','Native input differs from the exact intended value.');
        }
      }else{
      const target=await page.evaluate(selector=>{
        const nodes=[...document.querySelectorAll(selector)].filter(el=>{
          for(let p=el;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return false;}
          const r=el.getBoundingClientRect();return r.width>0&&r.height>0;
        });
        if(nodes.length!==1)return {count:nodes.length};
        const el=nodes[0];el.scrollIntoView({block:'center',inline:'center',behavior:'instant'});
        const r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
        const pickerControl=el.matches('.replace-image-dialog .el-dialog__headerbtn,.select-product-filter-dialog .el-dialog__headerbtn')||
          (el.matches('.replace-image-dialog button,.select-product-filter-dialog button')&&/^(关闭|确定)$/.test(el.innerText.trim()));
        const imageSlot=(el.matches('.replace-img-item .add-img-box,.base-edit-list .add-img-box')||pickerControl)&&
          location.hostname==='v2-dd.chengji-inc.com'&&location.pathname==='/product/batch/edit';
        return {count:1,x,y,actionable:!!hit&&(hit===el||el.contains(hit)),disabled:!!el.disabled,fieldName:el.name||null,imageSlot};
      },args.selector);
      if(target.count!==1||!target.actionable||target.disabled)fail('ego_target_not_unique','No unique actionable current DOM target.');
      await page.cdp('Emulation.setFocusEmulationEnabled',{enabled:true});
      try {
        // Resolve the observed selector again through Ego's native action layer.
        // Its scroll/layout mapping can change after the precheck (notably under
        // a fixed viewport); dispatching the earlier DOM coordinates can miss.
        if(action==='click'&&target.imageSlot){
          // Native page.click may reset an emulated viewport before dispatch,
          // moving an image slot underneath its earlier screen coordinates.
          // Keep this pointer input in the measured CDP coordinate space.
          const point=await page.evaluate(selector=>{
            const xs=[...document.querySelectorAll(selector)];if(xs.length!==1)return null;
            const el=xs[0],pickerControl=el.matches('.replace-image-dialog .el-dialog__headerbtn,.select-product-filter-dialog .el-dialog__headerbtn')||
              (el.matches('.replace-image-dialog button,.select-product-filter-dialog button')&&/^(关闭|确定)$/.test(el.innerText.trim()));
            if(!el.matches('.replace-img-item .add-img-box,.base-edit-list .add-img-box')&&!pickerControl)return null;
            const r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
            return r.width>0&&r.height>0&&hit&&(hit===el||el.contains(hit))?{x,y}:null;
          },args.selector);
          if(!point||Math.abs(point.x-target.x)>1||Math.abs(point.y-target.y)>1)
            fail('ego_target_not_unique','Image slot moved before pointer input.');
          await page.cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...point});
          await page.cdp('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
          result=await page.cdp('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
        }else result=await page.click(args.selector,{label:action==='fill'?'enter verified product content':'activate verified page control'});
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
