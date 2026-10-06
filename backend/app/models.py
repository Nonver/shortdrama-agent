"""ORM 模型：双账号、剧本、知识库、Agent/模型配置、对话会话、操作日志。"""
from __future__ import annotations
from datetime import datetime

from sqlalchemy import String, Integer, Boolean, Text, DateTime, JSON, ForeignKey, BLOB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .security import now


# 会员等级排序（数值越大权限越高）
MEMBERSHIP_LEVELS = ["free", "member", "pro"]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(16), default="user")  # admin | user
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 头像路径/URL
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | disabled
    # 会员等级：free(免费) / member(会员) / pro(会员Pro)
    membership_level: Mapped[str] = mapped_column(String(16), default="free", index=True)
    # 每日生成配额计数（免费档防滥用）
    script_used_today: Mapped[int] = mapped_column(Integer, default=0)
    quota_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 用户画像（图像/标签/习惯）—— 后台可编辑，Agent 自动个性化
    tags: Mapped[list] = mapped_column(JSON, default=list)        # 创作偏好标签
    habits: Mapped[dict] = mapped_column(JSON, default=dict)      # 习惯（时长/集数/钩子偏好等）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Script(Base):
    __tablename__ = "scripts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # 生成账号
    creator_username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 冗余便于列表显示
    title: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(32), default="douyin")
    genre: Mapped[str] = mapped_column(String(64), default="")
    episode_count: Mapped[int] = mapped_column(Integer, default=1)
    prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | done
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)  # 结构化剧本
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)   # 系统预置示例剧本
    # 关联的 Agent 与协作信息
    agent_key: Mapped[str] = mapped_column(String(32), default="director")
    collaborator_agent_keys: Mapped[list] = mapped_column(JSON, default=list)  # 协作过的 Agent
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 来自哪个聊天会话
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 优化来源：基于哪条剧本做的修订
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Conversation(Base):
    """对话会话——实现"防失忆"：结构化状态落库，回来接着聊。

    注：本表既用于通用 chat session 也用于脚本创作会话；
    `agent_key` 记录该会话归属哪个 Agent。"""
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    agent_key: Mapped[str] = mapped_column(String(32), default="director", index=True)  # 归属 Agent
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 消息：[{role:'user'|'agent'|'system', agent_key, content, tool_calls, mentions, ts}]
    messages: Mapped[list] = mapped_column(JSON, default=list)
    # 结构化记忆快照（用户需求摘要、知识库引用、生成的剧本 id 等）
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # 跨 Agent 共享上下文摘要
    cross_agent_summary: Mapped[str] = mapped_column(Text, default="")
    # 是否锁定（生成中）防止重复发送
    is_streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class KnowledgeItem(Base):
    """知识库 4 子库：platform / genre / style / asset。

    `platform` 用于二级导航分组：hongguo/douyin/kuaishou/general（跨平台通用）。
    """
    __tablename__ = "knowledge_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sublib: Mapped[str] = mapped_column(String(16), index=True)  # platform|genre|style|asset
    platform: Mapped[str] = mapped_column(String(16), default="general", index=True)  # 二级导航分组
    key: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # 二级导航内排序
    # 可见性：internal（后台运营机密，仅 admin 可见）/ public（可对外公开给用户端）
    visibility: Mapped[str] = mapped_column(String(16), default="internal", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AgentConfig(Base):
    """5 个角色 Agent 的后台可配置人设/提示词/工具/绑定模型。

    这是真正被生成器读取的『Agent 配置文件』，不是占位。
    """
    __tablename__ = "agent_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # director|writer|cameraman|narration|reviewer
    name: Mapped[str] = mapped_column(String(64))                # 中文名"总导演/编剧/..."
    persona_name: Mapped[str] = mapped_column(String(64), default="")  # "国家级总导演/金牌编剧/..."
    avatar: Mapped[str] = mapped_column(String(512), default="🎬")  # emoji 或 URL（/static/uploads/... 或 http）
    description: Mapped[str] = mapped_column(String(255), default="")  # 一句话简介
    persona: Mapped[str] = mapped_column(Text, default="")       # 人设描述
    system_prompt: Mapped[str] = mapped_column(Text, default="")  # 真正的差异化系统提示词
    # 兼容字段：历史 schema 中存在 NOT NULL 的 prompt 列，统一以 system_prompt 兜底，避免新建 Agent 时报 NOT NULL。
    prompt: Mapped[str] = mapped_column(Text, default="")  # 兼容旧表结构（始终 = system_prompt）
    # 可用工具列表：['image_generate','video_generate','tts','script_generate','script_download']
    tools: Mapped[list] = mapped_column(JSON, default=list)
    # 绑定的模型配置 key（对应 ModelConfig.model_name）
    bound_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 示例对话 JSON：[{role, content}, ...]
    example_dialogue: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 排序与版本
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ModelConfig(Base):
    """模型配置（含 API Key）—— 后台可编辑。"""
    __tablename__ = "model_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 一级分组：ark_chat | ark_image | ark_video | tts | embedding | fallback
    group_label: Mapped[str] = mapped_column(String(32), default="fallback", index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)  # 对应 Agent/用途
    provider: Mapped[str] = mapped_column(String(32), default="fallback")
    model_name: Mapped[str] = mapped_column(String(64), default="local-fallback")
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rate_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0=不限
    description: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class MembershipConfig(Base):
    """会员配置（后台可改）：以 key-value(JSON) 存储，避免频繁改表。"""
    __tablename__ = "membership_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Asset(Base):
    """用户生成的图片/视频/音频产物，便于『我的』画廊与权限校验。"""
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # image | video | audio
    url: Mapped[str] = mapped_column(String(512))
    prompt: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KbChunk(Base):
    """知识库向量分块（RAG 语义检索的数据源之一）。

    每条 KnowledgeItem（4 子库：platform/genre/style/asset/guide）切 1~N 块，
    每块带 embedding 向量 + 元数据（platform/sublib 用于硬过滤）。
    """
    __tablename__ = "kb_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), default="kb")  # kb | script
    ref_id: Mapped[int] = mapped_column(Integer, index=True)  # knowledge_items.id 或 scripts.id
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)  # 同一来源的第几块
    sublib: Mapped[str] = mapped_column(String(16), default="", index=True)
    platform: Mapped[str] = mapped_column(String(16), default="general", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[bytes] = mapped_column(BLOB, nullable=True)  # float32 向量序列化
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ScriptChunk(Base):
    """剧本向量分块（RAG 语义检索的数据源之二）。

    用户剧本按 集→场→镜头 三层切，每块独立索引，附 metadata（platform/genre/episode/scene）。
    隐私：owner_id + session_id 必查，绝不能与公开 KB 混库。
    """
    __tablename__ = "script_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), default="script")
    script_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    platform: Mapped[str] = mapped_column(String(32), default="", index=True)
    genre: Mapped[str] = mapped_column(String(64), default="", index=True)
    episode: Mapped[int] = mapped_column(Integer, default=0)
    scene: Mapped[int] = mapped_column(Integer, default=0)
    is_gold: Mapped[bool] = mapped_column(Boolean, default=False)  # 高分剧本标记
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[bytes] = mapped_column(BLOB, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Feedback(Base):
    """用户对 Agent 回答的反馈（点赞/点踩 + 备注），用于 RAG/意图质量监控与迭代。"""
    __tablename__ = "feedbacks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    agent_key: Mapped[str] = mapped_column(String(32), default="", index=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)  # 1=赞, -1=踩
    note: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
