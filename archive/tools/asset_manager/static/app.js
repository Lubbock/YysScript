/* YysScript 模板图片管理界面 —— 前端逻辑（原生 JS，无构建步骤） */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const S = {
  info: null,
  states: [],
  flows: [],
  filters: { q: "", kind: "", flow: "", missing: false, unused: false },
  current: null,        // 当前抽屉里打开的状态
  actualSize: false,    // 预览是否按原始像素显示
};

/* ------------------------------------------------------------------ 工具 */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function imgUrl(name) {
  return "/img/" + encodeURIComponent(name) + "?t=" + Date.now();
}

let toastTimer = null;
function toast(msg, kind = "") {
  const box = $("#toast");
  box.textContent = msg;
  box.className = "show " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = ""; }, kind === "err" ? 6000 : 3200);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch (_) { /* 非 JSON 响应 */ }
  if (!res.ok) {
    throw new Error((data && data.error) || ("HTTP " + res.status));
  }
  return data;
}

function humanBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(2) + " MB";
}

/* ------------------------------------------------------------------ 加载 */

async function loadAll() {
  const [info, states, flows] = await Promise.all([
    api("/api/info"), api("/api/states"), api("/api/flows"),
  ]);
  S.info = info; S.states = states; S.flows = flows;
  renderHeader();
  renderFlowFilter();
  renderGrid();
}

function renderHeader() {
  const c = S.info.counts, cap = S.info.capabilities;
  $("#hdr-sub").textContent = S.info.template_dir;
  $("#stats").innerHTML = [
    `状态 <b>${c.states}</b>`,
    `界面 <b>${c.screen}</b> / 标记 <b>${c.marker}</b>`,
    `磁盘模板 <b>${c.templates_on_disk}</b>`,
    c.missing.length
      ? `<span class="badge bad">缺失 ${c.missing.length}：${esc(c.missing.join("、"))}</span>`
      : `<span class="badge ok">模板齐全</span>`,
    c.orphans.length
      ? `<span class="badge warn">未被引用 ${c.orphans.length}</span>`
      : "",
    cap.capture
      ? `<span class="badge ok">截屏可用</span>`
      : `<span class="badge bad" title="${esc(cap.capture_error)}">截屏不可用</span>`,
    cap.match
      ? `<span class="badge ok">匹配可用</span>`
      : `<span class="badge warn" title="${esc(cap.match_error)}">probe 不可用</span>`,
    `<span class="path">基准客户区 ${S.info.base_client_size.join("×")} · 默认阈值 ${S.info.default_threshold}</span>`,
  ].join(" ");

  $("#btn-capture").disabled = !cap.capture;
  $("#btn-capture").title = cap.capture
    ? "截取当前屏幕，框选区域存成新模板"
    : "当前环境无法截屏：" + cap.capture_error;
}

function renderFlowFilter() {
  const sel = $("#f-flow");
  const keep = sel.value;
  sel.innerHTML = `<option value="">全部流程</option>` +
    S.flows.map(f => `<option value="${esc(f.name)}" title="${esc(f.description)}">` +
      `${esc(f.name)}${f.states.length ? ` (${f.states.length})` : " (无状态校验)"}</option>`).join("");
  sel.value = keep;
}

/* ------------------------------------------------------------------ 卡片网格 */

function passFilters(st) {
  const f = S.filters;
  if (f.kind && st.kind !== f.kind) return false;
  if (f.flow && !st.used_by.includes(f.flow)) return false;
  const missing = st.templates.some(t => !t.exists);
  if (f.missing && !missing) return false;
  if (f.unused && st.used_by.length) return false;
  if (f.q) {
    const hay = (st.key + " " + st.label + " " + st.description + " " +
                 st.templates.map(t => t.name).join(" ")).toLowerCase();
    if (!hay.includes(f.q.toLowerCase())) return false;
  }
  return true;
}

