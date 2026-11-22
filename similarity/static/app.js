'use strict';

const NS = 'http://www.w3.org/2000/svg';
const $ = (sel) => document.querySelector(sel);

const state = {
  info: null,
  groups: [],
  group: null,
  shots: [],
  current: null,
  annotations: [],
  selected: null,
  mode: 'box',
  dirty: false,
  lastLabel: '',
  drag: null,
  preview: null,
};

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

async function api(url, options) {
  const opts = options || {};
  if (opts.body && !opts.headers) opts.headers = { 'Content-Type': 'application/json' };
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch (err) { data = null; }
  if (!res.ok) {
    const detail = data && data.error ? data.error : 'HTTP ' + res.status;
    throw new Error(detail);
  }
  return data;
}

let toastTimer = null;
function toast(message, isError) {
  const box = $('#toast');
  box.textContent = message;
  box.className = isError ? 'show err' : 'show';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = ''; }, isError ? 6000 : 2600);
}

async function loadInfo(force) {
  let info;
  try {
    info = await api('/api/info');
  } catch (err) {
    toast(err.message, true);
    return;
  }
  state.info = info;
  $('#hdr-sub').textContent = info.platform;

  const stats = $('#stats');
  stats.textContent = '';
  const badge = document.createElement('span');
  badge.className = 'badge ' + (info.capture ? 'ok' : 'bad');
  badge.textContent = info.capture ? '截屏可用' : '截屏不可用';
  if (!info.capture) badge.title = info.capture_error;
  stats.appendChild(badge);
  const parts = [
    ['分组', info.stats.groups],
    ['截图', info.stats.shots],
    ['标注', info.stats.annotations],
    ['标签', info.stats.labels.length],
  ];
  parts.forEach(([name, value]) => {
    const span = document.createElement('span');
    span.textContent = name + ' ';
    const bold = document.createElement('b');
    bold.textContent = value;
    span.appendChild(bold);
    stats.appendChild(span);
  });
  const path = document.createElement('span');
  path.className = 'path';
  path.textContent = info.dataset_dir;
  stats.appendChild(path);

  const proc = $('#process');
  if (force || !proc.value) proc.value = info.default_process || '';
  syncCaptureButton();
}

async function loadShots() {
  if (!state.group) {
    state.shots = [];
    renderShotList();
    return;
  }
  try {
    state.shots = await api(gpath('/shots'));
  } catch (err) {
    toast(err.message, true);
    return;
  }
  renderShotList();
}

function renderShotList() {
  const list = $('#shot-list');
  list.textContent = '';
  $('#shot-count').textContent = state.shots.length;
  if (!state.shots.length) {
    const empty = document.createElement('div');
    empty.className = 'ann-empty';
    empty.textContent = '还没有截图';
    list.appendChild(empty);
    return;
  }
  state.shots.forEach((shot) => {
    const item = document.createElement('div');
    item.className = 'shot-item';
    if (state.current && shot.id === state.current.id) item.classList.add('on');

    const thumb = document.createElement('img');
    thumb.src = shot.thumb_url || ('/shots/' + state.group + '/' + shot.id + '.thumb.jpg');
    thumb.alt = shot.id;

    const meta = document.createElement('div');
    meta.className = 'shot-meta';
    const title = document.createElement('div');
    title.className = 't';
    title.textContent = shot.captured_at;
    const size = document.createElement('div');
    size.className = 's';
    size.textContent = shot.width + '×' + shot.height + ' · ' + (shot.source === 'fullscreen' ? '整屏' : '窗口');
    const count = document.createElement('div');
    count.className = 'n';
    count.textContent = (shot.annotation_count || 0) + ' 个标注';
    meta.append(title, size, count);

    const del = document.createElement('button');
    del.className = 'shot-del danger';
    del.textContent = '✕';
    del.title = '删除这张截图';
    del.onclick = (event) => {
      event.stopPropagation();
      deleteShot(shot.id);
    };

    item.append(thumb, meta, del);
    item.onclick = () => selectShot(shot.id);
    list.appendChild(item);
  });
}

function confirmDiscard() {
  if (!state.dirty) return true;
  return window.confirm('当前截图的标注还没保存，切换会丢失。继续？');
}

