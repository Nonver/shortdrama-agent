"""认证与权限依赖。"""
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, MembershipConfig
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)

# 会员等级排序（数值越大权限越高）
LEVEL_ORDER = {"free": 0, "member": 1, "pro": 2}

# 功能 → 默认最低开放档位（后台可覆盖）
DEFAULT_FEATURE_MIN = {
    "script_generate": "free",   # 登录即可（免费档也能生成，可设日限额）
    "script_download": "member", # 下载/导出需会员
    "image_generate": "member",  # 生图需会员
    "image_quality_4k": "pro",   # 4K 需会员Pro
    "video_generate": "pro",     # 文生视频需会员Pro
}

# 默认后台配置（首次启动写入，之后以后台为准）
DEFAULT_MEMBERSHIP_CONFIG = {
    "plans": [
        {"level": "free", "name": "免费用户", "can_script": True, "can_download": False,
         "can_image": False, "can_video": False},
        {"level": "member", "name": "会员", "can_script": True, "can_download": True,
         "can_image": True, "can_video": False},
        {"level": "pro", "name": "会员Pro", "can_script": True, "can_download": True,
         "can_image": True, "can_video": True},
    ],
    "free_script_quota": 5,
    "member_script_quota": 0,
    "pro_script_quota": 0,
    "image_4k_enabled": False,
    "quality_default": "2K",
    "watermark_implicit": True,
    "watermark_badge": True,
    "badge_text": "AI 生成",
    "feature_min_level": DEFAULT_FEATURE_MIN,
}


def level_ge(a: str, b: str) -> bool:
    return LEVEL_ORDER.get(a, 0) >= LEVEL_ORDER.get(b, 0)


def get_membership_config(db: Session) -> dict:
    """读取全部会员配置，合并默认值（缺字段自动补全）。"""
    cfg: dict = dict(DEFAULT_MEMBERSHIP_CONFIG)
    rows = db.query(MembershipConfig).all()
    for r in rows:
        cfg[r.key] = r.value
    # 确保关键字段存在
    cfg.setdefault("feature_min_level", dict(DEFAULT_FEATURE_MIN))
    cfg.setdefault("free_script_quota", 5)
    for k, v in DEFAULT_MEMBERSHIP_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if not creds or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = decode_access_token(creds.credentials)
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效令牌")
    user = db.get(User, uid)
    if not user or user.status == "disabled":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不可用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.account_type != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def _reset_quota_if_new_day(user: User, db: Session):
    today = datetime.now(timezone.utc).date()
    if user.quota_date is None or user.quota_date.date() != today:
        user.script_used_today = 0
        user.quota_date = datetime.now(timezone.utc)


def require_feature(feature_key: str):
    """权限依赖：按 feature_min_level 校验当前用户档位；生成类额外做每日配额。"""
    def dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        cfg = get_membership_config(db)
        min_level = (cfg.get("feature_min_level") or {}).get(feature_key,
                                                          DEFAULT_FEATURE_MIN.get(feature_key, "member"))
        if not level_ge(user.membership_level, min_level):
            names = {"free": "免费", "member": "会员", "pro": "会员Pro"}
            need = names.get(min_level, min_level)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"该功能需「{need}」及以上会员")
        if feature_key == "script_generate":
            _reset_quota_if_new_day(user, db)
            quota = 0
            if user.membership_level == "free":
                quota = cfg.get("free_script_quota", 5)
            elif user.membership_level == "member":
                quota = cfg.get("member_script_quota", 0)
            elif user.membership_level == "pro":
                quota = cfg.get("pro_script_quota", 0)
            if quota and user.script_used_today >= quota:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                    f"今日免费生成额度已用尽（{quota} 部），升级会员解锁不限量")
            user.script_used_today += 1
            db.commit()
        return user
    return dep
