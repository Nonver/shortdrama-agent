"""请求/响应模型（Pydantic v2）。"""
from __future__ import annotations
from pydantic import BaseModel, EmailStr, Field
from typing import Any, Optional
from datetime import datetime


# ---------- 鉴权 ----------
class RegisterReq(BaseModel):
    username: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    phone: str = Field(pattern=r"^1\d{10}$")
    captcha_id: str
    captcha_code: str


class LoginReq(BaseModel):
    account: str  # 用户名或手机号
    password: str
    captcha_id: str
    captcha_code: str


class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class CaptchaResp(BaseModel):
    captcha_id: str
    image: str  # base64 png (data URL)


# ---------- 用户 / 画像 ----------
class UserOut(BaseModel):
    id: int
    username: str
    phone: Optional[str]
    account_type: str
    membership_level: str = "free"
    nickname: Optional[str]
    avatar: Optional[str]
    status: str
    tags: list = []
    habits: dict = {}
    created_at: Optional[datetime]


class MeUpdate(BaseModel):
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    tags: Optional[list] = None
    habits: Optional[dict] = None
    old_password: Optional[str] = None
    new_password: Optional[str] = Field(None, min_length=6, max_length=64)


# ---------- 剧本生成 ----------
class GenerateReq(BaseModel):
    prompt: str
    platform: str = "douyin"   # hongguo | douyin | kuaishou
    genre: str = "逆袭"          # 类型
    episode_count: int = Field(1, ge=1, le=50)
    agent_key: str = "director"  # 入口角色


class ScriptOut(BaseModel):
    id: int
    owner_id: int
    title: str
    platform: str
    genre: str
    episode_count: int
    status: str
    prompt: str
    created_at: Optional[datetime]


# ---------- 生图 / 生视频 ----------
class ImageGenReq(BaseModel):
    prompt: str
    platform: str = "douyin"
    genre: str = ""
    quality: str = "2K"   # 2K | 4K


class VideoGenReq(BaseModel):
    script_id: int
    prompt: str = ""      # 可选：覆盖视频提示词
    quality: str = "2K"


# ---------- 知识库 ----------
class KnowledgeItemCreate(BaseModel):
    sublib: str
    key: str
    title: str
    content: str = ""
    tags: list = []
    meta: dict = {}


class KnowledgeItemOut(BaseModel):
    id: int
    sublib: str
    key: str
    title: str
    content: str
    tags: list
    meta: dict
    visibility: Optional[str] = "internal"
    created_at: Optional[datetime]


# ---------- Agent / 模型配置 ----------
class AgentConfigOut(BaseModel):
    key: str
    name: str
    persona: str
    prompt: str
    enabled: bool
    params: dict


class AgentConfigUpdate(BaseModel):
    name: Optional[str] = None
    persona: Optional[str] = None
    prompt: Optional[str] = None
    enabled: Optional[bool] = None
    params: Optional[dict] = None


class ModelConfigUpdate(BaseModel):
    provider: Optional[str] = None
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


# ---------- 后台 ----------
class AdminUserUpdate(BaseModel):
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    status: Optional[str] = None
    membership_level: Optional[str] = None
    tags: Optional[list] = None
    habits: Optional[dict] = None


class UserLevelUpdate(BaseModel):
    membership_level: str   # free | member | pro


class AdminUserCreate(BaseModel):
    username: str
    password: str = Field(min_length=6, max_length=64)
    phone: Optional[str] = None
    nickname: Optional[str] = None
    account_type: str = "user"          # admin | user
    membership_level: str = "free"      # free | member | pro
    status: str = "active"              # active | disabled


class MembershipConfigUpdate(BaseModel):
    key: str
    value: dict


class DashboardResp(BaseModel):
    users: int
    scripts: int
    knowledge: int
    agents: int