async function selectShot(id) {
  if (state.current && state.current.id === id) return;
  if (!confirmDiscard()) return;
  let record;
  try {
    record = await api(gpath('/shots/' + id));
  } catch (err) {
    toast(err.message, true);
    return;
  }
  state.current = record;
  state.annotations = JSON.parse(JSON.stringify(record.annotations || []));
  state.selected = null;
  state.drag = null;
  state.preview = null;
  setDirty(false);
  $('#note').value = record.note || '';
  $('#stage-empty').classList.add('hidden');
  $('#stage').classList.remove('hidden');
  renderFoot();
  renderAnns();
  const img = $('#shot-img');
  img.onload = () => renderOverlay();
  img.src = record.image_url + '?v=' + encodeURIComponent(record.updated_at || record.captured_at);
  renderOverlay();
  renderShotList();
  syncMoveControl();
}

function renderFoot() {
  const shot = state.current;
  const foot = $('#stage-foot');
  if (!shot) { foot.textContent = ''; return; }
  const cap = shot.region ? '窗口区域 [' + shot.region.join(', ') + ']' : '整屏';
  const parts = [
    shot.id,
    shot.captured_at,
    shot.width + '×' + shot.height,
    '来源 ' + shot.source,
    cap,
    shot.process ? '进程 ' + shot.process : '',
    shot.window_id ? 'wid=' + shot.window_id : '',
    shot.origin ? '屏幕原点 (' + shot.origin.join(', ') + ')' : '',
    shot.updated_at ? '标注保存于 ' + shot.updated_at : '',
  ];
  foot.textContent = parts.filter(Boolean).join('  ·  ');
}

function setDirty(value) {
  state.dirty = value;
  $('#dirty-hint').textContent = value ? '● 未保存' : '';
  const btn = $('#btn-save');
  btn.disabled = !value || !state.current;
}

function nextLabel() {
  if (state.lastLabel) return state.lastLabel;
  return '标注' + (state.annotations.length + 1);
}

function addAnn(partial) {
  const ann = Object.assign({ id: 'a' + Math.random().toString(36).slice(2, 10) }, partial);
  state.annotations.push(ann);
  state.selected = ann.id;
  if (ann.label) state.lastLabel = ann.label;
  setDirty(true);
  renderOverlay();
  renderAnns();
  const input = document.querySelector('.ann-row.on input[type="text"]');
  if (input) { input.focus(); input.select(); }
}

function removeAnn(id) {
  state.annotations = state.annotations.filter((item) => item.id !== id);
  if (state.selected === id) state.selected = null;
  setDirty(true);
  renderOverlay();
  renderAnns();
}

function setSelected(id) {
  state.selected = id;
  renderOverlay();
  renderAnns();
}

function renderAnns() {
  const list = $('#ann-list');
  list.textContent = '';
  $('#ann-count').textContent = state.annotations.length;
  if (!state.annotations.length) {
    const empty = document.createElement('div');
    empty.className = 'ann-empty';
    empty.textContent = state.current
      ? (state.mode === 'point' ? '在图上点一下标注一个点' : '在图上拖出一个框标注区域')
      : '先捕获或选择一张截图';
    list.appendChild(empty);
    return;
  }
  state.annotations.forEach((ann, index) => {
    const row = document.createElement('div');
    row.className = 'ann-row';
    if (ann.id === state.selected) row.classList.add('on');
    row.onclick = () => setSelected(ann.id);

    const top = document.createElement('div');
    top.className = 'ann-top';
    const kind = document.createElement('span');
    kind.className = 'ann-kind';
    kind.textContent = ann.kind === 'point' ? '•' : '▭';
    const label = document.createElement('input');
    label.type = 'text';
    label.value = ann.label || '';
    label.placeholder = '标签名，如 挑战按钮';
    label.onclick = (event) => event.stopPropagation();
    label.oninput = () => {
      ann.label = label.value;
      state.lastLabel = label.value.trim() || state.lastLabel;
      setDirty(true);
      renderOverlay();
    };
    const del = document.createElement('button');
    del.className = 'ann-del danger';
    del.textContent = '✕';
    del.onclick = (event) => {
      event.stopPropagation();
      removeAnn(ann.id);
    };
    top.append(kind, label, del);

    const coords = document.createElement('div');
    coords.className = 'ann-coords';
    const fields = ann.kind === 'point'
      ? [['x', ann.point.x], ['y', ann.point.y]]
      : [['x', ann.box.x], ['y', ann.box.y], ['w', ann.box.w], ['h', ann.box.h]];
    fields.forEach(([key, value]) => {
      const hint = document.createElement('span');
      hint.textContent = key;
      const input = document.createElement('input');
      input.type = 'number';
      input.value = value;
      input.onclick = (event) => event.stopPropagation();
      input.onchange = () => {
        const number = parseInt(input.value, 10);
        if (Number.isNaN(number)) { renderAnns(); return; }
        const target = ann.kind === 'point' ? ann.point : ann.box;
        target[key] = number;
        setDirty(true);
        renderOverlay();
      };
      coords.append(hint, input);
    });

    row.append(top, coords);
    list.appendChild(row);
  });
}

