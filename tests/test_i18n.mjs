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
  assert.equal(ui.t('\u4e0b\u8f7d\u4efb\u52a1'),'\u4e0b\u8f7d\u4efb\u52a1');
  assert.equal(ui.context.document.documentElement.lang,'zh-CN');
});
test('English covers navigation, status, forms and errors',()=>{
  const ui=load('en');
  for(const label of ['\u4e0b\u8f7d\u4efb\u52a1','\u5a92\u4f53\u5e93','\u5206\u914d\u4e0e\u64cd\u4f5c','\u7528\u6237\u540d\u6216\u5bc6\u7801\u4e0d\u6b63\u786e','\u5b57\u5e55\u83b7\u53d6、\u540c\u6b65\u4e0e\u6821\u9a8c',
    '\u5168\u5e93\u81ea\u52a8\u6574\u7406','\u81ea\u52a8\u6574\u7406\u8fd9\u90e8\u4f5c\u54c1','\u5df2\u81ea\u52a8\u5b8c\u6210','\u9ad8\u7ea7\u9009\u9879','\u67e5\u770b\u672a\u5904\u7406\u9879','\u6b63\u5728\u81ea\u52a8\u6574\u7406','\u81ea\u52a8\u8bc6\u522b、\u4fdd\u5b58、\u8865\u94fe\u5e76\u68c0\u67e5\u5b57\u5e55。','\u89c4\u5219 + AI \u8bc6\u522b','\u8bc6\u522b\u4e0e\u5206\u7c7b\u5efa\u8bae','\u67e5\u770b\u8bc6\u522b\u5efa\u8bae','\u5efa\u8bae\u5df2\u751f\u6210，\u5f85\u786e\u8ba4','\u6279\u91cf\u91cd\u65b0\u8bc6\u522b','\u6807\u4e3a\u9644\u52a0\u5185\u5bb9','\u786e\u8ba4\u4fdd\u5b58\u5df2\u52fe\u9009\u7ed3\u679c','\u4f60\u7684\u4f5c\u54c1\u5a92\u4f53\u5e93','\u4f5c\u54c1\u8eab\u4efd\u5df2\u786e\u8ba4','\u68c0\u67e5\u6620\u5c04','\u5b57\u5e55\u9700\u8981\u590d\u6838','\u751f\u6210\u8bc6\u522b\u9884\u89c8',
    '\u4efb\u52a1\u8be6\u60c5','\u6e05\u6670\u5ea6','\u7f51\u9875\u8bbf\u95ee\u6a21\u5f0f','\u89d2\u8272\u5df2\u66f4\u65b0，\u539f\u6709\u4f1a\u8bdd\u4e0e\u4ee4\u724c\u5df2\u5931\u6548。',
    '\u5f85\u590d\u6838 ','\u5168\u90e8\u5b8c\u6210 ','\u5df2\u68c0\u67e5 ',
    '\u5df2\u627e\u5230\u4f5c\u54c1，\u4f46\u7f3a\u5c11\u5bf9\u5e94\u5b63\u7684\u6765\u6e90\u8bc1\u636e，\u5c1a\u672a\u81ea\u52a8\u4fdd\u5b58。',
    '\u6b63\u5728\u6062\u590d\u65e7\u4f1a\u8bdd，\u5c1a\u672a\u91cd\u65b0\u63d0\u4ea4\u8bc6\u522b\u8bf7\u6c42','\u4f1a\u8bdd\u6062\u590d：',
    '\u65e7\u4f1a\u8bdd\u7ed3\u679c\u5c1a\u672a\u786e\u8ba4，\u6b63\u5728\u6062\u590d；\u8fd9\u4e0d\u4ee3\u8868\u989d\u5ea6\u4e0d\u8db3。',
    '\u65e7\u4f1a\u8bdd\u8bb0\u5f55\u4e0d\u53ef\u7528，\u6b63\u5728\u6309\u5b89\u5168\u89c4\u5219\u6062\u590d\u8bc6\u522b。',
    '\u65b0\u4f1a\u8bdd\u7ed3\u679c\u518d\u6b21\u672a\u77e5，\u5df2\u505c\u6b62\u81ea\u52a8\u66ff\u4ee3。']) {
    assert.doesNotMatch(ui.t(label),/[\u3400-\u9fff]/);
  }
  assert.equal(ui.t('SIMKL \u70ed\u95e8'),'SIMKL Trending');
  assert.equal(ui.context.document.documentElement.lang,'en');
});
test('only static template parts are translated; user titles and HTML escaping stay intact',()=>{
  const ui=load('en');
  const title='\u672a\u547d\u540d / \u5df2\u5b8c\u6210 / &lt;script&gt;';
  assert.equal(ui.html`<h2>\u786e\u8ba4\u4e0b\u8f7d ${title}</h2>`,'<h2>Confirm download '+title+'</h2>');
  assert.equal(ui.html`<label>\u6e05\u6670\u5ea6</label><span>${1080}</span>`,
    '<label>Resolution</label><span>1080</span>');
});
test('language choice persists and switches in both directions',()=>{
  for(const [before,after] of [['en','zh-CN'],['zh-CN','en']]) {
    const ui=load(before);ui.switchLanguage();
    assert.equal(ui.storage.get('media-language'),after);
    assert.equal(ui.context.reloaded,true);
  }
});
