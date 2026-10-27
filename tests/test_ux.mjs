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
