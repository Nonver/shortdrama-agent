"""首次启动种子数据：建表、超管账号、知识库、5 角色 Agent 配置、模型配置。"""
from __future__ import annotations
from sqlalchemy import select

from .db import engine, SessionLocal, Base
from .models import User, KnowledgeItem, AgentConfig, ModelConfig
from .security import hash_password
from .config import settings
from .knowledge import seed_items

DEFAULT_AGENTS = [
    ("director", "总导演", "掌控全局的金牌导演",
     "你是国家级总导演，负责拆解用户需求、调度编剧/分镜/旁白/审核，把控整剧风格、节奏与商业性。输出工程信息与场次结构。"),
    ("writer", "编剧", "金牌编剧",
     "你是金牌编剧，负责故事、人物、冲突、台词、爽点与泪点。保证人设一致、情绪递进。"),
    ("cameraman", "分镜导演", "电影感分镜导演",
     "你是分镜导演，负责镜头语言：景别、机位、运镜、构图、路人/环境镜头、色调灯光、节奏。画面要有电影感。"),
    ("narration", "旁白心理", "情绪旁白师",
     "你负责画外音、内心独白、潜台词与情绪，让观众共情。中文细腻、有感染力。"),
    ("reviewer", "审核", "平台合规审核",
     "你负责一致性、人设漂移、平台合规与敏感词审查，给出修改建议，守住红线。"),
]

ROLES = ["director", "writer", "cameraman", "narration", "reviewer"]


def init():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        # 超管
        if not db.query(User).filter(User.username == settings.ADMIN_SEED_USERNAME).first():
            admin = User(username=settings.ADMIN_SEED_USERNAME,
                         password_hash=hash_password(settings.ADMIN_SEED_PASSWORD),
                         account_type="admin", nickname="超级管理员", status="active",
                         tags=[], habits={})
            db.add(admin)
            print(f"[seed] 已创建后台超管账号：{settings.ADMIN_SEED_USERNAME}")

        # 知识库
        existing = db.query(KnowledgeItem).count()
        if existing == 0:
            for it in seed_items():
                db.add(KnowledgeItem(**it))
            print(f"[seed] 已写入知识库 {len(seed_items())} 条")

        # Agent 配置
        for key, name, persona, prompt in DEFAULT_AGENTS:
            if not db.query(AgentConfig).filter(AgentConfig.key == key).first():
                db.add(AgentConfig(key=key, name=name, persona=persona, prompt=prompt,
                                   enabled=True, params={}))

        # 模型配置（兜底，不启用云端）
        for i, role in enumerate(ROLES):
            if not db.query(ModelConfig).filter(ModelConfig.role == role).first():
                db.add(ModelConfig(role=role, provider="fallback", model_name="local-fallback",
                                   priority=i, enabled=False))

        db.commit()
        print("[seed] 完成：Agent 配置与模型配置已就绪")
    finally:
        db.close()


if __name__ == "__main__":
    init()