function annNode(ann, index, fontSize) {
  const group = document.createElementNS(NS, 'g');
  group.dataset.id = ann.id;
  const selected = ann.id === state.selected;
  const text = (index + 1) + '. ' + (ann.label || '未命名');

  if (ann.kind === 'point') {
    const r = Math.max(6, fontSize * 0.55);
    const dot = document.createElementNS(NS, 'circle');
    dot.setAttribute('cx', ann.point.x);
    dot.setAttribute('cy', ann.point.y);
    dot.setAttribute('r', r);
    dot.setAttribute('class', 'ann-dot' + (selected ? ' sel' : ''));
    group.appendChild(dot);
    const label = document.createElementNS(NS, 'text');
    label.setAttribute('x', ann.point.x + r + 3);
    label.setAttribute('y', ann.point.y + r);
    label.setAttribute('font-size', fontSize);
    label.setAttribute('stroke-width', fontSize / 4);
    label.setAttribute('class', 'ann-label');
    label.textContent = text;
    group.appendChild(label);
    return group;
  }

  const box = ann.box;
  const rect = document.createElementNS(NS, 'rect');
  rect.setAttribute('x', box.x);
  rect.setAttribute('y', box.y);
  rect.setAttribute('width', box.w);
  rect.setAttribute('height', box.h);
  rect.setAttribute('class', 'ann-box' + (selected ? ' sel' : ''));
  group.appendChild(rect);

  const label = document.createElementNS(NS, 'text');
  label.setAttribute('x', box.x + 2);
  label.setAttribute('y', box.y > fontSize * 1.2 ? box.y - fontSize * 0.25 : box.y + fontSize);
  label.setAttribute('font-size', fontSize);
  label.setAttribute('stroke-width', fontSize / 4);
  label.setAttribute('class', 'ann-label');
  label.textContent = text;
  group.appendChild(label);
  return group;
}

function renderOverlay() {
  const svg = $('#overlay');
  svg.textContent = '';
  if (!state.current) return;
  const width = state.current.width;
  const height = state.current.height;
  svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
  const fontSize = Math.max(11, Math.round(width / 55));
  state.annotations.forEach((ann, index) => svg.appendChild(annNode(ann, index, fontSize)));
  if (state.preview) svg.appendChild(state.preview);
}

function toImage(event) {
  const rect = $('#overlay').getBoundingClientRect();
  const width = state.current.width;
  const height = state.current.height;
  if (!rect.width || !rect.height) return { x: 0, y: 0 };
  return {
    x: clamp(Math.round((event.clientX - rect.left) / rect.width * width), 0, width - 1),
    y: clamp(Math.round((event.clientY - rect.top) / rect.height * height), 0, height - 1),
  };
}

function updatePreview() {
  const drag = state.drag;
  if (!drag) return;
  const x = Math.min(drag.x0, drag.x1);
  const y = Math.min(drag.y0, drag.y1);
  const w = Math.abs(drag.x1 - drag.x0);
  const h = Math.abs(drag.y1 - drag.y0);
  if (!state.preview) {
    state.preview = document.createElementNS(NS, 'rect');
    state.preview.setAttribute('class', 'ann-preview');
  }
  state.preview.setAttribute('x', x);
  state.preview.setAttribute('y', y);
  state.preview.setAttribute('width', w);
  state.preview.setAttribute('height', h);
  renderOverlay();
}

function onPointerDown(event) {
  if (!state.current || event.button !== 0) return;
  const hit = event.target.closest ? event.target.closest('g[data-id]') : null;
  if (hit) {
    setSelected(hit.dataset.id);
    return;
  }
  const point = toImage(event);
  if (state.mode === 'point') {
    addAnn({ kind: 'point', point: point, label: nextLabel() });
    return;
  }
  state.drag = { x0: point.x, y0: point.y, x1: point.x, y1: point.y };
  try { $('#overlay').setPointerCapture(event.pointerId); } catch (err) { }
  updatePreview();
  event.preventDefault();
}