function renderGrid() {
  const list = S.states.filter(passFilters);
  const grid = $("#grid");
  if (!list.length) {
    grid.innerHTML = `<div class="empty" style="grid-column:1/-1">没有匹配的状态</div>`;
  } else {
    grid.innerHTML = list.map(cardHtml).join("");
  }
  $$(".card", grid).forEach(el =>
    el.addEventListener("click", () => openDrawer(el.dataset.key)));
  renderOrphans();
}

function cardHtml(st) {
  const t = st.templates[0] || { exists: false };
  const missing = st.templates.some(x => !x.exists);
  const thumb = t.exists
    ? `<img src="${imgUrl(t.name)}" alt="${esc(t.name)}" loading="lazy">`
    : `<span class="placeholder">✗ 文件缺失</span>`;
  const size = t.exists ? `${t.width}×${t.height}` : "—";
  return `
  <div class="card ${missing ? "missing" : ""}" data-key="${esc(st.key)}" title="${esc(st.description)}">
    <div class="thumb">${thumb}</div>
    <div class="card-body">
      <div class="card-key">${esc(st.key)}</div>
      <div class="card-label">${esc(st.label)} · ${size}</div>
      <div class="card-meta">
        <span class="tag kind-${esc(st.kind)}">${st.kind === "screen" ? "界面" : "标记"}</span>
        <span class="tag">阈值 ${st.threshold}</span>
        ${st.used_by.map(f => `<span class="tag flow">${esc(f)}</span>`).join("")}
        ${st.used_by.length ? "" : `<span class="tag">未引用</span>`}
      </div>
    </div>
  </div>`;
}

function renderOrphans() {
  const box = $("#orphans");
  const orphans = S.info.counts.orphans;
  if (!orphans.length) { box.innerHTML = ""; return; }
  box.innerHTML = `
    <div class="section-title">磁盘上存在、但没有任何状态引用的图片（${orphans.length}）
      <span class="note">— 可能是遗留的调试截图，确认无用后可手动删除</span></div>
    <div class="grid">${orphans.map(n => `
      <div class="card" data-orphan="${esc(n)}">
        <div class="thumb"><img src="${imgUrl(n)}" alt="${esc(n)}" loading="lazy"></div>
        <div class="card-body">
          <div class="card-key">${esc(n)}</div>
          <div class="card-label">未绑定任何状态</div>
        </div>
      </div>`).join("")}
    </div>`;
}

/* ------------------------------------------------------------------ 详情抽屉 */

