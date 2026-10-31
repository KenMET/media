/* Exercises deletion only in an explicitly marked disposable preview. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path');
const manifest=JSON.parse(fs.readFileSync(process.env.MEDIA_PREVIEW_MANIFEST,'utf8'));
if(!manifest.root.startsWith('/tmp/media-platform-preview-')||fs.readFileSync(path.join(manifest.root,'.acceptance'),'utf8')!=='media-collection-preview')throw Error('Disposable preview required');
const base='http://127.0.0.1:18294',output=process.env.MEDIA_BROWSER_ARTIFACTS;
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],searches=[],previews=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',request=>{if(request.url().endsWith('/api/command')){const body=request.postDataJSON();if(body.operation==='search_titles')searches.push(body.arguments);}});
 page.on('response',async response=>{if(response.url().endsWith('/api/command')){const body=response.request().postDataJSON();if(body?.operation==='collection_delete_preview'){const result=await response.json();if(result.success)previews.push(result.data);}}});
 await page.route('https://image.tmdb.org/**',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="78" height="117"><rect width="78" height="117" fill="#789456"/></svg>'}));
 await page.goto(base);await page.locator('[name=username]').fill('preview');await page.locator('[name=password]').fill('preview-password-123');await page.locator('#login button').click();await page.locator('.nav').waitFor();
 await page.locator('[data-action=window][data-value=top]').click();await page.locator('.section-title h2').filter({hasText:'TMDB 历史高分'}).waitFor();
 await page.goto(base+'/#search');await page.locator('#search').waitFor();
 if(await page.locator('#search [name=kind],#search [name=year]').count())throw Error('Search still requires type or year');
 await page.locator('#search [name=query]').fill('Stories');await page.locator('#search button[type=submit]').click();await page.locator('#search-results [data-action=title]').first().waitFor();
 if(!searches.length||Object.keys(searches.at(-1)).join(',')!=='query')throw Error('Search arguments are not name-only');
 async function headerOrder(pageName){await page.goto(base+'/#'+pageName);await page.locator('.view-tabs').waitFor();const title=await page.locator('#content .heading').boundingBox(),tabs=await page.locator('.view-tabs').boundingBox();if(!title||title.y>=tabs.y)throw Error('Heading below tabs: '+pageName);}
 await headerOrder('jobs');
 if(await page.locator('.view-tabs [data-page=history]').count())throw Error('Separate history tab remains');
 const text=await page.locator('#jobs-table').innerText();if(text.indexOf('活动中')<0||text.indexOf('已完成与已结束')<text.indexOf('活动中'))throw Error('Active/completed grouping missing');
 const oldCount=await page.locator('#jobs-table tbody tr').count();
 await page.locator('#jobs-table [data-action=delete-download]').last().click();await page.locator('#deletion-confirm').waitFor();
 if(!await page.locator('[data-action=delete-confirm]').isDisabled())throw Error('Deletion lacks confirmation fence');
 await page.locator('[data-action=close-modal]').click();
 if(await page.locator('#jobs-table tbody tr').count()!==oldCount)throw Error('Preview mutated download task');
 await page.locator('#jobs-table [data-action=delete-download]').last().click();await page.locator('#deletion-confirm').check();await page.locator('[data-action=delete-confirm]').click();
 await page.locator('#jobs-table tbody tr').nth(oldCount-1).waitFor({state:'detached'});
 await headerOrder('tasks');
 await page.goto(base+'/#admin');await page.getByRole('heading',{name:'磁盘空间',exact:true}).waitFor();
 if(!(await page.locator('#content').innerText()).includes('剩余'))throw Error('Free disk space absent');
 const collectionResponse=await page.request.post(base+'/api/command',{data:{operation:'collections',arguments:{limit:24}},headers:{'x-csrf-token':await page.evaluate(()=>sessionStorage.getItem('media-csrf'))}});
 const collections=(await collectionResponse.json()).data.collections,item=collections.find(x=>x.title_id==='movie:1');if(!item)throw Error('Disposable movie fixture absent');
 const other=path.join(manifest.source,'Preview.Movie.2.mkv'),before=fs.readFileSync(other);
 for(const [width,columns] of [[1440,3],[1000,2],[390,1],[320,1]]){
  await page.setViewportSize({width,height:1000});await page.goto(base+'/#library');await page.locator('.collection-grid').waitFor();
  const count=await page.locator('.collection-grid').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);if(count!==columns)throw Error('Wrong library columns at '+width);
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow at '+width);
  if(output){fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,`library-${width}.png`),fullPage:true});}
 }
 await page.locator('[data-action=library-open][data-id="'+item.collection_id+'"]').click();await page.locator('.library-advanced>summary').click();
 await page.locator('[data-action=library-delete]').click();await page.locator('#deletion-confirm').waitFor();
 if(!previews.length)throw Error('No real deletion preview response');
 const preview=previews.at(-1);if(preview.files.some(file=>!file.startsWith(manifest.root+'/')))throw Error('Deletion escaped disposable fixture');
 if(output)await page.screenshot({path:path.join(output,'deletion-preview.png'),fullPage:true});
 await page.locator('#deletion-confirm').check();await page.locator('[data-action=delete-confirm]').click();await page.locator('.collection-grid').waitFor();
 for(const file of preview.files)if(fs.existsSync(file))throw Error('Planned file remains: '+file);
 if(!fs.readFileSync(other).equals(before))throw Error('Unselected media changed');
 // New headings must remain translated on both task pages and in management.
 await page.evaluate(()=>localStorage.setItem('media-language','en'));
 for(const route of ['jobs','tasks','admin']){await page.goto(base+'/#'+route);await page.reload();await page.locator('#content .heading').waitFor();const title=await page.locator('#content .heading').innerText();if(/[\u3400-\u9fff]/.test(title))throw Error('Untranslated heading: '+route);}
 if(errors.length)throw Error(errors.join('\n'));
 await browser.close();console.log(JSON.stringify({passed:true,search:'name-only',history:'merged',deletion:'disposable source/link removal with other media preserved',columns:[3,2,1,1]}));
})().catch(error=>{console.error(error);process.exit(1)});
