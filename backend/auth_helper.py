"""真实鉴权助手：取验证码(保存 png 供人读) + 登录/注册拿 token。
- python auth_helper.py captcha                      -> 保存 captcha.png, 打印 captcha_id
- python auth_helper.py register <user> <pw> <phone> <cid> <code>  -> 注册并写 token 到 token_<user>.txt
- python auth_helper.py login <acct> <pw> <cid> <code>            -> 登录并写 token 到 token_<acct>.txt
"""
import sys, json, base64, urllib.request, urllib.error

BASE = "http://127.0.0.1:8090"

def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")

def cmd_captcha():
    st, b = _req("GET", "/api/auth/captcha")
    j = json.loads(b)
    open("captcha.png", "wb").write(base64.b64decode(j["image"].split(",", 1)[1]))
    print("captcha_id=", j["captcha_id"])

def cmd_register(user, pw, phone, cid, code):
    st, b = _req("POST", "/api/auth/register",
                 {"username": user, "password": pw, "phone": phone,
                  "captcha_id": cid, "captcha_code": code})
    print("register", st, b[:200])
    if st == 200:
        open(f"token_{user}.txt", "w").write(json.loads(b)["access_token"])

def cmd_login(acct, pw, cid, code):
    st, b = _req("POST", "/api/auth/login",
                 {"account": acct, "password": pw, "captcha_id": cid, "captcha_code": code})
    print("login", st, b[:200])
    if st == 200:
        open(f"token_{acct}.txt", "w").write(json.loads(b)["access_token"])

def cmd_admin_login(acct, pw, cid, code):
    st, b = _req("POST", "/api/auth/admin/login",
                 {"account": acct, "password": pw, "captcha_id": cid, "captcha_code": code})
    print("admin_login", st, b[:200])
    if st == 200:
        open(f"token_{acct}.txt", "w").write(json.loads(b)["access_token"])

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "captcha": cmd_captcha()
    elif a[0] == "register": cmd_register(a[1], a[2], a[3], a[4], a[5])
    elif a[0] == "login": cmd_login(a[1], a[2], a[3], a[4])
    elif a[0] == "admin_login": cmd_admin_login(a[1], a[2], a[3], a[4])