function openDrawer(key) {
  const st = S.states.find(s => s.key === key);
  if (!st) return;
  S.current = st;
  const cap = S.info.capabilities;

  $("#drawer-root").innerHTML = `
  <div class="drawer-mask" id="d-mask"></div>
  <div class="drawer" role="dialog" aria-label="状态详情">
    <button class="close-x" id="d-close" title="关闭 (Esc)">×</button>
    <h2>${esc(st.key)}</h2>
    <div class="sub">${esc(st.label)} · ${st.kind === "screen" ? "界面状态 SCREEN" : "定位标记 MARKER"}</div>

    <dl class="kv">
      <dt>模板文件</dt><dd>${st.templates.map(t => esc(t.name)).join("、")}</dd>
      <dt>匹配阈值</dt><dd>${st.threshold}</dd>
      <dt>被引用</dt><dd>${st.used_by.length ? st.used_by.map(esc).join("、") : "<span style='color:var(--warn)'>没有任何流程引用</span>"}</dd>
      <dt>说明</dt><dd>${esc(st.description) || "—"}</dd>
    </dl>

    <h3>当前图片</h3>
    <div class="preview-box" id="d-preview"></div>
    <div class="note" id="d-meta"></div>
    <label class="check" style="margin-top:6px">
      <input type="checkbox" id="d-actual"> 按原始像素显示（默认缩放适应宽度）
    </label>

    <h3>替换图片</h3>
    <div class="dropzone" id="d-drop">
      把 PNG 拖到这里，或点击选择文件<br>
      <span style="font-size:11px">替换前会自动备份，可在下方回滚</span>
    </div>
    <input type="file" id="d-file" accept="image/png,.png" hidden>
    <div class="note" id="d-upload-result"></div>
    <div style="margin-top:8px">
      <button id="d-crop" ${cap.capture ? "" : "disabled"}>✂️ 改为从屏幕截图裁剪</button>
      ${cap.capture ? "" : `<span class="note err">${esc(cap.capture_error)}</span>`}
    </div>

    <h3>识别测试 (probe)</h3>
    <div class="cropbar">
      <label class="check">阈值 <input type="number" id="d-thr" step="0.01" min="0" max="1"
        value="${st.threshold}" style="width:70px"></label>
      <select id="d-region">
        <option value="full">整个屏幕</option>
        <option value="window" selected>仅游戏窗口</option>
      </select>
      <button id="d-probe" class="primary" ${cap.match ? "" : "disabled"}>▶ 立即匹配</button>
    </div>
    <div class="note" id="d-probe-hint">${cap.match
      ? "把游戏切到目标界面后点「立即匹配」：能看到分数、命中框和标注图。分数远低于阈值说明模板该换了。"
      : "probe 需要 cv2 + pyautogui：" + esc(cap.match_error)}</div>
    <div id="d-probe-out" class="probe-result"></div>

    <h3>历史备份</h3>
    <div id="d-backups"><span class="note">加载中…</span></div>
  </div>`;

  $("#d-mask").onclick = closeDrawer;
  $("#d-close").onclick = closeDrawer;
  $("#d-actual").onchange = e => { S.actualSize = e.target.checked; renderPreview(); };

  const drop = $("#d-drop"), fileInput = $("#d-file");
  drop.onclick = () => fileInput.click();
  fileInput.onchange = () => fileInput.files[0] && uploadTemplate(fileInput.files[0]);
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.add("over");
  }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.remove("over");
  }));
  drop.addEventListener("drop", e => {
    const f = e.dataTransfer.files[0];
    if (f) uploadTemplate(f);
  });

  $("#d-crop").onclick = () => openCrop({ presetTarget: st.templates[0].name });
  $("#d-probe").onclick = runProbe;

  renderPreview();
  loadBackups();
}

function closeDrawer() {
  $("#drawer-root").innerHTML = "";
  S.current = null;
}

function renderPreview() {
  const st = S.current;
  if (!st) return;
  const t = st.templates[0];
  const box = $("#d-preview"), meta = $("#d-meta");
  if (!t.exists) {
    box.innerHTML = `<span class="placeholder" style="color:var(--bad)">文件不存在：${esc(t.name)}</span>`;
    meta.innerHTML = `<span class="note err">模板缺失，该状态永远匹配不上。请用下方「替换图片」或「截屏裁剪」补上。</span>`;
    return;
  }
  box.innerHTML = `<img class="${S.actualSize ? "actual" : ""}" src="${imgUrl(t.name)}" alt="${esc(t.name)}">`;
  const bits = [`${t.width}×${t.height}`, humanBytes(t.bytes)];
  if (t.mode && t.mode !== "RGB") bits.push(t.mode);
  bits.push("修改于 " + t.mtime);
  if (!t.valid) bits.push("⚠ 无法解析：" + t.error);
  meta.innerHTML = esc(bits.join(" · "));
}

async function uploadTemplate(file) {
  const st = S.current;
  if (!st) return;
  if (!/\.png$/i.test(file.name)) {
    toast("只接受 .png 文件（收到 " + file.name + "）", "err");
    return;
  }
  const target = st.templates[0].name;
  const out = $("#d-upload-result");
  out.innerHTML = `<span class="note">上传中…</span>`;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await api("/api/template/" + encodeURIComponent(target), { method: "POST", body: fd });
    out.innerHTML = r.warning
      ? `<span class="note warn">⚠ ${esc(r.warning)}</span>`
      : `<span class="note ok">✓ 已替换 ${esc(target)}（${r.new.width}×${r.new.height}，${humanBytes(r.new.bytes)}）${r.backup ? "，旧图已备份到 " + esc(r.backup) : ""}</span>`;
    toast(r.warning ? "已替换，但尺寸变化较大，请检查" : "模板已替换", r.warning ? "warn" : "ok");
    await loadAll();
    renderPreview();
    loadBackups();
  } catch (e) {
    out.innerHTML = `<span class="note err">✗ ${esc(e.message)}</span>`;
    toast("替换失败：" + e.message, "err");
  }
}

