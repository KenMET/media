/* Browser-only acceptance with mocked APIs; no downloader, database or media mount. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../src/media_mcp/platform/static');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});page.setDefaultTimeout(10000);
  const errors=[],calls=[],jobs=new Map();let subscription=null,receiptMode='normal',holdStart=false,releaseStart=null,holdLatest=false,releaseLatest=null,currentKey=null,currentJob=null,plannedRelease=null;
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>sessionStorage.setItem('media-csrf','disposable-season-preview'));
  await page.route('http://media.test/**',async route=>{
   const request=route.request(),url=new URL(request.url());let data={};
   if(url.pathname.startsWith('/api/')){
    if(url.pathname==='/api/auth/setup-status')data={initialized:true};
    else if(url.pathname==='/api/auth/me')data={user:{id:'a'.repeat(32),username:'preview',role:'user',can_download:true,can_manage_media:true}};
    else if(url.pathname==='/api/status')data={worker_ready:true};
    else if(url.pathname==='/api/detail'&&url.searchParams.get('title_id')?.startsWith('movie:'))data={title_id:'movie:1',title:'Example Movie',kind:'movie',seasons:[]};
    else if(url.pathname==='/api/detail')data={title_id:'tv:1',title:'Example Show',kind:'tv',overview:'An overview that should stay collapsed so resources remain visible. '.repeat(30),seasons:[{season:1,episodes:12},{season:2,episodes:12},{season:3,episodes:12}]};
    else if(url.pathname==='/api/discover')data={items:[],page:1,total_pages:1};
    else if(url.pathname==='/api/command'){
     const command=request.postDataJSON();calls.push(command);
     if(command.operation==='search_releases'){
      const season=command.arguments.season;
      if(season==null){data={search_status:'complete',scope:{episodes:[]},releases:[{release_id:'9'.repeat(32),name:'Example Movie 1080p WEB-DL Complete Release Name',seeders:5,size:400,resolution:1080,indexer:'Fixture'}]};}
      else {
      if(season===3&&holdLatest)await new Promise(resolve=>{releaseLatest=resolve;});
      data={search_status:'partial',scope:{episodes:[1,2],known_episodes:[1,2,3]},releases:[
       {release_id:String(season).repeat(32),name:`Example S0${season} Complete 1080p WEB-DL English Multi Subtitle Long Release Name`,seeders:2,size:200,resolution:1080,indexer:'Fixture',coverage_kind:'season_pack',covered_episodes:[1,2]},
       {release_id:String(season+3).repeat(32),name:`Example S0${season}E01 1080p WEB-DL English Long Release Name`,seeders:100,size:100,resolution:1080,indexer:'Fixture',coverage_kind:'episode',covered_episodes:[1]}]};
      }
     }
     else if(command.operation==='plan'){
      if(receiptMode==='plan-denied')return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({success:false,error_code:'existing_media_or_active_job_review_required'})});
      plannedRelease=command.arguments.release_id;data={plan_id:'a'.repeat(32),revision:1,identity:{title:'Example Show'},release:{name:plannedRelease}};
     }
     else if(command.operation==='start'){
      currentKey=command.arguments.idempotency_key;
      currentJob={job_id:'d'.repeat(31)+(jobs.size+1).toString(16),revision:1,identity:{title:'Example Show'},release:{name:plannedRelease},stage:'completed',progress:1,created_at:'2026-01-01 00:00:00'};
      jobs.set(currentJob.job_id,currentJob);
      if(holdStart)await new Promise(resolve=>{releaseStart=resolve;});
      if(receiptMode==='lost')return route.abort('connectionreset');
      if(receiptMode==='invalid')return route.fulfill({contentType:'text/plain',body:'Unreadable acknowledgement'});
      if(receiptMode==='envelope')return route.fulfill({contentType:'application/json',body:'{}'});
      if(receiptMode==='malformed')return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,data:{}})});
      if(receiptMode==='gateway')return route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({success:false,error_code:'local_service_unavailable'})});
      data=currentJob;
     }
     else if(command.operation==='download_submission_status')data={found:currentKey===command.arguments.idempotency_key,task:currentJob};
     else if(command.operation==='job')data=jobs.get(command.arguments.job_id);

     else if(command.operation==='jobs')data={jobs:[],next_cursor:null};
     else if(command.operation==='subscription_create')data=subscription={request_id:'e'.repeat(32),revision:1,state:'active',title_id:'tv:1',season:command.arguments.season,resolution:1080,next_check_at:2000000000};
     else if(command.operation==='subscriptions')data={subscriptions:subscription?[subscription]:[]};
     else if(command.operation==='subscription_change')data=subscription={...subscription,state:command.arguments.state,revision:subscription.revision+1};
     else if(command.operation==='collections')data={collections:[],total:0,next_cursor:null,can_manage:true};
     else if(command.operation==='duplicates')data={groups:[{title_id:'movie:1',versions:[
      {id:1,target_path:'/library/first.mkv'},{id:2,target_path:'/library/second.mkv'}]}]};
     else if(command.operation==='duplicate_preview')data={plan_id:'f'.repeat(32),remove_targets:['/library/second.mkv']};
     else if(command.operation==='duplicate_apply')data={retired_versions:1};
     else data={items:[],tasks:[],jobs:[]};
    }
    return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,data})});
   }
   const name=url.pathname==='/'?'index.html':url.pathname.replace(/^\/assets\//,'');const file=path.resolve(root,name);
   if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:({'.js':'text/javascript','.css':'text/css','.html':'text/html'})[path.extname(file)]||'text/plain',body:fs.readFileSync(file)});
  });
  await page.goto('http://media.test/#title/tv:1');
  await page.locator('[data-action=season-subscribe]').waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.release-row').length===6);
  assert.match(await page.locator('.release-row').first().innerText(),/S03 Complete/);
  assert.deepEqual(await page.locator('.release-row .release-name').allTextContents(),[3,2,1].map(n=>`Example S0${n} Complete 1080p WEB-DL English Multi Subtitle Long Release Name`).concat([3,2,1].map(n=>`Example S0${n}E01 1080p WEB-DL English Long Release Name`)));
  assert.equal(await page.locator('#release-filter,#release-sort,#releases,[data-action=season-once],.release-row button').count(),0);
  assert.equal((await page.locator('[data-action=season-subscribe]').innerText()).trim(),'\u8ba2\u9605');
  assert.equal(await page.locator('#release-diagnostics').getAttribute('open'),null);
  const callsBefore=calls.filter(c=>c.operation==='search_releases').map(c=>c.arguments.season);
  assert.deepEqual(callsBefore,[3,2,1]);
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:640});
   const metrics=await page.locator('.release-row').evaluateAll(rows=>rows.map(row=>({height:row.getBoundingClientRect().height,bottom:row.getBoundingClientRect().bottom})));
   assert(metrics.every(row=>row.height<=96),JSON.stringify({width,metrics}));
   assert(metrics.filter(row=>row.bottom<=550).length>=2,'At least two complete resources must fit in a short phone viewport');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  await page.setViewportSize({width:390,height:640});
  await page.screenshot({path:process.env.RESOURCE_SCREENSHOT||'/tmp/media-compact-resources.png'});
  await page.locator('[data-action=language]').click();await page.waitForFunction(()=>document.querySelectorAll('.release-row').length===6);
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:640});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'English resource layout must not overflow');
   assert(await page.locator('.release-row').evaluateAll(rows=>rows.every(row=>row.getBoundingClientRect().height<=96)));
   assert(await page.locator('.release-row').evaluateAll(rows=>rows.filter(row=>row.getBoundingClientRect().bottom<=550).length>=2));
  }
  await page.setViewportSize({width:390,height:640});
  await page.screenshot({path:'/tmp/media-compact-resources-en.png'});
  assert.equal((await page.locator('[data-action=season-subscribe]').innerText()).trim(),'Subscribe');
  await page.locator('.release-row').first().click();await page.getByRole('heading',{name:'Release details',exact:true}).waitFor();
  await page.screenshot({path:'/tmp/media-resource-confirmation-en.png'});
  await page.locator('#modal').getByRole('button',{name:'Cancel',exact:true}).click();
  await page.locator('[data-action=language]').click();await page.waitForFunction(()=>document.querySelectorAll('.release-row').length===6);

  const count=operation=>calls.filter(call=>call.operation===operation).length;
  const secondSeason=page.locator('.release-row[data-release-id="'+ '2'.repeat(32)+'"]');
  await secondSeason.click();await page.locator('#modal[open]').waitFor();
  assert.match(await page.locator('.release-dialog-name').innerText(),/S02 Complete.*Long Release Name/);
  assert.equal(count('plan'),0);assert.equal(count('start'),0);
  await page.locator('[data-action=close-modal]').click();assert.equal(count('plan'),0);assert.equal(count('start'),0);
  await secondSeason.focus();await page.keyboard.press('Enter');await page.locator('#modal[open]').waitFor();
  await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('#modal[open]'));
  assert.equal(count('plan'),0);assert.equal(count('start'),0);

  // A late latest-season response must not change the resource already being reviewed.
  holdLatest=true;releaseLatest=null;await page.reload();
  await page.locator('.release-row[data-release-id="'+ '2'.repeat(32)+'"]').click();
  assert.match(await page.locator('.release-dialog-name').innerText(),/S02 Complete/);
  assert(releaseLatest);holdLatest=false;releaseLatest();
  await page.waitForFunction(()=>document.querySelectorAll('.release-row').length===6);
  assert.match(await page.locator('.release-dialog-name').innerText(),/S02 Complete/);
  await page.setViewportSize({width:320,height:480});
  assert(await page.locator('[data-action=close-modal]').evaluate(button=>{const r=button.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}));
  await page.screenshot({path:'/tmp/media-resource-confirmation.png'});
  holdStart=true;releaseStart=null;
  await page.locator('[data-action=confirm-release]').evaluate(button=>{button.click();button.click();button.click();});
  for(let attempt=0;attempt<100&&!releaseStart;attempt++)await new Promise(resolve=>setTimeout(resolve,10));
  assert(releaseStart);assert.equal(count('start'),1);assert.equal(count('plan'),1);
  assert.equal(calls.find(call=>call.operation==='plan').arguments.release_id,'2'.repeat(32));
  assert(await page.locator('[data-action=close-modal]').isDisabled());await page.keyboard.press('Escape');
  assert(await page.locator('#modal').evaluate(dialog=>dialog.open));holdStart=false;releaseStart();
  await page.waitForFunction(()=>location.hash.startsWith('#jobs/'));assert.equal(count('start'),1);

  // Lost, unreadable and gateway-failed receipts are observed using the same key, never resubmitted.
  for(const mode of ['lost','invalid','malformed','envelope','gateway']){
   receiptMode=mode;await page.goto('http://media.test/#title/tv:1');
   await page.locator('.release-row').first().click();const before=count('start');
   await page.locator('[data-action=confirm-release]').click();
   await page.waitForFunction(()=>location.hash.startsWith('#jobs/'));
   assert.equal(count('start'),before+1);
   assert(calls.some(call=>call.operation==='download_submission_status'&&call.arguments.idempotency_key===currentKey));
  }
  receiptMode='plan-denied';await page.goto('http://media.test/#title/tv:1');await page.locator('.release-row').first().click();
  const startsBeforeRejection=count('start');await page.locator('[data-action=confirm-release]').click();
  await page.locator('#toast').filter({hasText:'\u5df2\u6709\u5a92\u4f53'}).waitFor();
  assert.equal(count('start'),startsBeforeRejection);await page.locator('[data-action=close-modal]').click();
  receiptMode='normal';assert.equal(count('season_acquire'),0);assert.equal(count('subscription_create'),0);

  await page.goto('http://media.test/#title/tv:1');await page.locator('[data-action=season-subscribe]').click();
  await page.locator('#season-subscribe select[name=season]').selectOption('2');
  assert(await page.locator('#season-subscribe [data-action=close-modal]').evaluate(button=>{const r=button.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}));
  await page.screenshot({path:'/tmp/media-subscription-confirmation.png'});
  await page.locator('#season-subscribe [data-action=close-modal]').click();assert.equal(count('subscription_create'),0);
  await page.locator('[data-action=season-subscribe]').click();await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('#modal[open]'));assert.equal(count('subscription_create'),0);
  await page.goto('http://media.test/#title/tv:1');await page.locator('[data-action=season-subscribe]').click();await page.locator('#season-subscribe select[name=season]').selectOption('2');await page.locator('#season-subscribe button[type=submit]').click();
  await page.locator('[data-action=subscription-state][data-state=paused]').waitFor();
  assert.equal(calls.find(c=>c.operation==='subscription_create').arguments.season,2);
  await page.locator('[data-action=subscription-state][data-state=paused]').click();
  await page.locator('[data-action=subscription-state][data-state=active]').waitFor();
  await page.locator('[data-action=subscription-state][data-state=cancelled]').click();
  await page.waitForFunction(()=>!document.querySelector('[data-action=subscription-state]'));
  await page.goto('http://media.test/#title/movie:1');await page.locator('.release-row').first().click();
  assert.match(await page.locator('.release-dialog-name').innerText(),/Example Movie/);
  assert.doesNotMatch(await page.locator('.release-details').innerText(),/\u5b63|\u96c6\u6570/);
  await page.locator('[data-action=close-modal]').click();
  await page.goto('http://media.test/#duplicates');await page.locator('[data-action=duplicate-preview]').click();
  await page.locator('#modal[open]').waitFor();assert.equal(calls.filter(c=>c.operation==='duplicate_apply').length,0);
  await page.locator('[data-action=close-modal]').click();assert.equal(calls.filter(c=>c.operation==='duplicate_apply').length,0);
  await page.locator('[data-action=duplicate-preview]').click();await page.locator('[data-action=duplicate-confirm]').click();
  await page.waitForFunction(()=>!document.querySelector('#modal[open]'));
  assert.equal(calls.filter(c=>c.operation==='duplicate_apply').length,1);
  assert.equal(calls.find(c=>c.operation==='duplicate_apply').arguments.confirm,true);
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  await page.locator('[data-action=language]').click();await page.getByRole('heading',{name:'Duplicate versions',exact:true}).waitFor();
  assert.deepEqual(errors,[]);console.log('PASS: row preview/cancel, stable season identity, explicit confirmation, repeated taps, unknown receipts, cancellable subscription, compact bilingual layout');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
