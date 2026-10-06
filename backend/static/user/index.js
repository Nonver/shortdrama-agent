/* 首页：Agent 入口 + 知识中枢（可折叠三级树）+ 示例 + 我的快捷入口 */
const GENRES = ["逆袭", "甜宠", "悬疑", "战神", "搞笑", "古装", "穿越", "职场"];
const PLATFORMS = { hongguo: "红果短剧", douyin: "抖音短剧", kuaishou: "快手短剧" };

let agentsCache = [];
let kbSel = null;        // 当前选中的公开子库 key
let kbCache = [];

/* ---------- 头部用户态 ---------- */
function refreshHeader() {
  const authBtn = el("auth-btn"), chip = el("user-chip");
  if (state.user) {
    authBtn.classList.add("hidden");
    chip.classList.remove("hidden");
    chip.textContent = (state.user.nickname || state.user.username) + " · " + levelName(state.user.membership_level);
  } else {
    authBtn.classList.remove("hidden");
    chip.classList.add("hidden");
  }
}
window.onLogin = () => { refreshHeader(); };
window.onLogout = () => { refreshHeader(); };

function goMe() { if (!state.token) { location.href = "/login?next=" + encodeURIComponent("/me"); return; } location.href = "/me"; }
function goKnowledge() { switchTab("knowledge"); }

function switchTab(t) {
  if (t === "mine") { goMe(); return; }
  if (t === "knowledge" && !state.token) { openAuth(); return; }
  ["home", "knowledge"].forEach(v => { const e = el("view-" + v); if (e) e.classList.add("hidden"); });
  el("view-" + t).classList.remove("hidden");
  document.querySelectorAll(".nav div").forEach(d => d.classList.toggle("active", d.dataset.tab === t));
  if (t === "knowledge") loadKnowledge();
}

/* ---------- 加载 5 个 Agent 卡片 ---------- */
async function loadAgents() {
  try {
    const r = await api("/api/agents");
    if (r.ok) agentsCache = await r.json();
  } catch { agentsCache = []; }
  const grid = el("agent-grid");
  if (!agentsCache.length) { grid.innerHTML = `<div class="pill">智能体加载中…</div>`; return; }
  grid.innerHTML = "";
  agentsCache.forEach(a => {
    const card = document.createElement("div");
    card.className = "agent-card";
    card.innerHTML =
      `<div class="ac-avatar">${avatarHTML(a.avatar)}</div>
       <div class="ac-name">${a.name}</div>
       <div class="ac-persona">${a.persona_name || ""}</div>
       <div class="ac-desc">${a.description || ""}</div>
       <div class="ac-tools">${(a.tools || []).map(t => `<span class="tag">${toolLabel(t)}</span>`).join("")}</div>
       <div class="ac-enter">进入聊天 →</div>`;
    card.onclick = () => enterAgent(a.key);
    grid.appendChild(card);
  });
}
function toolLabel(t) {
  return { script_generate: "剧本", script_download: "导出", image_generate: "生图",
    video_generate: "生视频", tts: "配音" }[t] || t;
}
function enterAgent(key) {
  if (state.token) location.href = "/agent/" + key;
  else location.href = "/login?next=" + encodeURIComponent("/agent/" + key);
}

/* ---------- 资料库（对外公开：cases/monetize/compliance，绝不含内部机密） ---------- */
async function loadKnowledge() {
  const g = await (await api("/api/user/knowledge/public/groups")).json();
  el("kb-cards").innerHTML = (g.sublibs || []).map(s =>
    `<div class="kb-card" onclick="selectLib('${s.key}')">
       <div class="kb-card-ico">${s.icon}</div>
       <div class="kb-card-t">${s.name}</div>
       <div class="kb-card-s">${s.desc}</div>
     </div>`).join("");
  el("kb-list").innerHTML = "";
  kbSel = null;
  el("kb-crumb").textContent = "选择下方任意板块查看";
}
async function selectLib(key) {
  kbSel = key;
  const g = await (await api("/api/user/knowledge/public/groups")).json();
  const s = (g.sublibs || []).find(x => x.key === key) || {};
  el("kb-crumb").innerHTML = `当前板块：<b>资料库</b> › <b>${s.name || key}</b> <span class="link" onclick="clearKB()">× 返回</span>`;
  el("kb-cards").innerHTML = "";
  const r = await api("/api/user/knowledge/public/by-group?sublib=" + encodeURIComponent(key));
  const items = r.ok ? await r.json() : [];
  kbCache = items;
  if (!items.length) { el("kb-list").innerHTML = `<div class="pill center">该板块暂无内容</div>`; return; }
  el("kb-list").innerHTML = items.map(it =>
    `<div class="kb-item" onclick="showKB(${it.id})"><div class="kb-it-title">${escapeHtml(it.title)}</div>
     <div class="pill">${(it.tags || []).slice(0, 4).map(t => "#" + t).join(" ")}</div></div>`).join("");
}
function clearKB() { loadKnowledge(); }

function showKB(id) {
  const it = kbCache.find(x => x.id === id);
  if (!it) return;
  const m = it.meta || {};
  el("demo-sel").innerHTML = "";
  el("demo-body").textContent = it.content + (m.source ? "\n\n【来源】" + m.source : "");
  el("demo-modal").querySelector(".modal-head span").textContent = it.title;
  el("demo-modal").classList.remove("hidden");
}

/* ---------- 示例剧本（免登录） ---------- */
let demoData = [];
async function openDemo() {
  try { demoData = await (await fetch(API + "/api/scripts/demo")).json(); } catch { demoData = []; }
  const sel = el("demo-sel");
  if (!demoData.length) { sel.innerHTML = "<option>暂无示例</option>"; el("demo-body").textContent = "（示例生成中，请稍候重试）"; }
  else { sel.innerHTML = demoData.map((d, i) => `<option value="${i}">${d.title} ｜ ${PLATFORMS[d.platform] || d.platform} · ${d.genre}</option>`).join(""); renderDemo(); }
  el("demo-modal").querySelector(".modal-head span").textContent = "示例剧本（知识库驱动 · 带来源）";
  el("demo-modal").classList.remove("hidden");
}
function renderDemo() {
  const i = parseInt(el("demo-sel").value || "0", 10);
  const d = demoData[i];
  el("demo-body").textContent = d ? d.markdown : "";
}
function closeDemo() { el("demo-modal").classList.add("hidden"); }

/* ---------- 启动 ---------- */
window.onload = () => {
  refreshHeader();
  loadAgents();
  bootstrapUser().then(refreshHeader);
};