async function loadBackups() {
  const st = S.current;
  if (!st) return;
  const box = $("#d-backups");
  const target = st.templates[0].name;
  try {
    const list = await api("/api/template/" + encodeURIComponent(target) + "/backups");
    if (!list.length) {
      box.innerHTML = `<span class="note">暂无备份。每次替换 / 裁剪都会自动生成一份。</span>`;
      return;
    }
    box.innerHTML = `<ul class="backup-list">${list.map(b => `
      <li>
        <img src="/backup-img/${encodeURIComponent(b.stamp)}/${encodeURIComponent(target)}" alt="${esc(b.stamp)}">
        <span class="stamp">${esc(b.stamp)}</span>
        <span class="note">${b.exists ? `${b.width}×${b.height} · ${humanBytes(b.bytes)}` : "—"}</span>
        <span class="spacer"></span>
        <button data-rollback="${esc(b.stamp)}">回滚到此版本</button>
      </li>`).join("")}</ul>
      <div class="note">备份存放在 <code>${esc(S.info.backup_dir)}</code>（不入版本库，git 里另有完整历史）。
      上面缩略图就是该备份的真实内容，点「回滚」会把它恢复成当前模板。</div>`;
    $$("[data-rollback]", box).forEach(btn => btn.onclick = () => rollback(target, btn.dataset.rollback, btn));
  } catch (e) {
    box.innerHTML = `<span class="note err">读取备份失败：${esc(e.message)}</span>`;
  }
}

async function rollback(name, stamp, btn) {
  if (!confirm("把 " + name + " 回滚到备份 " + stamp + "？\n（当前版本也会先备份一份，可再次回滚）")) return;
  btn.disabled = true;
  try {
    await api("/api/template/" + encodeURIComponent(name) + "/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stamp }),
    });
    toast("已回滚到 " + stamp, "ok");
    await loadAll();
    renderPreview();
    loadBackups();
  } catch (e) {
    toast("回滚失败：" + e.message, "err");
    btn.disabled = false;
  }
}

