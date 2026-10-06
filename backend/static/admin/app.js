/* 后台：数据驾驶舱 / 用户分群 / 剧本库 / 知识中枢（三级树）/ Agent 矩阵 / 模型中心 / 会员与权益 */
const API = "";
const A = { token: localStorage.getItem("atoken") };
const ICON_PLAY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>';
const ICON_FILE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>';
const TITLES = { dashboard: "数据驾驶舱", users: "用户分群", scripts: "剧本库", knowledge: "知识中枢", agents: "Agent 矩阵", models: "模型中心", membership: "会员与权益" };

function el(id) { return document.getElementById(id); }
function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  if (A.token) opts.headers["Authorization"] = "Bearer " + A.token;
  return fetch(API + path, opts);
}
function setErr(id, m) { const e = el(id); if (e) e.textContent = m || ""; }
async function loadAdminCaptcha() { const r = await (await fetch(API + "/api/auth/captcha")).json(); const i = el("a-captcha-img"); i.src = r.image; i.dataset.id = r.captcha_id; }

async function adminLogin() {
  setErr("a-err", "");
  const body = { account: el("a-account").value, password: el("a-pass").value,
    captcha_id: el("a-captcha-img").dataset.id, captcha_code: el("a-code").value };
  const r = await api("/api/auth/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) return setErr("a-err", j.detail || "登录失败");
  A.token = j.access_token; localStorage.setItem("atoken", A.token);
  el("login").classList.add("hidden"); el("dash").classList.remove("hidden"); switchTab("dashboard");
}
function adminLogout() { A.token = null; localStorage.removeItem("atoken"); location.reload(); }

function switchTab(t) {
  el("title").textContent = TITLES[t] || t;
  document.querySelectorAll(".side .item").forEach(d => d.classList.toggle("active", d.dataset.tab === t));
  document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
  el("view-" + t).classList.remove("hidden");
  ({ dashboard: loadDashboard, users: loadUsers, scripts: loadScripts, knowledge: loadKnowledge, agents: loadAgents, models: loadModels, membership: loadMembership })[t]();
}

/* ---------- 数据驾驶舱 ---------- */
let chartDays = 14;
async function loadDashboard(days) {
  if (days) chartDays = days;
  const r = await api("/api/admin/dashboard"); if (!r.ok) return;
  const d = await r.json();
  el("stats").innerHTML = [
    ["用户", d.users], ["活跃今日", d.active_users_today], ["免费", d.free_users], ["会员", d.member_users], ["会员Pro", d.pro_users],
    ["剧本", d.scripts], ["今日剧本", d.scripts_today], ["知识中枢", d.knowledge], ["Agent", d.agents],
    ["会话", d.sessions], ["资产", d.assets], ["启用模型", d.models],
  ].map(([l, n]) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");
  // 高亮时间范围按钮
  [7, 14, 30, 90].forEach(n => {
    const b = el("dr-" + n); if (b) b.classList.toggle("active", n === chartDays);
  });
  el("dr-hint").textContent = `（按近 ${chartDays} 天统计剧本趋势、Agent 使用量等指标）`;
  const cr = await api("/api/admin/charts?days=" + chartDays);
  if (cr.ok) { const c = await cr.json(); renderCharts(c); renderAudit(c.recent_audit); }
}
function setChartDays(days) { chartDays = days; loadDashboard(days); }

/* ---------- 图表（纯 SVG，无外部依赖） ---------- */
const PALETTE = ["#4f46e5", "#8b5cf6", "#14b8a6", "#ea580c", "#ec4899", "#16a34a"];
const MEMBER_COLORS = { free: "#9ca3af", member: "#4f46e5", pro: "#8b5cf6" };
const SUBLIB_NAMES = { platform: "平台规则库", genre: "类型套路库", style: "风格样本库", asset: "剧本资产库" };
const GROUP_NAMES = { ark_chat: "方舟对话", ark_image: "方舟生图", ark_video: "方舟生视频", tts: "豆包语音", embedding: "Embedding", fallback: "本地兜底" };
const KNOWN_TOOLS = [
  { k: "script_generate", n: "剧本生成" }, { k: "script_download", n: "剧本下载" },
  { k: "image_generate", n: "文生图" }, { k: "image_quality_4k", n: "4K生图" },
  { k: "video_generate", n: "文生视频" }, { k: "tts", n: "配音" },
];

function svgDonut(items, opts = {}) {
  const size = opts.size || 170, cx = size / 2, cy = size / 2, r = size / 2 - 18;
  const C = 2 * Math.PI * r, total = items.reduce((s, i) => s + (i.value || 0), 0);
  let acc = 0, arcs = "";
  if (total === 0) arcs = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#e6e8eb" stroke-width="16"/>`;
  else items.forEach(it => {
    const len = (it.value || 0) / total * C;
    arcs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${it.color}" stroke-width="16" stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}" stroke-dashoffset="${(-acc).toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"/>`;
    acc += len;
  });
  const center = opts.centerLabel !== undefined ? `<text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="22" font-weight="700" fill="#1f2329">${opts.centerLabel}</text><text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="11" fill="#8a9099">${opts.centerSub || ""}</text>` : "";
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">${arcs}${center}</svg>`;
}
function donutCard(title, items, opts = {}) {
  const legend = items.map(it => `<span class="lg"><i style="background:${it.color}"></i>${it.label}<b>${it.value}</b></span>`).join("");
  return `<div class="card chart-card"><h4>${title}</h4><div class="chart-donut">${svgDonut(items, opts)}</div><div class="legend">${legend}</div></div>`;
}
function svgLine(series) {
  const W = 520, H = 170, pad = 28, n = series.length;
  const max = Math.max(1, ...series.map(s => s.count));
  const x = i => pad + i * ((W - 2 * pad) / (n - 1 || 1));
  const y = v => H - pad - v / max * (H - 2 * pad);
  const pts = series.map((s, i) => `${x(i).toFixed(1)},${y(s.count).toFixed(1)}`).join(" ");
  const area = `${pad},${H - pad} ${pts} ${W - pad},${H - pad}`;
  const dots = series.map((s, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(s.count).toFixed(1)}" r="3" fill="#4f46e5"/>`).join("");
  const last = series[n - 1];
  const lastLabel = last ? `<text x="${x(n - 1).toFixed(1)}" y="${(y(last.count) - 8).toFixed(1)}" text-anchor="end" font-size="11" fill="#4f46e5" font-weight="700">${last.count}</text>` : "";
  const labels = series.map((s, i) => (i % 3 === 0 || i === n - 1) ? `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="9" fill="#8a9099">${s.date.slice(5)}</text>` : "").join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="none" style="display:block"><line x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}" stroke="#e6e8eb"/>` +
    `<polygon points="${area}" fill="rgba(79,70,229,.10)"/><polyline points="${pts}" fill="none" stroke="#4f46e5" stroke-width="2"/>${dots}${lastLabel}${labels}</svg>`;
}
function lineCard(title, series) {
  const total = series.reduce((s, x) => s + x.count, 0);
  const step = series.length > 20 ? 5 : (series.length > 10 ? 3 : 1);
  const labels = series.map((s, i) => (i % step === 0 || i === series.length - 1) ? s.date.slice(5) : "").join(" / ");
  return `<div class="card chart-card span2"><h4>${title} <span class="muted">· 共 ${total} 部</span></h4>${svgLine(series)}<div class="muted" style="margin-top:6px;font-size:10px">${labels}</div></div>`;
}
function barsCard(title, items) {
  const max = Math.max(1, ...items.map(i => i.value));
  const rows = items.map(it => `<div class="bar-row"><span class="bar-label">${it.label}</span><span class="bar-track"><span class="bar-fill" style="width:${it.value / max * 100}%;background:${it.color || "#4f46e5"}"></span></span><b class="bar-val">${it.value}</b></div>`).join("");
  return `<div class="card chart-card"><h4>${title}</h4>${rows}</div>`;
}
function renderCharts(c) {
  const agentItems = c.agent_usage.map((a, i) => ({ label: a.name, value: a.scripts, color: PALETTE[i % PALETTE.length] }));
  const memberItems = c.member_dist.map(m => ({ label: { free: "免费", member: "会员", pro: "会员Pro" }[m.level] || m.level, value: m.count, color: MEMBER_COLORS[m.level] || "#9aa0a6" }));
  const kbItems = c.knowledge_by_sublib.map(k => ({ label: SUBLIB_NAMES[k.sublib] || k.sublib, value: k.count, color: "#14b8a6" }));
  const modelItems = c.model_status.map(m => ({ label: GROUP_NAMES[m.group] || m.group, value: m.enabled, color: m.enabled ? "#2ecc71" : "#ff9800" }));
  const totalScripts = c.agent_usage.reduce((s, a) => s + a.scripts, 0);
  el("charts").innerHTML = [
    donutCard("Agent 使用情况（剧本数）", agentItems, { centerLabel: totalScripts, centerSub: "剧本总数" }),
    donutCard("会员分布", memberItems),
    lineCard(c.days ? `近 ${c.days} 天剧本生成趋势` : "近 14 天剧本生成趋势", c.scripts_trend),
    barsCard("知识中枢各子库条目", kbItems),
    barsCard("模型启用状态（绿=启用 / 橙=停用）", modelItems),
  ].join("");
}
function renderAudit(list) {
  if (!list || !list.length) { el("audit-feed").innerHTML = `<div class="pill">暂无操作记录</div>`; return; }
  const map = { create_agent: "新增Agent", update_agent: "编辑Agent", delete_agent: "删除Agent", clone_agent: "克隆Agent", update_user: "编辑用户", set_level: "设会员等级", update_membership: "改会员配置", update_model: "改模型配置" };
  el("audit-feed").innerHTML = list.map(a => `<div class="audit-row"><span class="tag">${map[a.action] || a.action}</span><span class="pill">${a.target || ""}</span><span class="muted">${a.created_at ? a.created_at.slice(0, 19).replace("T", " ") : ""}</span></div>`).join("");
}

/* ---------- 用户 ---------- */
function openAddUser() {
  ["au-username", "au-password", "au-phone", "au-nick"].forEach(id => el(id).value = "");
  el("au-type").value = "user"; el("au-level").value = "free"; el("au-status").value = "active";
  el("au-err").textContent = ""; el("modal-add-user").classList.remove("hidden");
}
async function addUser() {
  setErr("au-err", "");
  const username = el("au-username").value.trim();
  const password = el("au-password").value;
  if (!username) return setErr("au-err", "用户名必填");
  if (!password || password.length < 6) return setErr("au-err", "密码至少6位");
  const body = {
    username, password,
    phone: el("au-phone").value.trim() || null,
    nickname: el("au-nick").value.trim() || null,
    account_type: el("au-type").value,
    membership_level: el("au-level").value,
    status: el("au-status").value,
  };
  const r = await api("/api/admin/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) return setErr("au-err", (await r.json()).detail || "创建失败");
  el("modal-add-user").classList.add("hidden"); loadUsers(); loadMembership();
}
async function loadUsers() {
  const r = await api("/api/admin/users"); if (!r.ok) return;
  const list = await r.json();
  el("users-tbody").innerHTML = list.map(u => `<tr>
    <td>${u.id}</td><td>${u.username}</td><td>${u.nickname || ""}</td><td>${u.phone || ""}</td>
    <td>${u.account_type}</td><td>${(u.membership_level || "free")}</td><td>${u.status}</td>
    <td>${(u.tags || []).map(t => `<span class="tag">${t}</span>`).join("")}</td>
    <td><select id="lv-${u.id}" class="input" style="max-width:110px"><option value="free">免费</option><option value="member">会员</option><option value="pro">会员Pro</option></select>
        <button class="btn ghost" onclick="setLevel(${u.id})">设等级</button>
        <button class="btn ghost" onclick="editUser(${u.id})">编辑画像</button></td></tr>`).join("");
  list.forEach(u => { const s = el("lv-" + u.id); if (s) s.value = u.membership_level || "free"; });
}
async function setLevel(id) {
  const sel = el("mlv-" + id) || el("lv-" + id);
  const lv = sel.value;
  const r = await api("/api/admin/users/" + id + "/level", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ membership_level: lv }) });
  if (!r.ok) return alert((await r.json()).detail || "失败");
  loadUsers(); loadMembership();
}
async function editUser(id) {
  const r = await api("/api/admin/users/" + id); const u = await r.json();
  el("eu-id").value = id; el("eu-nick").value = u.nickname || ""; el("eu-avatar").value = u.avatar || "";
  el("eu-status").value = u.status; el("eu-level").value = u.membership_level || "free"; el("eu-tags").value = (u.tags || []).join("、");
  el("eu-habits").value = JSON.stringify(u.habits || {}, null, 2);
  el("eu-err").textContent = ""; el("modal-user").classList.remove("hidden");
}
async function saveUser() {
  setErr("eu-err", "");
  const id = el("eu-id").value;
  let habits = {}; try { habits = JSON.parse(el("eu-habits").value || "{}"); } catch (e) { return setErr("eu-err", "habits 必须是 JSON"); }
  const body = { nickname: el("eu-nick").value, avatar: el("eu-avatar").value, status: el("eu-status").value,
    membership_level: el("eu-level").value,
    tags: el("eu-tags").value.split("、").map(s => s.trim()).filter(Boolean), habits };
  const r = await api("/api/admin/users/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) return setErr("eu-err", (await r.json()).detail || "失败");
  el("modal-user").classList.add("hidden"); loadUsers();
}

/* ---------- 剧本资产（创建人 + Agent 筛选） ---------- */
async function loadScripts() {
  const p = el("s-platform").value, ag = el("s-agent").value, cr = el("s-creator").value.trim();
  let url = "/api/admin/scripts?";
  if (p) url += "platform=" + encodeURIComponent(p) + "&";
  if (ag) url += "agent_key=" + encodeURIComponent(ag) + "&";
  if (cr) url += "creator=" + encodeURIComponent(cr) + "&";
  const r = await api(url); if (!r.ok) return;
  const list = await r.json();
  const AG = { director: "总导演", writer: "编剧", cameraman: "分镜导演", narration: "旁白心理", reviewer: "审核" };
  el("scripts-tbody").innerHTML = list.map(s => `<tr>
    <td>${s.id}</td><td>${s.title}</td><td>${s.platform}</td><td>${s.genre}</td>
    <td>${AG[s.agent_key] || s.agent_key}</td><td>${s.creator_username || "-"}</td>
    <td>${s.episode_count}</td><td>${s.status}${s.is_demo ? "·demo" : ""}</td>
    <td><button class="btn ghost" onclick="viewScript(${s.id})">查看</button>
        <a class="dl" href="/api/admin/scripts/${s.id}/download?fmt=pdf" target="_blank">PDF</a>
        <a class="dl" href="/api/admin/scripts/${s.id}/download?fmt=docx" target="_blank">DOCX</a>
        <a class="dl" href="/api/admin/scripts/${s.id}/download?fmt=xlsx" target="_blank">XLSX</a></td></tr>`).join("");
}
async function viewScript(id) {
  const r = await api("/api/admin/scripts/" + id + "/content"); const j = await r.json();
  el("vs-content").textContent = j.markdown || JSON.stringify(j.content, null, 2);
  el("modal-script").classList.remove("hidden");
}

/* ---------- 知识库（侧边栏三级树：知识库▸平台▸子库） ---------- */
let kbSel = null; // {platform, sublib}
function toggleKbTree() {
  const open = el("nav-kb").classList.toggle("open");
  el("kb-chev").textContent = open ? "▾" : "▸";
  if (open && !el("kb-platforms").childElementCount) loadKnowledgeTree();
}
async function loadKnowledgeTree() {
  const g = await (await api("/api/knowledge/groups")).json();
  el("kb-platforms").innerHTML = g.platforms.map(p => `
    <div class="nav-l2">
      <div class="nav-l2-head" data-p="${p.key}" onclick="toggleKbPlatform('${p.key}')">
        <span class="l2-left"><span class="ico">${ICON_PLAY}</span>${p.name}</span><span class="chev" id="chev-${p.key}">▸</span>
      </div>
      <div class="nav-l3 hidden" id="kb-subs-${p.key}">
        ${g.sublibs.map(s => `<div class="nav-l3-item" data-p="${p.key}" data-s="${s.key}" onclick="selectKbLeaf('${p.key}','${s.key}')"><span class="ico">${ICON_FILE}</span>${s.name}</div>`).join("")}
      </div>
    </div>`).join("");
}
function toggleKbPlatform(p) {
  const box = el("kb-subs-" + p);
  const hidden = box.classList.toggle("hidden");
  el("chev-" + p).textContent = hidden ? "▸" : "▾";
}
function selectKbLeaf(p, s) {
  kbSel = { platform: p, sublib: s };
  document.querySelectorAll(".nav-l3-item").forEach(d => d.classList.toggle("active", d.dataset.p === p && d.dataset.s === s));
  el("nav-kb").classList.add("open"); el("kb-chev").textContent = "▾";
  el("kb-subs-" + p).classList.remove("hidden"); el("chev-" + p).textContent = "▾";
  switchTab("knowledge");
}
async function loadKnowledge() {
  if (!kbSel) {
    el("kb-crumb").textContent = "请从左侧「知识库 › 平台 › 子库」选择要查看的内容";
    el("kb-tbody").innerHTML = `<tr><td colspan="6" class="pill">尚未选择分类</td></tr>`;
    return;
  }
  const g = await (await api("/api/knowledge/groups")).json();
  const pname = (g.platforms.find(x => x.key === kbSel.platform) || {}).name || kbSel.platform;
  const sname = (g.sublibs.find(x => x.key === kbSel.sublib) || {}).name || kbSel.sublib;
  el("kb-crumb").innerHTML = `当前位置：<b>知识库</b> › <b>${pname}</b> › <b>${sname}</b>`;
  fetchKB();
}
async function fetchKB() {
  if (!kbSel) return;
  const r = await api(`/api/knowledge/by-group?platform=${kbSel.platform}&sublib=${kbSel.sublib}`);
  const list = r.ok ? await r.json() : [];
  const box = el("kb-tbody");
  if (!list.length) { box.innerHTML = `<tr><td colspan="6" class="pill">该分类暂无内容</td></tr>`; return; }
  box.innerHTML = list.map(k => {
    const src = (k.meta && k.meta.source) || "";
    return `<tr><td>${k.id}</td><td>${k.title}</td><td>${k.sublib}</td>
      <td>${(k.tags || []).map(t => `<span class="tag">${t}</span>`).join("")}</td>
      <td><span class="tag src">${src || "-"}</span></td>
      <td><button class="btn ghost" onclick="openKbModal(${k.id})">编辑</button>
          <button class="btn danger" onclick="delKB(${k.id})">删除</button></td></tr>`;
  }).join("");
}
function openKbModal(id) {
  if (id) {
    api("/api/knowledge/" + id).then(r => r.json()).then(k => {
      el("kb-modal-title").textContent = "编辑知识条目";
      el("kb-id").value = k.id; el("kb-platform").value = k.platform || "general"; el("kb-sub").value = k.sublib;
      el("kb-title").value = k.title; el("kb-content").value = k.content;
      el("kb-tags").value = (k.tags || []).join("、"); el("kb-source").value = (k.meta && k.meta.source) || "";
      el("kb-err").textContent = ""; el("modal-kb").classList.remove("hidden");
    });
  } else {
    el("kb-modal-title").textContent = "新增知识条目";
    ["kb-id", "kb-title", "kb-content", "kb-tags", "kb-source"].forEach(i => el(i).value = "");
    el("kb-platform").value = (kbSel && kbSel.platform) || "general";
    el("kb-sub").value = (kbSel && kbSel.sublib) || "platform";
    el("kb-err").textContent = ""; el("modal-kb").classList.remove("hidden");
  }
}
async function saveKB() {
  setErr("kb-err", "");
  const id = el("kb-id").value;
  const body = { sublib: el("kb-sub").value, platform: el("kb-platform").value,
    key: "k" + Date.now(), title: el("kb-title").value || "新条目", content: el("kb-content").value,
    tags: el("kb-tags").value.split("、").map(s => s.trim()).filter(Boolean),
    meta: { source: el("kb-source").value.trim() } };
  let r;
  if (id) r = await api("/api/knowledge/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  else r = await api("/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) return setErr("kb-err", (await r.json()).detail || "失败");
  el("modal-kb").classList.add("hidden"); fetchKB();
}
async function delKB(id) { if (!confirm("确认删除该知识库条目？")) return; await api("/api/knowledge/" + id, { method: "DELETE" }); fetchKB(); }

/* ---------- Agent 矩阵 ---------- */
async function loadAgents() {
  const r = await api("/api/admin/agents"); if (!r.ok) return;
  const list = await r.json();
  const cr = await api("/api/admin/charts");
  const usage = {};
  if (cr.ok) (await cr.json()).agent_usage.forEach(a => usage[a.key] = { scripts: a.scripts, conversations: a.conversations });
  el("agents-box").innerHTML = list.map(a => {
    const u = usage[a.key] || { scripts: 0, conversations: 0 };
    return `<div class="card agent-card">
    <div style="display:flex;align-items:center;gap:10px">
      <span style="font-size:26px">${/^(https?:|\/static\/)/.test((a.avatar||"").trim()) ? `<img src="${a.avatar}" style="width:34px;height:34px;object-fit:cover;border-radius:8px;vertical-align:middle" onerror="this.replaceWith(document.createTextNode('🤖'))"/>` : (a.avatar || "🤖")}</span>
      <div><b>${a.name}</b> <span class="tag">${a.key}</span> ${a.enabled ? '<span class="tag ok">启用</span>' : '<span class="tag off">停用</span>'}
      <div class="pill">${a.persona_name || ""} · v${a.version || 1}</div></div>
    </div>
    <div class="pill" style="margin-top:6px">${a.description || ""}</div>
    <div class="pill">工具：${(a.tools || []).join(", ") || "无"} · 绑定模型：${a.bound_model || "默认兜底"}</div>
    <div class="pill usage">剧本 ${u.scripts} · 会话 ${u.conversations}</div>
    <div class="row" style="margin-top:8px">
      <button class="btn ghost" onclick="openAgentModal('${a.key}')">编辑</button>
      <button class="btn ghost" onclick="cloneAgent('${a.key}')">克隆</button>
      <button class="btn danger" onclick="delAgent('${a.key}')">删除</button>
    </div></div>`;
  }).join("");
}
function openAgentModal(key) {
  if (key) {
    api("/api/admin/agents/" + key).then(r => r.json()).then(a => {
      el("agent-modal-title").textContent = "编辑 Agent";
      el("ag-id").value = a.key; el("ag-key").value = a.key; el("ag-key").disabled = true;
      el("ag-name").value = a.name; el("ag-persona_name").value = a.persona_name || "";
      el("ag-avatar").value = a.avatar || ""; el("ag-description").value = a.description || "";
      el("ag-persona").value = a.persona || ""; el("ag-system_prompt").value = a.system_prompt || "";
      renderToolChips(a.tools || []); updateAgentAvatarPreview();
      fillBoundModelSelect(a.bound_model || "");
      el("ag-example").value = (a.example_dialogue ? JSON.stringify(a.example_dialogue, null, 2) : "");
      el("ag-enabled").checked = !!a.enabled; el("ag-err").textContent = ""; el("modal-agent").classList.remove("hidden");
    });
  } else {
    el("agent-modal-title").textContent = "新增 Agent";
    ["ag-id", "ag-key", "ag-name", "ag-persona_name", "ag-avatar", "ag-description", "ag-persona", "ag-system_prompt", "ag-example"].forEach(i => el(i).value = "");
    renderToolChips([]); el("ag-avatar").value = "🤖"; updateAgentAvatarPreview(); fillBoundModelSelect("");
    el("ag-key").disabled = false; el("ag-enabled").checked = true;
    el("ag-err").textContent = ""; el("modal-agent").classList.remove("hidden");
  }
}
// 头像预览：URL(http 或 /static) 渲染为图片，否则按 emoji 文本显示
function updateAgentAvatarPreview() {
  const v = (el("ag-avatar").value || "").trim();
  const prev = el("ag-avatar-preview");
  if (/^(https?:|\/static\/)/.test(v)) {
    prev.innerHTML = `<img src="${v}" style="width:100%;height:100%;object-fit:cover;border-radius:10px" />`;
  } else {
    prev.textContent = v || "🤖";
  }
}
// 上传头像图片：调后端保存，返回 URL 写入 avatar 字段并预览
async function uploadAgentAvatar() {
  const f = el("ag-avatar-file").files[0];
  if (!f) return;
  setErr("ag-err", "上传中…");
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch("/api/admin/agents/avatar", {
    method: "POST", headers: { "Authorization": "Bearer " + A.token }, body: fd,
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); return setErr("ag-err", e.detail || "上传失败"); }
  const d = await r.json();
  el("ag-avatar").value = d.url; updateAgentAvatarPreview();
  setErr("ag-err", "");
}
function renderToolChips(enabled) {
  el("ag-tools-box").innerHTML = KNOWN_TOOLS.map(t =>
    `<span class="chip ${(enabled || []).includes(t.k) ? "on" : ""}" data-tool="${t.k}" onclick="toggleChip(this)">${t.n}</span>`).join("");
}
function toggleChip(node) { node.classList.toggle("on"); }
async function fillBoundModelSelect(sel) {
  const r = await api("/api/model-configs"); if (!r.ok) return;
  const list = await r.json();
  el("ag-bound_model").innerHTML = ['<option value="">不绑定（走默认兜底）</option>'].concat(
    list.map(m => `<option value="${m.model_name}">${(GROUP_NAMES[m.group_label] || m.group_label)} · ${m.model_name}</option>`)).join("");
  if (sel) el("ag-bound_model").value = sel;
}
async function saveAgent() {
  setErr("ag-err", "");
  const key = el("ag-key").value.trim();
  if (!key) return setErr("ag-err", "key 必填");
  let example = [];
  const ex = el("ag-example").value.trim();
  if (ex) { try { example = JSON.parse(ex); } catch (e) { return setErr("ag-err", "示例对话必须是 JSON 数组"); } }
  const body = {
    name: el("ag-name").value, persona_name: el("ag-persona_name").value, avatar: el("ag-avatar").value,
    description: el("ag-description").value, persona: el("ag-persona").value, system_prompt: el("ag-system_prompt").value,
    tools: Array.from(document.querySelectorAll("#ag-tools-box .chip.on")).map(c => c.dataset.tool),
    bound_model: el("ag-bound_model").value || null,
    example_dialogue: example, enabled: el("ag-enabled").checked,
  };
  const id = el("ag-id").value;
  let r;
  if (id) r = await api("/api/admin/agents/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  else r = await api("/api/admin/agents", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ key }, body)) });
  if (!r.ok) return setErr("ag-err", (await r.json()).detail || "失败");
  el("modal-agent").classList.add("hidden"); loadAgents();
}
async function delAgent(key) {
  if (!confirm("确认删除 Agent「" + key + "」？")) return;
  await api("/api/admin/agents/" + key, { method: "DELETE" }); loadAgents();
}
async function cloneAgent(key) {
  const new_key = prompt("请输入新 Agent 的 key（英文，如 " + key + "_v2）：");
  if (!new_key) return;
  const r = await api("/api/admin/agents/" + key + "/clone", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_key, name: key + "·副本" }) });
  if (!r.ok) return alert((await r.json()).detail || "克隆失败");
  loadAgents();
}

/* ---------- 模型中心（分组 + Key） ---------- */
let modelState = { group: "ark_chat" };
async function loadModels() {
  const g = await (await api("/api/model-configs/groups")).json();
  el("model-groups").innerHTML = g.map(x =>
    `<div class="kb-tab ${x.key === modelState.group ? "active" : ""}" onclick="setModelGroup('${x.key}')">${x.icon} ${x.name}</div>`).join("");
  fetchModels();
}
function setModelGroup(g) { modelState.group = g; loadModels(); }
async function fetchModels() {
  const r = await api("/api/model-configs/by-group?group=" + modelState.group);
  const list = r.ok ? await r.json() : [];
  el("models-box").innerHTML = list.map(m => `<div class="card model-card">
    <div style="font-weight:700">${m.model_name} <span class="tag">${m.role}</span> ${m.enabled ? '<span class="tag ok">启用</span>' : '<span class="tag off">停用</span>'}
      <span class="pill" style="margin-left:6px">${GROUP_NAMES[m.group_label] || m.group_label} · provider:${m.provider || "-"}</span>
      <span class="pill">${m.description || ""}</span></div>
    <div class="row" style="margin-top:8px">
      <input class="input" id="m-url-${m.id}" value="${m.base_url || ""}" placeholder="base_url" />
    </div>
    <div class="row">
      <input class="input" id="m-key-${m.id}" type="password" value="${m.api_key || ""}" placeholder="API Key（明文保存，仅后台可见）" />
      <button class="btn ghost" type="button" onclick="toggleKeyEye(${m.id})">显隐</button>
      <span class="pill">${m.api_key_set ? "已配置" : "未配置"}</span>
    </div>
    <div class="row">
      <label class="pill">启用 <input type="checkbox" id="m-en-${m.id}" ${m.enabled ? "checked" : ""} /></label>
      <button class="btn ghost" onclick="saveModel(${m.id})">保存</button>
      <button class="btn ghost" onclick="toggleModel(${m.id})">启用/停用</button>
      <button class="btn ghost" onclick="probeModel(${m.id})">连通性自检</button>
    </div>
    <div id="probe-${m.id}" class="probe-result"></div></div>`).join("");
}
function toggleKeyEye(id) {
  const inp = el("m-key-" + id);
  if (inp) inp.type = inp.type === "password" ? "text" : "password";
}
function openModelModal() {
  el("model-modal-title").textContent = "新增模型配置";
  el("mm-id").value = "";
  ["mm-group", "mm-role", "mm-provider", "mm-model_name", "mm-base_url", "mm-api_key", "mm-description"].forEach(i => el(i).value = "");
  el("mm-enabled").checked = false; el("mm-err").textContent = "";
  el("modal-model").classList.remove("hidden");
}
async function saveModelModal() {
  setErr("mm-err", "");
  const body = {
    group_label: el("mm-group").value, role: el("mm-role").value, provider: el("mm-provider").value,
    model_name: el("mm-model_name").value, base_url: el("mm-base_url").value || null,
    api_key: el("mm-api_key").value || null, description: el("mm-description").value, enabled: el("mm-enabled").checked,
  };
  if (!body.model_name) return setErr("mm-err", "model_name 必填");
  const id = el("mm-id").value;
  const r = id
    ? await api("/api/model-configs/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    : await api("/api/model-configs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) return setErr("mm-err", (await r.json()).detail || "失败");
  el("modal-model").classList.add("hidden"); loadModels();
}
async function saveModel(id) {
  const body = { base_url: el("m-url-" + id).value, api_key: el("m-key-" + id).value, enabled: el("m-en-" + id).checked };
  const r = await api("/api/model-configs/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.ok) { toast2("已保存"); fetchModels(); } else alert((await r.json()).detail || "失败");
}
async function toggleModel(id) {
  await api("/api/model-configs/" + id + "/toggle", { method: "POST" }); fetchModels();
}
async function probeModel(id) {
  const box = el("probe-" + id);
  if (box) { box.className = "probe-result pending"; box.textContent = "正在自检…"; }
  const r = await api("/api/model-configs/" + id + "/probe", { method: "POST" });
  if (!r.ok) {
    if (box) { box.className = "probe-result err"; box.textContent = "❌ 自检失败：" + ((await r.json()).detail || r.status); }
    return;
  }
  const d = await r.json();
  if (box) {
    box.className = "probe-result " + (d.ok ? "ok" : "err");
    box.innerHTML = d.ok
      ? `✅ ${d.reason} · HTTP ${d.status_code} · ${d.latency_ms} ms`
      : `❌ ${d.reason}${d.status_code ? " · HTTP " + d.status_code : ""}${d.latency_ms ? " · " + d.latency_ms + " ms" : ""}`;
  }
}
function toast2(m) { const t = document.createElement("div"); t.className = "toast show"; t.textContent = m; document.body.appendChild(t); setTimeout(() => t.remove(), 1800); }

/* ---------- 会员体系 ---------- */
async function loadMembership() {
  const r = await api("/api/admin/membership"); if (!r.ok) return;
  const c = await r.json();
  const plans = (c.plans || []).map(p => `<span class="tag">${p.name}：生成${p.can_script ? "✅" : "❌"} / 下载${p.can_download ? "✅" : "❌"} / 生图${p.can_image ? "✅" : "❌"} / 生视频${p.can_video ? "✅" : "❌"}</span>`).join(" ");
  el("mb-plans").innerHTML = plans;
  const fm = c.feature_min_level || {};
  const feats = [["script_generate", "剧本生成"], ["script_download", "下载/导出"], ["image_generate", "生图"], ["image_quality_4k", "4K生图"], ["video_generate", "生视频"]];
  el("mb-features").innerHTML = feats.map(([k, name]) => `<div class="row" style="margin:6px 0">
     <span class="pill" style="min-width:120px">${name}</span>
     <select id="fm-${k}" class="input" style="max-width:140px"><option value="free">免费</option><option value="member">会员</option><option value="pro">会员Pro</option></select></div>`).join("");
  feats.forEach(([k]) => { const s = el("fm-" + k); if (s) s.value = fm[k] || "free"; });
  el("mb-4k").checked = !!c.image_4k_enabled; el("mb-badge").checked = !!c.watermark_badge; el("mb-implicit").checked = !!c.watermark_implicit;
  el("mb-quota").value = c.free_script_quota; el("mb-badge-text").value = c.badge_text || "AI 生成";
  const ru = await api("/api/admin/users"); const users = await ru.json();
  const nu = users.filter(u => u.account_type !== "admin");
  el("mb-users").innerHTML = nu.map(u => `<tr>
    <td>${u.id}</td><td>${u.username}</td><td>${u.membership_level || "free"}</td>
    <td><select id="mlv-${u.id}" class="input" style="max-width:110px"><option value="free">免费</option><option value="member">会员</option><option value="pro">会员Pro</option></select></td>
    <td><button class="btn ghost" onclick="setLevel(${u.id})">设等级</button></td></tr>`).join("");
  nu.forEach(u => { const s = el("mlv-" + u.id); if (s) s.value = u.membership_level || "free"; });
}
async function saveMembership() {
  setErr("mb-err", "");
  const fm = {};
  [["script_generate", "free"], ["script_download", "member"], ["image_generate", "member"], ["image_quality_4k", "pro"], ["video_generate", "pro"]].forEach(([k, def]) => { const s = el("fm-" + k); fm[k] = s ? s.value : def; });
  const put = (k, value) => api("/api/admin/membership", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: k, value }) });
  try {
    await put("feature_min_level", fm); await put("image_4k_enabled", el("mb-4k").checked);
    await put("watermark_badge", el("mb-badge").checked); await put("watermark_implicit", el("mb-implicit").checked);
    await put("free_script_quota", parseInt(el("mb-quota").value || "5", 10)); await put("badge_text", el("mb-badge-text").value.trim() || "AI 生成");
    setErr("mb-err", "已保存 ✅"); loadMembership();
  } catch (e) { setErr("mb-err", "保存出错：" + e); }
}

window.onload = () => {
  if (A.token) { el("login").classList.add("hidden"); el("dash").classList.remove("hidden"); switchTab("dashboard"); }
  else loadAdminCaptcha();
};