function onPointerMove(event) {
  if (!state.drag || !state.current) return;
  const point = toImage(event);
  state.drag.x1 = point.x;
  state.drag.y1 = point.y;
  updatePreview();
}

function onPointerUp(event) {
  if (!state.drag) return;
  const drag = state.drag;
  state.drag = null;
  if (state.current) {
    const end = toImage(event);
    drag.x1 = end.x;
    drag.y1 = end.y;
  }
  state.preview = null;
  const w = Math.abs(drag.x1 - drag.x0);
  const h = Math.abs(drag.y1 - drag.y0);
  if (w >= 4 && h >= 4) {
    addAnn({
      kind: 'box',
      box: { x: Math.min(drag.x0, drag.x1), y: Math.min(drag.y0, drag.y1), w: w, h: h },
      label: nextLabel(),
    });
    return;
  }
  renderOverlay();
}

function setMode(mode) {
  state.mode = mode;
  $('#mode-box').classList.toggle('on', mode === 'box');
  $('#mode-point').classList.toggle('on', mode === 'point');
  $('#overlay').style.cursor = mode === 'point' ? 'copy' : 'crosshair';
  renderAnns();
}

async function capture() {
  if (!state.group) { toast('请先新建或选择一个分组', true); return; }
  if (!confirmDiscard()) return;
  const btn = $('#btn-capture');
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ 截图中…';
  try {
    const record = await api(gpath('/capture'), {
      method: 'POST',
      body: JSON.stringify({
        source: $('#source').value,
        process: $('#process').value.trim(),
      }),
    });
    state.dirty = false;
    await loadShots();
    await selectShot(record.id);
    await loadGroups();
    await loadInfo();
    toast('已捕获 ' + record.width + '×' + record.height + ' 到分组「'
      + ((currentGroup() || {}).name || '') + '」');
  } catch (err) {
    toast(err.message, true);
  }
  btn.textContent = label;
  syncCaptureButton();
}

async function save() {
  if (!state.current || !state.dirty) return;
  const btn = $('#btn-save');
  btn.disabled = true;
  try {
    const record = await api(gpath('/shots/' + state.current.id + '/annotations'), {
      method: 'PUT',
      body: JSON.stringify({ annotations: state.annotations, note: $('#note').value }),
    });
    state.current = record;
    state.annotations = JSON.parse(JSON.stringify(record.annotations || []));
    state.selected = null;
    setDirty(false);
    renderAnns();
    renderOverlay();
    renderFoot();
    await loadShots();
    await loadGroups();
    await loadInfo();
    toast('已保存 ' + (record.annotation_count || 0) + ' 个标注');
  } catch (err) {
    toast(err.message, true);
    btn.disabled = false;
  }
}

async function deleteShot(id) {
  if (!window.confirm('删除截图 ' + id + ' 及其全部标注？不可恢复。')) return;
  try {
    await api(gpath('/shots/' + id), { method: 'DELETE' });
  } catch (err) {
    toast(err.message, true);
    return;
  }
  if (state.current && state.current.id === id) {
    state.current = null;
    state.annotations = [];
    state.selected = null;
    setDirty(false);
    $('#note').value = '';
    showStageEmpty(EMPTY_SHOT_HINT);
    renderOverlay();
    renderAnns();
    renderFoot();
    syncMoveControl();
  }
  await loadGroups();
  await loadShots();
  await loadInfo();
  if (!state.current && state.shots.length) await selectShot(state.shots[0].id);
  toast('已删除 ' + id);
}

function gpath(suffix) {
  return '/api/groups/' + encodeURIComponent(state.group || '') + (suffix || '');
}

function currentGroup() {
  return state.groups.find((item) => item.key === state.group) || null;
}

function syncCaptureButton() {
  const btn = $('#btn-capture');
  btn.disabled = !(state.info && state.info.capture) || !state.group;
  if (state.info && !state.info.capture) btn.title = state.info.capture_error;
  else if (!state.group) btn.title = '请先新建或选择一个分组';
  else btn.title = '抓取目标窗口画面，存进当前分组';
}

function showStageEmpty(text) {
  $('#stage').classList.add('hidden');
  $('#shot-img').removeAttribute('src');
  const empty = $('#stage-empty');
  empty.textContent = text;
  empty.classList.remove('hidden');
}

