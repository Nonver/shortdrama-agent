/* 通用前端工具：token、API、Markdown 渲染、验证码登录、SSE 解析、toast。
   各页面（index / agent / me）共用；登录现已独立为 /login 页面（带 next 回跳）。 */
const API = "";
const state = { token: localStorage.getItem("token"), user: null };

function el(id) { return document.getElementById(id); }
function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  if (state.token) opts.headers["Authorization"] = "Bearer " + state.token;
  return fetch(API + path, opts);
}
function levelName(l) { return { free: "免费", member: "会员", pro: "会员Pro" }[l] || l; }
/* Agent 头像：URL(http 或 /static) 渲染为图片，否则按 emoji 文本显示（带加载失败回退） */
function avatarHTML(v, fallback) {
  v = (v || "").trim();
  fallback = fallback || "🤖";
  if (/^(https?:|\/static\/)/.test(v)) {
    return `<img src="${v}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:10px" onerror="this.replaceWith(document.createTextNode('${fallback}'))" />`;
  }
  return escapeHtml(v) || fallback;
}
function canImage() { return state.user && state.user.membership_level !== "free"; }
function canVideo() { return state.user && state.user.membership_level === "pro"; }
function canDownload() { return state.user && (state.user.membership_level === "member" || state.user.membership_level === "pro"); }

/* 轻量 toast */
function toast(msg, kind) {
  let t = el("toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg;
  t.className = "toast show" + (kind ? " " + kind : "");
  clearTimeout(t._t);
  t._t = setTimeout(() => { t.className = "toast"; }, 2200);
}

/* ---------- Markdown → HTML（支持标题/加粗/列表/引用/分隔线） ---------- */
function escapeHtml(s) { return s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function mdInline(s) {
  return escapeHtml(s)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/【([^】]+)】/g, "<span class=\"md-tag\">【$1】</span>");
}
function renderMarkdown(md) {
  if (!md) return "";
  const lines = md.split("\n");
  let html = "", inList = false, inQuote = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  const closeQuote = () => { if (inQuote) { html += "</blockquote>"; inQuote = false; } };
  for (let raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { closeList(); closeQuote(); continue; }
    if (line.startsWith("```")) { closeList(); closeQuote(); continue; }
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      closeList(); closeQuote();
      const lv = m[1].length;
      html += `<h${lv} class="md-h">${mdInline(m[2])}</h${lv}>`;
    } else if ((m = line.match(/^>\s?(.*)$/))) {
      closeList();
      if (!inQuote) { html += "<blockquote>"; inQuote = true; }
      html += `<div>${mdInline(m[1])}</div>`;
    } else if ((m = line.match(/^[-*]\s+(.*)$/))) {
      closeQuote();
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${mdInline(m[1])}</li>`;
    } else if ((m = line.match(/^(\d+)\.\s+(.*)$/))) {
      closeQuote();
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li><b>${m[1]}.</b> ${mdInline(m[2])}</li>`;
    } else if (line.startsWith("---")) {
      closeList(); closeQuote(); html += "<hr/>";
    } else {
      closeList(); closeQuote();
      html += `<p>${mdInline(line)}</p>`;
    }
  }
  closeList(); closeQuote();
  return html;
}

/* ---------- SSE 解析 ---------- */
function parseSSE(chunk) {
  let event = "", dataStr = "";
  chunk.split("\n").forEach(line => {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
  });
  try { return { event, data: JSON.parse(dataStr) }; } catch { return { event, data: null }; }
}

/* ---------- 验证码 + 登录弹窗 ---------- */
async function loadCaptcha(prefix) {
  const r = await (await fetch(API + "/api/auth/captcha")).json();
  const img = el(prefix + "-captcha-img");
  if (img) { img.src = r.image; img.dataset.id = r.captcha_id; }
}
/* 登录改为独立页：任何需要登录的入口统一跳 /login?next=当前页（登录后回跳） */
function openAuth() {
  const next = location.pathname + location.search;
  location.href = "/login?next=" + encodeURIComponent(next);
}
function logout() { state.token = null; state.user = null; localStorage.removeItem("token"); if (window.onLogout) window.onLogout(); toast("已退出"); }
function setErr(id, msg) { const e = el(id); if (e) e.textContent = msg || ""; }

/* 启动：若有 token 拉取用户信息 */
async function bootstrapUser() {
  if (!state.token) { if (window.onLogout) window.onLogout(); return; }
  try {
    const r = await api("/api/me");
    if (r.ok) { state.user = await r.json(); if (window.onLogin) window.onLogin(); }
    else { state.token = null; localStorage.removeItem("token"); if (window.onLogout) window.onLogout(); }
  } catch { state.token = null; localStorage.removeItem("token"); if (window.onLogout) window.onLogout(); }
}
