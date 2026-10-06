"""FastAPI 入口：单服务同时托管 用户端H5(/) 与 后台(/admin)，并暴露全部 API。"""
from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import engine
from .seed import init
from .routers import auth, me, scripts, knowledge, agents, models_cfg, admin, assets, chat
from .routers import admin_rag

BASE = Path(__file__).resolve().parent.parent
USER_DIR = BASE / "static" / "user"
ADMIN_DIR = BASE / "static" / "admin"
ASSET_DIR = BASE / "static" / "assets"
UPLOAD_DIR = BASE / "static" / "uploads"

app = FastAPI(title="AI 短剧剧本生成 Agent", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(scripts.router)
app.include_router(knowledge.router)
app.include_router(knowledge.public_router)
app.include_router(agents.router)
app.include_router(models_cfg.router)
app.include_router(admin.router)
app.include_router(assets.router)
app.include_router(chat.router)
app.include_router(admin_rag.router)

# 静态资源
ASSET_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/user", StaticFiles(directory=str(USER_DIR)), name="user_static")
app.mount("/static/admin", StaticFiles(directory=str(ADMIN_DIR)), name="admin_static")
app.mount("/static/assets", StaticFiles(directory=str(ASSET_DIR)), name="assets_static")
app.mount("/static/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads_static")


@app.get("/api/health")
def health():
    return {"ok": True, "msg": "AI 短剧剧本 Agent 运行中", "version": "3.0"}


@app.get("/")
def user_index():
    return FileResponse(str(USER_DIR / "index.html"))


@app.get("/agent/{key}")
def agent_chat(key: str):
    """Agent 聊天路由（统一入口，key 校验放在前端 + chat API）。"""
    return FileResponse(str(USER_DIR / "agent.html"))


@app.get("/me")
def me_page():
    return FileResponse(str(USER_DIR / "me.html"))


@app.get("/login")
def login_page():
    return FileResponse(str(USER_DIR / "login.html"))


@app.get("/admin")
def admin_index():
    return FileResponse(str(ADMIN_DIR / "index.html"))


@app.on_event("startup")
def on_startup():
    # 确保表与种子数据存在
    init()
    print("[startup] 数据库与种子初始化完成")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
