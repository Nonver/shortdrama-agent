/* 登录/注册独立页：复用 common.js 的 api/toast/state/loadCaptcha/setErr。
   登录或注册成功后写入 token 并回跳 next（默认首页）。 */

function getNext() {
  const n = new URLSearchParams(location.search).get("next");
  if (!n) return "/";
  try {
    const u = new URL(n, location.origin);
    if (u.origin === location.origin) return u.pathname + u.search;
  } catch {}
  return "/";
}

function finishLogin(j) {
  state.token = j.access_token;
  localStorage.setItem("token", j.access_token);
  state.user = j.user;
  toast("登录成功");
  setTimeout(() => { location.href = getNext(); }, 350);
}

async function doLogin() {
  setErr("login-err", "");
  const captcha_id = el("login-captcha-img").dataset.id;
  const body = { account: el("login-account").value, password: el("login-pass").value,
    captcha_id, captcha_code: el("login-code").value };
  const r = await api("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { setErr("login-err", j.detail || "登录失败"); loadCaptcha("login"); return; }
  finishLogin(j);
}

async function doRegister() {
  setErr("reg-err", "");
  const captcha_id = el("reg-captcha-img").dataset.id;
  const body = { username: el("reg-user").value, password: el("reg-pass").value,
    phone: el("reg-phone").value, captcha_id, captcha_code: el("reg-code").value };
  const r = await api("/api/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { setErr("reg-err", j.detail || "注册失败"); loadCaptcha("reg"); return; }
  finishLogin(j);
}

function toggleAuth() {
  const isLogin = !el("login-card").classList.contains("hidden");
  el("login-card").classList.toggle("hidden", isLogin);
  el("reg-card").classList.toggle("hidden", !isLogin);
}

window.onload = () => { loadCaptcha("login"); loadCaptcha("reg"); };
