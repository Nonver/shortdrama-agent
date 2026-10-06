/* Agent 聊天页：流式对话 + 会话管理 + @召唤协作 + 跨Agent上下文
 * 交互模型（重构后）：聊天即 Agent 大脑。
 *  - 每条消息先意图识别再分流：生成 / 优化上一条 / 向导答疑 / 生图视频配音 / 追问澄清
 *  - Agent 先说一句自然语言（agent_thinking）再处理，不再直接「在构思剧本」
 *  - 生图/视频/配音由意图自动触发，不再有底部工具栏
 *  - AI 向导旁路入当前聊天流（顶部🤖按钮或选中文本快捷提问），不再独立弹窗
 */
let AGENT_KEY = (location.pathname.split("/agent/")[1] || "director").replace(/\/$/, "");
let agentsCache = {};
let sessions = [];
let currentSid = null;
let mentions = [];
let streaming = false;

/* ---------- 启动 ---------- */
window.onload = async () => {
  refreshAuth();
  await loadAgents();
  await loadAgentMeta();
  await bootstrapUser();
  refreshAuth();
  if (!state.token) { location.href = "/login?next=" + encodeURIComponent("/agent/" + AGENT_KEY); return; }
  await loadSessions();
  if (sessions.length) selectSession(sessions[0].id);
  else await newSession(true);
};
window.onLogin = () => { refreshAuth(); hideLoginHint(); loadSessions().then(() => { if (!sessions.length) newSession(true); }); };
window.onLogout = () => { refreshAuth(); showLoginHint(); };

function refreshAuth() { /* 由 common.js state 控制 */ }
function personaName() {
  const a = agentsCache[AGENT_KEY];
  return a ? (a.persona_name || a.name) : AGENT_KEY;
}

/* ---------- 智能体元信息 ---------- */
async function loadAgents() {
  try {
    const list = await (await api("/api/agents")).json();
    list.forEach(a => { agentsCache[a.key] = a; });
  } catch {}
}
async function loadAgentMeta() {
  const a = agentsCache[AGENT_KEY];
  if (a) { applyAgentMeta(a); return; }
  try {
    const r = await api("/api/agents/" + AGENT_KEY);
    if (r.ok) { const d = await r.json(); agentsCache[AGENT_KEY] = d; applyAgentMeta(d); }
  } catch {}
}
function applyAgentMeta(a) {
  el("agent-avatar").innerHTML = avatarHTML(a.avatar, "🎬");
  el("agent-name").textContent = a.name || AGENT_KEY;
  el("agent-desc").textContent = a.persona_name ? (a.persona_name + " · " + (a.description || "")) : (a.description || "");
  document.title = (a.name || "Agent") + " · AI 短剧导演组";
}

/* ---------- 会话 ---------- */
async function loadSessions() {
  if (!state.token) { sessions = []; return; }
  const r = await api("/api/chat/sessions?agent_key=" + AGENT_KEY);
  if (r.ok) { sessions = await r.json(); renderSessions(); }
}
function renderSessions() {
  const box = el("session-list");
  if (!sessions.length) { box.innerHTML = `<div class="pill">暂无会话，点「新建会话」开始</div>`; return; }
  box.innerHTML = sessions.map(s =>
    `<div class="session-item ${s.id === currentSid ? "active" : ""}" onclick="selectSession(${s.id})">
       <div class="si-title">${s.title || "新会话"}</div>
       <div class="pill">${s.message_count} 条 · ${s.is_streaming ? "生成中" : "空闲"}</div>
     </div>`).join("");
}
async function newSession(silent) {
  if (!state.token) { openAuth(); return; }
  const r = await api("/api/chat/sessions", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_key: AGENT_KEY, title: "" }) });
  if (!r.ok) { if (r.status === 401) openAuth(); return; }
  const s = await r.json();
  sessions.unshift(s); currentSid = s.id; renderSessions();
  el("chat").innerHTML = "";
  if (!silent) toast("已新建会话");
}
async function selectSession(sid) {
  currentSid = sid; renderSessions();
  el("session-drawer").classList.add("hidden");
  const r = await api("/api/chat/sessions/" + sid);
  if (!r.ok) return;
  const s = await r.json();
  renderMessages(s.messages || []);
}
function renderMessages(msgs) {
  const box = el("chat"); box.innerHTML = "";
  (msgs || []).forEach(m => appendMsg(m, false));
  scrollChat();
}

