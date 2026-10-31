/* Disposable preview only: distinguish checked files, full success and review. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path');
const manifest=JSON.parse(fs.readFileSync(process.env.MEDIA_PREVIEW_MANIFEST,'utf8'));
if(!manifest.root.startsWith('/tmp/media-platform-preview-')||fs.readFileSync(path.join(manifest.root,'.acceptance'),'utf8')!=='media-collection-preview')throw Error('Disposable preview required');
const base='http://127.0.0.1:18293',artifacts=process.env.MEDIA_BROWSER_ARTIFACTS;
fs.mkdirSync(artifacts,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://image.tmdb.org/**',r=>r.abort());
 await page.goto(base);await page.locator('[name=username]').fill('preview');
 await page.locator('[name=password]').fill('preview-password-123');await page.locator('#login button').click();
 await page.locator('.nav').waitFor();
 const id='e'.repeat(32);let succeeded=0;
 const job=()=>({job_id:id,state:'running',action:'auto',automatic:true,collection_id:null,
   completed:145,total:662,succeeded,review_count:145-succeeded,results:[],
   summary:{identified:4,linked:0,subtitles:0},analysis_progress:{phase:'identifying'},
   created_at:'2026-10-31 01:30:08',updated_at:'2026-10-31 01:35:30'});
 await page.route('**/api/command',async route=>{
   const op=route.request().postDataJSON()?.operation;let data;
   if(op==='library_task_status')data=job();
   else if(op==='library_task_details')data={task:job(),results:[{key:'m:1',name:'Episode.mkv',state:'needs_review',
     error_code:'analysis_season_evidence_missing',confidence:.98,reason:'Season source missing'}],next_cursor:null};
   else if(op==='library_tasks')data={tasks:[job()],next_cursor:null};
   else return route.continue();
   await route.fulfill({json:{success:true,data}});
 });
 for(const lang of ['zh-CN','en']){
   await page.evaluate(value=>localStorage.setItem('media-language',value),lang);
   for(const count of [0,84])for(const width of [320,390,768,1440]){
     succeeded=count;await page.setViewportSize({width,height:844});
     await page.goto(base+'/#tasks/'+id);await page.reload();
     await page.locator('#task-status progress').waitFor();await page.locator('.task-result').waitFor();
     const text=await page.locator('#task-status').innerText();
     const labels=lang==='zh-CN'?['\u5df2\u68c0\u67e5 145 / 662','\u5168\u90e8\u5b8c\u6210 '+count,'\u5f85\u590d\u6838 '+(145-count)]:['Checked 145 / 662','Fully completed '+count,'Needs review '+(145-count)];
     for(const label of labels)if(!text.includes(label))throw Error('Missing '+label+': '+text);
     const reason=await page.locator('.task-result').innerText();
     if(!reason.includes(lang==='zh-CN'?'\u7f3a\u5c11\u5bf9\u5e94\u5b63':'season evidence is missing'))throw Error('Missing specific review reason');
     if(lang==='en'&&/[\u3400-\u9fff]/.test(text))throw Error('Untranslated status');
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow at '+width);
     if(width===390)await page.screenshot({path:path.join(artifacts,`${lang}-${count}.png`),fullPage:true});
   }
 }
 if(errors.length)throw Error(errors.join('\n'));
 fs.writeFileSync(path.join(artifacts,'result.json'),JSON.stringify({passed:true,states:['zero success','partial success'],languages:['zh-CN','en'],widths:[320,390,768,1440],specific_season_reason:true}));
 await browser.close();console.log('Existing recovery browser acceptance passed');
})().catch(error=>{console.error(error);process.exit(1)});
