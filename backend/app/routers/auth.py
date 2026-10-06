"""鉴权路由：动态验证码、注册(用户端)、登录(用户端/后台分离)。"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import User
from ..security import hash_password, create_access_token, now
from ..captcha import generate_captcha, verify_captcha
from ..deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/captcha", response_model=schemas.CaptchaResp)
def captcha():
    cid, img = generate_captcha()
    return schemas.CaptchaResp(captcha_id=cid, image=img)


@router.post("/register", response_model=schemas.TokenResp)
def register(req: schemas.RegisterReq, db: Session = Depends(get_db)):
    if not verify_captcha(req.captcha_id, req.captcha_code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误 or 已失效")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名已存在")
    if db.query(User).filter(User.phone == req.phone).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "手机号已注册")
    user = User(username=req.username, phone=req.phone,
                password_hash=hash_password(req.password),
                account_type="user", nickname=req.username,
                tags=[], habits={})
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, user.account_type, membership_level=user.membership_level)
    return schemas.TokenResp(access_token=token, user=_user_out(user))


@router.post("/login", response_model=schemas.TokenResp)
def login(req: schemas.LoginReq, db: Session = Depends(get_db)):
    user = _identify(req.account, db)
    if not user or user.account_type != "user":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户账号不存在")
    if not verify_captcha(req.captcha_id, req.captcha_code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误 or 已失效")
    if not _check_pw(user, req.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "密码错误")
    user.last_login = now()
    db.commit()
    token = create_access_token(user.id, user.account_type, membership_level=user.membership_level)
    return schemas.TokenResp(access_token=token, user=_user_out(user))


@router.post("/admin/login", response_model=schemas.TokenResp)
def admin_login(req: schemas.LoginReq, db: Session = Depends(get_db)):
    user = _identify(req.account, db)
    if not user or user.account_type != "admin":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员账号不存在")
    if not verify_captcha(req.captcha_id, req.captcha_code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误 or 已失效")
    if not _check_pw(user, req.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "密码错误")
    user.last_login = now()
    db.commit()
    token = create_access_token(user.id, user.account_type, membership_level=user.membership_level)
    return schemas.TokenResp(access_token=token, user=_user_out(user))


# ---------- helpers ----------
def _identify(account: str, db: Session) -> User | None:
    return db.query(User).filter((User.username == account) | (User.phone == account)).first()


def _check_pw(user: User, password: str) -> bool:
    from ..security import verify_password
    return verify_password(password, user.password_hash)


def _user_out(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "phone": u.phone,
        "account_type": u.account_type, "membership_level": u.membership_level,
        "nickname": u.nickname,
        "avatar": u.avatar, "status": u.status, "tags": u.tags,
        "habits": u.habits,
    }
