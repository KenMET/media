/* Disposable browser acceptance: deterministic artwork and safe global action. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path');
const manifest=JSON.parse(fs.readFileSync(process.env.MEDIA_PREVIEW_MANIFEST,'utf8'));
if(!manifest.root.startsWith('/tmp/media-platform-preview-')||fs.readFileSync(path.join(manifest.root,'.acceptance'),'utf8')!=='media-collection-preview')throw Error('Disposable preview required');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage(),errors=[],calls=[],autoCalls=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://image.tmdb.org/**',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="78" height="117"><rect width="78" height="117" fill="#789456"/></svg>'}));
 await page.route('**/api/detail?**',r=>{const id=new URL(r.request().url()).searchParams.get('title_id');calls.push(id);return r.fulfill({json:{success:true,data:{title_id:id,poster_url:'https://image.tmdb.org/t/p/w342/test.jpg'}}});});
 await page.route('**/api/command',async route=>{
  const body=route.request().postDataJSON();
  if(body.operation==='library_auto'){autoCalls.push(body.arguments);return route.fulfill({status:400,json:{success:false,error_code:'permission_denied'}});}
  if(body.operation!=='collections')return route.continue();
  const response=await route.fetch(),payload=await response.json();
  const original={kind:'tv',year:'2024',summary:{files:1,main_files:1,mapped:1,main_mapped:1,subtitle_verified:1,main_subtitle_verified:1,subtitle_discovered:0,subtitle_missing:0,seasons:1,episodes:1,extras:0,identity_pending:0}};
  payload.data.collections=Array.from({length:6},(_,i)=>({...original,collection_id:String(i+1).padStart(32,'0'),title_id:'tv:'+String(i+1),title:'Known work '+i,poster_url:null,identified:true}));
  payload.data.total=6;payload.data.analysis_tasks=[];payload.data.next_cursor=null;
  return route.fulfill({json:payload});
 });
 await page.goto('http://127.0.0.1:18293');await page.locator('[name=username]').fill('preview');
 await page.locator('[name=password]').fill('preview-password-123');await page.locator('#login button').click();await page.locator('.nav').waitFor();
 for(const [width,columns] of [[1440,3],[1000,2],[390,1],[320,1]]){
  await page.setViewportSize({width,height:900});await page.goto('http://127.0.0.1:18293/#library');
  await page.locator('.collection-grid .collection-poster img').nth(5).waitFor();
  const actual=await page.locator('.collection-grid').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
  if(actual!==columns)throw Error(`Expected ${columns} columns at ${width}, got ${actual}`);
  if(await page.getByText('重新整理全部资源',{exact:true}).count())throw Error('Global forced action still exposed');
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Horizontal overflow');
  if(process.env.MEDIA_BROWSER_ARTIFACTS){fs.mkdirSync(process.env.MEDIA_BROWSER_ARTIFACTS,{recursive:true});await page.screenshot({path:path.join(process.env.MEDIA_BROWSER_ARTIFACTS,`library-${width}.png`),fullPage:true});}
 }
 await page.locator('[data-action=library-auto-all]').click();
 await page.locator('#toast').waitFor();
 if(autoCalls.length!==1||autoCalls[0].scope!=='pending'||autoCalls[0].collection_id!==null)throw Error('Global action requested full scope');
 if(calls.length!==6||new Set(calls).size!==6)throw Error('Artwork refetched or wrong identity');
 if(errors.length)throw Error(errors.join('\n'));
 await browser.close();console.log(JSON.stringify({passed:true,metadata_calls:calls.length,widths:[1440,1000,390,320]}));
})().catch(error=>{console.error(error);process.exit(1)});
