/* Disposable collection-preview acceptance. Never target a real media service. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path');
const manifest=JSON.parse(fs.readFileSync(process.env.MEDIA_PREVIEW_MANIFEST||'/tmp/media-collections-preview.json','utf8'));
if(!manifest.root.startsWith('/tmp/media-platform-preview-')||fs.readFileSync(path.join(manifest.root,'.acceptance'),'utf8')!=='media-collection-preview')throw Error('Disposable preview marker required');
const artifacts=process.env.MEDIA_BROWSER_ARTIFACTS||'/tmp/media-collections-acceptance';fs.mkdirSync(artifacts,{recursive:true});
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
await page.route('https://image.tmdb.org/**',route=>{const n=Number((route.request().url().match(/preview-(\d+)/)||[])[1]||3);const palettes=[['#253a41','#d6be91'],['#604336','#f0c782'],['#384930','#c8d2a2'],['#3e394d','#bdb6d5'],['#354c4b','#b0d0c4'],['#5a433f','#e6bfc0']];const [bg,fg]=palettes[n%palettes.length];return route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="342" height="513"><rect width="342" height="513" fill="${bg}"/><circle cx="220" cy="150" r="110" fill="${fg}" opacity=".4"/><path d="M-20 470L150 160L370 470" fill="${fg}" opacity=".35"/><text x="28" y="60" fill="${fg}" font-size="13" font-family="sans-serif" letter-spacing="3">COLLECTION / ${n}</text><text x="28" y="435" fill="${fg}" font-size="28" font-family="sans-serif">TEST STORIES</text><text x="28" y="468" fill="${fg}" font-size="13" font-family="sans-serif">DISPOSABLE PREVIEW</text></svg>`});});
async function command(operation,args={}){return page.evaluate(async({operation,args})=>{const response=await fetch('/api/command',{method:'POST',headers:{'content-type':'application/json','x-csrf-token':sessionStorage.getItem('media-csrf')},body:JSON.stringify({operation,arguments:args})});const envelope=await response.json();if(!response.ok)throw Error(envelope.error_code);return envelope.data;},{operation,args});}
async function noOverflow(label){const value=await page.evaluate(()=>({viewport:innerWidth,content:document.documentElement.scrollWidth}));if(value.content>value.viewport)throw Error(label+' overflow '+JSON.stringify(value));}
await page.goto('http://127.0.0.1:18293');await page.locator('[name=username]').fill('preview');await page.locator('[name=password]').fill('preview-password-123');await page.locator('#login button').click();await page.locator('.nav [data-page=library]').click();await page.getByRole('heading',{name:'\u4f60\u7684\u4f5c\u54c1\u5a92\u4f53\u5e93',exact:true}).waitFor();
let list=await command('collections');if(list.total!==5)throw Error('Expected four movies and one provisional TV collection');
let series=list.collections.find(item=>item.kind==='tv');if(series.summary.files!==3)throw Error('Episodes were not grouped');
if(await page.locator('.collection-card').count()!==5)throw Error('Unexpected per-episode cards');
await noOverflow('initial library');await page.screenshot({path:artifacts+'/mobile-library-before.png',fullPage:true});
await page.locator(`[data-action=library-open][data-id="${series.collection_id}"]`).click();await page.getByRole('heading',{name:'\u5b63\u96c6\u4e0e\u7248\u672c',exact:true}).waitFor();
await page.goBack();await page.getByRole('heading',{name:'\u4f60\u7684\u4f5c\u54c1\u5a92\u4f53\u5e93',exact:true}).waitFor();await page.goForward();await page.getByRole('heading',{name:'\u5b63\u96c6\u4e0e\u7248\u672c',exact:true}).waitFor();
async function advanced(){const panel=page.locator('.library-advanced');if(await panel.getAttribute('open')===null)await panel.locator('summary').click();}
async function identifySeason(season){
 await advanced();
 const bucket=page.locator(`.library-season[data-season="${season}"]`);if(await bucket.getAttribute('open')===null)await bucket.locator('summary').first().click();
 await page.getByRole('button',{name:'\u6e05\u7a7a\u9009\u62e9',exact:true}).click();await bucket.getByRole('button',{name:'\u9009\u62e9\u672c\u5b63\u6587\u4ef6',exact:true}).click();
 await page.getByRole('button',{name:'\u91cd\u65b0\u8bc6\u522b',exact:true}).click();await page.locator('#library-identify-search button[type=submit]').click();await page.locator('.library-candidate').nth(2).click();
 await page.locator('#library-identify-plan button[type=submit]').click();await page.getByRole('button',{name:'\u786e\u8ba4\u8bc6\u522b',exact:true}).waitFor();await noOverflow('identity preview');
 await page.screenshot({path:artifacts+`/identity-season-${season}.png`,fullPage:true});await page.getByRole('button',{name:'\u786e\u8ba4\u8bc6\u522b',exact:true}).click();await page.locator('#modal').waitFor({state:'hidden'});
}
await identifySeason(1);
list=await command('collections');series=list.collections.find(item=>item.title_id==='tv:3');if(list.total!==5||series.summary.identity_pending!==1||series.summary.files!==3)throw Error('Partial identification split the title or lost files');
await identifySeason(2);list=await command('collections');series=list.collections.find(item=>item.title_id==='tv:3');if(!series.identified||series.summary.episodes!==3||series.summary.seasons!==2)throw Error('Confirmed seasons missing');
await page.getByText('\u4f5c\u54c1\u8eab\u4efd\u5df2\u786e\u8ba4',{exact:true}).waitFor();await noOverflow('collection detail');await page.screenshot({path:artifacts+'/mobile-series-detail.png',fullPage:true});
await advanced();await page.getByRole('button',{name:'\u6e05\u7a7a\u9009\u62e9',exact:true}).click();
const source=path.join(manifest.source,'Island.S01E01.mkv'),target=path.join(manifest.library,'series/\u5c9b\u5c7f\u6f2b\u6e38/\u7b2c01\u5b63/\u5c9b\u5c7f\u6f2b\u6e38 - S01E01 - 2025.mkv');
if(fs.readFileSync(source,'utf8')!=='preview-episode'||fs.readFileSync(target,'utf8')!=='preview-episode')throw Error('Not a fixture file');
const original=fs.statSync(source).ino,subtitle=target.replace(/\.mkv$/,'.zh.srt'),subtitleBefore=fs.readFileSync(subtitle,'utf8');fs.unlinkSync(target);
await page.getByRole('button',{name:'\u68c0\u67e5\u6620\u5c04',exact:true}).click();await page.getByRole('button',{name:'\u6267\u884c\u5b89\u5168\u8865\u94fe',exact:true}).waitFor();await page.screenshot({path:artifacts+'/mapping-preview.png',fullPage:true});
const mappingResponse=page.waitForResponse(response=>response.url().endsWith('/api/command')&&response.request().postDataJSON()?.operation==='collection_mapping_apply');await page.getByRole('button',{name:'\u6267\u884c\u5b89\u5168\u8865\u94fe',exact:true}).click();const mapping=(await (await mappingResponse).json()).data;
async function finish(job){for(let i=0;i<30;i++){const status=await command('collection_task',{job_id:job.job_id});if(status.state==='completed')return status;if(['needs_review','completed_with_warnings'].includes(status.state))throw Error(JSON.stringify(status));await page.waitForTimeout(250);}throw Error('Maintenance timeout');}
await finish(mapping);if(fs.statSync(source).ino!==original||fs.statSync(target).ino!==original)throw Error('Source or hardlink changed');
await page.locator('#modal').waitFor({state:'hidden'});await page.getByRole('button',{name:'\u5b57\u5e55\u5904\u7406',exact:true}).click();await page.locator('#library-subtitle-submit select').selectOption('recheck');
const subtitleResponse=page.waitForResponse(response=>response.url().endsWith('/api/command')&&response.request().postDataJSON()?.operation==='collection_subtitles');await page.locator('#library-subtitle-submit button[type=submit]').click();const subtitleJob=(await (await subtitleResponse).json()).data;await finish(subtitleJob);
if(fs.readFileSync(subtitle,'utf8')!==subtitleBefore)throw Error('Valid subtitle bytes changed');
await page.reload();await page.locator('.nav [data-page=library]').click();await page.getByRole('heading',{name:'\u4f60\u7684\u4f5c\u54c1\u5a92\u4f53\u5e93',exact:true}).waitFor();if(await page.locator('.collection-card').count()!==5)throw Error('Collection grouping lost after reload');
await page.screenshot({path:artifacts+'/mobile-library-after.png',fullPage:true});
for(const width of [320,375,390,430,768,1440]){await page.setViewportSize({width,height:900});await noOverflow('library '+width);await page.screenshot({path:artifacts+`/library-${width}.png`,fullPage:true});}
await page.setViewportSize({width:390,height:844});await page.locator(`[data-action=library-open][data-id="${series.collection_id}"]`).click();await page.getByRole('heading',{name:'\u5b63\u96c6\u4e0e\u7248\u672c',exact:true}).waitFor();await noOverflow('detail final');
await page.locator('.language-switch').click();await page.locator('.nav [data-page=library]').click();await page.getByRole('heading',{name:'Your collection',exact:true}).waitFor();await noOverflow('English library');await page.screenshot({path:artifacts+'/mobile-library-en.png',fullPage:true});
if(errors.length)throw Error(errors.join('\n'));fs.writeFileSync(artifacts+'/result.json',JSON.stringify({passed:true,collections:5,series_files:3,seasons:2,checks:['grouping','browser back/forward','poster','partial identity without split','season selection','identity preview and confirmation','safe mapping repair','preserved source inode','subtitle task','preserved existing subtitle','reload persistence','320–1440px','English','no JS errors']},null,2));console.log('Collection browser acceptance passed: '+artifacts);await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