async function runProbe() {
  const st = S.current;
  if (!st) return;
  const out = $("#d-probe-out");
  const btn = $("#d-probe");
  btn.disabled = true;
  out.innerHTML = `<span class="note">正在截屏并匹配…</span>`;
  try {
    const r = await api("/api/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: st.templates[0].name,
        threshold: parseFloat($("#d-thr").value) || S.info.default_threshold,
        region: $("#d-region").value,
      }),
    });
    if (r.note) {
      out.innerHTML = `<span class="note warn">${esc(r.note)}</span>`;
      return;
    }
    const hit = r.total_matches > 0;
    out.innerHTML = `
      <div class="probe-score ${hit ? "hit" : "miss"}">${r.best_score.toFixed(4)}</div>
      <div class="note">
        阈值 ${r.threshold} · 命中 <b>${r.total_matches}</b> 处
        ${hit ? `· 最高分位置 (${r.matched[0].x}, ${r.matched[0].y})` : `· 最像的位置 (${r.best_location.join(", ")}`}
      </div>
      ${hit
        ? `<div class="note ok">✓ 能认出来。前 3 个命中：${r.matched.slice(0, 3).map(m => m.score.toFixed(3)).join(" / ")}</div>`
        : `<div class="note err">✗ 没达到阈值。蓝框是它认为最像的位置 —— 如果那里确实是目标，说明模板该重截了；
             如果分数只差一点（&gt;0.6），可以试着把阈值调低。</div>`}
      ${r.annotated_url ? `<img class="probe-img" src="${r.annotated_url}?t=${Date.now()}" alt="标注图">` : ""}`;
  } catch (e) {
    out.innerHTML = `<span class="note err">✗ ${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ 裁剪工作区 */

const CROP = { url: null, name: null, natW: 0, natH: 0, scale: 1, sel: null, dragging: false, start: null };

async function openCrop(opts = {}) {
  if (!S.info.capabilities.capture) {
    toast("当前环境无法截屏：" + S.info.capabilities.capture_error, "err");
    return;
  }
  toast("正在截屏，请把游戏窗口保持在目标界面…");
  let cap;
  try {
    cap = await api("/api/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region: opts.region || "full" }),
    });
  } catch (e) {
    toast("截屏失败：" + e.message, "err");
    return;
  }

  CROP.url = cap.url; CROP.name = cap.name;
  CROP.natW = cap.width; CROP.natH = cap.height; CROP.sel = null;

  const options = S.states.flatMap(st =>
    st.templates.map(t => ({ key: st.key, label: st.label, name: t.name })));

  $("#crop-root").innerHTML = `
  <div class="drawer-mask" id="c-mask"></div>
  <div class="drawer" style="width:min(1100px,98vw)" role="dialog" aria-label="裁剪模板">
    <button class="close-x" id="c-close" title="关闭 (Esc)">×</button>
    <h2>从截图裁剪新模板</h2>
    <div class="sub">${esc(cap.name)} · 原图 ${cap.width}×${cap.height}${cap.region ? " · 游戏窗口区域 " + cap.region.join(", ") : " · 全屏"}</div>

    <div class="cropbar">
      <label class="check">存为
        <select id="c-target" style="min-width:280px">
          ${options.map(o => `<option value="${esc(o.name)}" ${o.name === opts.presetTarget ? "selected" : ""}>
            ${esc(o.key)} — ${esc(o.label)} (${esc(o.name)})</option>`).join("")}
        </select>
      </label>
      <span class="spacer"></span>
      <label class="check"><input type="checkbox" id="c-zoom"> 放大 2×（小图更好框选）</label>
      <button id="c-recapture">📷 重新截屏</button>
      <button id="c-save" class="primary" disabled>💾 保存为模板</button>
    </div>

    <div class="note" style="margin-bottom:8px">
      在图上<b>按住鼠标拖拽</b>框选要作为模板的区域。选区就是 matchTemplate 的搜索图案 ——
      框得越紧凑（只含不变的特征、不含会动的背景）识别越稳。
    </div>

    <div class="cropwrap" id="c-wrap">
      <div id="c-inner" style="position:relative;display:inline-block">
        <img id="c-img" src="${cap.url}?t=${Date.now()}" alt="截图" draggable="false">
        <div class="sel" id="c-sel" style="display:none"><span class="sel-label" id="c-sel-label"></span></div>
      </div>
    </div>
    <div class="note" id="c-info">尚未选择区域</div>
  </div>`;

  $("#c-mask").onclick = closeCrop;
  $("#c-close").onclick = closeCrop;
  $("#c-recapture").onclick = () => { closeCrop(); openCrop(opts); };
  $("#c-save").onclick = saveCrop;
  $("#c-zoom").onchange = e => { applyZoom(e.target.checked); };

  const img = $("#c-img");
  img.onload = () => { applyZoom($("#c-zoom").checked); bindSelection(); };
}

function applyZoom(zoom) {
  const img = $("#c-img");
  if (!img.naturalWidth) return;
  const base = Math.min(1, ($("#c-wrap").clientWidth - 24) / img.naturalWidth);
  CROP.scale = zoom ? base * 2 : base;
  img.style.width = (img.naturalWidth * CROP.scale) + "px";
  img.style.height = (img.naturalHeight * CROP.scale) + "px";
  redrawSel();
}

function bindSelection() {
  const inner = $("#c-inner");
  inner.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    const r = $("#c-img").getBoundingClientRect();
    CROP.dragging = true;
    CROP.start = { x: e.clientX - r.left, y: e.clientY - r.top, rect: r };
    CROP.sel = { x0: CROP.start.x, y0: CROP.start.y, x1: CROP.start.x, y1: CROP.start.y };
    redrawSel();
  });
  window.addEventListener("mousemove", e => {
    if (!CROP.dragging) return;
    const r = CROP.start.rect;
    CROP.sel.x1 = clamp(e.clientX - r.left, 0, r.width);
    CROP.sel.y1 = clamp(e.clientY - r.top, 0, r.height);
    redrawSel();
  });
  window.addEventListener("mouseup", () => {
    if (!CROP.dragging) return;
    CROP.dragging = false;
    const s = normSel();
    if (!s || s.w < 4 || s.h < 4) {
      CROP.sel = null; redrawSel();
      $("#c-info").textContent = "选区太小（至少 4×4 像素），请重新框选";
      return;
    }
    $("#c-save").disabled = false;
    $("#c-info").innerHTML =
      `已选 <b>${s.w}×${s.h}</b> 像素，位于原图 (${s.x}, ${s.y})。` +
      `<span class="note">提示：模板越小匹配越快，但要包含足够的独特特征。</span>`;
  });
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function normSel() {
  if (!CROP.sel) return null;
  const s = CROP.sel, k = CROP.scale || 1;
  const x = Math.round(Math.min(s.x0, s.x1) / k), y = Math.round(Math.min(s.y0, s.y1) / k);
  const w = Math.round(Math.abs(s.x1 - s.x0) / k), h = Math.round(Math.abs(s.y1 - s.y0) / k);
  return { x, y, w, h };
}

function redrawSel() {
  const el = $("#c-sel"), label = $("#c-sel-label");
  if (!el) return;
  if (!CROP.sel) { el.style.display = "none"; return; }
  const s = CROP.sel;
  el.style.display = "block";
  el.style.left = Math.min(s.x0, s.x1) + "px";
  el.style.top = Math.min(s.y0, s.y1) + "px";
  el.style.width = Math.abs(s.x1 - s.x0) + "px";
  el.style.height = Math.abs(s.y1 - s.y0) + "px";
  const n = normSel();
  if (label && n) label.textContent = `${n.w} × ${n.h}`;
}

async function saveCrop() {
  const s = normSel();
  const target = $("#c-target").value;
  if (!s || !target) return;
  const existing = S.states.flatMap(st => st.templates.map(t => t.name)).includes(target);
  if (existing && !confirm(`将覆盖 ${target}\n（旧图会自动备份，可在状态详情里回滚）\n\n继续？`)) return;
  try {
    const r = await api("/api/crop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "capture", name: CROP.name, target, ...s }),
    });
    toast(`已保存 ${target}（${r.size[0]}×${r.size[1]}）${r.backup ? "，旧图已备份" : ""}`, "ok");
    closeCrop();
    await loadAll();
    const st = S.states.find(x => x.templates.some(t => t.name === target));
    if (st) openDrawer(st.key);
  } catch (e) {
    toast("保存失败：" + e.message, "err");
  }
}

function closeCrop() {
  $("#crop-root").innerHTML = "";
  CROP.url = CROP.name = CROP.sel = null;
}

/* ------------------------------------------------------------------ 事件绑定 */

function bindToolbar() {
  const debounced = debounce(() => { S.filters.q = $("#q").value.trim(); renderGrid(); }, 160);
  $("#q").addEventListener("input", debounced);
  $("#f-kind").onchange = e => { S.filters.kind = e.target.value; renderGrid(); };
  $("#f-flow").onchange = e => { S.filters.flow = e.target.value; renderGrid(); };
  $("#f-missing").onchange = e => { S.filters.missing = e.target.checked; renderGrid(); };
  $("#f-unused").onchange = e => { S.filters.unused = e.target.checked; renderGrid(); };
  $("#btn-reload").onclick = async () => { await loadAll(); toast("已刷新", "ok"); };
  $("#btn-capture").onclick = () => openCrop({ region: "full" });

  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    if ($("#crop-root").innerHTML) closeCrop();
    else if ($("#drawer-root").innerHTML) closeDrawer();
  });
}

function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ------------------------------------------------------------------ 启动 */

(async function init() {
  bindToolbar();
  try {
    await loadAll();
  } catch (e) {
    $("#grid").innerHTML = `<div class="empty" style="grid-column:1/-1">加载失败：${esc(e.message)}</div>`;
  }
})();
