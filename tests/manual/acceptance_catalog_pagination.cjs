/* Disposable browser acceptance: all API traffic is mocked; no media is mounted. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../src/media_mcp/platform/static');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[],calls=[];
  page.setDefaultTimeout(10000);
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>sessionStorage.setItem('media-csrf','disposable-browser-test'));
  await page.route('http://media.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname.startsWith('/api/')){
    let data={};
    if(url.pathname==='/api/auth/setup-status')data={initialized:true};
    else if(url.pathname==='/api/auth/me')data={user:{id:1,username:'preview',role:'user'}};
    else if(url.pathname==='/api/status')data={worker_ready:true};
    else if(url.pathname==='/api/discover'){
     const n=Number(url.searchParams.get('page'));calls.push(Object.fromEntries(url.searchParams));
     data={page:n,total_pages:3,has_next:n<3,items:[{title_id:'movie:'+n,title:'Page '+n,kind:'movie'}]};
    } else data={items:[],tasks:[],jobs:[]};
    return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,data})});
   }
   const name=url.pathname==='/'?'index.html':url.pathname.replace(/^\/assets\//,'');
   const file=path.resolve(root,name);
   if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   const ext=path.extname(file),types={'.html':'text/html','.js':'text/javascript','.css':'text/css'};
   return route.fulfill({contentType:types[ext]||'text/plain',body:fs.readFileSync(file)});
  });
  await page.goto('http://media.test/');
  const prev=page.locator('[data-action=discover-page]').first(),next=page.locator('[data-action=discover-page]').last();
  await page.getByRole('heading',{name:'Page 1',exact:true}).waitFor();assert(await prev.isDisabled());
  await next.click();await page.getByRole('heading',{name:'Page 2',exact:true}).waitFor();assert(await prev.isEnabled());
  await next.click();await page.getByRole('heading',{name:'Page 3',exact:true}).waitFor();assert(await next.isDisabled());
  await prev.click();await page.getByRole('heading',{name:'Page 2',exact:true}).waitFor();
  await page.locator('[data-action=window][data-value=top]').click();
  await page.getByRole('heading',{name:'Page 1',exact:true}).waitFor();assert.equal(calls.at(-1).window,'top');assert.equal(calls.at(-1).page,'1');
  await page.locator('[data-action=source][data-value=simkl]').click();
  await page.getByRole('heading',{name:'Page 1',exact:true}).waitFor();assert.equal(calls.at(-1).source,'simkl');assert.equal(calls.at(-1).page,'1');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);
  console.log('PASS: next/previous, final-page bounds, filter reset and mobile layout');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
