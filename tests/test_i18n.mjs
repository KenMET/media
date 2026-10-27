import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/media_mcp/platform/static/i18n.js',import.meta.url),'utf8');
function load(language) {
  const storage = new Map([['media-language',language]]);
  const context = vm.createContext({document:{documentElement:{},title:''},
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    location:{reload(){context.reloaded=true;}}});
  vm.runInContext(source.replaceAll('export ','')+'\nglobalThis.ui={t,html,switchLanguage,lang};',context);
  return {context,storage,...context.ui};
}
test('Chinese is the default and preserves authored text',()=>{
  const ui=load('invalid');
  assert.equal(ui.lang,'zh-CN');
  assert.equal(ui.t('下载任务'),'下载任务');
  assert.equal(ui.context.document.documentElement.lang,'zh-CN');
});
test('English covers navigation, status, forms and errors',()=>{
  const ui=load('en');
  for(const label of ['下载任务','媒体库','分配与操作','用户名或密码不正确','字幕获取、同步与校验',
    '任务详情','清晰度','网页访问模式','角色已更新，原有会话与令牌已失效。']) {
    assert.doesNotMatch(ui.t(label),/[\u3400-\u9fff]/);
  }
  assert.equal(ui.t('SIMKL 热门'),'SIMKL Trending');
  assert.equal(ui.context.document.documentElement.lang,'en');
});
test('only static template parts are translated; user titles and HTML escaping stay intact',()=>{
  const ui=load('en');
  const title='未命名 / 已完成 / &lt;script&gt;';
  assert.equal(ui.html`<h2>确认下载 ${title}</h2>`,'<h2>Confirm download '+title+'</h2>');
  assert.equal(ui.html`<label>清晰度</label><span>${1080}</span>`,
    '<label>Resolution</label><span>1080</span>');
});
test('language choice persists and switches in both directions',()=>{
  for(const [before,after] of [['en','zh-CN'],['zh-CN','en']]) {
    const ui=load(before);ui.switchLanguage();
    assert.equal(ui.storage.get('media-language'),after);
    assert.equal(ui.context.reloaded,true);
  }
});
