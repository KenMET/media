/* Injected APIs only: no real indexer or media configuration is mutated. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../src/media_mcp/platform/static');
const origin=process.env.MEDIA_BROWSER_ASSET_ORIGIN||'http://media.test';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:390,height:740}});page.setDefaultTimeout(12000);page.setDefaultNavigationTimeout(45000);
  let role='admin',holdSave=null,releaseSave=null,credentialFailure=false;const calls=[],errors=[];
  const data={revision:0,indexers:[{id:'public',name:'Public One',language:'en-US',configured:true,enabled:false},{id:'available',name:'Public Two',language:'zh-CN',configured:false,enabled:false}]};
  const job={job_id:'b'.repeat(32),stage:'needs_review',can_delete:true,progress:1,revision:1,identity:{title:'Existing Movie'},release:{name:'New H264 release'},error_code:'processing_needs_review',
   processing:[{stage:'ingest',state:'needs_review',error:'no_media_processed',result_json:JSON.stringify({created:0,relinked:0,existed:0,failed:0})},{stage:'subtitle',state:'succeeded',result_json:JSON.stringify({media_count:0,handled:0,missing:0,review:0,failed:0})}],
   library_outcome:{explains_review:true,retained_count:1,quality_review:true,items:[{name:'Existing HEVC Movie.mkv',reason:'quality_not_comparable',identity_unverified:true}],subtitle_no_media:true}};
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>sessionStorage.setItem('media-csrf','disposable-indexers'));
  await page.route(origin+'/**',async route=>{
   const request=route.request(),url=new URL(request.url());let result={};
   if(url.pathname.startsWith('/api/')){
    if(url.pathname==='/api/auth/setup-status')result={initialized:true};
    else if(url.pathname==='/api/auth/me')result={user:{id:'a'.repeat(32),username:'preview',role,can_download:true,can_manage_media:true}};
    else if(url.pathname==='/api/status')result={worker_ready:true};
    else if(url.pathname==='/api/settings/model')result={model:'fixture',effort:'low',revision:0};
    else if(url.pathname==='/api/settings/model/options')result={models:[]};
    else if(url.pathname==='/api/settings/jackett'){
     if(request.method()==='GET')result=data;
     else{
      const command=request.postDataJSON();calls.push(command);
      if(command.action==='configuration'){
       if(credentialFailure)return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({success:false,error_code:'jackett_admin_auth_required'})});
       result={id:command.site,configured:data.indexers.find(row=>row.id===command.site).configured,revision:'a'.repeat(64),fields:[{id:'freeleech',name:'Freeleech',type:'inputbool',value:false},{id:'mirror',name:'Mirror',type:'inputselect',value:'one',options:{one:'One',two:'Two'}}]};
      }else{
       const row=data.indexers.find(row=>row.id===command.site);
       if(command.action==='save'){if(holdSave)await holdSave;row.configured=true;row.enabled=true;}
       if(command.action==='enabled'){assert.equal(command.revision,data.revision);row.enabled=command.enabled;data.revision++;}
       if(command.action==='test')row.test={status:'passed',tested_at:2000000000};
       if(command.action==='remove'){assert.equal(command.confirm,true);row.configured=false;row.enabled=false;}
       result=data;
      }
     }
    }else if(url.pathname==='/api/command'){
     const command=request.postDataJSON();calls.push(command);
     if(command.operation==='library_tasks')result={tasks:[],next_cursor:null};
     else if(command.operation==='jobs')result={jobs:[job],next_cursor:null};
     else if(command.operation==='job')result=job;
     else if(command.operation==='download_delete_preview')result={plan_id:'c'.repeat(32),action:'download',title:'Existing Movie',file_count:0,torrent_count:1,files:[],directories:[],retained_directories:[]};
     else throw Error('Unexpected operation '+command.operation);
    }else throw Error('Unexpected API '+url.pathname);
    await route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,data:result})});return;
   }
   if(origin!=='http://media.test')return route.continue();
   const file=path.resolve(root,url.pathname==='/'?'index.html':url.pathname.replace(/^\/assets\//,''));
   if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   await route.fulfill({contentType:({'.js':'text/javascript','.css':'text/css','.html':'text/html'})[path.extname(file)]||'text/plain',body:fs.readFileSync(file)});
  });
  await page.goto(origin+'/#jobs/'+job.job_id,{waitUntil:'domcontentloaded'});await page.locator('.existing-library-notice').waitFor();
  assert.match(await page.locator('.existing-library-notice').innerText(),/Existing HEVC Movie/);
  assert(!await page.locator('#content').innerText().then(text=>text.includes('no_media_processed')));
  assert.equal(await page.locator('.phase-list .done').count(),1);
  assert((await page.locator('.processing-stage').nth(1).innerText()).includes('\u672a\u5904\u7406\uff1a\u6ca1\u6709\u5165\u5e93\u5a92\u4f53'));
  await page.locator('#section-navigation [data-page=jobs]').click();await page.locator('#jobs-table .badge').filter({hasText:'\u5df2\u6709\u5165\u5e93\u7248\u672c'}).waitFor();
  await page.locator('.avatar[data-page=settings]').click();await page.locator('[data-page=jackett]').click();await page.locator('.indexer-row').first().waitFor();
  assert.equal(await page.locator('.indexer-row').count(),2);
  await page.evaluate(()=>window.savedIndexerFilters=document.querySelector('#jackett-query'));
  await page.locator('#jackett-query').fill('zh-cn');assert.equal(await page.locator('.indexer-row').count(),1);await page.locator('#jackett-query').fill('');
  await page.locator('[data-action=jackett-enabled][data-id=public]').click();await page.locator('[data-action=jackett-enabled][data-enabled=false]').waitFor();
  await page.locator('[data-action=jackett-test][data-id=public]').click();await page.locator('.indexer-row').first().getByText(/\u8fde\u901a\u6027\u6d4b\u8bd5\u901a\u8fc7/).waitFor();
  assert(await page.evaluate(()=>savedIndexerFilters===document.querySelector('#jackett-query')));
  await page.locator('[data-action=jackett-config][data-id=available]').click();await page.locator('#modal[open]').waitFor();await page.locator('[data-action=close-modal]').click();assert(!calls.some(call=>call.action==='save'));
  await page.locator('[data-action=jackett-config][data-id=available]').click();await page.locator('#modal[open]').waitFor();
  await page.locator('#jackett-config [name=freeleech]').check();await page.locator('#jackett-config [name=mirror]').selectOption('two');
  holdSave=new Promise(resolve=>releaseSave=resolve);await page.evaluate(()=>{const button=document.querySelector('[data-action=jackett-save]');button.click();button.click();});
  await page.locator('[data-action=close-modal]:disabled').waitFor();await page.keyboard.press('Escape');assert(await page.locator('#modal').evaluate(node=>node.open));
  assert.equal(calls.filter(call=>call.action==='save').length,1);assert.deepEqual(calls.find(call=>call.action==='save').values,{freeleech:true,mirror:'two'});
  await page.goBack();await page.locator('#password').waitFor();await page.locator('.nav [data-page=jobs]').click();await page.locator('#jobs-table [data-action=job]').first().click();await page.locator('#content [data-action=delete-download]').click();await page.locator('#modal[open]').waitFor();
  assert(!await page.locator('[data-action=close-modal]').isDisabled());holdSave=null;releaseSave();
  await page.waitForTimeout(100);assert(await page.locator('#modal').evaluate(node=>node.open));await page.locator('[data-action=close-modal]').click();
  await page.locator('.avatar[data-page=settings]').click();await page.locator('[data-page=jackett]').click();await page.locator('[data-action=jackett-remove][data-id=available]').waitFor();
  await page.locator('[data-action=jackett-remove][data-id=available]').click();await page.locator('#modal[open]').waitFor();await page.locator('[data-action=close-modal]').click();assert(!calls.some(call=>call.action==='remove'));
  await page.locator('[data-action=jackett-remove][data-id=available]').click();await page.locator('[data-action=jackett-remove-confirm]').click();await page.locator('[data-action=jackett-config][data-id=available]').waitFor();
  assert.equal(calls.filter(call=>call.action==='remove').length,1);
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:740});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  await page.setViewportSize({width:390,height:740});await page.screenshot({path:'/tmp/media-jackett-settings.png'});
  credentialFailure=true;await page.locator('[data-action=jackett-config][data-id=public]').click();await page.locator('#toast').filter({hasText:'Jackett'}).waitFor();assert.equal(await page.locator('#modal[open]').count(),0);
  credentialFailure=false;await page.locator('[data-action=language]').click();await page.locator('.indexer-row').first().waitFor();await page.getByRole('heading',{name:'Jackett public sites',exact:true}).waitFor();
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:740});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  role='user';await page.reload({waitUntil:'domcontentloaded'});await page.locator('#password').waitFor();assert.equal(await page.locator('[data-page=jackett]').count(),0);
  assert(!calls.some(call=>['retry','start','library_auto','deletion_apply'].includes(call.operation)));assert.deepEqual(errors,[]);
  process.stdout.write('PASS: retained-library outcomes, zero-media subtitles, public-site settings, test/toggle/add/remove, consent fences, admin UI and bilingual responsive layout\n');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