const EMPTY_GROUP_HINT = '还没有分组。点左上角「＋ 新建分组」建一个，比如「御魂探索」。';
const EMPTY_SHOT_HINT = '这个分组还没有截图。点「📷 捕获截图」抓一张模拟器画面。';

async function loadGroups(preferKey) {
  try {
    state.groups = await api('/api/groups');
  } catch (err) {
    state.groups = [];
    toast(err.message, true);
    return;
  }
  const wanted = preferKey || state.group;
  const found = state.groups.find((item) => item.key === wanted);
  state.group = found ? found.key : (state.groups.length ? state.groups[0].key : null);
  renderGroupBar();
  syncCaptureButton();
}

function renderGroupBar() {
  const select = $('#group-select');
  select.textContent = '';
  state.groups.forEach((group) => {
    const option = document.createElement('option');
    option.value = group.key;
    option.textContent = group.name + '（' + group.shots + '）';
    if (group.key === state.group) option.selected = true;
    select.appendChild(option);
  });
  const group = currentGroup();
  const desc = $('#group-desc');
  desc.textContent = group
    ? [group.description, group.dir].filter(Boolean).join('  ·  ')
    : EMPTY_GROUP_HINT;
  desc.title = group ? group.dir : '';
  select.disabled = !group;
  $('#btn-group-edit').disabled = !group;
  $('#btn-group-del').disabled = !group;

  syncMoveControl();
}

function syncMoveControl() {
  const move = $('#move-target');
  const keep = move.value;
  move.textContent = '';
  state.groups.forEach((item) => {
    if (item.key === state.group) return;
    const option = document.createElement('option');
    option.value = item.key;
    option.textContent = item.name;
    move.appendChild(option);
  });
  if ([...move.options].some((option) => option.value === keep)) move.value = keep;
  const canMove = !!state.current && move.options.length > 0;
  $('#stage-tools').classList.toggle('hidden', !canMove);
  $('#btn-move').disabled = !canMove;
}

async function enterGroup(key) {
  if (!key) return;
  state.group = key;
  state.shots = [];
  state.current = null;
  state.annotations = [];
  state.selected = null;
  state.drag = null;
  state.preview = null;
  setDirty(false);
  $('#note').value = '';
  renderGroupBar();
  showStageEmpty(EMPTY_SHOT_HINT);
  renderOverlay();
  renderAnns();
  renderFoot();
  await loadShots();
  if (state.shots.length) await selectShot(state.shots[0].id);
  syncCaptureButton();
}

async function switchGroup(key) {
  if (!key || key === state.group) { renderGroupBar(); return; }
  if (!confirmDiscard()) { renderGroupBar(); return; }
  await enterGroup(key);
  await loadInfo();
  toast('已切换到分组「' + ((currentGroup() || {}).name || '') + '」');
}

let modalMode = 'create';

function openGroupModal(mode) {
  modalMode = mode;
  const group = currentGroup();
  $('#modal-title').textContent = mode === 'create' ? '新建分组' : '编辑分组';
  $('#modal-name').value = mode === 'create' ? '' : (group ? group.name : '');
  $('#modal-desc').value = mode === 'create' ? '' : ((group && group.description) || '');
  $('#modal-root').classList.remove('hidden');
  $('#modal-name').focus();
}

function closeGroupModal() {
  $('#modal-root').classList.add('hidden');
}

async function submitGroupModal() {
  const name = $('#modal-name').value.trim();
  const description = $('#modal-desc').value.trim();
  if (!name) { toast('分组名不能为空', true); return; }
  const ok = $('#modal-ok');
  ok.disabled = true;
  const previous = state.group;
  try {
    const group = modalMode === 'create'
      ? await api('/api/groups', {
        method: 'POST',
        body: JSON.stringify({ name: name, description: description }),
      })
      : await api(gpath(), {
        method: 'PATCH',
        body: JSON.stringify({ name: name, description: description }),
      });
    closeGroupModal();
    await loadGroups(group.key);
    if (state.group !== previous) await enterGroup(state.group);
    await loadInfo();
    toast((modalMode === 'create' ? '已创建分组「' : '已保存分组「') + group.name + '」');
  } catch (err) {
    toast(err.message, true);
  }
  ok.disabled = false;
}

