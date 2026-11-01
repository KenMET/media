import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
const source=readFileSync(new URL('../src/media_mcp/platform/static/releases.js',import.meta.url),'utf8');
const {seriesSeasons,orderedReleases,discoverReleases,readSearchResponse}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const item=(name,kind='season_pack')=>({name,coverage_kind:kind,seeders:1,indexer:'Fixture',size:100});

test('season discovery starts with latest regular season and skips empty/special seasons',()=>{
  assert.deepEqual(seriesSeasons({seasons:[{season:0},{season:1},{season:3},{season:2},{season:4,episodes:0},{season:3}]}),[3,2,1]);
  assert.deepEqual(seriesSeasons({seasons:[{season:0}]}),[0]);
});
test('all season packs precede singles regardless of completion order or seeder count',()=>{
  const rows=orderedReleases([{season:1,releases:[item('Season one'),item('Episode one','episode')]},
    {season:3,releases:[{...item('Episode three','episode'),seeders:999},item('Season three')]},
    {season:2,releases:[item('Season two')]}]);
  assert.deepEqual(rows.map(row=>row.name),['Season three','Season two','Season one','Episode three','Episode one']);
});
test('progressive discovery searches every season with at most two concurrent scoped requests',async()=>{
  let running=0,peak=0;const calls=[],updates=[];
  await discoverReleases({kind:'tv',seasons:[{season:1},{season:2},{season:3}]},async season=>{
    calls.push(season);peak=Math.max(peak,++running);await new Promise(resolve=>setTimeout(resolve,season===3?15:1));running--;
    return {search_status:'complete',releases:[item('Season '+season)]};
  },report=>updates.push(report),new AbortController().signal);
  assert.deepEqual(calls,[3,2,1]);assert.equal(peak,2);
  assert.equal(updates.at(-1).loading,false);assert.deepEqual(updates.at(-1).releases.map(row=>row.season),[3,2,1]);
});
test('a failed season does not hide other results or require a more-results click',async()=>{
  const updates=[];
  await discoverReleases({kind:'tv',seasons:[{season:1},{season:2}]},async season=>{
    if(season===2)throw new Error('Provider unavailable');return {search_status:'partial',releases:[item('Available')]};
  },report=>updates.push(report),new AbortController().signal);
  assert.equal(updates.at(-1).finished,2);assert.equal(updates.at(-1).releases.length,1);
});
test('navigation abort stops further season requests and late page updates',async()=>{
  const controller=new AbortController(),calls=[],updates=[];
  await discoverReleases({kind:'tv',seasons:[{season:1},{season:2},{season:3}]},async season=>{
    calls.push(season);controller.abort();return {search_status:'complete',releases:[item('Late')]};
  },report=>updates.push(report),controller.signal);
  assert.deepEqual(calls,[3]);assert.equal(updates.length,1);assert.deepEqual(updates[0].releases,[]);
});
test('account throttling retries only the scoped read without asking for a manual continuation',async context=>{
  context.mock.timers.enable({apis:['setTimeout']});
  let calls=0;const updates=[];
  const run=discoverReleases({kind:'movie'},async()=>{
    if(++calls===1)throw Object.assign(new Error('Rate limited'),{code:'account_rate_limited'});
    return {search_status:'complete',releases:[item('Movie')]};
  },report=>updates.push(report),new AbortController().signal);
  await new Promise(resolve=>setImmediate(resolve));context.mock.timers.tick(60000);await run;
  assert.equal(calls,2);assert.equal(updates.at(-1).releases.length,1);
});

test('movie resources retain the existing descending-seeder default',()=>{
  const rows=orderedReleases([{season:null,releases:[{...item('Unknown'),seeders:null},
    {...item('Low'),seeders:1},{...item('High'),seeders:100}]}]);
  assert.deepEqual(rows.map(row=>row.name),['High','Low','Unknown']);
});

test('site progress is independent of movie or season counts and stops after navigation',async()=>{
  const updates=[],controller=new AbortController();
  await discoverReleases({kind:'movie'},async(season,signal,progress)=>{
    progress({sites:['slow','fast']});progress({site:'fast',status:'ok'});
    progress({site:'slow',status:'searching'});
    controller.abort();progress({site:'late',status:'ok'});
    return {releases:[]};
  },report=>updates.push(report),controller.signal);
  assert.deepEqual(updates.at(-1).sites.map(row=>row.site),['fast','slow']);
  assert.equal(updates.at(-1).loading,true);
});
test('stream parser handles fragmented unicode, progress and a final response',async()=>{
  const events=[],payload=new TextEncoder().encode(JSON.stringify({progress:{sites:['Fixture']}})+'\n'+JSON.stringify({success:true,data:{title:'\u6d4b\u8bd5'}})+'\n');
  const body=new ReadableStream({start(controller){for(const byte of payload)controller.enqueue(Uint8Array.of(byte));controller.close();}});
  const result=await readSearchResponse(new Response(body,{headers:{'content-type':'application/x-ndjson'}}),event=>events.push(event));
  assert.deepEqual(events,[{sites:['Fixture']}]);assert.equal(result.data.title,'\u6d4b\u8bd5');
});
test('stream parser preserves error codes, supports JSON and rejects a missing receipt',async()=>{
  const headers={'content-type':'application/x-ndjson'};
  assert.equal((await readSearchResponse(new Response('{"success":false,"error_code":"account_rate_limited"}\n',{headers}),()=>{})).error_code,'account_rate_limited');
  assert.deepEqual(await readSearchResponse(new Response('{"success":true,"data":{}}'),()=>{}),{success:true,data:{}});
  await assert.rejects(readSearchResponse(new Response('{"progress":{"sites":[]}}\n',{headers}),()=>{}),/search_response_incomplete/);
});
