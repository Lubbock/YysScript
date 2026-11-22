'use strict';

const $ = (sel) => document.querySelector(sel);

const cmp = {
  info: null,
  slots: { a: null, b: null },
  comparing: false,
};

async function api(url, options) {
  const opts = options || {};
  if (opts.body && !opts.headers) opts.headers = { 'Content-Type': 'application/json' };
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch (err) { data = null; }
  if (!res.ok) {
    throw new Error(data && data.error ? data.error : 'HTTP ' + res.status);
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

function nextSlot() {
  if (!cmp.slots.a) return 'a';
  if (!cmp.slots.b) return 'b';
  return 'b';
}

function missingCount() {
  return (cmp.slots.a ? 0 : 1) + (cmp.slots.b ? 0 : 1);
}

function syncButtons() {
  const missing = missingCount();
  const captureOk = !!(cmp.info && cmp.info.capture);
  $('#btn-capture').disabled = !captureOk || cmp.comparing;
  $('#btn-compare').disabled = missing > 0 || cmp.comparing;
  $('#btn-clear').disabled = missing === 2 || cmp.comparing;
  $('#slot-hint').textContent = missing === 0
    ? '两张已就绪，可以点「🔍 对比」'
    : '还需要捕获 ' + missing + ' 张';
  ['a', 'b'].forEach((slot) => {
    $('.cmp-recap[data-slot="' + slot + '"]').disabled = !cmp.slots[slot] || cmp.comparing;
  });
}

function renderSlot(slot) {
  const shot = cmp.slots[slot];
  const image = $('#img-' + slot);
  const empty = $('#empty-' + slot);
  const foot = $('#foot-' + slot);
  const time = $('#time-' + slot);
  if (!shot) {
    image.classList.add('hidden');
    image.removeAttribute('src');
    empty.classList.remove('hidden');
    foot.textContent = '';
    time.textContent = '未捕获';
    $('#slot-' + slot).classList.remove('filled');
    return;
  }
  empty.classList.add('hidden');
  image.classList.remove('hidden');
  image.src = shot.image_url + '?t=' + encodeURIComponent(shot.id);
  time.textContent = shot.captured_at;
  $('#slot-' + slot).classList.add('filled');
  const origin = shot.origin ? '屏幕原点 (' + shot.origin.join(', ') + ')' : '';
  foot.textContent = [
    shot.width + '×' + shot.height,
    shot.source === 'fullscreen' ? '整屏' : '窗口',
    shot.process || '',
    origin,
    shot.id,
  ].filter(Boolean).join('  ·  ');
}

function renderInfo() {
  const info = cmp.info;
  if (!info) return;
  $('#hdr-sub').textContent = info.platform;
  const stats = $('#stats');
  stats.textContent = '';

  const badge = document.createElement('span');
  badge.className = 'badge ' + (info.capture ? 'ok' : 'bad');
  badge.textContent = info.capture ? '截屏可用' : '截屏不可用';
  if (!info.capture) badge.title = info.capture_error;
  stats.appendChild(badge);

  const model = info.model || {};
  const badgeModel = document.createElement('span');
  badgeModel.className = 'badge ' + (model.ok ? 'ok' : 'bad');
  badgeModel.textContent = model.ok
    ? '模型 ' + (model.model || info.compare_method) + ' 在线'
    : '模型不可用';
  badgeModel.title = model.ok
    ? '能力: ' + (model.capabilities || []).join(', ') + '  ·  阈值 ' + (info.threshold != null ? info.threshold : '-')
    : (model.error || '未知错误');
  stats.appendChild(badgeModel);

  if (!model.ok && model.error) {
    const warn = document.createElement('span');
    warn.className = 'badge warn';
    warn.textContent = '对比不可用';
    warn.title = model.error;
    stats.appendChild(warn);
  }

  const dir = document.createElement('span');
  dir.className = 'path';
  dir.textContent = info.compare_dir;
  stats.appendChild(dir);

  const proc = $('#process');
  if (!proc.value) proc.value = info.default_process || '';
  $('#btn-capture').title = info.capture
    ? '连点两次，依次填入 A、B 两个槽位'
    : info.capture_error;
}

async function loadInfo() {
  try {
    cmp.info = await api('/api/info');
  } catch (err) {
    toast(err.message, true);
    return;
  }
  renderInfo();
  syncButtons();
}

async function captureTo(slot) {
  const btn = $('#btn-capture');
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ 截图中…';
  try {
    const record = await api('/api/compare/capture', {
      method: 'POST',
      body: JSON.stringify({
        source: $('#source').value,
        process: $('#process').value.trim(),
      }),
    });
    cmp.slots[slot] = record;
    renderSlot(slot);
    hideResult();
    toast('已捕获 ' + (slot === 'a' ? 'A' : 'B') + '：' + record.width + '×' + record.height);
  } catch (err) {
    toast(err.message, true);
  }
  btn.textContent = label;
  syncButtons();
}

function hideResult() {
  $('#result').classList.add('hidden');
}

function pct(value) {
  return typeof value === 'number' ? (value * 100).toFixed(1) + '%' : '—';
}

function renderResult(result) {
  const d = (result.details && typeof result.details === 'object') ? result.details : {};
  $('#result').classList.remove('hidden');

  const badge = $('#result-badge');
  badge.className = 'badge ' + (result.matched ? 'ok' : 'bad');
  badge.textContent = result.matched ? '✓ 同一界面' : '✗ 不是同一界面';

  $('#result-title').textContent = typeof d.same_screen === 'boolean'
    ? (d.same_screen ? '模型判定：同一界面' : '模型判定：不同界面')
    : '对比结果';

  const score = typeof result.score === 'number' ? result.score : null;
  $('#result-score').textContent = score === null ? '' : '可信度 ' + pct(score);
  const bar = $('#result-bar');
  bar.style.width = (score === null ? 0 : Math.round(score * 100)) + '%';
  bar.className = score === null ? '' : (score >= 0.8 ? 'hi' : (score >= 0.5 ? 'mid' : 'lo'));

  const meta = [];
  if (d.model || result.method) meta.push('模型 ' + (d.model || result.method));
  const ms = typeof d.elapsed_ms === 'number' ? d.elapsed_ms : result.elapsed_ms;
  if (typeof ms === 'number') meta.push('模型耗时 ' + (ms / 1000).toFixed(1) + 's');
  if (typeof d.confidence === 'number') meta.push('模型把握 ' + pct(d.confidence));
  if (typeof d.threshold === 'number') meta.push('阈值 ' + d.threshold);
  $('#result-meta').textContent = meta.join('  ·  ');

  const notes = [];
  if (d.inconsistent) {
    notes.push('模型结论与可信度不自洽（same_screen=' + d.same_screen
      + '，可信度 ' + pct(score) + '），建议人工复核。');
  }
  if (d.truncated) notes.push('模型输出被截断，以上字段是尽力解析的结果。');
  const warn = $('#result-warn');
  warn.textContent = notes.join(' ');
  warn.classList.toggle('hidden', notes.length === 0);

  $('#result-a').textContent = d.a_summary || '—';
  $('#result-b').textContent = d.b_summary || '—';

  const list = $('#result-diffs');
  list.textContent = '';
  const diffs = Array.isArray(d.differences) ? d.differences : [];
  diffs.forEach((item) => {
    const li = document.createElement('li');
    li.textContent = item;
    list.appendChild(li);
  });
  $('#result-diff-box').classList.toggle('hidden', diffs.length === 0);

  $('#result-message').textContent = result.message || '';
  $('#result-message').classList.toggle('hidden', !result.message);

  $('#result-details-box').classList.remove('hidden');
  $('#result-details').textContent = JSON.stringify(result, null, 2);
}

async function runCompare() {
  if (missingCount() > 0 || cmp.comparing) return;
  cmp.comparing = true;
  const btn = $('#btn-compare');
  const label = btn.textContent;
  btn.textContent = '⏳ 模型判定中…';
  syncButtons();
  try {
    const result = await api('/api/compare', {
      method: 'POST',
      body: JSON.stringify({ a: cmp.slots.a.id, b: cmp.slots.b.id }),
    });
    renderResult(result);
    toast(result.matched
      ? '同一界面，可信度 ' + pct(result.score)
      : '不是同一界面，可信度 ' + pct(result.score), !result.matched);
  } catch (err) {
    hideResult();
    toast(err.message, true);
  }
  btn.textContent = label;
  cmp.comparing = false;
  syncButtons();
}

function clearAll() {
  cmp.slots.a = null;
  cmp.slots.b = null;
  renderSlot('a');
  renderSlot('b');
  hideResult();
  syncButtons();
  toast('已清空两个槽位');
}

async function checkModel() {
  const btn = $('#btn-model');
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ 检测中…';
  try {
    const model = await api('/api/model');
    if (cmp.info) cmp.info.model = model;
    renderInfo();
    toast(model.ok
      ? '模型 ' + model.model + ' 可用（' + (model.capabilities || []).join('/') + '）'
      : '模型不可用：' + (model.error || '未知错误'), !model.ok);
  } catch (err) {
    toast(err.message, true);
  }
  btn.textContent = label;
  btn.disabled = false;
}

function bind() {
  $('#btn-capture').onclick = () => captureTo(nextSlot());
  $('#btn-compare').onclick = runCompare;
  $('#btn-clear').onclick = clearAll;
  $('#btn-model').onclick = checkModel;
  document.querySelectorAll('.cmp-recap').forEach((button) => {
    button.onclick = () => captureTo(button.dataset.slot);
  });
  document.addEventListener('keydown', (event) => {
    const tag = (event.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'r') {
      event.preventDefault();
      if (!$('#btn-capture').disabled) captureTo(nextSlot());
      return;
    }
    if (event.key === 'Enter' && !$('#btn-compare').disabled) runCompare();
  });
}

async function init() {
  bind();
  renderSlot('a');
  renderSlot('b');
  await loadInfo();
}

init();
