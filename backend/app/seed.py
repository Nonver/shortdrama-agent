"""首次启动种子数据：建表、超管账号、知识库、5 角色 Agent 配置、模型配置、示例剧本。"""
from __future__ import annotations

from .db import engine, SessionLocal, Base
from .models import User, KnowledgeItem, AgentConfig, ModelConfig, Script, MembershipConfig, Asset
from .security import hash_password
from .config import settings
from .deps import DEFAULT_MEMBERSHIP_CONFIG
from .knowledge import seed_items, retrieve_kb
from .generator import build_script

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


def _default_agent_payload(key: str, name: str, persona: str, prompt: str, sort_order: int) -> dict:
    """返回 5 个 Agent 的真正可配置字段（不只是 persona/prompt 两条）。"""
    persona_name_map = {
        "director": "国家级总导演", "writer": "金牌编剧", "cameraman": "电影感分镜导演",
        "narration": "情绪旁白师", "reviewer": "平台合规审核",
    }
    avatar_map = {
        "director": "🎬", "writer": "📝", "cameraman": "🎥",
        "narration": "🎙️", "reviewer": "✅",
    }
    desc_map = {
        "director": "一句话成剧 · 全局总控",
        "writer": "故事 · 台词 · 爽点",
        "cameraman": "运镜 · 镜头 · 路人",
        "narration": "情绪 · 旁白 · 独白",
        "reviewer": "合规 · 质检 · 红线",
    }
    # 真正差异化的 system_prompt（5 个 Agent 各有专长，不是糊一个通用 prompt）
    sys_prompts = {
        "director": (
            "你是一位『国家级短剧总导演』。职责：\n"
            "1) 拆解用户一句话需求为【工程信息 + 场次结构 + 主线】；\n"
            "2) 总控全局风格、节奏与商业性，决定平台/类型/集数/钩子密度；\n"
            "3) 调度编剧/分镜/旁白/审核协同，明确分工；\n"
            "4) 输出严格只给 JSON 结构（详见后续规范）。"
        ),
        "writer": (
            "你是一位『金牌短剧编剧』。职责：\n"
            "1) 专注故事、人物、冲突、台词、爽点、泪点；\n"
            "2) 保证人设一致、情绪递进、台词上头；\n"
            "3) 注重【钩子密度】：每 10~15 秒一个小冲突、每 30 秒一个反转；\n"
            "4) 必要时主动召唤『分镜导演』补镜头描述，或召唤『旁白心理』强化 OS。"
        ),
        "cameraman": (
            "你是一位『电影感分镜导演』。职责：\n"
            "1) 把每个镜头语言填满：景别 / 机位角度 / 运镜 / 构图 / 镜头标记（人物或路人）；\n"
            "2) 调度路人环境镜头反衬人物情绪；\n"
            "3) 决定色调 / 灯光 / BGM / 音效 / 花字；\n"
            "4) 输出严格只给 JSON，必要时召唤『编剧』补全人物动机后再填镜头。"
        ),
        "narration": (
            "你是一位『情绪旁白师』。职责：\n"
            "1) 负责画外音 (OS)、内心独白 (VO)、潜台词、心理活动、微表情/肢体；\n"
            "2) 让观众共情，每集 1~2 处关键心理揭示；\n"
            "3) 不抢戏，与画面/节奏匹配；\n"
            "4) 可召唤『编剧』核对人物动机后再写心理。"
        ),
        "reviewer": (
            "你是一位『平台合规审核』。职责：\n"
            "1) 审查一致性、人设漂移、平台合规、敏感词；\n"
            "2) 给出明确修改建议，守住红线；\n"
            "3) 输出严格 JSON；\n"
            "4) 可召唤『编剧』返工被驳回的桥段。"
        ),
    }
    # 各 Agent 默认可用工具
    tools_map = {
        "director": ["script_generate", "script_download", "image_generate"],
        "writer":   ["script_generate", "script_download", "image_generate"],
        "cameraman":["script_generate", "image_generate", "video_generate"],
        "narration":["script_generate", "tts"],
        "reviewer": ["script_generate"],
    }
    # 示例对话（前端展示给用户看这个 Agent 怎么用）
    example_map = {
        "director": [
            {"role": "user", "content": "帮我做一个『被辞退的外卖员逆袭成首富』的 3 集剧本，抖音平台，节奏要快。"},
            {"role": "agent", "content": "已拆解：3 集 / 抖音 / 类型=逆袭 / 单集 90 秒 / 钩子密度 = 高。准备调度『编剧』起骨架，要现在开干吗？"},
        ],
        "writer": [
            {"role": "user", "content": "第一集开头 3 秒要炸，给个钩子？"},
            {"role": "agent", "content": "可参考爆款《我在 80 后妈》—— 现代女主睁眼穿越成 80 年代『后妈』，身份反差瞬间锁定。建议你这场用『外卖员在年会门口被当众羞辱』，前 3 秒镜头定格主角平静却暗藏锋芒的眼神。"},
        ],
        "cameraman": [
            {"role": "user", "content": "这场冲突戏怎么拍？"},
            {"role": "agent", "content": "建议：镜 1 中景·固定·会议室内反派把辞退信扔桌上；镜 2 特写·慢推·信封压在主角手指；镜 3 近景·平角·主角抬眼不接；镜 4 大特写·顶光·嘴角冷勾(暖光切入)；色调：压抑冷蓝→暖橙爆发。"},
        ],
        "narration": [
            {"role": "user", "content": "主角被辞退那一刻要写心理。"},
            {"role": "agent", "content": "OS 旁白：『三年，三年啊……今天，把压在心底的话，全说出来。』配合大特写 + 冷调侧光 + 心跳音效。"},
        ],
        "reviewer": [
            {"role": "user", "content": "这段会不会过不了审？"},
            {"role": "agent", "content": "提示：『当众羞辱』桥段需弱化体貌描写，避免美化暴力；建议改为冷嘲+工作能力质疑，更安全。"},
        ],
    }
    return {
        "name": name,
        "persona_name": persona_name_map.get(key, name),
        "avatar": avatar_map.get(key, "🎬"),
        "description": desc_map.get(key, ""),
        "persona": persona,
        "system_prompt": sys_prompts.get(key, prompt),
        "tools": tools_map.get(key, []),
        "bound_model": None,
        "example_dialogue": example_map.get(key, []),
        "enabled": True,
        "sort_order": sort_order,
        "version": 1,
        "params": {},
    }


