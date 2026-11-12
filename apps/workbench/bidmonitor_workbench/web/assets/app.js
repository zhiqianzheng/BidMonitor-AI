'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => { try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
const prettyTime = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '未设置';
const state = {meta:null, page:'search', offset:0, total:0, project:null, tab:'article', searchSeq:0, detailSeq:0, leadSeq:0, running:false};
const selectedNoticeTypes = new Set();
let toastTimer;
function toast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.classList.toggle('error', error); el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.hidden = true, error ? 8000 : 4000);
}
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {method, headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = Array.isArray(data.detail) ? data.detail.map(e => `${e.loc.at(-1)}：${e.msg}`).join('；') : data.detail;
    const error = new Error(message || `请求失败（${response.status}），请检查服务后重试`); error.status = response.status; throw error;
  }
  return data;
}
async function busy(button, action) {
  if (button?.disabled) return;
  const label = button?.textContent;
  if (button) { button.disabled = true; button.textContent = '处理中…'; }
  try { await action(); } catch (error) { toast(error.message || '连接失败，请重试', true); }
  finally { if (button?.isConnected) { button.disabled = false; button.textContent = label; } }
}
function selectOptions(element, values, placeholder, selected = element.value) {
  element.innerHTML = (placeholder === null ? '' : `<option value="">${esc(placeholder)}</option>`) + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  if ([...element.options].some(o => o.value === selected)) element.value = selected;
}
function tag(value, extra = '') { return `<span class="tag ${extra}">${esc(value)}</span>`; }
function availabilityTag(p) { return tag(p.availability_label || '截止待核实', {open:'green',unknown:'orange',expired:'red',ended:'red'}[p.availability] || 'orange'); }
function typeTag(value) { return tag(value, value === '中标结果' ? 'green' : value === '变更公告' ? 'orange' : value === '采购意向' ? 'purple' : ''); }
function empty(title, description, button = '') { return `<div class="empty"><h3>${esc(title)}</h3><p>${esc(description)}</p>${button}</div>`; }

function updateNoticeTypeSummary() {
  const values = [...selectedNoticeTypes];
  const summary = $('#noticeTypeSummary');
  summary.textContent = values.length ? (values.length <= 2 ? values.join('、') : `已选 ${values.length} 种类型`) : '全部类型';
  summary.title = values.join('、') || '不限公告类型';
}
function renderNoticeTypes(types) {
  const options = $('#noticeTypeOptions');
  if (options.dataset.types !== JSON.stringify(types)) {
    options.innerHTML = types.map(type => `<label><input type="checkbox" value="${esc(type)}"><span>${esc(type)}</span></label>`).join('');
    options.dataset.types = JSON.stringify(types);
  }
  for (const input of $$('input', options)) input.checked = selectedNoticeTypes.has(input.value);
  updateNoticeTypeSummary();
}
function noticeTypesChanged() { updateNoticeTypeSummary(); state.offset = 0; search(); }
$('#noticeTypeOptions').addEventListener('change', e => {
  const input = e.target;
  if (!input.matches('input[type=checkbox]')) return;
  if (input.checked) selectedNoticeTypes.add(input.value); else selectedNoticeTypes.delete(input.value);
  noticeTypesChanged();
});
$('#noticeTypeAll').addEventListener('click', () => {
  for (const type of state.meta?.notice_types || []) selectedNoticeTypes.add(type);
  renderNoticeTypes(state.meta?.notice_types || []); noticeTypesChanged();
});
$('#noticeTypeClear').addEventListener('click', () => {
  selectedNoticeTypes.clear(); renderNoticeTypes(state.meta?.notice_types || []); noticeTypesChanged();
});
document.addEventListener('click', e => { if (!$('#noticeType').contains(e.target)) $('#noticeType').open = false; });
$('#noticeType').addEventListener('keydown', e => {
  if (e.key === 'Escape') { $('#noticeType').open = false; $('#noticeType summary').focus(); }
});