/* ---------- 发送（SSE 流式） ---------- */
async function send() {
  if (!state.token) { openAuth(); return; }
  const input = el("c-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  await sendText(text);
}
async function sendText(text) {
  if (!state.token) { openAuth(); return; }
  if (streaming) { toast("正在生成，请稍候"); return; }
  if (!currentSid) await newSession(true);
  const sid = currentSid;
  appendMsg({ role: "user", content: text, mentions: mentions.slice() }, true);
  const platform = el("c-platform").value;
  const genre = el("c-genre").value;
  const episode_count = parseInt(el("c-episodes").value) || 1;
  const sentMentions = mentions.slice(); clearMentions();

  streaming = true; setSending(true);
  let curRaw = "", curScriptBubble = null, tokenCount = 0, curThinking = null;
  try {
    let res = await api(`/api/chat/sessions/${sid}/stream`, { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, platform, genre, episode_count, mentions: sentMentions }) });
    if (res.status === 401) { openAuth(); streaming = false; setSending(false); return; }
    // 409 = 会话锁仍被上一次 SSE 占着（并发/僵尸锁竞态）。自动解锁后重试一次，避免把用户卡死。
    if (res.status === 409) {
      await resetStreaming(sid);
      toast("上一轮会话卡住了，已自动解锁并重试…");
      res = await api(`/api/chat/sessions/${sid}/stream`, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, platform, genre, episode_count, mentions: sentMentions }) });
      if (res.status === 409) throw new Error("会话仍被锁定，请刷新页面后再试");
    }
    if (!res.body) throw new Error("无响应");
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
        const p = parseSSE(chunk);
        if (!p || !p.event) continue;
        if (p.event === "agent_start") {
          // 仅记录，气泡在 token / thinking 时创建
        } else if (p.event === "agent_thinking") {
          if ((p.data && p.data.stage) !== "writing") curThinking = onAgentThinking(p.data);
        } else if (p.event === "guide_answer") {
          appendGuideBubble(p.data.answer, p.data.refs);
          if (curThinking) { curThinking.classList.remove("writing"); }
        } else if (p.event === "tool_result") {
          appendToolResultFromSSE(p.data);
          if (curThinking) curThinking.classList.remove("writing");
        } else if (p.event === "collab") {
          appendAgentBubble(p.data.agent_key, p.data.persona_name, false, p.data.content, true);
        } else if (p.event === "token") {
          if (!curScriptBubble) curScriptBubble = appendAgentBubble(AGENT_KEY, personaName(), true);
          curRaw += p.data.text; tokenCount++;
          if (curScriptBubble && (tokenCount % 4 === 0)) curScriptBubble.querySelector(".md").textContent = curRaw;
          if (curThinking) curThinking.classList.add("writing");
        } else if (p.event === "done") {
          if (curThinking) curThinking.classList.remove("writing");
          if (p.data && p.data.markdown && curScriptBubble) {
            curScriptBubble.querySelector(".md").innerHTML = renderMarkdown(p.data.markdown);
            if (p.data.is_optimize) {
              const who = curScriptBubble.querySelector(".who");
              if (who) who.innerHTML += ` <span class="summon-tag">⚡ 优化版</span>`;
            }
          }
          // 文本产物（提示词/文案）或出片失败降级：提供"一键真出片"二次确认
          if (p.data && (p.data.intent === "TEXT_PROMPT" || p.data.tool_error) && p.data.prompt_kind) {
            appendPromptActions(p.data.prompt_kind, p.data.prompt_text, p.data.tool_error);
          }
          if (p.data && p.data.script_id && state.user && canDownload()) appendDownload(p.data.script_id);
          toast("完成 ✅");
        } else if (p.event === "error") {
          toast("出错：" + (p.data && p.data.msg), "err");
          if (curThinking) curThinking.classList.remove("writing");
        }
      }
    }
  } catch (e) {
    toast("生成失败：" + e, "err");
  } finally {
    streaming = false; setSending(false);
    loadSessions();
  }
}
// agent_thinking：understanding/planning 渲染持久气泡（Agent 先回应）；writing 仅由主循环标记加载中
function onAgentThinking(data) {
  const stage = (data && data.stage) || "understanding";
  const text = (data && data.text) || "思考中…";
  if (stage === "writing") return null;
  const d = document.createElement("div"); d.className = "msg agent thinking-msg";
  d.innerHTML = `<div class="av">🤖</div><div class="bubble agent-b"><div class="who">${personaName()}</div><div class="md think">${escapeHtml(text)}</div></div>`;
  el("chat").appendChild(d); scrollChat();
  return d;
}

