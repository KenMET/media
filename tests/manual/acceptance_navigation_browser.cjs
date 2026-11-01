/* Browser acceptance with injected APIs; no production state or media operations. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../src/media_mcp/platform/static');
// Live-asset mode still intercepts every API call; no production mutations are sent.
const origin=process.env.MEDIA_BROWSER_ASSET_ORIGIN||'http://media.test';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:390,height:740}});page.setDefaultTimeout(10000);
  const errors=[],calls=[],gates=new Map(),failures=new Set();const user='a'.repeat(32),jobId='b'.repeat(32);
  const job={job_id:jobId,stage:'completed',identity:{title:'Existing download'},release:{name:'Existing release'},progress:1,created_at:'2026-01-01 00:00:00'};
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(({user,jobId})=>{sessionStorage.setItem('media-csrf','disposable');sessionStorage.setItem('media-last-download-task:'+user,jobId);},{user,jobId});
  const hold=key=>{let release;const wait=new Promise(resolve=>release=resolve);gates.set(key,wait);return ()=>{gates.delete(key);release();};};
  await page.route(origin+'/**',async route=>{
   const request=route.request(),url=new URL(request.url());let data={},key=url.pathname;
   if(url.pathname.startsWith('/api/')){
    if(url.pathname==='/api/auth/setup-status')data={initialized:true};
    else if(url.pathname==='/api/auth/me')data={user:{id:user,username:'preview',role:'admin',can_download:true,can_manage_media:true}};
    else if(url.pathname==='/api/status')data={worker_ready:true};
    else if(url.pathname==='/api/discover'){
     key='catalog:'+url.searchParams.get('source')+':'+url.searchParams.get('kind')+':'+url.searchParams.get('window');
     data={items:Array.from({length:8},(_,n)=>({title_id:'movie:'+n,title:key+' '+n,kind:url.searchParams.get('kind'),date:'2026-01-01'})),page:1,total_pages:2,has_next:true};
    }else if(url.pathname==='/api/command'){
     const command=request.postDataJSON();calls.push(command);key=command.operation;
     if(key==='job')data=job;
     else if(key==='jobs')data={jobs:[{...job,identity:{...job.identity}}],next_cursor:null};
     else if(key==='library_tasks')data={tasks:[],next_cursor:null};
     else if(key==='subscriptions')data={subscriptions:[]};
     else if(key==='library_task_status')data={job_id:jobId,state:'completed_with_warnings',action:'auto',automatic:true,total:2,completed:2,review_count:1,summary:{},created_at:'2026-01-01 00:00:00'};
     else if(key==='library_task_details'){
      key='details:'+String(command.arguments.issues_only);
      data={results:[{key:'one',name:'Complete file',state:'completed'},{key:'two',name:'Review file',state:'needs_review'}].filter(row=>!command.arguments.issues_only||row.state!=='completed'),next_cursor:null};
     }
     else if(key==='collections'){
      key='collections:'+command.arguments.kind;
      data={collections:[],total:0,can_manage:true,analysis_tasks:[],next_cursor:null};
      if(command.arguments.kind==='movie')data={...data,total:1,collections:[{collection_id:'c'.repeat(32),title:'Example Movie',kind:'movie',identified:false,summary:{files:1,mapped:0,subtitle_verified:0,subtitle_discovered:0,subtitle_missing:1,extras:0}}]};
     }else if(key==='search_titles')data={titles:[]};
     else throw Error('Unexpected command '+key);
    }else throw Error('Unexpected API '+url.pathname);
    const fail=failures.delete(key);
    if(gates.has(key))await gates.get(key);
    try{await route.fulfill({status:fail?503:200,contentType:'application/json',body:JSON.stringify(fail?{success:false,error_code:'dependency_unavailable'}:{success:true,data})});}catch{}
    return;
   }
   if(origin!=='http://media.test')return route.continue();
   const name=url.pathname==='/'?'index.html':url.pathname.replace(/^\/assets\//,'');const file=path.resolve(root,name);
   if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   await route.fulfill({contentType:({'.js':'text/javascript','.css':'text/css','.html':'text/html'})[path.extname(file)]||'text/plain',body:fs.readFileSync(file)});
  });
  const noBanner=async()=>assert.equal(await page.locator('#background-work,.background-task').count(),0);
  const noOverflow=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),JSON.stringify(await page.evaluate(()=>({width:innerWidth,overflow:[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().right>innerWidth+1).map(el=>[el.className,el.textContent.slice(0,60)])}))));
  await page.goto(origin+'/#discover');await page.locator('.poster-card').first().waitFor();await noBanner();
  await page.evaluate(()=>{window.savedShell=document.querySelector('.layout');window.savedControls=document.querySelector('.filter-toolbar');window.savedSource=document.querySelector('[data-action=source][data-value=simkl]');});
  let release=hold('catalog:simkl:movie:week');await page.locator('[data-action=source][data-value=simkl]').click();
  await page.locator('#discover-results .spinner').waitFor();
  assert(await page.evaluate(()=>savedShell===document.querySelector('.layout')&&savedControls===document.querySelector('.filter-toolbar')&&savedSource===document.activeElement));
  assert.equal(await page.locator('[data-action=source][data-value=simkl]').getAttribute('aria-pressed'),'true');
  release();await page.locator('.poster-card').first().waitFor();
  assert.equal(await page.locator('[data-action=window][data-value=top]').isVisible(),false);
  await page.locator('[data-action=source][data-value=tmdb]').click();await page.locator('[data-action=window][data-value=top]').waitFor();
  failures.add('catalog:simkl:movie:week');await page.locator('[data-action=source][data-value=simkl]').click();await page.locator('#discover-results .error-state').waitFor();
  assert(await page.evaluate(()=>savedControls===document.querySelector('.filter-toolbar')));await page.locator('#discover-results .error-state button').click();await page.locator('.poster-card').first().waitFor();
  await page.locator('[data-action=source][data-value=tmdb]').click();await page.locator('.poster-card').first().waitFor();
  // An older delayed filter must never overwrite a newer selection.
  release=hold('catalog:tmdb:tv:week');await page.locator('[data-action=kind][data-value=tv]').click();await page.locator('#discover-results .spinner').waitFor();
  await page.locator('[data-action=window][data-value=top]').click();await page.locator('.poster-card').first().waitFor();
  assert.match(await page.locator('.poster-card').first().innerText(),/catalog:tmdb:tv:top/);release();
  await page.waitForTimeout(100);assert.match(await page.locator('.poster-card').first().innerText(),/catalog:tmdb:tv:top/);
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:740});await noOverflow();}
  await page.setViewportSize({width:390,height:740});await page.screenshot({path:'/tmp/media-stable-discover.png',fullPage:true});
  await page.locator('.nav [data-page=library]').click();await page.locator('#library-results .empty').waitFor();
  await page.evaluate(()=>{window.savedLibraryControls=document.querySelector('.library-toolbar');window.savedLibraryFilter=document.querySelector('[data-action=library-filter][data-kind=tv]');});
  release=hold('collections:tv');await page.locator('[data-action=library-filter][data-kind=tv]').click();await page.locator('#library-results .spinner').waitFor();
  assert(await page.evaluate(()=>savedLibraryControls===document.querySelector('.library-toolbar')&&savedLibraryFilter===document.activeElement));
  release();await page.locator('#library-results .empty').waitFor();
  await page.evaluate(()=>{window.savedLibraryInput=document.querySelector('#library-filter input');});
  release=hold('collections:tv');await page.locator('#library-filter input').fill('Example');await page.locator('#library-filter button').click();await page.locator('#library-results .spinner').waitFor();
  assert(await page.evaluate(()=>savedLibraryInput===document.querySelector('#library-filter input')&&savedLibraryInput.value==='Example'));release();await page.locator('#library-results .empty').waitFor();
  release=hold('collections:tv');await page.locator('[data-action=library-filter][data-kind=tv]').click();await page.locator('#library-results .spinner').waitFor();
  await page.locator('[data-action=library-filter][data-kind=movie]').click();await page.locator('.collection-card').waitFor();release();await page.waitForTimeout(100);assert.equal(await page.locator('.collection-card').count(),1);
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:740});await noOverflow();}
  await page.locator('.nav [data-page=jobs]').click();await page.locator('#jobs-table .table-wrap').waitFor();await noBanner();
  await page.evaluate(()=>{window.savedTaskTabs=document.querySelector('#section-navigation nav');window.savedJobInput=document.querySelector('#jobs-filter');});
  await page.locator('#jobs-filter').fill('Existing');release=hold('jobs');await page.locator('#content [data-action=refresh]').click();await page.locator('#jobs-table .spinner').waitFor();
  assert(await page.evaluate(()=>savedJobInput===document.querySelector('#jobs-filter')&&savedJobInput.value==='Existing'));release();await page.locator('#jobs-table .table-wrap').waitFor();
  release=hold('subscriptions');await page.locator('#section-navigation [data-page=subscriptions]').click();await page.locator('#content .spinner').waitFor();
  assert(await page.evaluate(()=>savedTaskTabs===document.querySelector('#section-navigation nav')&&savedShell===document.querySelector('.layout')));release();await page.locator('#content .empty').waitFor();
  await page.locator('#section-navigation [data-page=tasks]').click();await page.locator('#task-center-list .empty').waitFor();
  assert(await page.evaluate(()=>savedTaskTabs===document.querySelector('#section-navigation nav')));await noBanner();
  await page.locator('#section-navigation [data-page=jobs]').click();await page.locator('#jobs-table .table-wrap').waitFor();assert.equal(await page.locator('#jobs-filter').inputValue(),'Existing');
  await page.locator('#jobs-filter').fill('');
  const readsBefore=calls.filter(call=>call.operation==='jobs').length;release=hold('jobs');await page.evaluate(()=>window.dispatchEvent(new Event('online')));
  for(let attempt=0;attempt<100&&calls.filter(call=>call.operation==='jobs').length===readsBefore;attempt++)await new Promise(resolve=>setTimeout(resolve,10));
  assert(calls.filter(call=>call.operation==='jobs').length>readsBefore);gates.delete('jobs');job.identity.title='Fresh download';
  await page.locator('#content [data-action=refresh]').click();await page.waitForFunction(()=>document.querySelector('#jobs-table')?.textContent.includes('Fresh download'));
  release();await page.waitForTimeout(100);assert.match(await page.locator('#jobs-table').innerText(),/Fresh download/);
  await page.locator('.nav [data-page=search]').click();release=hold('search_titles');await page.locator('#search input').fill('Example');await page.locator('#search button').click();await page.locator('#search-results .spinner').waitFor();assert.equal(await page.locator('#search input').inputValue(),'Example');release();await page.locator('#search-results .empty').waitFor();await noBanner();
  await page.locator('.nav [data-page=discover]').click();await page.locator('.poster-card').first().waitFor();await page.locator('[data-action=language]').click();await page.locator('.poster-card').first().waitFor();
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:740});await noOverflow();}
  await page.setViewportSize({width:390,height:740});await page.screenshot({path:'/tmp/media-stable-discover-en.png',fullPage:true});
  await page.goto(origin+'/#tasks/'+jobId);await page.locator('.task-result').first().waitFor();
  await page.evaluate(()=>{window.savedResultFilter=document.querySelector('[data-action=task-results-filter][data-filter=issues]');});
  release=hold('details:true');await page.locator('[data-action=task-results-filter][data-filter=issues]').click();await page.locator('#task-results .spinner').waitFor();
  assert(await page.evaluate(()=>savedResultFilter===document.activeElement));
  await page.locator('[data-action=task-results-filter][data-filter=all]').click();await page.waitForFunction(()=>document.querySelectorAll('.task-result').length===2);
  release();await page.waitForTimeout(100);assert.equal(await page.locator('.task-result').count(),2);await noBanner();
  failures.add('details:true');await page.locator('.filter-group [data-action=task-results-filter][data-filter=issues]').click();await page.locator('#task-results .error-state').waitFor();
  await page.locator('#task-results .error-state button').click();await page.waitForFunction(()=>document.querySelectorAll('.task-result').length===1);
  assert.equal(await page.locator('.filter-group [data-filter=issues]').getAttribute('aria-pressed'),'true');
  assert(calls.some(call=>call.operation==='job'),'Existing download receipts must still recover without a banner');
  assert.deepEqual(errors,[]);assert(!calls.some(call=>['start','library_auto','subscription_create'].includes(call.operation)));
  process.stdout.write('PASS: stable shell, filter focus, scoped loaders, latest-response ownership, task tabs, no global banners, bilingual responsive layout\n');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
