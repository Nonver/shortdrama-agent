"""Agent（5 角色）配置路由：后台可配人设/提示词/参数。"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import AgentConfig, User
from ..deps import get_current_user, require_admin

router = APIRouter(prefix="/api/agent-configs", tags=["agent-configs"])


@router.get("", response_model=list[schemas.AgentConfigOut])
def list_cfg(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(AgentConfig).order_by(AgentConfig.id).all()


@router.put("/{key}", response_model=schemas.AgentConfigOut)
def update(key: str, body: schemas.AgentConfigUpdate, _: User = Depends(require_admin),
           db: Session = Depends(get_db)):
    obj = db.query(AgentConfig).filter(AgentConfig.key == key).first()
    if not obj:
        raise HTTPException(404, "角色不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj
