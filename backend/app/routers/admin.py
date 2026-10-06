"""后台管理路由（仅 admin）：仪表盘、用户与画像、剧本资产（含创建人）、Agent 管理、模型配置、知识库。"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Response, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, Integer
import uuid
from pathlib import Path

from .. import schemas
from ..db import get_db
from ..models import User, Script, KnowledgeItem, AgentConfig, ModelConfig, AuditLog, MembershipConfig, Asset, Conversation
from ..deps import require_admin, get_membership_config
from ..security import hash_password
from ..exports import to_markdown, to_json, to_docx, to_xlsx, to_pdf

router = APIRouter(prefix="/api/admin", tags=["admin"])

FMT_MEDIA = {
    "md": ("text/markdown", "md"),
    "json": ("application/json", "json"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}


# ---------- 仪表盘（数据更全） ----------
@router.get("/dashboard", response_model=dict)
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    today = __import__("datetime").datetime.utcnow().date()
    return {
        "users": db.query(User).count(),
        "active_users_today": db.query(User).filter(User.last_login.isnot(None)).count(),
        "free_users": db.query(User).filter(User.membership_level == "free").count(),
        "member_users": db.query(User).filter(User.membership_level == "member").count(),
        "pro_users": db.query(User).filter(User.membership_level == "pro").count(),
        "scripts": db.query(Script).count(),
        "scripts_today": db.query(Script).filter(Script.created_at >= today).count(),
        "knowledge": db.query(KnowledgeItem).count(),
        "agents": db.query(AgentConfig).filter(AgentConfig.enabled.is_(True)).count(),
        "sessions": db.query(Conversation).count(),
        "assets": db.query(Asset).count(),
        "models": db.query(ModelConfig).filter(ModelConfig.enabled.is_(True)).count(),
    }


# ---------- 仪表盘图表数据（聚合） ----------
@router.get("/charts", response_model=dict)
def charts(days: int = Query(14, ge=1, le=90, description="剧本趋势天数：7/14/30/90"),
           db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """仪表盘图表聚合：Agent 使用量、近 N 天剧本趋势、会员分布、模型状态、知识库子库、最近审计。"""
    # Agent 使用量（剧本 + 会话）
    agents = db.query(AgentConfig).order_by(AgentConfig.sort_order).all()
    agent_keys = [a.key for a in agents]
    name_map = {a.key: a.name for a in agents}
    sc = dict(db.query(Script.agent_key, func.count(Script.id)).group_by(Script.agent_key).all())
    cv = dict(db.query(Conversation.agent_key, func.count(Conversation.id)).group_by(Conversation.agent_key).all())
    agent_usage = [{"key": k, "name": name_map.get(k, k),
                    "scripts": int(sc.get(k, 0)), "conversations": int(cv.get(k, 0))}
                   for k in agent_keys]

    # 近 N 天剧本趋势
    days = min(max(int(days), 1), 90)
    today = date.today()
    span = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    day_set = {d.isoformat(): 0 for d in span}
    since = datetime.combine(span[0], time.min)
    rows = db.query(func.date(Script.created_at), func.count(Script.id)) \
             .filter(Script.created_at >= since).group_by(func.date(Script.created_at)).all()
    for d, c in rows:
        key = str(d)
        if key in day_set:
            day_set[key] = int(c)
    scripts_trend = [{"date": d, "count": day_set[d]} for d in day_set]

    # 会员分布
    lv = dict(db.query(User.membership_level, func.count(User.id)).group_by(User.membership_level).all())
    member_dist = [{"level": l, "count": int(lv.get(l, 0))} for l in ("free", "member", "pro")]

    # 模型状态（按分组：总数 / 启用数）
    mc = db.query(ModelConfig.group_label, func.count(ModelConfig.id),
                  func.sum(func.cast(ModelConfig.enabled, Integer))) \
            .group_by(ModelConfig.group_label).all()
    model_status = [{"group": g, "total": int(t), "enabled": int(e or 0)} for g, t, e in mc]

    # 知识库各子库数量
    kb = dict(db.query(KnowledgeItem.sublib, func.count(KnowledgeItem.id)).group_by(KnowledgeItem.sublib).all())
    knowledge_by_sublib = [{"sublib": s, "count": int(kb.get(s, 0))}
                           for s in ("platform", "genre", "style", "asset")]

    # 最近审计
    audit = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(8).all()
    recent_audit = [{"id": a.id, "action": a.action, "target": a.target,
                     "created_at": a.created_at.isoformat() if a.created_at else None}
                    for a in audit]

    return {"days": days, "agent_usage": agent_usage, "scripts_trend": scripts_trend,
            "member_dist": member_dist, "model_status": model_status,
            "knowledge_by_sublib": knowledge_by_sublib, "recent_audit": recent_audit}


@router.post("/users", response_model=schemas.UserOut)
def create_user(body: schemas.AdminUserCreate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "用户名已存在")
    if body.phone and db.query(User).filter(User.phone == body.phone).first():
        raise HTTPException(400, "手机号已注册")
    if body.membership_level not in ("free", "member", "pro"):
        raise HTTPException(400, "档位只能是 free/member/pro")
    if body.account_type not in ("user", "admin"):
        raise HTTPException(400, "类型只能是 user/admin")
    u = User(username=body.username, phone=body.phone,
             password_hash=hash_password(body.password),
             account_type=body.account_type, nickname=body.nickname or body.username,
             membership_level=body.membership_level, status=body.status,
             tags=[], habits={})
    db.add(u); db.commit(); db.refresh(u)
    db.add(AuditLog(actor_id=admin.id, action="create_user", target=str(u.id),
                    detail=body.username))
    db.commit()
    return u


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id.desc()).all()


@router.get("/users/{uid}", response_model=schemas.UserOut)
def get_user(uid: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "用户不存在")
    return u


@router.put("/users/{uid}", response_model=schemas.UserOut)
def update_user(uid: int, body: schemas.AdminUserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "用户不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            setattr(u, k, v)
    db.add(AuditLog(actor_id=admin.id, action="update_user", target=str(uid),
                    detail=str(data)))
    db.commit()
    db.refresh(u)
    return u


# ---------- 剧本资产（含创建人 + 多维筛选） ----------
@router.get("/scripts", response_model=list[dict])
def list_scripts(db: Session = Depends(get_db), _: User = Depends(require_admin),
                 creator: str | None = Query(None),
                 platform: str | None = Query(None),
                 genre: str | None = Query(None),
                 agent_key: str | None = Query(None)):
    """剧本资产列表：含创建人、可按创建人/平台/类型/Agent 筛选。"""
    q = db.query(Script)
    if creator:
        q = q.filter(or_(Script.creator_username == creator,
                         Script.owner_id == User.id, User.username == creator)).join(User, isouter=True)
    if platform:
        q = q.filter(Script.platform == platform)
    if genre:
        q = q.filter(Script.genre == genre)
    if agent_key:
        q = q.filter(Script.agent_key == agent_key)
    rows = q.order_by(Script.id.desc()).limit(500).all()
    # 拿到所有 owner 的 username 一次查
    owner_ids = {r.owner_id for r in rows}
    user_map = {u.id: u.username for u in db.query(User).filter(User.id.in_(owner_ids)).all()} if owner_ids else {}
    return [{
        "id": r.id,
        "owner_id": r.owner_id,
        "creator_username": r.creator_username or user_map.get(r.owner_id, ""),
        "title": r.title,
        "platform": r.platform,
        "genre": r.genre,
        "episode_count": r.episode_count,
        "agent_key": r.agent_key,
        "collaborator_agent_keys": r.collaborator_agent_keys or [],
        "session_id": r.session_id,
        "status": r.status,
        "is_demo": r.is_demo,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/scripts/{sid}/content")
def script_content(sid: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    s = db.get(Script, sid)
    if not s:
        raise HTTPException(404, "不存在")
    u = db.get(User, s.owner_id)
    return {"id": s.id, "title": s.title, "owner_id": s.owner_id,
            "creator_username": s.creator_username or (u.username if u else ""),
            "agent_key": s.agent_key,
            "content": s.content_json,
            "markdown": to_markdown(s.content_json) if s.content_json else ""}


@router.get("/scripts/{sid}/download")
def download(sid: int, fmt: str = "md", db: Session = Depends(get_db),
             _: User = Depends(require_admin)):
    s = db.get(Script, sid)
    if not s or not s.content_json:
        raise HTTPException(404, "不存在")
    if fmt not in FMT_MEDIA:
        raise HTTPException(400, "不支持的格式")
    media, ext = FMT_MEDIA[fmt]
    data = {"md": to_markdown, "json": to_json, "docx": to_docx, "xlsx": to_xlsx, "pdf": to_pdf}[fmt](s.content_json)
    from urllib.parse import quote
    fname = f"{s.title}.{ext}"
    disp = f"attachment; filename=\"download.{ext}\"; filename*=UTF-8''{quote(fname)}"
    return Response(content=data, media_type=media, headers={"Content-Disposition": disp})


@router.get("/audit", response_model=list[dict])
def audit(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "actor_id": r.actor_id, "action": r.action,
            "target": r.target, "detail": r.detail, "created_at": r.created_at} for r in rows]


# ---------------- 会员体系配置 ----------------
@router.get("/membership", response_model=dict)
def get_membership(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return get_membership_config(db)


@router.put("/membership", response_model=dict)
def update_membership(body: schemas.MembershipConfigUpdate,
                      db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = db.query(MembershipConfig).filter(MembershipConfig.key == body.key).first()
    if not row:
        row = MembershipConfig(key=body.key, value=body.value)
        db.add(row)
    else:
        row.value = body.value
    db.add(AuditLog(actor_id=_.id, action="update_membership", target=body.key,
                    detail=str(body.value)))
    db.commit()
    return {"ok": True, "key": body.key, "value": row.value}


@router.post("/users/{uid}/level", response_model=schemas.UserOut)
def set_user_level(uid: int, body: schemas.UserLevelUpdate,
                  db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "用户不存在")
    if body.membership_level not in ("free", "member", "pro"):
        raise HTTPException(400, "档位只能是 free/member/pro")
    u.membership_level = body.membership_level
    db.add(AuditLog(actor_id=admin.id, action="set_level", target=str(uid),
                    detail=body.membership_level))
    db.commit()
    db.refresh(u)
    return u


@router.get("/assets", response_model=list[dict])
def list_assets(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(Asset).order_by(Asset.id.desc()).limit(200).all()
    user_map = {u.id: u.username for u in db.query(User).filter(User.id.in_({r.owner_id for r in rows})).all()} if rows else {}
    return [{"id": r.id, "owner_id": r.owner_id,
             "creator_username": user_map.get(r.owner_id, ""),
             "kind": r.kind, "url": r.url, "prompt": r.prompt, "meta": r.meta,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


# ---------------- Agent 管理（真正 CRUD） ----------------
@router.get("/agents", response_model=list[dict])
def list_agents(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(AgentConfig).order_by(AgentConfig.sort_order).all()
    return [_agent_serialize(r) for r in rows]


@router.get("/agents/{key}", response_model=dict)
def get_agent(key: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    r = db.query(AgentConfig).filter(AgentConfig.key == key).first()
    if not r:
        raise HTTPException(404, "Agent 不存在")
    return _agent_serialize(r)


@router.post("/agents", response_model=dict)
def create_agent(body: dict, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    key = body.get("key")
    if not key:
        raise HTTPException(400, "key 必填")
    if db.query(AgentConfig).filter(AgentConfig.key == key).first():
        raise HTTPException(400, "key 已存在")
    # prompt 是历史 schema 的 NOT NULL 兼容列，新建时务必赋值，避免 IntegrityError
    r = AgentConfig(key=key, prompt=body.get("prompt") or body.get("system_prompt") or "")
    _apply_agent_payload(r, body)
    db.add(r); db.commit(); db.refresh(r)
    db.add(AuditLog(actor_id=admin.id, action="create_agent", target=key))
    return _agent_serialize(r)


@router.put("/agents/{key}", response_model=dict)
def update_agent(key: str, body: dict, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    r = db.query(AgentConfig).filter(AgentConfig.key == key).first()
    if not r:
        raise HTTPException(404, "Agent 不存在")
    _apply_agent_payload(r, body)
    r.version = (r.version or 1) + 1
    db.add(AuditLog(actor_id=admin.id, action="update_agent", target=key,
                    detail=str({k: body.get(k) for k in ["name","enabled"]})))
    db.commit(); db.refresh(r)
    return _agent_serialize(r)


@router.delete("/agents/{key}")
def delete_agent(key: str, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    r = db.query(AgentConfig).filter(AgentConfig.key == key).first()
    if not r:
        raise HTTPException(404, "Agent 不存在")
    db.delete(r); db.commit()
    db.add(AuditLog(actor_id=admin.id, action="delete_agent", target=key))
    return {"ok": True}


@router.post("/agents/{key}/clone", response_model=dict)
def clone_agent(key: str, body: dict, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    src = db.query(AgentConfig).filter(AgentConfig.key == key).first()
    if not src:
        raise HTTPException(404, "源 Agent 不存在")
    new_key = body.get("new_key")
    if not new_key:
        raise HTTPException(400, "new_key 必填")
    if db.query(AgentConfig).filter(AgentConfig.key == new_key).first():
        raise HTTPException(400, "new_key 已存在")
    new = AgentConfig(key=new_key, name=body.get("name") or f"{src.name}·副本")
    for col in ("persona_name", "avatar", "description", "persona",
                "system_prompt", "prompt", "tools", "bound_model", "example_dialogue",
                "enabled", "sort_order", "params"):
        setattr(new, col, getattr(src, col))
    new.version = 1
    db.add(new); db.commit(); db.refresh(new)
    db.add(AuditLog(actor_id=admin.id, action="clone_agent", target=f"{key}->{new_key}"))
    return _agent_serialize(new)


def _agent_serialize(r: AgentConfig) -> dict:
    return {
        "key": r.key, "name": r.name, "persona_name": r.persona_name,
        "avatar": r.avatar, "description": r.description, "persona": r.persona,
        "system_prompt": r.system_prompt, "prompt": r.prompt or "",
        "tools": r.tools or [],
        "bound_model": r.bound_model, "example_dialogue": r.example_dialogue or [],
        "enabled": r.enabled, "sort_order": r.sort_order, "version": r.version,
        "params": r.params or {},
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _apply_agent_payload(r: AgentConfig, body: dict):
    for k in ("name", "persona_name", "avatar", "description", "persona",
              "system_prompt", "prompt", "tools", "bound_model", "example_dialogue",
              "enabled", "sort_order", "params"):
        if k in body and body[k] is not None:
            setattr(r, k, body[k])
    # 若只传了 system_prompt 没传 prompt，则 prompt 同步兜底
    if "system_prompt" in body and body["system_prompt"] is not None and body.get("prompt") is None:
        r.prompt = body["system_prompt"]


# ---------- Agent 头像上传（保存文件返回可访问 URL） ----------
_ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


@router.post("/agents/avatar", response_model=dict)
async def upload_agent_avatar(file: UploadFile = File(...), _: User = Depends(require_admin)):
    """上传 Agent 头像图片，保存到 static/uploads/agents/，返回 '/static/uploads/agents/xxx.ext' 形式 URL。
    前端把它写入 avatar 字段（与 emoji/外链 URL 同字段），保存即生效。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_AVATAR_EXT:
        raise HTTPException(400, f"不支持的头像格式，仅允许：{', '.join(_ALLOWED_AVATAR_EXT)}")
    if (file.size or 0) > 2 * 1024 * 1024:
        raise HTTPException(400, "头像文件过大（上限 2MB）")
    upload_root = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "agents"
    upload_root.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    dest = upload_root / name
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    dest.write_bytes(data)
    return {"url": f"/static/uploads/agents/{name}", "size": len(data)}