def _default_models() -> list[dict]:
    """模型配置种子：覆盖方舟对话/生图/生视频 + 豆包语音。"""
    return [
        {"group_label": "ark_chat",   "role": "director", "provider": "volcengine",
         "model_name": "doubao-seed-2-1-pro-260628",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 60,
         "description": "方舟 · 总导演主力对话模型"},
        {"group_label": "ark_chat",   "role": "writer", "provider": "volcengine",
         "model_name": "doubao-seed-2-1-pro-260628",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 60,
         "description": "方舟 · 编剧对话模型"},
        {"group_label": "ark_chat",   "role": "cameraman", "provider": "volcengine",
         "model_name": "doubao-seed-2-1-pro-260628",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 60,
         "description": "方舟 · 分镜导演对话模型"},
        {"group_label": "ark_chat",   "role": "narration", "provider": "volcengine",
         "model_name": "doubao-seed-2-1-pro-260628",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 60,
         "description": "方舟 · 旁白心理对话模型"},
        {"group_label": "ark_chat",   "role": "reviewer", "provider": "volcengine",
         "model_name": "doubao-seed-2-1-pro-260628",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 60,
         "description": "方舟 · 合规审核对话模型"},
        {"group_label": "ark_image",  "role": "default", "provider": "volcengine",
         "model_name": "doubao-seedream-4-0-250828",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 30,
         "description": "方舟 · Seedream 4.0 文生图（2K/4K）"},
        {"group_label": "ark_video",  "role": "default", "provider": "volcengine",
         "model_name": "doubao-seedance-1-0-pro-fast-251015",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 10,
         "description": "方舟 · Seedance 1.0 pro-fast 文生视频"},
        {"group_label": "tts",        "role": "default", "provider": "volcengine_tts",
         "model_name": "volcano_tts",
         "base_url": "https://openspeech.bytedance.com/api/v1/tts",
         "api_key": "", "enabled": False, "rate_limit": 60,
         "description": "豆包语音 · 服务端合成（多角色配音）"},
        {"group_label": "embedding",  "role": "default", "provider": "volcengine",
         "model_name": "doubao-embedding-vision-2",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "api_key": "", "enabled": False, "rate_limit": 30,
         "description": "方舟 · 视觉向量（占位，当前用关键词检索）"},
        {"group_label": "fallback",   "role": "default", "provider": "local",
         "model_name": "rule-based-fallback",
         "base_url": "",
         "api_key": "", "enabled": True, "rate_limit": 0,
         "description": "本地规则兜底生成器（永远可用，断网也能出片）"},
    ]


