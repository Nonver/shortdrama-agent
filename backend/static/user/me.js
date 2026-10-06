/* 我的：资料 + 会员 + 我的剧本(含生成账号/Agent) + 资产画廊 */
const PLATFORMS = { hongguo: "红果", douyin: "抖音", kuaishou: "快手" };
const AGENT_NAMES = { director: "总导演", writer: "编剧", cameraman: "分镜导演", narration: "旁白心理", reviewer: "审核" };

window.onload = () => {
  bootstrapUser().then(() => {
    if (!state.token) { location.href = "/login?next=" + encodeURIComponent("/me"); return; }
    render();
  });
};
window.onLogin = () => render();
window.onLogout = () => { toast("已退出"); location.href = "/me"; };

function render() {
  if (!state.user) { location.href = "/login?next=" + encodeURIComponent("/me"); return; }
  const u = state.user;
  el("me-name").textContent = u.nickname || u.username;
  el("me-level").textContent = "当前等级：" + levelName(u.membership_level);
  el("pf-nick").value = u.nickname || "";
  el("pf-tags").value = (u.tags || []).join("、");
  el("mb-status").textContent = canDownload() ? "已解锁下载/导出/生图" + (canVideo() ? "/生视频/配音" : "") : "免费档：仅基础生成";
  loadScripts(); loadAssets();
}

async function loadScripts() {
  const r = await api("/api/scripts");
  if (!r.ok) { el("my-scripts").innerHTML = `<div class="pill">加载失败</div>`; return; }
  const list = await r.json();
  el("my-scripts").innerHTML = list.length ? list.map(s =>
    `<div class="script-item">
       <span>${s.title} <span class="pill">·${PLATFORMS[s.platform] || s.platform}·${s.genre}·${AGENT_NAMES[s.agent_key] || s.agent_key}</span></span>
       <span class="dl-mini">
         <a href="/api/scripts/${s.id}/download?fmt=md" target="_blank">MD</a>
         <a href="/api/scripts/${s.id}/download?fmt=pdf" target="_blank">PDF</a>
       </span></div>`).join("")
    : `<div class="pill">还没有剧本，去首页和智能体聊聊吧。</div>`;
}
async function loadAssets() {
  const r = await api("/api/assets/mine");
  if (!r.ok) { el("my-assets").innerHTML = `<div class="pill">加载失败</div>`; return; }
  const list = await r.json();
  el("my-assets").innerHTML = list.length ? list.map(a => {
    if (a.kind === "image") return `<div class="asset"><img src="${a.url}"/><span>🖼️ 图</span></div>`;
    if (a.kind === "video") return `<div class="asset"><video src="${a.url}"></video><span>🎬 视频</span></div>`;
    return `<div class="asset"><audio src="${a.url}" controls></audio><span>🎧 配音</span></div>`;
  }).join("") : `<div class="pill">暂无资产</div>`;
}

async function saveProfile() {
  setErr("pf-err", "");
  const body = { nickname: el("pf-nick").value, tags: el("pf-tags").value.split("、").map(s => s.trim()).filter(Boolean) };
  const np = el("pf-newpass").value;
  if (np) { body.old_password = el("pf-oldpass").value; body.new_password = np; }
  const r = await api("/api/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) return setErr("pf-err", j.detail || "保存失败");
  state.user = j.user; render(); setErr("pf-err", "已保存 ✅");
}