async function deleteGroup() {
  const group = currentGroup();
  if (!group) return;
  const text = group.shots
    ? '删除分组「' + group.name + '」及其 ' + group.shots + ' 张截图和全部标注？不可恢复。'
    : '删除分组「' + group.name + '」？';
  if (!window.confirm(text)) return;
  try {
    await api(gpath(), { method: 'DELETE' });
  } catch (err) {
    toast(err.message, true);
    return;
  }
  state.group = null;
  state.current = null;
  state.annotations = [];
  state.selected = null;
  setDirty(false);
  $('#note').value = '';
  await loadGroups();
  if (state.group) {
    await enterGroup(state.group);
  } else {
    state.shots = [];
    renderGroupBar();
    showStageEmpty(EMPTY_GROUP_HINT);
    renderShotList();
    renderOverlay();
    renderAnns();
    renderFoot();
    syncCaptureButton();
  }
  await loadInfo();
  toast('已删除分组「' + group.name + '」');
}

async function moveShot() {
  if (!state.current) return;
  const target = $('#move-target').value;
  if (!target) return;
  const targetName = (state.groups.find((item) => item.key === target) || {}).name || target;
  const moved = state.current.id;
  try {
    await api(gpath('/shots/' + moved + '/move'), {
      method: 'POST',
      body: JSON.stringify({ to: target }),
    });
  } catch (err) {
    toast(err.message, true);
    return;
  }
  const keep = state.group;
  state.current = null;
  state.annotations = [];
  state.selected = null;
  setDirty(false);
  $('#note').value = '';
  await loadGroups(keep);
  await loadShots();
  if (state.shots.length) await selectShot(state.shots[0].id);
  else {
    showStageEmpty(EMPTY_SHOT_HINT);
    renderOverlay();
    renderAnns();
    renderFoot();
    syncMoveControl();
  }
  await loadInfo();
  toast('已把 ' + moved + ' 移到分组「' + targetName + '」');
}

function bind() {
  $('#btn-capture').onclick = capture;
  $('#btn-save').onclick = save;
  $('#btn-refresh').onclick = async () => {
    if (!confirmDiscard()) return;
    await loadInfo(true);
    await loadGroups();
    await loadShots();
    toast('已刷新');
  };
  $('#group-select').onchange = (event) => switchGroup(event.target.value);
  $('#btn-group-new').onclick = () => openGroupModal('create');
  $('#btn-group-edit').onclick = () => openGroupModal('edit');
  $('#btn-group-del').onclick = deleteGroup;
  $('#btn-move').onclick = moveShot;
  $('#modal-ok').onclick = submitGroupModal;
  $('#modal-cancel').onclick = closeGroupModal;
  $('#modal-close').onclick = closeGroupModal;
  $('#modal-root').onclick = (event) => {
    if (event.target.id === 'modal-root') closeGroupModal();
  };
  $('#modal-name').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); submitGroupModal(); }
  });
  $('#mode-box').onclick = () => setMode('box');
  $('#mode-point').onclick = () => setMode('point');
  $('#zoom-1to1').onchange = (event) => {
    $('#stage').classList.toggle('actual', event.target.checked);
    renderOverlay();
  };
  $('#note').oninput = () => { if (state.current) setDirty(true); };

  const svg = $('#overlay');
  svg.addEventListener('pointerdown', onPointerDown);
  svg.addEventListener('pointermove', onPointerMove);
  svg.addEventListener('pointerup', onPointerUp);
  svg.addEventListener('pointercancel', onPointerUp);

  document.addEventListener('keydown', (event) => {
    const tag = (event.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    if (event.key === 'Escape' && !$('#modal-root').classList.contains('hidden')) {
      closeGroupModal();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      save();
      return;
    }
    if (typing) return;
    if (event.key === 'b') setMode('box');
    if (event.key === 'p') setMode('point');
    if (event.key === 'Escape') setSelected(null);
    if ((event.key === 'Delete' || event.key === 'Backspace') && state.selected) {
      event.preventDefault();
      removeAnn(state.selected);
    }
  });

  window.addEventListener('beforeunload', (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
}

async function init() {
  bind();
  setMode('box');
  await loadInfo(true);
  await loadGroups();
  await loadShots();
  if (state.shots.length) await selectShot(state.shots[0].id);
  else {
    showStageEmpty(state.group ? EMPTY_SHOT_HINT : EMPTY_GROUP_HINT);
    renderAnns();
  }
}

init();
