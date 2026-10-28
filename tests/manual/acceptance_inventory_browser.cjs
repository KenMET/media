const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
const artifacts=process.env.MEDIA_BROWSER_ARTIFACTS||'/tmp/media-ui-acceptance';
// Run only against tests/manual/preview_platform.py and its disposable credentials.
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
 const page=await context.newPage();await page.route('https://image.tmdb.org/**',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="342" height="513"><rect width="342" height="513" fill="#324632"/></svg>'})); const errors=[];page.on('pageerror',e=>errors.push(e.message));
 fs.mkdirSync(artifacts,{recursive:true});
 await page.goto('http://127.0.0.1:18293');
 await page.screenshot({path:artifacts+'/mobile-login.png',fullPage:true});
 await page.locator('[name=username]').fill('preview');await page.locator('[name=password]').fill('preview-password-123');await page.locator('#login button[type=submit]').click();
 await page.locator('.poster-grid .poster-card').first().waitFor();
 await page.screenshot({path:artifacts+'/mobile-discover.png',fullPage:true});
 async function check(label){const sizes=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));if(sizes.scroll>sizes.width)throw new Error(label+' overflows '+JSON.stringify(sizes));}
 await check('discover');
 await page.locator('.nav [data-page=library]').click();await page.getByRole('button',{name:'扫描已有文件'}).click();
 await page.getByRole('button',{name:'扫描已有资源',exact:true}).click();
 if(process.env.MEDIA_BROWSER_EMPTY==='true'){
   await page.getByRole('heading',{name:'未发现可导入资源',exact:true}).waitFor();
   if(await page.getByRole('button',{name:'确认导入索引',exact:true}).count())throw new Error('Empty import button must not exist');
   if(!await page.getByText('扫描结果为 0 项，没有导入任何资源。',{exact:true}).isVisible())throw new Error('Empty scan must be explicit');
   const rejected=await page.evaluate(async()=>{
     const r=await fetch('/api/command',{method:'POST',headers:{'content-type':'application/json','x-csrf-token':sessionStorage.getItem('media-csrf')},body:JSON.stringify({operation:'inventory_import',arguments:{scan_id:sessionStorage.getItem('media-inventory-scan')}})});
     return {status:r.status,body:await r.json()};
   });
   if(rejected.status!==400||rejected.body.error_code!=='inventory_empty_scan')throw new Error('Empty import was not rejected');
   await page.screenshot({path:artifacts+'/empty-scan.png',fullPage:true});
   console.log('Empty scan browser acceptance passed.');await browser.close();return;
 }
 await page.getByRole('button',{name:'确认导入索引'}).waitFor();
 await page.screenshot({path:artifacts+'/mobile-scan-preview.png',fullPage:true});await check('scan preview');
 if(await page.locator('.disk-card').count()!==6)throw new Error('Expected six preview items');
 await page.getByRole('button',{name:'确认导入索引'}).click();await page.getByRole('heading',{name:'已保存的资源'}).waitFor();
 await page.screenshot({path:artifacts+'/mobile-imported.png',fullPage:true});
 await page.reload();await page.locator('.nav [data-page=library]').click();await page.getByRole('heading',{name:'远山来信',exact:true}).waitFor();
 if(process.env.MEDIA_BROWSER_NO_LINKS==='true'){
   if(await page.locator('.collection-card').count()<3)throw new Error('Unpaired resources disappeared from library');
 }else if(!await page.getByText('字幕待校验 1',{exact:true}).isVisible())throw new Error('Subtitle discovery state missing');
 await page.screenshot({path:artifacts+'/mobile-library.png',fullPage:true});await check('library');
 for(const width of [320,375,430,768,1440]){await page.setViewportSize({width,height:900});await check('library '+width);await page.screenshot({path:`${artifacts}/library-${width}.png`,fullPage:true});}
 await page.setViewportSize({width:390,height:844});
 await page.locator('.nav [data-page=jobs]').click();await page.getByRole('heading',{name:'下载任务',exact:true}).waitFor();await check('downloads');
 await page.screenshot({path:artifacts+'/mobile-downloads.png',fullPage:true});
 await page.locator('.nav [data-page=search]').click();await page.locator('#search [name=query]').fill('远山来信');await page.locator('#search button[type=submit]').click();await page.locator('#search-results .poster-button').first().waitFor();await check('search');
 await page.locator('#search-results .poster-button').first().click();await page.locator('#releases').waitFor();await check('title detail');
 await page.screenshot({path:artifacts+'/mobile-title.png',fullPage:true});
 await page.locator('.account-button').click();await page.getByRole('heading',{name:'我的账号',exact:true}).waitFor();await check('account');
 await page.getByRole('button',{name:'系统管理'}).click();await page.getByRole('heading',{name:'系统管理',exact:true}).waitFor();await check('admin');
 await page.getByRole('button',{name:'用户与权限'}).click();await page.getByRole('heading',{name:'用户管理',exact:true}).waitFor();await check('users');
 await page.screenshot({path:artifacts+'/mobile-users.png',fullPage:true});
 await page.locator('.language-switch').click();await page.getByRole('heading').first().waitFor();
 await page.locator('.nav [data-page=library]').click();await page.getByRole('button',{name:'Scan existing files'}).click();await page.getByRole('heading',{name:'Bring your collection home'}).waitFor();await check('english inventory');
 await page.screenshot({path:artifacts+'/mobile-inventory-en.png',fullPage:true});
 if(errors.length)throw new Error(errors.join('\n'));
 fs.writeFileSync(artifacts+'/result.json',JSON.stringify({passed:true,widths:[320,375,390,430,768,1440],checks:['login','discovery','disk preview','confirmed import','reload persistence','unverified subtitles','downloads','search','title detail','account','admin','users','English inventory','no horizontal overflow','no JS errors']},null,2));
 console.log('Browser acceptance passed; screenshots: '+artifacts);await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