async function refreshMeta() {
  const meta = await api('/api/meta');
  const unchanged = JSON.stringify(meta) === JSON.stringify(state.meta);
  state.meta = meta; state.running = meta.collection.running;
  if (unchanged) return meta;
  $('#navProjects').textContent = meta.projects; $('#navLeads').textContent = meta.leads;
  const stats = [ ['已收录公告', meta.projects, '含历史公告，搜索默认过滤已结束', '▤'], ['正文已就绪', meta.details_ready, '可全文搜索与查看详情', '≡'], ['团队跟进中', meta.leads - ['成交','失标','放弃'].reduce((n,s) => n + (meta.stages[s] || 0),0), '从发现到投标统一管理', '↗'], ['到期未完成', meta.due, '已到下次跟进时间的线索', '◷'] ];
  $('#stats').innerHTML = stats.map(([label,count,foot,symbol]) => `<div class="stat"><div class="stat-label">${label}</div><span class="stat-symbol">${symbol}</span><div class="stat-number">${count.toLocaleString()}</div><div class="stat-foot">${foot}</div></div>`).join('');
  selectOptions($('#industry'), meta.industries, '全部行业');
  selectOptions($('#category'), meta.categories, '全部采购类别');
  $('#industryOptions').innerHTML = meta.industries.map(v => `<option value="${esc(v)}"></option>`).join('');
  selectOptions($('#region'), meta.regions, '全部地区'); renderNoticeTypes(meta.notice_types); selectOptions($('#source'), meta.sources, '全部来源');
  selectOptions($('#leadStage'), meta.stage_options, '全部阶段');
  const owner = $('#leadOwner').value;
  selectOptions($('#leadOwner'), meta.members, '所有负责人');
  $('#leadOwner').insertAdjacentHTML('beforeend','<option value="__unassigned">待分配</option>'); $('#leadOwner').value = owner;
  selectOptions($('#newNoticeType'), meta.notice_types, null, $('#newNoticeType').value || '招标公告');
  $('#memberList').innerHTML = meta.members.length ? meta.members.map(m => `<span class="member-pill">${esc(m)}</span>`).join('') : '<span class="muted">还没有成员，添加后即可分配线索。</span>';
  $('#timezoneInfo').textContent = `本机时区：${meta.timezone}。下次跟进时间按本机时间判断，不会自动发送通知。`;
  $('#collectionStatus').textContent = meta.collection.message;
  for (const id of ['collectButton','settingsCollect']) { const el = $('#' + id); el.disabled = meta.collection.running; el.textContent = meta.collection.running ? '正在采集…' : id === 'collectButton' ? '↻ 采集最新公告' : '开始采集'; }
  $('#stopCollect').disabled = !meta.collection.running;
  $('#runList').innerHTML = meta.runs.length ? meta.runs.map(r => `<div class="run-row">${tag({success:'采集完成',error:'采集失败',stopped:'已停止',empty:'窗口内无公告',partial:'部分失败',needs_adapter:'待适配',blocked:'访问受限',interrupted:'上次中断'}[r.status] || r.status, r.status === 'success' ? 'green' : 'orange')}<div>${esc(r.source)}<small>${esc(r.message)}</small></div><span class="muted">${esc(prettyTime(r.created_at))}</span></div>`).join('') : '<div class="notice">暂无采集记录。点击“开始采集”读取来源的当前公开公告。</div>';
  renderSources();
  $('#provincialCollect').disabled = meta.collection.running;
  renderSchedule();
  renderStages();
  return meta;
}
function searchParams(paging = true) {
  const params = new URLSearchParams();
  for (const [key,id] of Object.entries({q:'query',scope:'scope',industry:'industry',category:'category',region:'region',source:'source',date_from:'dateFrom',date_to:'dateTo',availability:'availability',refine:'refineQuery'})) if ($('#'+id).value) params.set(key, $('#'+id).value.trim());
  for (const type of selectedNoticeTypes) params.append('notice_type', type);
  if ($('#tracked').checked) params.set('tracked','true');
  if (paging) { params.set('offset', state.offset); params.set('limit','20'); }
  return params;
}
async function search() {
  const sequence = ++state.searchSeq;
  $('#projectResults').innerHTML = '<div class="loading">正在查询公告库…</div>';
  try {
    const data = await api('/api/projects?' + searchParams());
    if (sequence !== state.searchSeq) return;
    state.total = data.total;
    $('#resultHint').textContent = {active:'已隐藏明确截止及结果类公告；截止待核实的公告仍保留，请核对原文',open:'仅显示已提取到未来截止时间的公告；请核对原文及最新更正',unknown:'未取得有效截止时间，不能确认是否仍可参与',closed:'历史公告：已过截止时间，或处于中标、合同、终止等结束阶段',all:'全部公告（含历史）；截止状态随查询时间更新'}[data.availability];
    $('#resultCount').textContent = `${data.total.toLocaleString()} 条`;
    $('#projectResults').innerHTML = data.items.length ? data.items.map(p => `<article class="project-card"><div class="project-main"><div class="card-top">${typeTag(p.notice_type)}${availabilityTag(p)}${p.industry && p.industry !== '待分类' ? tag(p.industry) : ''}${p.category && p.category !== '待分类' ? tag(p.category,'purple') : ''}${p.region ? tag(p.region) : ''}${p.lead_id ? tag('已跟进 · '+p.stage,'green') : ''}</div><button class="project-title" data-open="${esc(p.id)}">${esc(p.title)}</button><div class="project-meta"><span>发布 <b>${esc(p.published_at || '日期待补全')}</b></span><span>截止 <b>${esc(p.deadline?.replace('T',' ') || '待核实')}</b></span><span>预算 <b>${esc(p.budget || '待补全')}</b></span><span>采购单位 <b>${esc(p.purchaser || '待补全')}</b></span></div>${p.excerpt ? `<div class="excerpt">${esc(p.excerpt)}</div>` : ''}</div><div class="card-actions"><span class="muted">${esc(p.source || '来源待补全')}</span><button class="button ${p.lead_id ? '' : 'primary'}" ${p.lead_id ? 'data-follow' : 'data-convert'}="${esc(p.id)}">${p.lead_id ? '查看跟进 →' : '＋ 加入线索'}</button></div></article>`).join('') : empty('暂无符合条件的公告', state.meta?.projects ? '试试减少筛选条件，或使用更简短的关键词。' : '点击“采集最新公告”获取真实公告，也可以录入已有项目。');
    $('#pageInfo').textContent = data.total ? `第 ${Math.floor(state.offset / 20) + 1} / ${Math.ceil(data.total / 20)} 页，共 ${data.total} 条` : '暂无结果';
    $('#prevPage').disabled = state.offset === 0; $('#nextPage').disabled = state.offset + 20 >= data.total;
  } catch (error) { if (sequence === state.searchSeq) { $('#projectResults').innerHTML = `<div class="error-box">${esc(error.message)}。可再次点击搜索重试。</div>`; $('#prevPage').disabled = true; $('#nextPage').disabled = true; } }
}
function renderStages() {
  if (!state.meta) return;
  $('#stageSummary').innerHTML = state.meta.stage_options.map(stage => `<button class="stage-chip ${$('#leadStage').value === stage ? 'active' : ''}" data-stage="${esc(stage)}">${esc(stage)}<b>${state.meta.stages[stage] || 0}</b></button>`).join('');
}
function overdue(lead) { return lead.next_followup && new Date(lead.next_followup) <= new Date() && !['成交','失标','放弃'].includes(lead.stage); }
async function loadLeads() {
  const sequence = ++state.leadSeq;
  const params = new URLSearchParams({owner:$('#leadOwner').value, stage:$('#leadStage').value, q:$('#leadQuery').value.trim(), due:$('#dueOnly').checked});
  try {
    const data = await api('/api/leads?' + params);
    if (sequence !== state.leadSeq) return;
    $('#leadCount').textContent = `${data.total} 条`;
    $('#leadRows').innerHTML = data.items.map(l => `<tr><td><button class="project-title" data-follow="${esc(l.project_id)}">${esc(l.title)}</button><small>${esc(l.purchaser || l.source || '采购单位待补全')}</small></td><td>${tag(l.stage, ['成交','已投标'].includes(l.stage) ? 'green' : '')}</td><td>${esc(l.owner || '待分配')}</td><td>${tag(l.priority, l.priority === '紧急' ? 'red' : l.priority === '重要' ? 'orange' : '')}</td><td class="${overdue(l) ? 'overdue' : ''}">${l.next_followup ? esc(l.next_followup.replace('T',' ')) : '未安排'}${overdue(l) ? '<small class="overdue">待跟进</small>' : ''}</td><td><button class="text-button" data-follow="${esc(l.project_id)}">跟进 →</button></td></tr>`).join('');
    $('#leadEmpty').innerHTML = data.items.length ? '' : empty('这里还没有待处理的线索', '从公告库加入线索，或调整负责人、阶段和到期筛选。', '<a class="button" href="#search">前往公告库</a>');
    renderStages();
  } catch (error) { if (sequence === state.leadSeq) { $('#leadRows').innerHTML = ''; $('#leadEmpty').innerHTML = `<div class="error-box">${esc(error.message)}</div>`; } }
}
async function route() {
  const hash = location.hash.slice(1);
  if (hash.startsWith('project/')) {
    await openProject(hash.slice(8)); return;
  }
  state.detailSeq++;
  if ($('#detailDialog').open) $('#detailDialog').close();
  state.page = ['search','leads','settings'].includes(hash) ? hash : 'search';
  $$('.page').forEach(el => el.classList.toggle('active', el.id === 'page-'+state.page));
  $$('[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === state.page));
  $('#breadcrumb').textContent = {search:'标讯搜索',leads:'线索跟进',settings:'数据与成员'}[state.page];
  if (state.page === 'search') await search();
  if (state.page === 'leads') await loadLeads();
}
function navigateProject(key, tab = 'article') { state.tab = tab; if (location.hash === '#project/'+key) openProject(key); else location.hash = 'project/'+key; }
async function openProject(key) {
  const sequence = ++state.detailSeq;
  const dialog = $('#detailDialog'); if (!dialog.open) dialog.showModal();
  $('#detailBody').innerHTML = '<div class="loading">正在打开项目…</div>';
  try { const p = await api('/api/projects/'+encodeURIComponent(key)); if (sequence !== state.detailSeq) return; state.project = p; renderDetail(); dialog.scrollTop = 0; }
  catch (error) { if (sequence === state.detailSeq) $('#detailBody').innerHTML = `<div class="error-box">${esc(error.message)}</div>`; }
}
function detailFields(p) {
  return [['行业（辅助分类，可修改）',p.industry],['采购类别（可修改）',p.category],['采购单位',p.purchaser],['项目编号',p.project_no],['预算金额',p.budget],['截止状态',p.availability_label],['投标截止（无时区按北京时间）',p.deadline?.replace('T',' ')],['所在地区',p.region],['代理机构',p.agency]].map(([label,value]) => `<div class="info-item"><small>${label}</small><span>${esc(value || '待补全 · 以原文为准')}</span></div>`).join('');
}
function renderDetail() {
  const p = state.project, lead = p.lead, url = safeURL(p.url);
  const ownerOptions = [''].concat(state.meta?.members || []).map(m => `<option value="${esc(m)}" ${lead?.owner === m ? 'selected' : ''}>${esc(m || '待分配')}</option>`).join('');
  const related = p.related.length ? `<div class="related"><h3>相同项目编号的公告 · 请核对采购单位</h3>${p.related.map(r => `<button class="project-title" data-open="${esc(r.id)}">${esc(r.title)}</button>`).join('')}</div>` : '';
  $('#detailBody').innerHTML = `<div class="detail-head"><div class="card-top">${typeTag(p.notice_type)}${availabilityTag(p)}${lead ? tag(lead.stage,'green') : tag('尚未加入线索池')}</div><h2>${esc(p.title)}</h2><div class="project-meta"><span>来源 <b>${esc(p.source || '待补全')}</b></span><span>发布 <b>${esc(p.published_at || '日期待补全')}</b></span></div><div class="detail-actions">${url ? `<a class="button" href="${esc(url)}" target="_blank" rel="noopener noreferrer">查看公告原文 ↗</a><button class="button" id="fetchDetail">↻ ${p.content ? '更新正文' : '提取公告正文'}</button>` : ''}${lead ? '<button class="button primary" data-tab="follow">进入线索跟进 →</button>' : `<button class="button primary" data-convert="${esc(p.id)}">＋ 加入线索池</button>`}</div></div><div class="info-grid">${detailFields(p)}</div><div class="detail-tabs"><button data-tab="article" class="${state.tab === 'article' ? 'active' : ''}">公告正文</button><button data-tab="follow" class="${state.tab === 'follow' ? 'active' : ''}">线索跟进${lead ? ' · '+p.notes.filter(n => n.kind === 'note').length : ''}</button></div><section id="detail-article" class="detail-section ${state.tab === 'article' ? 'active' : ''}">${p.detail_error ? `<div class="detail-note">上次提取未成功：${esc(p.detail_error)}${p.content ? '。已保留上次正文。' : ''}</div>` : ''}${p.content ? `<div class="detail-note">正文为网页提取或人工录入内容。时间、金额及投标要求请核对原文。${p.detail_fetched_at ? ' 最近提取：'+esc(prettyTime(p.detail_fetched_at)) : ''}</div><div class="article-content">${esc(p.content)}</div>` : empty('正文尚未提取', url ? '点击上方“提取公告正文”，也可以直接访问公告原文。' : '此项目未填写正文。可通过录入项目保存完整信息。')}${p.attachments.length ? `<div class="attachments"><h3>原文附件链接</h3>${p.attachments.filter(a => safeURL(a.url)).map(a => `<a href="${esc(safeURL(a.url))}" target="_blank" rel="noopener noreferrer">↗ ${esc(a.name)}</a>`).join('')}</div>` : ''}${related}</section><section id="detail-follow" class="detail-section ${state.tab === 'follow' ? 'active' : ''}">${lead ? `<form id="leadForm"><div class="form-grid"><label>负责人<select name="owner">${ownerOptions}</select></label><label>跟进阶段<select name="stage">${state.meta.stage_options.map(s => `<option ${s === lead.stage ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></label><label>优先级<select name="priority">${['普通','重要','紧急'].map(s => `<option ${s === lead.priority ? 'selected' : ''}>${s}</option>`).join('')}</select></label><label>下次跟进（本机时间）<input name="next_followup" type="datetime-local" value="${esc(lead.next_followup)}"></label><label>业务联系人<input name="contact_name" maxlength="100" value="${esc(lead.contact_name)}" placeholder="例如：采购项目负责人"></label><label>联系方式<input name="contact_info" maxlength="300" value="${esc(lead.contact_info)}" placeholder="电话、邮箱或其他联系方式"></label></div><div class="form-footer"><span class="muted">负责人可在“数据与成员”中添加。</span><button type="submit" class="button primary">保存跟进信息</button></div></form><div class="notes"><h3>跟进记录</h3><form class="note-form" id="noteForm"><textarea name="body" required maxlength="10000" placeholder="记录沟通结果、客户需求，以及下一步计划…" aria-label="跟进记录内容"></textarea><button class="button" type="submit">＋ 添加记录</button></form><div class="timeline">${p.notes.map(n => `<div class="timeline-item ${n.kind === 'system' ? 'system' : ''}"><small>${esc(prettyTime(n.created_at))} · ${n.kind === 'system' ? '状态记录' : '沟通记录'}</small><p>${esc(n.body)}</p></div>`).join('')}</div></div>` : empty('将项目加入线索池，开始跟进', '分配负责人、安排下次跟进，并记录每次沟通。', `<button class="button primary" data-convert="${esc(p.id)}">＋ 加入线索池</button>`)}</section>`;
  if (p.collected_sources?.length > 1) $('.detail-head').insertAdjacentHTML('beforeend', `<p class="muted">收录频道：${p.collected_sources.map(esc).join(' · ')}（相同原文已合并）</p>`);
  $('.detail-actions').insertAdjacentHTML('beforeend', '<button class="button" id="editProject">补充 / 编辑信息</button>');
}
function chooseTab(tab) { state.tab = tab; $$('.detail-tabs button').forEach(b => b.classList.toggle('active',b.dataset.tab === tab)); $$('.detail-section').forEach(s => s.classList.toggle('active',s.id === 'detail-'+tab)); }
async function refreshLists() { await refreshMeta(); if (state.page === 'leads') await loadLeads(); else if (state.page === 'search') await search(); }
async function convert(key, button) {
  await busy(button, async () => {
    const data = await api('/api/projects/'+key+'/lead','POST',{});
    await refreshLists(); toast(data.created ? '已加入线索池，可设置负责人和下次跟进' : '此项目已在线索池中');
    navigateProject(key,'follow');
  });
}
async function startCollection(button) {
  await busy(button, async () => { await api('/api/collect','POST'); await refreshMeta(); toast('采集已开始，可继续搜索或处理线索'); });
  if (state.running) { $('#collectButton').disabled = true; $('#settingsCollect').disabled = true; }
}
document.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.open) navigateProject(button.dataset.open);
  if (button.dataset.follow) navigateProject(button.dataset.follow,'follow');
  if (button.dataset.convert) convert(button.dataset.convert, button);
  if (button.dataset.tab) chooseTab(button.dataset.tab);
  if (button.dataset.stage) { $('#leadStage').value = $('#leadStage').value === button.dataset.stage ? '' : button.dataset.stage; loadLeads(); }
  if (button.id === 'editProject') {
    const form = $('#projectForm'), p = state.project;
    form.reset(); form.dataset.editing = p.id;
    for (const element of form.elements) if (element.name && p[element.name] !== undefined) {
      let value = p[element.name];
      if (element.type === 'date') value = value.slice(0,10);
      if (element.type === 'datetime-local') value = value.replace(' ','T').slice(0,16);
      element.value = value;
    }
    form.elements.url.disabled = true;
    $('.dialog-heading h2').textContent = '补充 / 编辑项目信息';
    $('#projectDialog').showModal();
  }
  if (button.id === 'fetchDetail') {
    const key = state.project.id;
    busy(button, async () => {
      try { const p = await api('/api/projects/'+key+'/detail','POST'); if (state.project?.id === key) { state.project = p; renderDetail(); } await refreshLists(); toast('正文已更新'); }
      catch (error) { if (state.project?.id === key) { state.project = await api('/api/projects/'+key); renderDetail(); } throw error; }
    });
  }
});
document.addEventListener('submit', event => {
  if (event.target.id === 'leadForm') {
    event.preventDefault(); const form = event.target, p = state.project;
    const values = {...Object.fromEntries(new FormData(form)), version:p.lead.version};
    busy($('button[type=submit]',form), async () => {
      const updated = await api('/api/leads/'+p.lead.id,'PATCH',values);
      if (state.project?.id === p.id) { state.project = updated; renderDetail(); }
      await refreshLists(); toast('跟进信息已保存');
    });
  }
  if (event.target.id === 'noteForm') {
    event.preventDefault(); const form = event.target, p = state.project;
    busy($('button[type=submit]',form), async () => {
      await api('/api/leads/'+p.lead.id+'/notes','POST',Object.fromEntries(new FormData(form)));
      const updated = await api('/api/projects/'+p.id);
      if (state.project?.id === p.id) { state.project.notes = updated.notes; form.reset(); $('.timeline').innerHTML = updated.notes.map(n => `<div class="timeline-item ${n.kind === 'system' ? 'system' : ''}"><small>${esc(prettyTime(n.created_at))} · ${n.kind === 'system' ? '状态记录' : '沟通记录'}</small><p>${esc(n.body)}</p></div>`).join(''); }
      const counter = $('.detail-tabs button[data-tab="follow"]');
      if (state.project?.id === p.id && counter) counter.textContent = '线索跟进 · '+updated.notes.filter(n => n.kind === 'note').length;
      toast('沟通记录已保存');
    });
  }
});
$('#searchForm').addEventListener('submit', e => { e.preventDefault(); state.offset = 0; search(); });
for (const id of ['industry','category','region','source','dateFrom','dateTo','tracked','scope','availability']) $('#'+id).addEventListener('change', () => { state.offset = 0; search(); });
$('#clearRefine').addEventListener('click', () => { $('#refineQuery').value = ''; state.offset = 0; search(); });
$('#resetSearch').addEventListener('click', () => { $('#searchForm').reset(); selectedNoticeTypes.clear(); renderNoticeTypes(state.meta?.notice_types || []); $('#noticeType').open = false; state.offset = 0; search(); });
$('#prevPage').addEventListener('click', () => { state.offset = Math.max(0,state.offset-20); search(); });
$('#nextPage').addEventListener('click', () => { state.offset += 20; search(); });
$('#exportButton').addEventListener('click', () => { if (state.total > 10000) toast('当前最多导出前 10000 条，请缩小筛选范围'); location.href = '/api/export?'+searchParams(false); });
$('#collectButton').addEventListener('click', e => startCollection(e.currentTarget));
$('#settingsCollect').addEventListener('click', e => startCollection(e.currentTarget));
$('#stopCollect').addEventListener('click', e => busy(e.currentTarget, async () => { const data = await api('/api/collect/stop','POST'); toast(data.message); }));
$('#refreshLeads').addEventListener('click', e => busy(e.currentTarget, refreshLists));
for (const id of ['leadOwner','leadStage','dueOnly']) $('#'+id).addEventListener('change',loadLeads);
let leadTimer; $('#leadQuery').addEventListener('input', () => { clearTimeout(leadTimer); leadTimer = setTimeout(loadLeads,250); });
$('#memberForm').addEventListener('submit', e => { e.preventDefault(); const form = e.currentTarget; busy($('button',form),async () => { await api('/api/members','POST',Object.fromEntries(new FormData(form))); form.reset(); await refreshMeta(); toast('成员已添加'); }); });
$('#addProjectButton').addEventListener('click', () => { const form = $('#projectForm'); form.reset(); delete form.dataset.editing; form.elements.url.disabled = false; $('.dialog-heading h2').textContent = '录入项目'; $('#projectDialog').showModal(); });
$('#closeProject').addEventListener('click', () => $('#projectDialog').close());
$('#projectForm').addEventListener('submit', e => { e.preventDefault(); const form = e.currentTarget; busy($('button[type=submit]',form), async () => { const editing = form.dataset.editing; const values = Object.fromEntries(new FormData(form)); if (editing) values.agency = state.project.agency; const data = await api('/api/projects'+(editing ? '/'+editing : ''),editing ? 'PATCH' : 'POST',values); $('#projectDialog').close(); form.reset(); await refreshLists(); toast(data.created ? '项目已录入' : '项目信息已更新'); navigateProject(data.project.id); }); });
function closeDetail() { state.detailSeq++; if ($('#detailDialog').open) $('#detailDialog').close(); location.hash = state.page; }
$('#closeDetail').addEventListener('click',closeDetail);
$('#detailDialog').addEventListener('cancel', e => { e.preventDefault(); closeDetail(); });
$('#copyProjectLink').addEventListener('click', e => busy(e.currentTarget,async () => { await navigator.clipboard.writeText(location.href); toast('工作台链接已复制，仅在本机可打开'); }));
window.addEventListener('hashchange',route);
async function poll() {
  try { const wasRunning = state.running; await refreshMeta(); if (wasRunning && !state.running) { await refreshLists(); toast(state.meta.collection.message, state.meta.collection.failures > 0); } }
  catch { /* Keep editable forms intact during a temporary service outage. */ }
  finally { setTimeout(poll,5000); }
}
(async () => { try { await refreshMeta(); await route(); } catch (error) { toast(error.message,true); $('#projectResults').innerHTML = '<div class="error-box">服务连接失败，请重新打开工作台。</div>'; } setTimeout(poll,5000); })();

let sourceLimit = 20, scheduleDirty = false, scheduleInitialized = false;
const sourceLabels = {pending:'尚未验证',running:'正在采集',success:'采集成功',partial:'部分失败',empty:'窗口内无公告',blocked:'访问受限',needs_adapter:'待适配',error:'采集失败',stopped:'已停止',interrupted:'上次中断'};
function renderSchedule() {
  const c = state.meta.collection, s = state.meta.schedule;
  if (!scheduleInitialized || !scheduleDirty) {
    $('#scheduleEnabled').checked = s.enabled;
    $('#scheduleInterval').value = s.interval_minutes;
    $('#schedulePages').value = s.pages_per_source;
    scheduleInitialized = true;
  }
  $('#scheduleStatus').textContent = s.enabled ? `自动更新已启用 · 每 ${s.interval_minutes} 分钟 · ${c.running ? '本轮结束后安排下次更新' : '下次：'+prettyTime(s.next_run)}。服务需保持运行。` : '自动更新已暂停，可随时手动采集。';
  $('#collectionProgress').max = Math.max(1,c.total); $('#collectionProgress').value = c.completed;
}
function renderSources() {
  const sources = [...(state.meta.source_configs || [])].sort((a,b) => Number(b.channel === '省站直采') - Number(a.channel === '省站直采') || a.province.localeCompare(b.province,'zh-CN'));
  selectOptions($('#sourceProvince'), [...new Set(sources.map(s => s.province))], '全部地区');
  const problems = s => ['error','blocked','needs_adapter','partial','interrupted'].includes(s.status);
  const stats = [['已登记频道',sources.length,'登记数量不代表已接入'],['省站直采有数据',sources.filter(s => s.channel === '省站直采' && s.stored_count > 0).length,'与全国汇聚独立计数'],['启用自动采集',sources.filter(s => s.enabled).length,'按更新计划执行'],['需要关注',sources.filter(problems).length,'失败、部分失败或待适配']];
  $('#sourceStats').innerHTML = stats.map(([label,count,hint]) => `<div class="stat"><div class="stat-label">${label}</div><div class="stat-number">${count}</div><div class="stat-foot">${hint}</div></div>`).join('');
  const query = $('#sourceQuery').value.trim().toLowerCase(), kind = $('#sourceKind').value, province = $('#sourceProvince').value, health = $('#sourceHealth').value, channel = $('#sourceChannel').value;
  const rows = sources.filter(s => (!query || s.name.toLowerCase().includes(query)) && (!kind || s.kind === kind) && (!channel || (channel === 'direct' ? s.channel === '省站直采' : s.adapter === 'national')) && (!province || s.province === province) && (!health || (health === 'data' && s.stored_count > 0) || (health === 'problem' && problems(s)) || (health === 'pending' && s.status === 'pending') || (health === 'disabled' && !s.enabled) || (health === 'empty' && s.stored_count === 0) || (health === 'backfill' && s.coverage === 'backfill')));
  $('#sourceCount').textContent = `匹配 ${rows.length} 个来源 · 显示 ${Math.min(sourceLimit,rows.length)} 个`;
  $('#moreSources').hidden = sourceLimit >= rows.length;
  $('#sourceList').innerHTML = rows.length ? rows.slice(0,sourceLimit).map(s => `<article class="source-row"><div class="source-main"><div class="source-heading"><h3>${esc(s.name)}</h3>${tag(sourceLabels[s.status] || s.status, ['success','empty'].includes(s.status) ? 'green' : problems(s) ? 'orange' : '')}</div><div class="source-meta">${esc(s.province)} · ${esc(s.kind)} · ${esc(s.channel)} · 已收录 ${s.stored_count} 条</div><p>${esc(s.scope)}</p>${s.coverage ? tag(({backfill:'有待续采的历史页',limited:'覆盖有限，请结合原站核对',window:'已检查查询窗口'})[s.coverage] || s.coverage, s.coverage === 'window' ? '' : 'orange') : ''}<div class="source-message">${esc(s.message || '尚未执行采集，不能确认可用')}</div><small>最近尝试：${esc(prettyTime(s.last_attempt))}　最近有数据：${esc(prettyTime(s.last_success))}${s.retry_at ? '　自动重试不早于：'+esc(prettyTime(s.retry_at)) : ''}</small><div class="source-links"><a href="${esc(safeURL(s.url))}" target="_blank" rel="noopener noreferrer">平台原站 ↗</a>${s.feed_url ? `<a href="${esc(safeURL(s.feed_url))}" target="_blank" rel="noopener noreferrer">汇聚入口 ↗</a>` : ''}</div></div><div class="source-actions"><button class="button" data-source-toggle="${esc(s.id)}" data-enabled="${s.enabled}">${s.enabled ? '停用来源' : '启用来源'}</button><button class="button" data-source-collect="${esc(s.id)}" ${state.running ? 'disabled' : ''}>单独采集</button></div></article>`).join('') : empty('没有匹配的数据源','调整名称、地区或状态筛选。');
}
for (const id of ['sourceKind','sourceProvince','sourceHealth','sourceChannel']) $('#'+id).addEventListener('change', () => { sourceLimit=20; renderSources(); });
$('#sourceQuery').addEventListener('input', () => { sourceLimit=20; renderSources(); });
$('#moreSources').addEventListener('click', () => { sourceLimit+=20; renderSources(); });
$('#scheduleForm').addEventListener('input', () => { scheduleDirty = true; });
$('#scheduleForm').addEventListener('submit', e => { e.preventDefault(); busy($('button',e.currentTarget), async () => {
  const body = {enabled:$('#scheduleEnabled').checked,interval_minutes:Number($('#scheduleInterval').value),pages_per_source:Number($('#schedulePages').value)};
  await api('/api/schedule','PUT',body); scheduleDirty=false; await refreshMeta(); toast('自动更新计划已保存，重启后继续生效');
}); });
$('#sourceList').addEventListener('click', e => {
  const toggle = e.target.closest('[data-source-toggle]'), collect = e.target.closest('[data-source-collect]');
  if (toggle) busy(toggle,async () => { await api('/api/sources/'+toggle.dataset.sourceToggle,'PATCH',{enabled:toggle.dataset.enabled !== 'true'}); await refreshMeta(); toast('来源设置已保存'); });
  if (collect) busy(collect,async () => { await api('/api/sources/'+collect.dataset.sourceCollect+'/collect','POST'); await refreshMeta(); toast('已开始单独采集'); });
});
$('#provincialCollect').addEventListener('click', async e => {
  const button = e.currentTarget;
  await busy(button, async () => { await api('/api/collect/provincial','POST'); await refreshMeta(); toast('已开始省站直采，未完成的补采页会继续推进'); });
  button.disabled = state.running;
});
