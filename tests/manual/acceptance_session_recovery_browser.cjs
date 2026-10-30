/* Fixed disposable preview endpoint; never point this at a production service. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
const base='http://127.0.0.1:18294';
const artifacts=process.env.MEDIA_BROWSER_ARTIFACTS||'/qa/session-artifacts';
fs.mkdirSync(artifacts,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://image.tmdb.org/**',r=>r.abort());
 await page.goto(base);await page.locator('[name=username]').fill('preview');
 await page.locator('[name=password]').fill('preview-password-123');await page.locator('#login button').click();
 await page.locator('.nav').waitFor();
 const id='f'.repeat(32);let mode='session';
 const job=()=>({job_id:id,state:'queued',action:'auto',automatic:true,collection_id:null,label:'Recovery fixture',
   completed:121,total:746,results:[],summary:{identified:121,linked:0,extras:0,subtitles:0},
   analysis_progress:{phase:mode==='session'?'waiting_session':'waiting_quota'},
   session_recovery:mode==='session'?{checks:2,next_check_at:'2099-01-01 00:00:00',observation:'thread_unavailable'}:null,
   quota_wait:mode!=='session'?{checks:6,next_check_at:'2099-01-01 00:00:00',...(mode==='probe'?{observation:'probe_unavailable',probe_error_code:'model_upstream_unavailable'}:{})}:null,
   error_code:mode==='session'?'model_session_waiting':'model_quota_waiting',
   created_at:'2026-10-30 01:00:00',updated_at:'2026-10-30 13:00:00'});
 await page.route('**/api/command',async route=>{
   const op=route.request().postDataJSON()?.operation;
   let data;
   if(op==='library_task_status')data=job();
   else if(op==='library_task_details')data={task:job(),results:[],next_cursor:null};
   else if(op==='library_tasks')data={tasks:[job()],next_cursor:null};
   else return route.continue();
   await route.fulfill({json:{success:true,data}});
 });
 for(const language of ['zh-CN','en']){
   await page.evaluate(value=>localStorage.setItem('media-language',value),language);
   for(const width of [320,390,768,1440]){
     await page.setViewportSize({width,height:844});mode='session';
     await page.goto(base+'/#tasks/'+id);await page.reload();
     await page.locator('#task-status progress').waitFor();
     let text=await page.locator('#task-status').innerText();
     if(!text.includes('2 / 3')||!text.includes('121 / 746'))throw Error('Missing durable recovery progress');
     if(language==='zh-CN'&&(!text.includes('旧会话')||text.includes('模型额度不足')))throw Error('Session failure confused with quota');
     if(language==='en'&&(!text.includes('session')||/[\u3400-\u9fff]/.test(text)))throw Error('Recovery translation incomplete');
     const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
     if(overflow)throw Error('Horizontal overflow at '+width);
     if(width===390)await page.screenshot({path:artifacts+'/session-'+language+'.png',fullPage:true});
     mode='quota';await page.reload();await page.locator('#task-status progress').waitFor();
     text=await page.locator('#task-status').innerText();
     if(!text.includes('6 / 10'))throw Error('Missing quota check budget');
     if(text.includes('2 / 3'))throw Error('Quota and session counters mixed');
     mode='probe';await page.reload();await page.locator('#task-status progress').waitFor();
     text=await page.locator('#task-status').innerText();
     if(language==='zh-CN'&&(!text.includes('连接失败')||text.includes('模型额度不足')))throw Error('Probe connection failure confused with quota');
     if(language==='en'&&!text.includes('could not connect'))throw Error('Missing probe failure explanation');
   }
 }
 if(errors.length)throw Error(errors.join('\n'));
 fs.writeFileSync(artifacts+'/result.json',JSON.stringify({passed:true,widths:[320,390,768,1440],languages:['zh-CN','en'],session_counter:'2/3',quota_counter:'6/10',progress:'121/746',page_errors:errors},null,2));
 await browser.close();console.log('Session recovery browser acceptance passed');
})().catch(error=>{console.error(error);process.exit(1);});
