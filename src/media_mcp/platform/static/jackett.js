import {html,t,lang} from './i18n.js';

// The server filters public sites and owns all Jackett credentials.
export function createIndexerUI(ui){
  const {api,paint,loadData,heading,escape,toast,modalBusy,current,revision}=ui;
  const $=selector=>document.querySelector(selector);
  let data=null,choice=null,query='',filter='all';
  function render(){
    if(!data||!$('#jackett-indexers'))return;
    const rows=data.indexers.filter(row=>(!query||(row.name+' '+row.id+' '+row.language).toLowerCase().includes(query))&&
      (filter==='all'||filter==='enabled'&&row.enabled||filter==='disabled'&&row.configured&&!row.enabled||filter==='unconfigured'&&!row.configured));
    paint('#jackett-indexers',html`<p class="muted">${rows.length} / ${data.indexers.length} ${t('个公共资源站')}</p><div class="indexer-list">${rows.map(row=>html`<article class="indexer-row"><div><strong>${escape(row.name)}</strong><p class="muted">${escape(row.id)} · ${escape(row.language)}</p><span class="badge">${row.enabled?t('已启用搜索'):row.configured?t('已添加 · 搜索停用'):t('未添加')}</span>${row.test?html`<p class="muted">${t('上次：')} ${row.test.status==='passed'?t('连通性测试通过'):t('连通性测试未通过')} · ${new Date(row.test.tested_at*1000).toLocaleString(lang==='en'?'en-US':'zh-CN',{hour12:false})}</p>`:''}</div><div class="indexer-actions">${row.configured?html`<button class="secondary" data-action="jackett-enabled" data-id="${row.id}" data-enabled="${!row.enabled}">${row.enabled?t('停用搜索'):t('启用搜索')}</button><button class="secondary" data-action="jackett-test" data-id="${row.id}">${t('测试')}</button><button class="quiet" data-action="jackett-config" data-id="${row.id}">${t('配置')}</button><button class="quiet" data-action="jackett-remove" data-id="${row.id}">${t('移除')}</button>`:html`<button class="secondary" data-action="jackett-config" data-id="${row.id}">${t('添加')}</button>`}</div></article>`).join('')||html`<p class="muted">${t('没有匹配的公共资源站。')}</p>`}</div>`);
  }
  async function load(){
    if(!$('#jackett-indexers'))paint('#content',html`<div class="indexer-heading">`+heading(t('Jackett 公共资源站'),t('添加资源站、控制搜索启用状态并测试连接。'),html`<button class="quiet" data-action="navigate" data-page="settings">${t('返回设置')}</button>`)+html`</div><p class="muted indexer-explanation">${t('这里只显示 public 资源站。停用搜索会保留 Jackett 配置；移除会删除该站配置。')}</p><div class="filters indexer-filters"><input id="jackett-query" aria-label="${t('筛选资源站')}" placeholder="${t('按名称或语言筛选')}" value="${escape(query)}"><select id="jackett-filter"><option value="all">${t('全部')}</option><option value="enabled">${t('已启用搜索')}</option><option value="disabled">${t('已添加 · 搜索停用')}</option><option value="unconfigured">${t('未添加')}</option></select><button class="secondary" data-action="jackett-refresh">${t('刷新')}</button></div><div id="jackett-indexers"></div>`);
    const result=await loadData('#jackett-indexers',t('正在读取公共资源站…'),()=>api('/api/settings/jackett'));
    if(!result)return;data=result;render();
  }
  function fields(){return choice.fields.map(field=>html`<label>${escape(field.name||field.id)}${field.type==='inputbool'?html`<input type="checkbox" name="${escape(field.id)}" ${field.value?'checked':''}>`:html`<select name="${escape(field.id)}">${Object.entries(field.options||{}).map(([value,label])=>html`<option value="${escape(value)}" ${String(field.value)===value?'selected':''}>${escape(label)}</option>`).join('')}</select>`}</label>`).join('');}
  async function open(site,remove=false){
    if(modalBusy()){toast(t('正在提交…'));return;}
    const rev=revision();const config=await api('/api/settings/jackett',{action:'configuration',site});if(!current(rev))return;
    choice=config;const row=data.indexers.find(row=>row.id===site);const modal=$('#modal');modal.classList.add('indexer-dialog');
    modal.innerHTML=html`<h2>${remove?t('移除资源站'):config.configured?t('配置资源站'):t('添加资源站')} · ${escape(row.name)}</h2>${remove?html`<p>${t('确认移除此公共资源站的 Jackett 配置？下载文件和媒体库不会被删除。')}</p>`:html`<form id="jackett-config" class="stack">${fields()||html`<p class="muted">${t('使用资源站默认配置。保存时 Jackett 可能同时测试连接。')}</p>`}</form>`}<div class="dialog-actions"><button class="secondary" data-action="close-modal">${t('取消')}</button><button data-action="${remove?'jackett-remove-confirm':'jackett-save'}">${remove?t('确认移除'):t('保存')}</button></div>`;
    modal.showModal();
  }
  async function mutate(payload){
    const rev=revision();
    try{const result=await api('/api/settings/jackett',payload);if(!current(rev))return;data=result;render();}
    catch(error){if(current(rev))await load().catch(()=>{});throw error;}
  }
  async function action(action,button){
    const site=button.dataset.id;
    if(action==='jackett-refresh')return load();
    if(action==='jackett-config')return open(site);
    if(action==='jackett-remove')return open(site,true);
    if(action==='jackett-enabled')return mutate({action:'enabled',site,enabled:button.dataset.enabled==='true',revision:data.revision});
    if(action==='jackett-test')return mutate({action:'test',site});
    if(action==='jackett-save'||action==='jackett-remove-confirm'){
      const selected=choice,rev=revision();const values={};
      if(action==='jackett-save')for(const field of selected.fields){const input=$('#jackett-config').elements.namedItem(field.id);values[field.id]=field.type==='inputbool'?input.checked:input.value;}
      await mutate({action:action==='jackett-save'?'save':'remove',site:selected.id,revision:selected.revision,values,confirm:action==='jackett-remove-confirm'});
      if(current(rev)&&choice===selected&&$('#modal').classList.contains('indexer-dialog')&&$('#modal').open)$('#modal').close();
    }
  }
  document.addEventListener('input',event=>{if(event.target.id==='jackett-query'){query=event.target.value.toLowerCase().trim();render();}});
  document.addEventListener('change',event=>{if(event.target.id==='jackett-filter'){filter=event.target.value;render();}});
  return {load,action};
}