def _sync_model_keys_from_env(db) -> None:
    """幂等：仅当 ModelConfig.api_key 为空时，从 .env(settings) 注入方舟/豆包 key 并启用。
    不覆盖管理员在后台已手动配置的 key；已配置则跳过。避免重建数据库后密钥丢失。"""
    ark_groups = {"ark_chat", "ark_image", "ark_video", "embedding"}
    ark_key = settings.ARK_API_KEY
    tts_key = settings.VOLC_TTS_API_KEY
    changed = 0
    for m in db.query(ModelConfig).all():
        if m.group_label in ark_groups and ark_key and not m.api_key:
            m.api_key = ark_key
            m.enabled = True
            changed += 1
        elif m.group_label == "tts" and tts_key and not m.api_key:
            m.api_key = tts_key
            m.enabled = True
            changed += 1
    if changed:
        db.commit()
        print(f"[seed] 已从 .env 注入 {changed} 个模型密钥（方舟 / 豆包语音）")


def init():
    Base.metadata.create_all(engine)
    # 旧库兼容：补充缺失列（SQLite 不支持 create_all 自动加列）
    import sqlalchemy
    with engine.connect() as conn:
        # scripts.is_demo / creator / agent
        scols = [r[1] for r in conn.execute(sqlalchemy.text(
            "PRAGMA table_info(scripts)")).fetchall()]
        scripts_alters = [
            ("is_demo", "BOOLEAN NOT NULL DEFAULT 0"),
            ("creator_username", "VARCHAR(64)"),
            ("agent_key", "VARCHAR(32) NOT NULL DEFAULT 'director'"),
            ("collaborator_agent_keys", "JSON"),
            ("session_id", "INTEGER"),
        ]
        for col, ddl in scripts_alters:
            if col not in scols:
                conn.execute(sqlalchemy.text(f"ALTER TABLE scripts ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"[seed] 已为 scripts 表补充 {col} 列")

        # users 新会员字段
        ucols = [r[1] for r in conn.execute(sqlalchemy.text(
            "PRAGMA table_info(users)")).fetchall()]
        alters = [
            ("membership_level", "VARCHAR(16) NOT NULL DEFAULT 'free'"),
            ("script_used_today", "INTEGER NOT NULL DEFAULT 0"),
            ("quota_date", "DATETIME"),
        ]
        for col, ddl in alters:
            if col not in ucols:
                conn.execute(sqlalchemy.text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"[seed] 已为 users 表补充 {col} 列")

        # agent_configs 新增字段（后台可配 Agent 真正生效的关键）
        acols = [r[1] for r in conn.execute(sqlalchemy.text(
            "PRAGMA table_info(agent_configs)")).fetchall()]
        agent_alters = [
            ("persona_name", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("avatar", "VARCHAR(32) NOT NULL DEFAULT '🎬'"),
            ("description", "VARCHAR(255) NOT NULL DEFAULT ''"),
            ("system_prompt", "TEXT NOT NULL DEFAULT ''"),
            ("tools", "JSON"),
            ("bound_model", "VARCHAR(64)"),
            ("example_dialogue", "JSON"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
            ("version", "INTEGER NOT NULL DEFAULT 1"),
        ]
        for col, ddl in agent_alters:
            if col not in acols:
                conn.execute(sqlalchemy.text(f"ALTER TABLE agent_configs ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"[seed] 已为 agent_configs 表补充 {col} 列")

        # model_configs 新增字段
        mcols = [r[1] for r in conn.execute(sqlalchemy.text(
            "PRAGMA table_info(model_configs)")).fetchall()]
        model_alters = [
            ("group_label", "VARCHAR(32) NOT NULL DEFAULT 'fallback'"),
            ("rate_limit", "INTEGER NOT NULL DEFAULT 0"),
            ("description", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ]
        for col, ddl in model_alters:
            if col not in mcols:
                conn.execute(sqlalchemy.text(f"ALTER TABLE model_configs ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"[seed] 已为 model_configs 表补充 {col} 列")

        # knowledge_items 新增 platform / sort_order
        kcols = [r[1] for r in conn.execute(sqlalchemy.text(
            "PRAGMA table_info(knowledge_items)")).fetchall()]
        kb_alters = [
            ("platform", "VARCHAR(16) NOT NULL DEFAULT 'general'"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
            ("visibility", "VARCHAR(16) NOT NULL DEFAULT 'internal'"),
            ("updated_at", "DATETIME"),
        ]
        for col, ddl in kb_alters:
            if col not in kcols:
                conn.execute(sqlalchemy.text(f"ALTER TABLE knowledge_items ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"[seed] 已为 knowledge_items 表补充 {col} 列")

        # conversations 新增字段
        ccols = [r[1] for r in conn.execute(sqlalchemy.text(
            "PRAGMA table_info(conversations)")).fetchall()]
        conv_alters = [
            ("cross_agent_summary", "TEXT NOT NULL DEFAULT ''"),
            ("is_streaming", "BOOLEAN NOT NULL DEFAULT 0"),
            ("created_at", "DATETIME"),
        ]
        for col, ddl in conv_alters:
            if col not in ccols:
                conn.execute(sqlalchemy.text(f"ALTER TABLE conversations ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"[seed] 已为 conversations 表补充 {col} 列")

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == settings.ADMIN_SEED_USERNAME).first():
            admin = User(username=settings.ADMIN_SEED_USERNAME,
                         password_hash=hash_password(settings.ADMIN_SEED_PASSWORD),
                         account_type="admin", nickname="超级管理员", status="active",
                         membership_level="free", tags=[], habits={})
            db.add(admin)
            print(f"[seed] 已创建后台超管账号：{settings.ADMIN_SEED_USERNAME}")

        # 会员配置（后台可改）
        if db.query(MembershipConfig).count() == 0:
            for k, v in DEFAULT_MEMBERSHIP_CONFIG.items():
                db.add(MembershipConfig(key=k, value=v))
            db.commit()
            print(f"[seed] 已写入会员配置 {len(DEFAULT_MEMBERSHIP_CONFIG)} 项")

        # 演示「会员Pro」账号（便于体验全功能）
        # 注意：手机号唯一，且旧库可能残留测试账号占用同号，故先查 phone 再决定号码
        if not db.query(User).filter(User.username == "prodemo").first():
            demo_phone = "13900000001"
            # 若目标手机号已被占用，自动顺延避免 UNIQUE 冲突
            if db.query(User).filter(User.phone == demo_phone).first():
                demo_phone = "13900000002"
                while db.query(User).filter(User.phone == demo_phone).first():
                    demo_phone = str(int(demo_phone) + 1)
            db.add(User(username="prodemo", phone=demo_phone,
                       password_hash=hash_password(settings.DEMO_PRO_PASSWORD),
                       account_type="user", nickname="会员Pro演示",
                       membership_level="pro", status="active", tags=[], habits={}))
            db.commit()
            print(f"[seed] 已创建会员Pro演示账号：prodemo (phone={demo_phone})")

        items = seed_items()
        synced = 0
        for it in items:
            s = it.get("sublib")
            k = it.get("key")
            if not s or not k:
                continue
            row = db.query(KnowledgeItem).filter(
                KnowledgeItem.sublib == s,
                KnowledgeItem.key == k).first()
            if not row:
                db.add(KnowledgeItem(**it))
                synced += 1
            else:
                # 已存在则同步内容/平台/排序（幂等升级，不重复插入）
                row.platform = it.get("platform", row.platform)
                row.title = it.get("title", row.title)
                row.content = it.get("content", row.content)
                row.tags = it.get("tags", row.tags)
                row.meta = it.get("meta", row.meta)
                row.sort_order = it.get("sort_order", row.sort_order)
                synced += 1
        db.commit()
        print(f"[seed] 知识库已同步 {synced} 条（新增/更新）")

        # 5 Agent 配置（真正可配：人设名/头像/描述/人设/system_prompt/工具/绑定模型/示例对话）
        for i, (key, name, persona, prompt) in enumerate(DEFAULT_AGENTS):
            row = db.query(AgentConfig).filter(AgentConfig.key == key).first()
            cfg = _default_agent_payload(key, name, persona, prompt, i)
            if not row:
                db.add(AgentConfig(key=key, **cfg))
            else:
                # 升级路径：旧 Agent 缺新字段则补全
                for k, v in cfg.items():
                    if not getattr(row, k, None):
                        setattr(row, k, v)
                row.version = (row.version or 0) + 1

        # 模型配置（带 group_label + description）
        default_models = _default_models()
        for i, m in enumerate(default_models):
            row = db.query(ModelConfig).filter(
                ModelConfig.group_label == m["group_label"],
                ModelConfig.model_name == m["model_name"]).first()
            if not row:
                db.add(ModelConfig(**m, priority=i))
            else:
                for k, v in m.items():
                    if not getattr(row, k, None):
                        setattr(row, k, v)

        db.commit()
        print("[seed] 完成：Agent 配置与模型配置已就绪")
        _sync_model_keys_from_env(db)

        # 预生成示例剧本（知识库驱动），让产品开箱即满、便于演示
        if db.query(Script).filter(Script.is_demo.is_(True)).count() == 0:
            admin = db.query(User).filter_by(username=settings.ADMIN_SEED_USERNAME).first()
            demos = [
                ("被羞辱的实习生，竟是隐世厨神", "douyin", "逆袭"),
                ("闪婚老公的隐藏小娇妻", "hongguo", "甜宠"),
                ("监控里消失的第三秒", "kuaishou", "悬疑"),
            ]
            for title, platform, genre in demos:
                kbdb = retrieve_kb(db, platform, genre)
                s = build_script(title, platform, genre, 2, "director",
                                 {"tags": [], "habits": {}}, kbdb=kbdb)
                db.add(Script(owner_id=admin.id, creator_username=admin.username,
                              title=s["project"]["项目名"],
                              platform=platform, genre=genre, episode_count=2,
                              prompt=title, status="done", content_json=s, is_demo=True,
                              agent_key="director"))
            db.commit()
            print(f"[seed] 已预生成 {len(demos)} 部示例剧本（知识库驱动）")
    finally:
        db.close()


if __name__ == "__main__":
    init()
