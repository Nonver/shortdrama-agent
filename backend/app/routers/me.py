"""当前用户：个人中心（头像/昵称/密码/标签/习惯）。"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import User
from ..security import hash_password, verify_password
from ..deps import get_current_user

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("", response_model=schemas.UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("")
def update(body: schemas.MeUpdate, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.avatar is not None:
        user.avatar = body.avatar
    if body.tags is not None:
        user.tags = body.tags
    if body.habits is not None:
        user.habits = body.habits
    if body.new_password:
        if not verify_password(body.new_password, user.password_hash) if False else True:
            pass
        if body.old_password and not verify_password(body.old_password, user.password_hash):
            return {"ok": False, "msg": "原密码错误"}
        user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True, "msg": "已更新", "user": {
        "id": user.id, "username": user.username, "nickname": user.nickname,
        "avatar": user.avatar, "tags": user.tags, "habits": user.habits,
    }}
