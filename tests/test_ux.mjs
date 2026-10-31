import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
const source=readFileSync(new URL('../src/media_mcp/platform/static/ux.js',import.meta.url),'utf8');
const {Requests}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

test('rapid repeated actions share one request even if the starting DOM is replaced',async()=>{
  const requests=new Requests(),gate=deferred();let submissions=0;
  const send=()=>{submissions++;return gate.promise;};
  const responses=Array.from({length:40},()=>requests.run('submit-download',send));
  await Promise.resolve();assert.equal(submissions,1);assert.equal(requests.busy('submit-download'),true);
  gate.resolve({job:'same-job'});const rows=await Promise.all(responses);
  assert.ok(rows.every(row=>row.job==='same-job'));assert.equal(requests.busy(),false);
});
test('a slow old search cannot replace a newer view',async()=>{
  const requests=new Requests(),old=deferred(),fresh=deferred();let screen='';
  const first=requests.nextView();
  const a=requests.run('search:first',async()=>{const row=await old.promise;if(requests.current(first))screen=row;});
  const second=requests.nextView();
  const b=requests.run('search:second',async()=>{const row=await fresh.promise;if(requests.current(second))screen=row;});
  fresh.resolve('new results');await b;old.resolve('obsolete results');await a;
  assert.equal(screen,'new results');
});
test('a failed action unlocks retry without automatically resubmitting',async()=>{
  const requests=new Requests();let attempts=0;
  await assert.rejects(requests.run('search',()=>{attempts++;throw new Error('offline');}));
  assert.equal(requests.busy('search'),false);assert.equal(attempts,1);
  assert.equal(await requests.run('search',()=>{attempts++;return 'recovered';}),'recovered');
  assert.equal(attempts,2);
});
test('completion of one action does not unlock a different pending action',async()=>{
  const requests=new Requests(),gate=deferred();
  const slow=requests.run('save-user',()=>gate.promise);await requests.run('read-library',()=>1);
  assert.equal(requests.busy(),true);assert.equal(requests.busy('save-user'),true);
  gate.resolve();await slow;assert.equal(requests.busy(),false);
});

test('batch suggestions reject ambiguity, wrong years and first-result guesses',async()=>{
  const {collectionCandidate}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  const item={title:'\u4f5c\u54c1 (Original Title)',year:2024};
  const exact={title_id:'movie:1',title:'\u4f5c\u54c1',date:'2024-01-01'};
  assert.equal(collectionCandidate(item,[{title_id:'movie:9',title:'Other',date:'2024'},exact]),exact);
  assert.equal(collectionCandidate(item,[{...exact,title_id:'movie:2'},exact]),null);
  assert.equal(collectionCandidate(item,[{...exact,date:'2023-01-01'}]),null);
  assert.equal(collectionCandidate(item,[{...exact,title:'Completely unrelated'}]),null);
  assert.equal(collectionCandidate(item,[{...exact,title:'Translated',original_title:'Original Title'}]).title_id,'movie:1');
});

test('task status retries a disconnected read without another user click',async()=>{
  const {ReconnectPoller}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  const recovered=deferred();let reads=0,failures=0;
  const poller=new ReconnectPoller(async()=>{if(++reads===1)throw Error('offline');recovered.resolve();},{interval:5,maxDelay:10,failed:()=>failures++});
  poller.wake();await recovered.promise;poller.stop();assert.equal(reads,2);assert.equal(failures,1);
});
test('resuming replaces a suspended status read and aborts its old request',async()=>{
  const {ReconnectPoller}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  const first=deferred();let reads=0,aborted=false;
  const poller=new ReconnectPoller(async signal=>{if(++reads===1){signal.addEventListener('abort',()=>{aborted=true;first.reject(Error('aborted'));});await first.promise;}},{interval:1000});
  const old=poller.wake();await Promise.resolve();await poller.wake();await old;poller.stop();assert.equal(reads,2);assert.equal(aborted,true);
});
test('a hidden page stops reading and a visibility wake immediately fetches progress',async()=>{
  const {ReconnectPoller}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  let visible=false,reads=0;const poller=new ReconnectPoller(async()=>{reads++;},{visible:()=>visible,interval:1000});
  await poller.wake();assert.equal(reads,0);visible=true;await poller.wake();assert.equal(reads,1);poller.stop();
});