function setSending(b) { el("c-send").disabled = b; el("c-send").textContent = b ? "生成中…" : "发送"; }

/* ---------- 消息气泡 ---------- */
function agentInfo(key) { return agentsCache[key] || { avatar: "🤖", name: key }; }
function appendMsg(m, scroll) {
  const box = el("chat");
  if (m.role === "user") {
    const d = document.createElement("div"); d.className = "msg user";
    d.innerHTML = `<div class="bubble">${escapeHtml(m.content)}${mentionChipsHtml(m.mentions)}</div>`;
    box.appendChild(d);
  } else {
    const info = agentInfo(m.agent_key);
    const d = document.createElement("div"); d.className = "msg agent";
    d.innerHTML = `<div class="av">${avatarHTML(info.avatar)}</div>
      <div class="bubble agent-b"><div class="who">${m.persona_name || info.name}${m.is_optimize ? " <span class='summon-tag'>⚡ 优化版</span>" : ""}</div>
      <div class="md">${renderMarkdown(m.content || "")}</div></div>`;
    if (m.script_id && state.user && canDownload()) d._sid = m.script_id;
    box.appendChild(d);
  }
  if (scroll !== false) scrollChat();
}
function appendAgentBubble(key, persona, streaming, content, isCollab) {
  const info = agentInfo(key);
  const d = document.createElement("div"); d.className = "msg agent" + (isCollab ? " collab" : "");
    d.innerHTML = `<div class="av">${avatarHTML(info.avatar)}</div>
    <div class="bubble agent-b"><div class="who">${persona || info.name}${isCollab ? " <span class='summon-tag'>被召唤</span>" : ""}</div>
    <div class="md">${content ? renderMarkdown(content) : (streaming ? "<span class='thinking'>💭 生成中…</span>" : "")}</div></div>`;
  el("chat").appendChild(d); scrollChat();
  return d;
}
function appendGuideBubble(answer, refs) {
  const refsHtml = (refs || []).length
    ? `<div class="kb-guide-refs">📚 相关参考：` + refs.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("") + `</div>`
    : "";
  const d = document.createElement("div"); d.className = "msg agent guide-msg";
  d.innerHTML = `<div class="av">🤖</div><div class="bubble agent-b"><div class="who">AI 向导</div>
    <div class="md">${renderMarkdown(answer || "")}</div>${refsHtml}</div>`;
  el("chat").appendChild(d); scrollChat();
}
function appendToolResultFromSSE(res) {
  const d = document.createElement("div"); d.className = "msg agent tool-msg";
  let inner = "";
  if (res.kind === "image") inner = `<img src="${res.url}" class="tool-img"/>`;
  else if (res.kind === "video") inner = `<video src="${res.url}" controls class="tool-video"></video>`;
  else inner = `<audio src="${res.url}" controls class="tool-audio"></audio><div class="pill">${escapeHtml(res.text || "")}</div>`;
  if (res.script_id) inner += `<div class="pill">🔗 已关联剧本 #${res.script_id}</div>`;
  const label = { image: "图片", video: "视频", audio: "配音" }[res.kind] || "生成";
  d.innerHTML = `<div class="av">🛠️</div><div class="bubble agent-b"><div class="who">已生成${label}</div>${inner}</div>`;
  el("chat").appendChild(d); scrollChat();
}
function appendPromptActions(kind, promptText, isError) {
  const map = { video: ["🎬 真的去出视频", "video"], image: ["🖼️ 真的去出图", "image"], tts: ["🔊 真的去配音", "tts"] };
  const cfg = map[kind] || (kind === "text" ? ["🛠️ 用这段文字去出片", "video"] : null);
  if (!cfg) return;
  const [label, tool] = cfg;
  const d = document.createElement("div"); d.className = "msg agent tool-msg";
  const hint = isError
    ? `<div class="pill warn">⚠️ 上次出片失败（额度/服务问题），请先去方舟控制台解决，或复制上方提示词手动出片</div>`
    : "";
  d.innerHTML = `<div class="av">🛠️</div><div class="bubble agent-b"><div class="who">下一步</div>${hint}<button class="btn slim" id="prompt-go-${tool}">${label}</button></div>`;
  el("chat").appendChild(d); scrollChat();
  const btn = d.querySelector("button");
  btn.onclick = async () => {
    if (!state.token) { openAuth(); return; }
    btn.disabled = true; btn.textContent = "生成中…";
    try {
      const body = tool === "tts" ? { text: promptText } : { prompt: promptText };
      const r = await api(`/api/chat/sessions/${currentSid}/tool/${tool}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const res = await r.json().catch(() => ({}));
      // 三类异常统一走 paintToolError：
      // 1) 结构化 200 + {error}：_tool_err_friendly 包装后的 JSON
      // 2) 4xx/5xx 依赖注入层抛出：detail 在 res.detail（HTTPException）
      // 3) 网络/解析异常：交由 catch 处理
      if (!r.ok || res.error || res.detail) {
        const synth = res.error
            ? res
            : { error: res.detail || `出片失败（HTTP ${r.status}）`,
                error_kind: r.status === 403 ? "permission" : (r.status === 429 ? "rate" : "service"),
                prompt: promptText };
        paintToolError(d, tool, synth, btn, label, promptText);
        return;
      }
      appendToolResultFromSSE(res);
      btn.remove();             // 成功后移除按钮，避免重复点
      toast("已生成 ✅");
    } catch (e) {
      toast("网络异常：" + (e.message || e), "err");
      btn.disabled = false; btn.textContent = label;
    }
  };
}

/* 出片失败时的统一渲染：中文引导 + 复制提示词 + 按钮永久禁用 */
function paintToolError(host, tool, payload, btn, origLabel, promptText) {
  const msg = payload.error || "出片失败，请稍后再试";
  const kind = payload.error_kind || "other";
  const copyLabel = "📋 复制提示词（手动出片）";
  // 错误类型→动作
  const actions = {
    quota:      "👉 解决方式：到『火山方舟控制台 → 模型激活页』关闭『安全体验模式』或等月底重置。",
    permission: "👉 解决方式：升级到对应会员等级（生视频/配音需 Pro）。",
    rate:       "👉 稍等 10 秒再点一次，或换条更精简的提示词。",
    safety:     "👉 提示词里含敏感词，已自动拦下。改用更安全的描述后再试。",
    service:    "👉 底层模型服务暂时抽风/超时，可稍后再试。",
    other:      "👉 如反复失败，可在 Agent 里告诉我具体错误。",
  }[kind] || "";
  // 复用宿主气泡：在里头追加错误条；按钮禁用 + 改名
  const bubble = host.querySelector(".bubble");
  const errBox = document.createElement("div");
  errBox.className = "err-box";
  errBox.innerHTML = `
    <div class="pill warn">⚠️ 出片失败 · ${kind}</div>
    <div class="err-msg">${escapeHtml(msg)}</div>
    <div class="err-action">${actions}</div>
    <div class="err-prompt-box"><div class="err-prompt-label">📝 提示词（可直接长按选中复制）：</div><pre class="err-prompt">${escapeHtml(promptText)}</pre></div>
    <button class="btn slim ghost" id="err-copy">${copyLabel}</button>`;
  bubble.appendChild(errBox);
  btn.disabled = true;
  btn.classList.add("disabled");
  btn.textContent = "出片已失败（见下方处理）";
  // 复制提示词（多种兜底：clipboard API → execCommand → 选中弹 toast）
  const cb = errBox.querySelector("#err-copy");
  cb.onclick = async (e) => {
    e.preventDefault();
    const ok = await copyText(promptText);
    if (ok) { cb.textContent = "✅ 已复制，可去方舟粘贴出片"; setTimeout(() => (cb.textContent = copyLabel), 2200); }
    else { cb.textContent = "⚠️ 浏览器拒绝自动复制，请长按上方提示词选中手动复制"; }
  };
  toast("出片失败（已显示原因）", "err");
}

/* 复制兜底：clipboard API → 老式 textarea + execCommand → 失败返回 false */
async function copyText(txt) {
  // 1) 现代 API
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(txt);
      return true;
    }
  } catch { /* fallthrough */ }
  // 2) 老式 textarea + execCommand（http/非 secure 也能用）
  try {
    const ta = document.createElement("textarea");
    ta.value = txt;
    ta.style.position = "fixed"; ta.style.top = "0"; ta.style.left = "0";
    ta.style.width = "1px"; ta.style.height = "1px"; ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    const ok = document.execCommand && document.execCommand("copy");
    document.body.removeChild(ta);
    return !!ok;
  } catch { return false; }
}
function appendDownload(sid) {
  const box = el("chat");
  const d = document.createElement("div"); d.className = "msg agent";
  const info = agentInfo(AGENT_KEY);
  d.innerHTML = `<div class="av">${info.avatar}</div>
    <div class="bubble agent-b"><div class="who">导出</div>
    <div class="dl-row">${["md", "docx", "pdf", "xlsx", "json"].map(f =>
      `<a href="javascript:void(0)" data-fmt="${f}" class="dl-link">.${f}</a>`).join("")}</div></div>`;
  box.appendChild(d); scrollChat();
  // 每个导出按钮走 fetch+Blob 在当前 Agent 窗口直接下载（不再开新标签、避免丢登录态）
  d.querySelectorAll(".dl-link").forEach(a => {
    a.onclick = async (e) => {
      e.preventDefault();
      const fmt = a.dataset.fmt;
      if (!state.token) { openAuth(); return; }
      const orig = a.textContent; a.textContent = "…下载中"; a.classList.add("disabled");
      try {
        const r = await api(`/api/scripts/${sid}/download?fmt=${fmt}`);
        if (!r.ok) {
          // 401/403 走统一降级：提示登录/升级，避免弹未登录页
          let detail = "下载失败";
          try { const j = await r.json(); detail = j.detail || detail; } catch {}
          toast(`${fmt} 下载失败：${detail}`, "err");
          return;
        }
        // 拿到二进制 → 触发浏览器本地下载，不离开当前页面
        const blob = await r.blob();
        const cd = r.headers.get("content-disposition") || "";
        const m = cd.match(/filename\*=UTF-8''([^;]+)/i);
        const fallback = `剧本.${fmt}`;
        const fname = m ? decodeURIComponent(m[1]) : fallback;
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url; link.download = fname;
        document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        toast(`${fmt} 已下载 ✅`);
      } catch (err) {
        toast(`${fmt} 下载异常：${err.message || err}`, "err");
      } finally {
        a.textContent = orig; a.classList.remove("disabled");
      }
    };
  });
}
function mentionChipsHtml(list) {
  if (!list || !list.length) return "";
  return `<div class="bubble-mentions">` + list.map(k => {
    const a = agentsCache[k]; return `<span class="tag">@${a ? a.name : k}</span>`;
  }).join("") + `</div>`;
}
function scrollChat() { const c = el("chat"); c.scrollTop = c.scrollHeight; }

/* ---------- 主动解锁被僵尸锁占住的会话 ---------- */
async function resetStreaming(sid) {
  try {
    await api(`/api/chat/sessions/${sid}/reset-streaming`, { method: "POST" });
  } catch { /* 忽略：解锁失败不影响后续重试 */ }
}

/* ---------- @召唤 ---------- */
function toggleMention() { el("mention-pop").classList.toggle("hidden"); renderMentionPop(); }
function renderMentionPop() {
  const pop = el("mention-pop");
  const others = Object.values(agentsCache).filter(a => a.key !== AGENT_KEY);
  pop.innerHTML = `<div class="mp-title">召唤其他智能体协作（生成后接力批注）</div>` +
    others.map(a => `<div class="mp-item ${mentions.includes(a.key) ? "on" : ""}" onclick="toggleMentionAgent('${a.key}')">
      <span>${avatarHTML(a.avatar)} ${a.name}</span> ${mentions.includes(a.key) ? "✓" : ""}</div>`).join("") +
    `<div class="mp-item sum" onclick="summonAll()">⚡ 一键召唤全部</div>`;
}
function toggleMentionAgent(key) {
  if (mentions.includes(key)) mentions = mentions.filter(k => k !== key);
  else mentions.push(key);
  renderMentionPop(); renderMentionChips();
}
function summonAll() {
  mentions = Object.values(agentsCache).filter(a => a.key !== AGENT_KEY).map(a => a.key);
  renderMentionPop(); renderMentionChips(); toast("已召唤全部智能体");
}
function renderMentionChips() {
  const box = el("mention-chips");
  if (!mentions.length) { box.innerHTML = ""; return; }
  box.innerHTML = mentions.map(k => { const a = agentsCache[k];
    return `<span class="tag m-chip">@${a ? a.name : k} <span class="x" onclick="toggleMentionAgent('${k}')">✕</span></span>`; }).join("");
}
function clearMentions() { mentions = []; renderMentionChips(); }

/* ---------- 跨 Agent 上下文 ---------- */
function toggleContext() { el("context-panel").classList.toggle("hidden"); if (!el("context-panel").classList.contains("hidden")) loadContext(); }
async function loadContext() {
  const r = await api("/api/me/cross-context");
  if (!r.ok) { el("context-body").textContent = "（需登录后查看协作记忆）"; return; }
  const j = await r.json();
  el("context-body").textContent = j.merged ? j.merged : "（暂无跨 Agent 协作记录，生成剧本后会自动沉淀）";
}

/* ---------- 会话抽屉 / 登录遮罩 ---------- */
function toggleSessions() { el("session-drawer").classList.toggle("hidden"); }
function showLoginHint() {
  const h = el("login-hint");
  h.classList.remove("hidden");
  h.innerHTML = `<div class="lh-box"><div>登录后进入智能体聊天，与 5 位导演组对话出片</div>
    <button class="btn" onclick="openAuth()">去登录 / 注册</button></div>`;
}
function hideLoginHint() { el("login-hint").classList.add("hidden"); }

/* ---------- AI 向导：旁路入聊天流（不再独立弹窗） ---------- */
function openGuide() {
  // 选中聊天区文本 → 直接作为问题发到当前会话（走 GUIDE_QUESTION 意图）
  const sel = (window.getSelection && window.getSelection().toString && window.getSelection().toString()) || "";
  if (sel.trim()) { el("c-input").value = sel.trim(); send(); return; }
  // 否则聚焦输入框，提示用户直接提问
  const i = el("c-input");
  if (i) { i.focus(); i.placeholder = "问 AI 向导任何问题，例如：新手怎么用 AI 做短剧？"; }
}
