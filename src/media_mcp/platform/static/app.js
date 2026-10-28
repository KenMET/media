import {lang, t, html, switchLanguage} from './i18n.js';
import {Requests} from './ux.js';
import {createLibraryUI} from './library.js';
const languageButton=()=>html`<button class="quiet language-switch" data-action="language" aria-label="${lang==='en'?'切换为中文':'Switch to English'}">${lang==='en'?'中文':'English'}</button>`;
const $ = (selector) => document.querySelector(selector);
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const state = {user:null, csrf:sessionStorage.getItem('media-csrf') || '', page:'discover', source:'tmdb', kind:'movie', window:'week', items:[], selected:null, releases:[], plan:null, job:null, filter:'', jobs:[], cursor:'', busy:false};
const stages = {queued:t('等待提交'), submitting:t('正在提交'), submission_unknown:t('正在核对下载'), downloading:t('下载中'), enqueue_processing:t('等待处理'), processing:t('入库与字幕处理中'), completed:t('已完成'), completed_with_warnings:t('完成 · 有待处理项'), needs_review:t('需要复核'), failed:t('失败'), cancelled:t('已取消')};
function requestKey() {
  // getRandomValues is available on ordinary LAN HTTP; randomUUID requires HTTPS.
  const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
  return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
}
const errors = {analysis_select_smaller_scope:t('请缩小到不超过 500 个视频。'),analysis_context_too_large:t('目录上下文过大，请选择更具体的文件夹或更少文件。'),analysis_file_missing:t('媒体文件缺失，请先检查路径和挂载。'),analysis_directory_changed:t('目录内容已经变化，请重新生成识别建议。'),analysis_result_not_applicable:t('所选结果证据不足或不确定，不能保存。'),analysis_ai_outcome_unknown:t('AI 请求结果未知，未自动重试，请重新检查任务。'),snapshot_expired_search_again:t('预览已过期，请重新识别。'),collection_not_found:t('作品不存在或无权访问，请刷新媒体库。'),collection_cursor_changed:t('作品列表已变化，请刷新后继续浏览。'),collection_selection_changed:t('所选文件已变化，请刷新详情后重试。'),collection_select_smaller_scope:t('请按季或选择不超过 500 个文件处理。'),collection_changed_rebuild_plan:t('文件或识别信息已变化，请重新生成预览。'),collection_episode_requires_review:t('季集对应与作品资料不一致，请检查每个文件的集数。'),collection_season_requires_review:t('文件标记的季号未在该作品中找到，请核对作品或修正季号。'),collection_no_safe_repairs:t('当前没有可以安全补建的链接，请检查预览中的待复核项。'),collection_no_eligible_subtitles:t('没有可处理的文件，请先确认作品身份和映射，或选择重新核验。'),collection_operation_busy:t('相同文件已有维护任务在执行，请稍候。'),media_management_permission_required:t('你没有媒体管理权限，请联系管理员。'),cloud_search_only:t('请通过云端网站进行作品识别。'),inventory_empty_scan:t('本次扫描为 0 项，未导入任何资源。请检查宿主机媒体目录及容器挂载。'),inventory_import_verification_failed:t('导入结果校验失败，请刷新检查已保存资源。'),inventory_root_unavailable:t('媒体目录不可用，请管理员检查本地目录挂载。'),inventory_roots_overlap:t('下载目录和整理目录不能互相包含，请检查配置。'),inventory_scan_unreadable:t('部分目录无法读取，本次未生成可导入预览。请检查权限后重新扫描。'),inventory_scan_limit:t('目录规模或扫描时间超过本次上限，未导入任何资源。请缩小扫描目录后重试。'),inventory_preview_expired:t('扫描预览已过期，请重新扫描。'),inventory_changed_rescan:t('文件或映射在扫描后发生变化，本次未导入。请重新扫描确认。'),media_busy_retry_later:t('媒体正在处理，请稍后重新操作。'),account_rate_limited:t('操作太频繁，请稍后重试。'),account_concurrency_limited:t('已有操作正在处理，请稍候再试。'),account_queue_full:t('待处理任务已达上限，请等待现有任务结束。'),account_token_limit:t('连接密钥已达上限，请先撤销不用的密钥。'),download_permission_required:t('你没有下载权限，请联系管理员。'),invalid_username:t('用户名仅支持 3–48 个字母、数字或 . _ -。'),invalid_credentials:t('用户名或密码不正确'), authentication_required:t('请重新登录'), csrf_failed:t('会话校验已失效，请重新登录'), login_rate_limited:t('登录尝试过多，请稍后再试'), bootstrap_closed:t('管理员已初始化，请直接登录'), bootstrap_denied:t('初始化令牌不正确或未配置'), username_exists:t('用户名已存在'), permission_denied:t('你没有执行此操作的权限'), last_admin_required:t('必须保留至少一名启用的管理员'), record_not_found:t('任务不存在或你没有访问权限'), existing_media_or_active_job_review_required:t('已有媒体或正在进行的任务，请先检查媒体库和下载记录'), dependency_unavailable:t('依赖服务暂不可用，请检查服务状态后重试'), stale_or_submitted_plan:t('计划已变化或已提交，请刷新任务'), snapshot_expired_search_again:t('搜索结果已过期，请重新搜索'), tmdb_not_configured:t('尚未配置 TMDB API key'), tmdb_unavailable:t('TMDB 暂时不可用'), douban_unavailable:t('豆瓣数据源暂不可用'), simkl_unavailable:t('SIMKL 暂时不可用'), simkl_invalid_response:t('SIMKL 返回了无法识别的榜单'), simkl_outdated:t('SIMKL 榜单超过两天未更新'), catalog_empty_response:t('榜单暂时为空'), catalog_unavailable:t('榜单来源暂不可用'), job_not_safe_to_retry:t('此任务当前不能安全重试'), password_requires_12_to_256_characters:t('密码需为 12–256 个字符')};
function toast(message) { const node=$('#toast'); node.textContent=message; node.style.display='block'; clearTimeout(toast.timer); toast.timer=setTimeout(()=>node.style.display='none',5500); }
async function api(path, body, method='POST') {
  const sessionAtStart=state.csrf, controller=new AbortController(),revision=requests.revision;
  const read=body===undefined||(path==='/api/command'&&['search_titles','search_releases','jobs','job','media','library','collections','collection','collection_task','collection_analysis_plan'].includes(body.operation));
  if(read)readControllers.set(controller,revision);
  const timer=setTimeout(()=>controller.abort(),60000);
  const options={method:body===undefined?'GET':method,credentials:'same-origin',headers:{},signal:controller.signal};
  if(body!==undefined){options.headers={'content-type':'application/json','x-csrf-token':state.csrf};options.body=JSON.stringify(body);}
  try {
    const response=await fetch(path,options);
    if(sessionAtStart!==state.csrf)throw new Error(t('会话已改变，请重新操作。'));
    let result;try{result=await response.json();}catch{throw new Error(t('服务返回了无法识别的响应'));}
    if(!response.ok||!result.success){if(response.status===401){state.user=null;auth();}throw new Error(errors[result.error_code]||t('操作未完成，请稍后重试。'));}
    return result.data;
  } catch(error) {
    if(error.name==='AbortError'&&!requests.current(revision)){const changed=new Error('view_changed');changed.name='ViewChanged';throw changed;}
    if(error.name==='AbortError')throw new Error(t('等待超时，请重试；下载提交会沿用原请求核对结果。'));
    if(error instanceof TypeError)throw new Error(t('连接中断，请检查网络后重试。'));
    throw error;
  } finally{clearTimeout(timer);readControllers.delete(controller);}
}
const busyUI=new Map(),lockedButtons=new Map(),readControllers=new Map();
const requests=new Requests(syncBusyControls);
function newView(){const revision=requests.nextView();for(const [controller,owner] of readControllers){if(owner!==revision)controller.abort();}return revision;}
function syncBusyControls(){
  for(const [button,saved] of lockedButtons){
    if(!button.isConnected){lockedButtons.delete(button);continue;}
    if(!requests.busy(saved.key)){button.disabled=saved.disabled;button.innerHTML=saved.markup;button.removeAttribute('aria-busy');lockedButtons.delete(button);}
  }
  for(const [key,ui] of busyUI){if(!requests.busy(key))continue;
    const buttons=new Set([...(ui.selector?document.querySelectorAll(ui.selector):[]),...(ui.button?.isConnected?[ui.button]:[])]);
    for(const button of buttons){if(lockedButtons.has(button)||button.disabled)continue;
      lockedButtons.set(button,{key,disabled:button.disabled,markup:button.innerHTML});button.disabled=true;button.setAttribute('aria-busy','true');
      if(ui.label&&(button===ui.button||button.closest('form')))button.innerHTML=html`<span class="spinner" aria-hidden="true"></span>${escape(ui.label)}`;
    }
  }
}
async function act(key,operation,{button=null,selector='',label=t('处理中…')}={}){
  if(requests.busy(key))return;
  busyUI.set(key,{button,selector,label});
  try{return await requests.run(key,operation);}catch(error){if(error.name!=='ViewChanged')toast(error.message);}finally{busyUI.delete(key);syncBusyControls();}
}
function paint(selector,markup){const node=$(selector);if(node){node.innerHTML=markup;syncBusyControls();}}
function loading(message,cards=false){return html`<div class="loading-state" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><span>${escape(message)}</span><p>请稍候，正在获取最新内容。</p></div>${cards?html`<div class="poster-grid skeleton-grid" aria-hidden="true">${Array.from({length:6},()=>'<div class="skeleton-card"><div class="skeleton-poster"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div></div>').join('')}</div>`:''}`;}
async function loadData(selector,message,operation,{cards=false,quiet=false}={}){
  const revision=requests.revision;
  if(!quiet)paint(selector,loading(message,cards));
  try{const data=await operation();return requests.current(revision)?data:null;}
  catch(error){if(!requests.current(revision))return null;
    if(!quiet){const retry=state.page==='inventory'?'scan-disk':selector==='#search-results'?'retry-search':selector==='#release-results'?'retry-releases':state.page==='detail'?'retry-detail':'refresh';
      paint(selector,html`<div class="empty error-state" role="alert"><h2>暂时没有加载成功</h2><p>${escape(error.message)}</p><button data-action="${retry}">重试</button></div>`);}
    throw error;
  }
}
const command=(operation,arguments_={})=>api('/api/command',{operation,arguments:arguments_});
const libraryUI=createLibraryUI({state,command,loadData,paint,heading,escape,toast,showCollection,navigateLibrary:()=>navigate('library'),syncBusyControls,current:rev=>requests.current(rev),revision:()=>requests.revision});
const bytes=(value)=>value == null ? '—' : value>=1073741824 ? (value/1073741824).toFixed(1)+' GB' : value>=1048576 ? (value/1048576).toFixed(1)+' MB' : value>=1024 ? (value/1024).toFixed(0)+' KB' : value+' B';
const date=(value)=>value ? new Date(typeof value==='number'?value*1000:value.replace(' ','T')+'Z').toLocaleString(lang === 'en' ? 'en-US' : 'zh-CN',{hour12:false}) : t('尚无记录');
const progress=(value)=>Number.isFinite(value)?Math.round(Math.max(0,Math.min(1,value))*100):null;
const badge=(stage)=>html`<span class="badge ${['needs_review','failed','submission_unknown'].includes(stage)?'warn':''}">${escape(stages[stage]||stage)}</span>`;
function heading(title,subtitle,action='') { return html`<div class="heading"><div><div class="eyebrow">YOUR PERSONAL MEDIA SPACE</div><h1>${escape(title)}</h1><p>${escape(subtitle)}</p></div>${action}</div>`; }
function empty(title,message,action='') {return html`<div class="empty"><h2>${escape(title)}</h2><p>${escape(message)}</p>${action}</div>`;}
function auth(mode='login') {
  if(mode==='bootstrap'&&!state.canBootstrap)mode='login';
  newView();state.page='auth';if($('#modal').open)$('#modal').close();
  $('#app').innerHTML=html`<div class="auth-layout"><section class="auth-intro"><div class="brand">MEDIA<span>·</span></div><h1>想看的故事，<br>有一个自己的家。</h1><p>发现值得看的电影与剧集，让寻找、下载和整理在同一个地方完成。</p></section><section class="auth-box"><div class="auth-card">${languageButton()}<div class="eyebrow">WELCOME HOME</div><h2>${mode==='login'?t('登录你的 Media'):t('初始化管理员')}</h2><p class="muted">${mode==='login'?t('继续管理你的私人媒体库。'):t('首次部署时使用服务器配置的初始化令牌。')}</p>${state.canBootstrap?html`<div class="tabs"><button data-action="auth-login" class="${mode==='login'?'active':''}">账号登录</button><button data-action="auth-bootstrap" class="${mode==='bootstrap'?'active':''}">首次初始化</button></div>`:''}<form id="${mode}" class="stack">${mode==='bootstrap'?t('<label>初始化令牌<input name="token" type="password" required autocomplete="off"></label>'):''}<label>用户名<input name="username" required minlength="3" maxlength="48" autocomplete="username" placeholder="你的用户名"></label><label>密码<input name="password" type="password" required minlength="${mode==='bootstrap'?12:1}" maxlength="256" autocomplete="${mode==='bootstrap'?'new-password':'current-password'}" placeholder="${mode==='bootstrap'?t('至少 12 个字符'):t('输入密码')}"></label><button type="submit">${mode==='login'?t('登录'):t('创建管理员')}</button></form><p class="footnote">仅供你的私人媒体服务使用。没有公开注册入口，请联系管理员获取账号。</p></div></section></div>`;
}
function shell() {
  const navPage=['job','history'].includes(state.page)?'jobs':['inventory','collection'].includes(state.page)?'library':state.page==='detail'?'search':['users','events'].includes(state.page)?'admin':state.page;
  const links=[['discover','◈',t('发现')],['search','⌕',t('搜索')],['jobs','↓',t('下载')],['library','▤',t('媒体库')],['settings','◉',t('我的账号')],...(state.user.role==='admin'?[['admin','⚙',t('管理')]]:[])];
  $('#app').innerHTML=html`<div class="layout"><aside class="sidebar"><div class="brand">MEDIA<span>·</span></div><div class="brand-caption">COLLECT THE STORIES YOU LOVE</div><nav class="nav" aria-label="主导航">${links.map(([id,icon,label])=>html`<button class="${navPage===id?'active':''}" aria-current="${navPage===id?'page':'false'}" data-action="navigate" data-page="${id}"><span aria-hidden="true">${icon}</span><span class="nav-label">${label}</span></button>`).join('')}</nav><div class="sidebar-bottom"><div class="connection"><i class="dot" id="worker-dot"></i><span id="worker-state">连接中…</span></div><span>你的片库，你来决定。</span></div></aside><section class="workspace"><header class="topbar"><button class="mobile-wordmark quiet" data-action="navigate" data-page="discover">MEDIA<span>·</span></button><form id="global-search" class="global-search"><input name="query" aria-label="搜索电影或剧集" placeholder="搜索电影、剧集或原名…" maxlength="200" required><button class="secondary" type="submit">搜索</button></form>${languageButton()}<div class="user-chip"><button class="avatar account-button" data-action="navigate" data-page="settings" aria-label="我的账号">${escape(state.user.username[0].toUpperCase())}</button><span class="username">${escape(state.user.username)}</span><button class="quiet" data-action="logout">退出</button></div></header><main class="content" id="content"><div class="loading">正在加载…</div></main></section></div>`;
  syncBusyControls();refreshStatus();
}
async function refreshStatus() {const revision=requests.revision;try {const status=await api('/api/status');if(!requests.current(revision))return;if($('#worker-state')) {$('#worker-state').textContent=status.worker_ready?t('服务正常'):t('后台暂不可用');$('#worker-dot').classList.toggle('offline',!status.worker_ready);} state.status=status;} catch(error) {if(!requests.current(revision)||error.name==='ViewChanged')return;if($('#worker-state')) $('#worker-state').textContent=t('服务连接中断');}}
function posters(items) {return html`<div class="poster-grid">${items.map((item,index)=>html`<article class="poster-card"><button class="poster-button" data-action="title" data-index="${index}" aria-label="查看 ${escape(item.title)}"><div class="poster">${item.poster_url?html`<img src="${escape(item.poster_url)}" alt="${escape(item.title)}海报" loading="lazy" referrerpolicy="no-referrer">`:'◈'}${item.rating?html`<span class="score">★ ${escape(item.rating)}</span>`:''}</div><h3>${escape(item.title)}</h3><p>${escape(item.date?.slice(0,4)||'')} ${item.kind==='tv'?t('剧集'):t('电影')}${item.rating_source?' · '+escape(item.rating_source):''}</p></button></article>`).join('')}</div>`;}
async function discover() {
  const data=await loadData('#content',t('正在加载榜单…'),()=>api(html`/api/discover?source=${state.source}&kind=${state.kind}&window=${state.window}`),{cards:true});
  if(!data)return;
  if(state.page!=='discover') return;
  state.items=data.items;
  $('#content').innerHTML=heading(t('发现值得看的故事'),t('从热门榜单出发，找到下一部想收藏的作品。'))+html`<div class="hero"><div><div class="eyebrow">YOUR NEXT GREAT WATCH</div><h2>让好故事，不止停留在想看。</h2><p>浏览榜单，挑选资源。下载、入库和字幕进度都在这里。</p></div><div class="hero-mark" aria-hidden="true">◈</div></div><div class="tabs">${[['tmdb',t('TMDB 趋势')],['simkl',t('SIMKL 热门')],['douban',t('豆瓣热门')]].map(([id,label])=>html`<button data-action="source" data-value="${id}" class="${state.source===id?'active':''}" ${id==='douban'?'disabled title="'+t('豆瓣榜单暂不可用')+'"':''}>${label}${id==='douban'?t('（暂不可用）'):''}</button>`).join('')}<button data-action="kind" data-value="movie" class="${state.kind==='movie'?'active':''}">电影</button><button data-action="kind" data-value="tv" class="${state.kind==='tv'?'active':''}">剧集</button>${state.source!=='douban'?html`<button data-action="window" data-value="${state.window==='week'?'day':'week'}">${state.window==='week'?t('本周趋势'):t('今日趋势')} ⇄</button>`:''}</div>${data.error_code?html`<div class="notice">${escape(errors[data.error_code]||data.error_code)}。${data.fetched_at?t('当前显示历史缓存，更新于 ')+escape(date(data.fetched_at)):t('尚无可用缓存；可以切换数据来源或直接搜索作品。')}</div>`:''}<div class="section-title"><h2>${state.source==='douban'?t('豆瓣热门'):state.source==='simkl'?t('SIMKL 热门'):t('TMDB 趋势')} · ${state.kind==='tv'?t('剧集'):t('电影')}</h2><span class="muted">${data.fetched_at?escape(date(data.fetched_at))+t(' 抓取'):''}</span></div>${data.source_updated_at?t('<p class="muted">来源更新时间：')+escape(date(data.source_updated_at))+t(' · 榜单按 SIMKL 观看人数排序</p>'):''}${data.items.length?posters(data.items):empty(t('榜单暂时不可用'),t('配置或检查对应数据源后再试，媒体搜索和已有任务仍可独立使用。'),t('<button data-action="refresh">重新检查</button>'))}<footer class="source-footer">TMDB 数据与海报来源：The Movie Database。This product uses the TMDB API but is not endorsed or certified by TMDB.<br><a href="https://simkl.com/movies/best-movies/most-watched/" target="_blank" rel="noopener noreferrer">SIMKL 电影榜单</a> · <a href="https://simkl.com/tv/best-shows/most-watched/" target="_blank" rel="noopener noreferrer">SIMKL 剧集榜单</a>：SIMKL 榜单与评分单独标注来源。<br>外部条目缺少 TMDB 标识时，点击后需先确认匹配的作品。</footer>`;
}
function searchPage() {$('#content').innerHTML=heading(t('找到你想看的作品'),t('先确认作品，再搜索资源站。'))+html`<form id="search" class="panel form-grid"><label>名称或原名<input name="query" placeholder="例如：星际穿越 / Interstellar" maxlength="200" required></label><label>类型<select name="kind"><option value="movie">电影</option><option value="tv">剧集</option></select></label><label>年份（可选）<input name="year" type="number" min="1880" max="2200"></label><button type="submit">搜索作品</button></form><div id="search-results">${empty(t('从一个片名开始'),t('中文名、原名都可以。剧集请先选择“剧集”。'))}</div>`;}
async function search(query,kind='movie',year=null) {
  recordRoute('#search');
  newView();const changed=state.page!=='search';state.page='search';
  if(changed)shell();if(!$('#search'))searchPage();
  $('#search [name=query]').value=query;$('#search [name=kind]').value=kind;
  $('#search [name=year]').value=year??'';syncBusyControls();
  const data=await loadData('#search-results',t('正在搜索作品…'),()=>command('search_titles',{query,kind,year}),{cards:true});
  if(!data||state.page!=='search')return;
  state.items=data.titles;
  paint('#search-results',html`<div class="section-title"><h2>匹配作品</h2><span class="muted">${data.titles.length} 个结果</span></div>`+(data.titles.length?posters(data.titles):empty(t('没有找到匹配作品'),t('试试原名，或不指定年份重新搜索。'))));
}
async function title(index) {
  const item=typeof index==='object'?index:state.items[index];if(!item)return;state.requestedTitle=item;
  if(!item.title_id) {await search(item.title,item.kind);toast(t('请确认外部榜单条目对应的作品，避免同名误下载。'));return;}
  newView();state.page='detail';shell();
  const selected=await loadData('#content',t('正在加载作品详情…'),()=>api('/api/detail?title_id='+encodeURIComponent(item.title_id)));
  if(!selected)return;state.selected=selected;
  const defaultSeason=selected.seasons?.find(season=>season.season>0)?.season??selected.seasons?.[0]?.season;
  $('#content').innerHTML=html`<div class="details"><div class="poster">${selected.poster_url?html`<img src="${escape(selected.poster_url)}" alt="${escape(selected.title)}海报">`:'◈'}</div><div><div class="eyebrow">${selected.kind==='movie'?'MOVIE':'TV SERIES'}</div><h1>${escape(selected.title)}</h1><div class="meta"><span>${escape(selected.original_title)}</span><span>${escape(selected.date)}</span><span>${escape(selected.genres?.join(' / '))}</span></div><p>${escape(selected.overview||t('暂无简介。'))}</p></div></div><section class="panel"><h2>搜索可下载资源</h2><form id="releases" class="form-grid">${selected.kind==='tv'?html`<label>季<select name="season" required>${(selected.seasons||[]).map(s=>html`<option value="${s.season}" ${s.season===defaultSeason?"selected":""}>${escape(s.name||t('第 ')+s.season+t(' 季'))} · ${s.episodes??'?'} 集</option>`).join('')}</select></label><label>集数（留空为全季）<input name="episodes" placeholder="例如：1,2,3"></label>`:''}<label>清晰度<select name="resolution"><option value="">不限</option><option>1080</option><option>2160</option><option>720</option><option>480</option></select></label><button type="submit">搜索资源</button></form></section><div id="release-results">${empty(t('准备好后搜索资源'),t('资源标题是来源声明，实际文件身份会在下载后校验。'))}</div>`;
  if(!state.user.can_download){$('#releases').closest('section').innerHTML=html`<h2>浏览作品</h2><p class="muted">下载功能尚未开通，请联系管理员。</p>`;$('#release-results').remove();}
  syncBusyControls();
}
function renderReleases(report) {
  state.releases=report.releases;
  const diagnostics=report.search_status!=='complete'?html`<div class="notice">部分站点未返回完整结果。状态：${escape(report.search_status)}。可用资源仍可查看。</div>`:'';
  $('#release-results').innerHTML=diagnostics+html`<div class="section-title"><h2>资源列表</h2><span class="muted">${report.releases.length} 个候选</span></div><div class="filters"><input id="release-filter" placeholder="按资源名、站点筛选" aria-label="筛选资源"><select id="release-sort" aria-label="资源排序"><option value="seeders">做种数优先</option><option value="size">体积从小到大</option></select></div><div id="release-table"></div>`;
  releaseTable();
}
function releaseTable() {
  const query=$('#release-filter')?.value.toLowerCase()||'';const sort=$('#release-sort')?.value||'seeders';
  const rows=state.releases.map((item,index)=>({...item,index})).filter(item=>(item.name+' '+item.indexer).toLowerCase().includes(query)).sort((a,b)=>sort==='size'?(a.size??Infinity)-(b.size??Infinity):(b.seeders??-1)-(a.seeders??-1));
  $('#release-table').innerHTML=rows.length?html`<div class="table-wrap"><table><thead><tr><th>资源名称</th><th>来源</th><th>大小</th><th>做种</th><th>清晰度</th><th></th></tr></thead><tbody>${rows.map(row=>html`<tr><td class="title-cell">${escape(row.name)}</td><td data-label="来源">${escape(row.indexer||t('未知'))}</td><td data-label="大小">${bytes(row.size)}</td><td data-label="做种">${row.seeders??t('未知')}</td><td data-label="清晰度">${row.resolution?row.resolution+'p':t('未知')}</td><td><button data-action="plan" data-index="${row.index}">选择下载</button></td></tr>`).join('')}</tbody></table></div>`:empty(t('没有匹配的资源'),t('尝试调整筛选条件或稍后重新搜索。'));
}
async function plan(index) {
  const row=state.releases[index]; if(!row) return;
  const revision=requests.revision;paint('#modal',loading(t('正在准备下载…')));$('#modal').showModal();
  let result;try{result=await command('plan',{release_id:row.release_id});}catch(error){$('#modal').close();throw error;}
  if(!requests.current(revision)||!$('#modal').open){if($('#modal').open)$('#modal').close();return;}
  state.plan={...result,key:requestKey()};
  const p=state.plan;
  $('#modal').innerHTML=html`<div class="eyebrow">CONFIRM DOWNLOAD</div><h2>确认下载 ${escape(p.identity.title)}</h2><p class="muted">${escape(p.release.name)}</p><div class="meta"><span>${bytes(p.release.size)}</span><span>${escape(p.release.indexer||'')}</span><span>${p.scope.season!=null?t('第 ')+p.scope.season+t(' 季'):''} ${p.scope.episodes?.length?escape(p.scope.episodes.join(', '))+t(' 集'):''}</span></div><p>提交后后台继续下载、入库和字幕处理。关闭网页不会取消任务。</p><div id="submit-status"></div><div class="dialog-actions"><button class="secondary" data-action="close-modal">取消</button><button data-action="start">确认下载</button></div>`;
  syncBusyControls();
}
async function start() {
  const p=state.plan;if(!p)return;paint('#submit-status',loading(t('正在提交下载…')));
  try {const result=await command('start',{plan_id:p.plan_id,revision:p.revision,idempotency_key:p.key});$('#modal').close();state.plan=null;toast(t('任务已提交，后台将继续处理。'));await showJob(result.job_id);}
  catch(error) {if($('#submit-status'))$('#submit-status').innerHTML=html`<div class="notice">${escape(error.message)}。如果响应中断，可再次点击确认；会沿用同一个请求标识核对结果。</div>`;throw error;}
}
function jobTable(jobs) {return html`<div class="table-wrap"><table><thead><tr><th>作品与资源</th><th>状态</th><th>下载进度</th><th>速度</th><th>提交时间</th><th></th></tr></thead><tbody>${jobs.map(job=>html`<tr><td class="title-cell"><strong>${escape(job.identity?.title||t('未识别作品'))}</strong><br><span class="muted">${escape(job.release?.name||t('字幕处理任务'))}</span></td><td data-label="状态">${badge(job.stage)}</td><td data-label="下载进度">${progress(job.progress)==null?'—':progress(job.progress)+'%'}<progress class="progress" value="${progress(job.progress)||0}" max="100" aria-label="下载进度"></progress></td><td data-label="速度">${['completed','completed_with_warnings','failed','cancelled'].includes(job.stage)||job.download_speed==null?'—':bytes(job.download_speed)+'/s'}</td><td class="muted" data-label="提交时间">${escape(date(job.created_at))}</td><td><button class="secondary" data-action="job" data-id="${job.job_id}">详情</button></td></tr>`).join('')}</tbody></table></div>`;}
async function jobs(append=false,quiet=false) {
  const data=await loadData('#content',t('正在加载下载记录…'),()=>command('jobs',{after:append?state.cursor:'',limit:50}),{quiet});
  if(!data)return;
  if(!['jobs','history'].includes(state.page)) return;
  state.jobs=append?state.jobs.concat(data.jobs):data.jobs;state.cursor=data.next_cursor||'';
  const history=state.page==='history';
  $('#content').innerHTML=heading(history?t('下载历史'):t('下载任务'),history?t('查看提交记录、最终结果和需要复核的原因。'):t('下载完成后仍需进行入库与字幕处理。'),t('<button class="secondary" data-action="refresh">刷新</button>'))+html`<div class="filters"><input id="jobs-filter" aria-label="筛选任务" placeholder="按作品或资源名筛选" value="${escape(state.jobQuery||'')}"><select id="jobs-stage" aria-label="按状态筛选"><option value="">全部状态</option>${Object.entries(stages).map(([id,label])=>html`<option value="${id}" ${state.jobStage===id?'selected':''}>${label}</option>`).join('')}</select></div><div id="jobs-table"></div>`+(state.cursor?t('<div class="section-title"><button class="secondary" data-action="more-jobs">加载更多记录</button></div>'):'');
  $('#content').insertAdjacentHTML('afterbegin',html`<div class="view-tabs"><button data-action="navigate" data-page="jobs" class="${history?'':'active'}">进行中</button><button data-action="navigate" data-page="history" class="${history?'active':''}">下载历史</button></div>`);
  filterJobs();syncBusyControls();
}
function filterJobs() {
  const query=(state.jobQuery||'').toLowerCase();
  const rows=state.jobs.filter(job=>(state.page==='history'||state.jobStage||!['completed','completed_with_warnings','failed','cancelled'].includes(job.stage))&&(!state.jobStage||job.stage===state.jobStage)&&((job.identity?.title||'')+' '+(job.release?.name||'')).toLowerCase().includes(query));
  $('#jobs-table').innerHTML=rows.length?jobTable(rows):empty(t('没有匹配的任务'),t('可调整筛选条件，或加载更多记录。'));
}
async function showJob(id) {recordRoute('#jobs');newView();state.job=id;state.page='job';shell();await jobDetail();}
async function jobDetail(quiet=false) {
  const id=state.job;const job=await loadData('#content',t('正在加载任务…'),()=>command('job',{job_id:id}),{quiet});if(!job)return;if(state.page!=='job'||state.job!==id)return;
  const p=progress(job.progress);const done=['completed','completed_with_warnings'].includes(job.stage);const downloaded=done||['processing','enqueue_processing'].includes(job.stage);
  $('#content').innerHTML=heading(job.identity?.title||t('任务详情'),t('下载、入库和字幕处理进度'),t('<button class="secondary" data-action="refresh">刷新状态</button>'))+html`<div class="section-title">${badge(job.stage)}<span class="muted">${job.sampled_at?t('采样于 ')+escape(date(job.sampled_at)):t('尚无下载采样')}</span></div><div class="metrics"><div class="metric"><strong>${p==null?'—':p+'%'}</strong><span>视频下载进度</span></div><div class="metric"><strong>${['completed','completed_with_warnings','failed','cancelled'].includes(job.stage)||job.download_speed==null?'—':bytes(job.download_speed)+'/s'}</strong><span>下载速度</span></div><div class="metric"><strong>${job.eta==null||job.eta>=8640000?'—':Math.ceil(job.eta/60)+t(' 分钟')}</strong><span>下载预计剩余</span></div></div><div class="panel"><h2>处理阶段</h2><div class="phase-list"><div class="${downloaded?'done':''}"><span class="phase-num">1</span>视频下载 ${downloaded?t('· 已完成'):''}</div><div class="${done?'done':''}"><span class="phase-num">2</span>整理到媒体库 ${done?t('· 已完成'):t('· 查看处理结果')}</div><div class="${job.stage==='completed'?'done':''}"><span class="phase-num">3</span>字幕处理 ${job.stage==='completed'?t('· 流程结束'):t('· 以字幕结果为准')}</div></div></div>${job.error_code?html`<div class="notice">当前原因：<span class="error-code">${escape(t('后台处理遇到问题，请稍后重试或联系管理员。'))}</span>${job.submission_outcome_unknown?t('<p>提交结果未知，正在核对下载器。请勿换一个请求重新下载。</p>'):''}</div>`:''}<div class="panel"><h2>下载信息</h2><p>${escape(job.release?.name||t('为已有媒体补字幕'))}</p><p class="muted">提交入口：${escape(job.entry||'legacy')} · 创建：${escape(date(job.created_at))}</p>${job.stage==='needs_review'&&job.error_code==='processing_needs_review'?html`<button data-action="retry" data-id="${job.job_id}" data-revision="${job.revision}">重试已复核的处理阶段</button>`:''}${job.result&&state.user.role==='admin'?html`<details><summary>查看处理结果</summary><pre>${escape(JSON.stringify(job.result,null,2))}</pre></details>`:''}</div>`;
}
async function library(append=false){return libraryUI.list(append);}
function recordRoute(hash,replace=false){if(location.hash!==hash)history[replace?'replaceState':'pushState']({},'',hash);}
async function restoreRoute(){const collection=location.hash.match(/^#library\/([a-f0-9]{32})$/);if(collection)return showCollection(collection[1],{historyMode:'none'});const page=location.hash.slice(1);return navigate(['discover','search','jobs','history','library','settings','admin','users','events','inventory'].includes(page)?page:'discover',{historyMode:'none'});}
window.addEventListener('popstate',()=>{if(state.user)act('history-navigation',restoreRoute);});
async function showCollection(id,{replace=false,historyMode='push'}={}){if(historyMode!=='none')recordRoute('#library/'+id,replace);newView();state.page='collection';state.collectionId=id;state.plan=null;window.scrollTo(0,0);if($('#modal').open)$('#modal').close();shell();await libraryUI.detail(id);}

const diskLabels={paired:t('已确认硬链接'),linked:t('已有映射'),unorganized:t('待整理'),library_only:t('仅有整理文件'),source_missing:t('源文件缺失'),target_missing:t('整理文件缺失'),missing_both:t('两端均缺失'),conflict:t('文件关系冲突'),ambiguous:t('多个关联待核对'),subtitle_matched:t('字幕已匹配'),subtitle_unmatched:t('字幕待匹配'),needs_review:t('需要复核'),outside_roots:t('路径不在当前目录范围'),excluded_mapping:t('映射包含跳过的文件')};
function diskCards(items){return items.map(item=>html`<article class="disk-card panel"><div class="disk-icon" aria-hidden="true">${item.kind==='subtitle'?'CC':item.kind==='record'?'!':'▶'}</div><div class="disk-info"><div class="eyebrow">${item.role==='download'?t('下载目录'):item.role==='library'?t('整理目录'):t('历史记录')}</div><h2>${escape(item.name)}</h2><span class="badge ${['linked','paired','subtitle_matched'].includes(item.status)?'':'warn'}">${escape(diskLabels[item.status]||item.status)}</span>${item.subtitles?.length?html`<span class="file-meta">${item.subtitles.length} 个外挂字幕 · 内容未校验</span>`:''}<details><summary>文件与关联</summary><p class="file-path">${escape(item.path)}</p>${(item.peers||[]).map(path=>html`<p class="file-path">↔ ${escape(path)}</p>`).join('')}${item.target_path?html`<p class="file-path">↔ ${escape(item.target_path)}</p>`:''}${item.video_path?html`<p class="file-path">${escape(item.video_path)}</p>`:''}${(item.subtitles||[]).map(path=>html`<p class="file-path">${escape(path)}</p>`).join('')}</details></div></article>`).join('');}
async function inventory(append=false){
  if(state.user.role!=='admin')return;
  const scanId=state.diskScanId||sessionStorage.getItem('media-inventory-scan');
  const data=await loadData('#content',t('正在加载磁盘资源…'),()=>scanId?command('inventory_preview',{scan_id:scanId,after:append?state.diskCursor:0,limit:50}):command('inventory',{after:append?state.diskCursor:0,limit:50}));
  if(!data||state.page!=='inventory')return;
  state.diskItems=append?(state.diskItems||[]).concat(data.items):data.items;state.diskCursor=data.next_cursor;state.diskPreview=data.state==='preview'&&data.total>0?data:null;
  const preview=data.state==='preview'&&data.total>0,emptyScan=data.state==='empty';
  paint('#content',heading(t('让已有收藏回到片库'),t('视频、硬链接和字幕，都有清晰的去处。'),html`<button class="quiet" data-action="navigate" data-page="library">返回媒体库</button>`)+html`<section class="inventory-intro panel"><div class="eyebrow">${emptyScan?t('空扫描结果'):preview?t('扫描预览'):t('磁盘资源')}</div><h2>${emptyScan?t('未发现可导入资源'):preview?t('已找到资源，等待确认导入'):t('从现有目录开始')}</h2><p>扫描只读取文件信息。导入会保存资源索引，并登记已确认的硬链接，不移动或修改原文件。</p><div class="inventory-actions">${preview?html`<button data-action="import-disk">确认导入索引</button><button class="secondary" data-action="scan-disk">重新扫描</button>`:html`<button data-action="scan-disk">扫描已有资源</button>`}${scanId?html`<button class="quiet" data-action="new-scan">查看已导入资源</button>`:''}</div><p class="scan-note">未整理、源文件缺失或关系不明的资源会保留状态。此处不会自动补链、下载或处理字幕。</p></section>${data.summary?html`<div class="inventory-summary">${Object.entries(data.summary).map(([key,count])=>html`<div><strong>${count}</strong><span>${escape(diskLabels[key]||key)}</span></div>`).join('')}</div>`:''}${emptyScan?html`<div class="notice" role="status"><strong>扫描结果为 0 项，没有导入任何资源。</strong><p>请核对宿主机媒体目录。容器内的 /data 可能映射到了项目内的空 data 目录，而不是真实媒体目录。</p></div>`:''}${data.imported_at?html`<p class="muted">已保存 ${data.total} 项 · ${escape(date(data.imported_at))}</p>`:''}${data.roots?.length?html`<details class="scan-roots" ${emptyScan?'open':''}><summary>本次扫描目录</summary>${data.data_directory?html`<p>宿主机媒体目录：<code>${escape(data.data_directory)}</code></p>`:''}${data.roots.map(root=>html`<p class="file-path">${escape(root)}</p>`).join('')}</details>`:''}${data.skipped_count?html`<div class="notice">${data.skipped_count} 个符号链接或特殊文件已跳过，未读取或导入。<details><summary>查看路径</summary>${data.skipped.map(path=>html`<p class="file-path">${escape(path)}</p>`).join('')}</details></div>`:''}<div class="section-title"><h2>${preview?t('导入前预览'):t('已保存的资源')}</h2><span class="muted">${data.total??state.diskItems.length} 项</span></div><div class="disk-list">${state.diskItems.length?diskCards(state.diskItems):empty(t('还没有磁盘资源索引'),t('点击“扫描已有资源”，预览目录中的视频与字幕。'))}</div>${state.diskCursor!=null?html`<button class="secondary" data-action="more-inventory">继续加载资源</button>`:''}`);
}
async function scanDisk(){
  const revision=requests.revision;
  const data=await loadData('#content',t('正在扫描视频与字幕，请稍候…'),()=>command('inventory_scan',{}));
  if(!data||!requests.current(revision))return;
  state.diskScanId=data.scan_id;sessionStorage.setItem('media-inventory-scan',data.scan_id);await inventory();
}
async function importDisk(){
  const revision=requests.revision,scanId=state.diskPreview?.scan_id;if(!scanId)return;
  const receipt=await command('inventory_import',{scan_id:scanId});
  if(!(receipt.indexed_count>0))throw new Error(t('未收到有效的入库数量，请刷新检查已保存资源。'));
  if(!requests.current(revision))return;
  state.diskScanId=null;state.diskPreview=null;sessionStorage.removeItem('media-inventory-scan');toast(t('已保存 ')+receipt.indexed_count+t(' 项资源索引，原文件保持不变。'));await inventory();
}
function permissionOptions(user={role:'user',can_download:true,can_manage_media:false}){
  const admin=user.role==='admin';
  return html`<div class="permission-options"><label class="check-option"><input type="checkbox" name="can_download" ${admin||user.can_download?'checked':''} ${admin?'disabled':''}><span>允许下载<small>查找资源并提交自己的下载任务</small></span></label><label class="check-option"><input type="checkbox" name="can_manage_media" ${admin||user.can_manage_media?'checked':''} ${admin?'disabled':''}><span>允许管理媒体<small>查看全库并维护字幕</small></span></label></div>`;
}
const adminBack=()=>html`<button class="secondary" data-action="navigate" data-page="admin">返回系统管理</button>`;
async function users(){
  const data=await loadData('#content',t('正在加载用户…'),()=>api('/api/users'));if(!data)return;state.users=data.users;
  const rows=data.users.map(user=>html`<form id="user-update-${user.id}" data-user-id="${user.id}" class="panel user-card"><div class="section-title"><h2>${escape(user.username)}</h2><span class="badge">${user.enabled?t('已启用'):t('已禁用')}</span></div><div class="form-grid"><label>角色<select name="role" data-permission-role><option value="user" ${user.role==='user'?'selected':''}>普通用户</option><option value="admin" ${user.role==='admin'?'selected':''}>管理员</option></select></label><label class="check-option"><input type="checkbox" name="enabled" ${user.enabled?'checked':''}><span>账号可登录</span></label></div>${permissionOptions(user)}<p class="muted permission-help">${user.role==='admin'?t('管理员拥有全部权限。'):t('按需开启权限，无需逐个分配任务或媒体。')}</p><button type="submit" class="secondary">保存权限</button></form>`).join('');
  paint('#content',heading(t('用户管理'),t('为家人创建账号，勾选他们需要的功能。'),adminBack())+html`<details class="panel add-user"><summary>添加用户</summary><form id="users" class="stack"><div class="form-grid"><label>用户名<input name="username" required minlength="3" maxlength="48" autocomplete="off"></label><label>初始密码<input name="password" type="password" required minlength="12" maxlength="256" autocomplete="new-password"></label><label>角色<select name="role" data-permission-role><option value="user">普通用户</option><option value="admin">管理员</option></select></label></div>${permissionOptions()}<button type="submit">创建用户</button></form></details><div class="user-cards">${rows}</div>`);
}
async function events(append=false){
  const result=await loadData('#content',t('正在加载操作记录…'),()=>Promise.all([api('/api/events?after='+(append?state.eventCursor:0)),api('/api/users')]));if(!result)return;
  const [data,userData]=result;state.events=append?state.events.concat(data.events):data.events;state.eventCursor=data.events.length===50?data.events.at(-1).id:null;
  const labels={user_created:t('创建用户'),user_updated:t('更新用户权限'),password_changed:t('修改密码'),download_requested:t('提交下载'),processing_retry:t('重试处理'),subtitles_requested:t('补充字幕'),allocation_read:t('更新访问权限'),allocation_manage:t('更新访问权限'),allocation_none:t('更新访问权限'),mcp_token_created:t('创建 AI 连接'),mcp_token_revoked:t('撤销 AI 连接')};
  paint('#content',heading(t('操作记录'),t('管理员查看账号和任务的操作历史。'),adminBack())+(state.events.length?html`<div class="activity-list">${state.events.map(item=>html`<article class="activity-item"><div><strong>${escape(labels[item.action]||t('系统操作'))}</strong><p>${escape(userData.users.find(user=>user.id===(item.subject_id||item.actor_id))?.username||t('历史账号'))}</p></div><time>${escape(date(item.created_at))}</time></article>`).join('')}</div>`:empty(t('尚无操作记录'),t('任务提交和账号变更后会出现在这里。')))+(state.eventCursor?html`<button class="secondary" data-action="more-events">加载更多记录</button>`:''));
}
function settings(){
  paint('#content',heading(t('我的账号'),t('管理登录密码，查看已开通的功能。'))+html`<section class="panel"><h2>${escape(state.user.username)}</h2><p class="muted">${state.user.role==='admin'?t('管理员'):t('普通用户')}</p><div class="permission-badges"><span class="badge">${state.user.can_download?t('可以下载'):t('仅浏览作品')}</span><span class="badge">${state.user.can_manage_media?t('可以管理媒体'):t('媒体只读')}</span></div></section>${state.user.role==='admin'?html`<button class="panel admin-card account-admin" data-action="navigate" data-page="admin"><strong>系统管理 <span aria-hidden="true">↗</span></strong><span>用户、服务与操作记录</span></button>`:''}<section class="panel"><h2>修改密码</h2><form id="password" class="form-grid"><label>当前密码<input type="password" name="old_password" required autocomplete="current-password"></label><label>新密码<input type="password" name="new_password" minlength="12" maxlength="256" required autocomplete="new-password"></label><button type="submit">修改并重新登录</button></form></section>`);
}
async function adminPage(){
  const status=await loadData('#content',t('正在检查服务…'),()=>api('/api/status'));if(!status)return;
  paint('#content',heading(t('系统管理'),t('管理账号与服务，日常使用不需要进入这里。'))+html`<div class="admin-links"><button class="panel admin-card" data-action="navigate" data-page="users"><strong>用户与权限</strong><span>创建账号，设置下载和媒体管理权限</span></button><button class="panel admin-card" data-action="navigate" data-page="events"><strong>操作记录</strong><span>查看任务和账号的变更记录</span></button></div><section class="panel"><div class="section-title"><h2>服务状态</h2><button class="secondary" data-action="refresh">重新检查</button></div><div class="service-list"><p><span>后台处理</span><strong>${status.worker_ready?t('正常'):t('暂不可用')}</strong></p><p><span>作品搜索</span><strong>${status.tmdb_configured?t('已配置'):t('未配置')}</strong></p><p><span>资源站连接</span><strong>${status.indexer_configured?t('已配置'):t('未配置')}</strong></p></div><p class="muted">服务连接由管理员在部署配置中维护。</p></section><details class="panel advanced-settings"><summary>高级设置：AI 客户端连接</summary><p class="muted">仅在需要让 AI 控制媒体服务时配置。</p><button class="secondary" data-action="open-ai-settings">管理 AI 连接</button><div id="ai-settings"></div></details>`);
}
async function tokenSettings(){
  const data=await loadData('#ai-settings',t('正在加载连接设置…'),()=>api('/api/tokens'));if(!data)return;
  paint('#ai-settings',html`<p>连接密钥只在创建时显示一次，请保存在 AI 客户端的私有设置中。</p><button data-action="create-token">创建连接密钥</button>${data.tokens.map(token=>html`<p>${escape(token.name)} · ${escape(date(token.expires_at))} 到期 <button class="secondary" data-action="revoke-token" data-id="${token.id}">撤销</button></p>`).join('')}`);
}
async function tokenAction(action, button) {
  if(action==='create-token') {
    const data=await api('/api/tokens',{name:t('我的 MCP 客户端')});
    $('#modal').innerHTML=html`<h2>保存 MCP 访问令牌</h2><p>仅显示这一次，请保存到客户端的私有凭据设置中。有效期 30 天。</p><label>访问令牌<input readonly value="${escape(data.token)}" autocomplete="off"></label><div class="dialog-actions"><button data-action="close-modal">已保存</button></div>`;
    $('#modal').showModal();
  } else {
    await api('/api/tokens/'+button.dataset.id,{},'DELETE');
    await tokenSettings();
  }
}
async function navigate(page,{historyMode='push'}={}){
  if(['admin','users','events','inventory'].includes(page)&&state.user.role!=='admin')page='settings';
  if(historyMode!=='none')recordRoute('#'+page);
  newView();state.page=page;state.plan=null;window.scrollTo(0,0);if($('#modal').open)$('#modal').close();shell();await render();
}
async function render(){if(state.page==='discover')return discover();if(state.page==='search'){searchPage();syncBusyControls();return;}if(['jobs','history'].includes(state.page))return jobs();if(state.page==='job')return jobDetail();if(state.page==='detail')return title(state.requestedTitle);if(state.page==='library')return library();if(state.page==='collection')return libraryUI.detail(state.collectionId);if(state.page==='inventory')return inventory();if(state.page==='users')return users();if(state.page==='events')return events();if(state.page==='settings')return settings();if(state.page==='admin')return adminPage();}
function submitForm(id){const form=document.getElementById(id);if(form)form.requestSubmit();}
document.addEventListener('click',event=>{
  const button=event.target.closest('button[data-action]');if(!button||button.disabled)return;
  const action=button.dataset.action;
  if(action==='language'){switchLanguage();return;}
  if(action==='close-modal'){$('#modal').close();return;}
  if(action==='retry-search'){submitForm('search');return;}if(action==='retry-releases'){submitForm('releases');return;}
  const selectors={catalog:'[data-action="source"],[data-action="kind"],[data-action="window"]',plan:'[data-action="plan"]',start:'#modal button'};
  const key=['source','kind','window'].includes(action)?'catalog':action==='navigate'?'navigate:'+button.dataset.page:action==='job'?'open-job':action==='subtitles'?'subtitles:'+button.dataset.id:action;
  const revision=requests.revision;
  act(key,async()=>{
    if(action==='auth-login')auth();else if(action==='auth-bootstrap')auth('bootstrap');
    else if(action==='navigate')await navigate(button.dataset.page);
    else if(action==='logout'){await api('/api/auth/logout',{});recordRoute('#discover',true);state.user=null;state.csrf='';state.diskScanId=null;state.diskPreview=null;sessionStorage.removeItem('media-inventory-scan');sessionStorage.removeItem('media-csrf');auth();}
    else if(action==='refresh')await render();
    else if(['source','kind','window'].includes(action)){newView();state[action]=button.dataset.value;await discover();}
    else if(action==='title')await title(Number(button.dataset.index));else if(action==='retry-detail')await title(state.requestedTitle);
    else if(action==='plan')await plan(Number(button.dataset.index));else if(action==='start')await start();
    else if(action==='job')await showJob(button.dataset.id);else if(action==='more-jobs')await jobs(true);
    else if(action==='scan-disk')await scanDisk();else if(action==='import-disk')await importDisk();else if(action==='more-inventory')await inventory(true);else if(action==='new-scan'){state.diskPreview=null;state.diskScanId=null;sessionStorage.removeItem('media-inventory-scan');await inventory();}
    else if(action.startsWith('library-'))await libraryUI.action(action,button);
    else if(action==='more-media')await library(true);else if(action==='more-events')await events(true);
    else if(action==='open-ai-settings')await tokenSettings();else if(['create-token','revoke-token'].includes(action))await tokenAction(action,button);
    else if(action==='retry'){if(confirm(t('确认已检查失败原因，并重试处理阶段？'))){await command('retry',{job_id:button.dataset.id,revision:Number(button.dataset.revision)});if(requests.current(revision))await jobDetail();}}
    else if(action==='subtitles'){if(confirm(t('为这个已入库媒体补充并核验字幕？'))){const job=await command('subtitles',{media_id:Number(button.dataset.id),idempotency_key:requestKey()});toast(t('字幕任务已提交。'));if(requests.current(revision))await showJob(job.job_id);}}
  },{button,selector:selectors[key]||'',label:action==='start'?t('正在提交…'):t('请稍候…')});
});
document.addEventListener('submit',event=>{
  const form=event.target;if(!form.matches('form'))return;event.preventDefault();
  const values=Object.fromEntries(new FormData(form)),isSearch=['search','global-search'].includes(form.id);
  const key=isSearch?'title-search':form.id;
  const selector=isSearch?'#search button[type="submit"],#global-search button[type="submit"]':'#'+form.id+' button[type="submit"]';
  const revision=requests.revision;
  act(key,async()=>{
    if(form.id==='login'){const data=await api('/api/auth/login',values);state.user=data.user;state.csrf=data.csrf;sessionStorage.setItem('media-csrf',state.csrf);await restoreRoute();}
    else if(form.id.startsWith('library-'))await libraryUI.submit(form,values);
    else if(form.id==='bootstrap'){await api('/api/auth/bootstrap',values);state.canBootstrap=false;auth();toast(t('管理员已创建，请登录。'));}
    else if(isSearch)await search(values.query,values.kind||state.kind,values.year?Number(values.year):null);
    else if(form.id==='releases'){
      const episodes=values.episodes?.trim()?values.episodes.split(/[,，\s]+/).map(Number):null;
      if(episodes?.some(n=>!Number.isInteger(n)||n<1||n>999))throw new Error(t('集数需为 1–999 的整数，以逗号分隔。'));
      const report=await loadData('#release-results',t('正在搜索资源…'),()=>command('search_releases',{title_id:state.selected.title_id,season:values.season==null?null:Number(values.season),episodes,resolution:values.resolution?Number(values.resolution):null}),{cards:true});
      if(report){renderReleases(report);syncBusyControls();}
    } else if(form.id==='users'){
      await api('/api/users',{...values,can_download:values.role==='admin'||form.elements.can_download.checked,can_manage_media:values.role==='admin'||form.elements.can_manage_media.checked});if(requests.current(revision))await users();toast(t('用户已创建。'));
    } else if(form.dataset.userId){
      await api('/api/users/'+form.dataset.userId,{role:values.role,enabled:form.elements.enabled.checked,can_download:values.role==='admin'||form.elements.can_download.checked,can_manage_media:values.role==='admin'||form.elements.can_manage_media.checked},'PATCH');
      toast(t('用户权限已保存，下次登录生效。'));if(requests.current(revision))await users();
    } else if(form.id==='password'){await api('/api/auth/password',values);state.user=null;state.csrf='';state.diskScanId=null;state.diskPreview=null;sessionStorage.removeItem('media-inventory-scan');sessionStorage.removeItem('media-csrf');auth();toast(t('密码已修改，请重新登录。'));}
  },{selector,label:isSearch?t('正在搜索…'):form.id==='releases'?t('正在搜索…'):t('正在保存…')});
});
document.addEventListener('input',event=>{if(event.target.id==='release-filter')releaseTable();if(event.target.id==='jobs-filter'){state.jobQuery=event.target.value;filterJobs();}});
document.addEventListener('change',event=>{
  if(event.target.id==='release-sort')releaseTable();if(event.target.id==='jobs-stage'){state.jobStage=event.target.value;filterJobs();}
  if(event.target.matches('[data-permission-role]')){const form=event.target.closest('form'),admin=event.target.value==='admin';for(const name of ['can_download','can_manage_media']){form.elements[name].disabled=admin;if(admin)form.elements[name].checked=true;}const help=form.querySelector('.permission-help');if(help)help.textContent=admin?t('管理员拥有全部权限。'):t('按需开启权限，无需逐个分配任务或媒体。');}
});
$('#modal').addEventListener('cancel',event=>{if(requests.busy('start')||requests.busy('create-token'))event.preventDefault();});
$('#modal').addEventListener('close',()=>{if(!requests.busy('start'))$('#modal').innerHTML='';});
setInterval(async()=>{
  if(requests.busy()||state.pollBusy||!state.user||document.visibilityState!=='visible'||!['jobs','job','history'].includes(state.page)||document.activeElement?.matches('input,select,textarea'))return;
  state.pollBusy=true;try{if(state.page==='job')await jobDetail(true);else await jobs(false,true);await refreshStatus();}
  catch{if($('#worker-state'))$('#worker-state').textContent=t('连接中断 · 状态可能过期');}finally{state.pollBusy=false;}
},5000);
try{const setup=await api('/api/auth/setup-status');state.canBootstrap=!setup.initialized;}catch{state.canBootstrap=false;}
try{const data=await api('/api/auth/me');state.user=data.user;if(state.csrf)await act('initial-view',restoreRoute);else auth();}catch{auth();}
