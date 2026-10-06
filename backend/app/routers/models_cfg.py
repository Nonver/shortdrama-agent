"""模型配置路由（带 API Key + 二级导航）。"""
from __future__ import annotations
import time
import urllib.request
import urllib.error
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import ModelConfig, User
from ..deps import get_current_user, require_admin

router = APIRouter(prefix="/api/model-configs", tags=["model-configs"])


# 一级分组定义（与 seed 一致）
MODEL_GROUPS = [
    {"key": "ark_chat",   "name": "方舟对话模型",   "icon": "💬"},
    {"key": "ark_image",  "name": "方舟文生图",     "icon": "🖼️"},
    {"key": "ark_video",  "name": "方舟文生视频",   "icon": "🎬"},
    {"key": "tts",        "name": "豆包语音(TTS)",  "icon": "🎙️"},
    {"key": "embedding",  "name": "向量 Embedding", "icon": "🔢"},
    {"key": "fallback",   "name": "本地兜底",       "icon": "🛟"},
]


@router.get("/groups", response_model=list[dict])
def list_groups(_: User = Depends(get_current_user)):
    return MODEL_GROUPS


@router.get("/by-group", response_model=list[dict])
def list_by_group(group: str, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    rows = db.query(ModelConfig).filter(
        ModelConfig.group_label == group).order_by(ModelConfig.priority).all()
    return [_serialize(r, mask_key=False) for r in rows]


@router.get("", response_model=list[dict])
def list_cfg(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(ModelConfig).order_by(ModelConfig.priority).all()
    return [_serialize(r, mask_key=True) for r in rows]


def _serialize(r: ModelConfig, mask_key: bool = True):
    """序列化：默认脱敏 api_key（仅管理员视图可见明文）。"""
    api_key = r.api_key or ""
    if mask_key and api_key:
        api_key = api_key[:6] + "***" + api_key[-4:] if len(api_key) > 12 else "***"
    return {
        "id": r.id, "group_label": r.group_label, "role": r.role,
        "provider": r.provider, "model_name": r.model_name,
        "base_url": r.base_url, "api_key": api_key,
        "api_key_set": bool(r.api_key),
        "priority": r.priority, "enabled": r.enabled,
        "rate_limit": r.rate_limit or 0, "description": r.description or "",
    }


@router.get("/{mid}", response_model=dict)
def get_one(mid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    r = db.get(ModelConfig, mid)
    if not r:
        raise HTTPException(404, "配置不存在")
    return _serialize(r, mask_key=False)


@router.put("/{mid}", response_model=dict)
def update(mid: int, body: schemas.ModelConfigUpdate, _: User = Depends(require_admin),
           db: Session = Depends(get_db)):
    obj = db.get(ModelConfig, mid)
    if not obj:
        raise HTTPException(404, "配置不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return _serialize(obj, mask_key=False)


@router.post("", response_model=dict)
def create(body: dict, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    group = body.get("group_label")
    if not group:
        raise HTTPException(400, "group_label 必填")
    model_name = (body.get("model_name") or "new-model").strip() or "new-model"
    obj = ModelConfig(
        group_label=group,
        role=body.get("role") or group,
        provider=body.get("provider") or "custom",
        model_name=model_name,
        base_url=body.get("base_url") or None,
        api_key=body.get("api_key") or None,
        priority=int(body.get("priority", 0) or 0),
        enabled=bool(body.get("enabled", False)),
        description=body.get("description") or "",
    )
    db.add(obj); db.commit(); db.refresh(obj)
    return _serialize(obj, mask_key=False)


@router.post("/{mid}/toggle", response_model=dict)
def toggle(mid: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    obj = db.get(ModelConfig, mid)
    if not obj:
        raise HTTPException(404, "配置不存在")
    obj.enabled = not obj.enabled
    db.commit()
    return {"id": obj.id, "enabled": obj.enabled}


@router.post("/{mid}/probe", response_model=dict)
def probe(mid: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """连通性自检：fallback 直接 OK；其余按 base_url 做一次轻量 HTTP 探测（5s 超时）。
    返回：{ok, latency_ms, status_code, reason}"""
    obj = db.get(ModelConfig, mid)
    if not obj:
        raise HTTPException(404, "配置不存在")
    # fallback（本地兜底）：不需要网络
    if obj.group_label == "fallback" or (obj.provider or "").lower() == "self":
        return {"ok": True, "latency_ms": 0, "status_code": 200, "reason": "本地兜底，无需网络", "model_name": obj.model_name}
    # 没配 key
    if not obj.api_key:
        return {"ok": False, "latency_ms": 0, "status_code": 0, "reason": "未配置 API Key", "model_name": obj.model_name}
    # 没配 base_url：跳过网络探测，只做格式校验
    if not obj.base_url:
        return {"ok": False, "latency_ms": 0, "status_code": 0, "reason": "未配置 base_url，无法自检", "model_name": obj.model_name}
    # 网络探测（HEAD -> 失败再 GET，5s 超时）
    url = obj.base_url.rstrip("/")
    t0 = time.time()
    try:
        sc = _http_probe(url, obj.api_key, timeout=5)
        latency = int((time.time() - t0) * 1000)
        ok = sc < 500
        reason = "网络可达" if ok else f"服务端错误 {sc}"
        return {"ok": ok, "latency_ms": latency, "status_code": sc, "reason": reason, "model_name": obj.model_name}
    except TimeoutError:
        return {"ok": False, "latency_ms": 5000, "status_code": 0, "reason": "连接超时（5s）", "model_name": obj.model_name}
    except urllib.error.URLError as e:
        return {"ok": False, "latency_ms": int((time.time() - t0) * 1000), "status_code": 0,
                "reason": "网络不可达：" + (str(getattr(e, "reason", None) or e)[:120]), "model_name": obj.model_name}
    except Exception as e:
        return {"ok": False, "latency_ms": 0, "status_code": 0, "reason": "自检异常：" + str(e)[:120], "model_name": obj.model_name}


def _http_probe(url: str, api_key: str, timeout: int = 5) -> int:
    """轻量探测，返回 HTTP 状态码（HEAD 不支持则返回 GET 的）。"""
    headers = {"Authorization": "Bearer " + api_key}
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            sc = resp.status
    except urllib.error.HTTPError as e:
        sc = e.code
    # 某些网关不接 HEAD，改用 GET
    if sc in (405, 501):
        req2 = urllib.request.Request(url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                sc = resp2.status
        except urllib.error.HTTPError as e2:
            sc = e2.code
    return sc
