"""兜底剧本生成器（不依赖付费大模型）。
用『平台规则 + 类型套路 + 用户画像』三维约束，规则/模板驱动产出
含 7 大类专业字段、分镜、旁白、心理活动的完整短剧剧本。
预留 LLM 适配器：real_generate() 接口留空，填好 ModelConfig 后即可替换。"""
from __future__ import annotations
import re
import random
from typing import Any, Callable, Iterator

from .knowledge import retrieve

# ---------- 素材池（兜底用，保证产出像样） ----------
SURNAMES = ["陆", "顾", "沈", "霍", "厉", "苏", "薄", "江", "傅", "夜"]
GIVEN = ["霆", "渊", "枭", "辰", "衍", "妄", "洲", "野", "寒", "舟"]
FEMALE = ["晚", "浅", "霜", "瑶", "笙", "汐", "宁", "悠", "忆", "暖"]

CAMERA_SIZE = ["远景", "全景", "中景", "近景", "特写", "大特写"]
ANGLE = ["平视", "俯拍", "仰拍", "顶视", "侧拍"]
MOVEMENT = ["固定", "推", "拉", "摇", "移", "跟", "环绕", "升降", "手持", "甩"]
COMPOSITION = ["黄金分割", "三分法", "中心构图", "留白", "前景虚化", "框架式"]
MOOD_COLOR = ["冷蓝", "暖黄", "莫兰迪灰", "高饱和红", "青绿", "暗调金属"]
LIGHT = ["主光硬光", "主光+补光", "逆光剪影", "侧逆光", "柔光", "色温 3200K 暖"]
BGM = ["悬疑低音", "史诗管弦", "轻快吉他", "钢琴独奏", "鼓点电子", "古风箫"]
SFX = ["心跳声", "玻璃碎裂", "风声", "关门声", "手机震动", "倒吸一口凉气"]
SUBTITLE = ["他以为赢定了", "下一秒，全场寂静", "原来……是他", "这一巴掌，等了三年", "身份，藏不住了"]
FUNCTION = ["钩子", "铺垫", "冲突", "反转", "高潮", "收尾"]
MARKER = ["冲突点", "反转点", "爽点", "泪点", "悬念"]

ROLE_FILL = {  # 哪个 Agent 负责哪些字段（体现"导演组"协作）
    "writer": "编剧", "cameraman": "分镜导演", "narration": "旁白心理",
    "director": "总导演", "reviewer": "审核",
}


def _name(genre: str) -> tuple[str, str]:
    m = SURNAMES[random.randint(0, len(SURNAMES) - 1)]
    if genre in ("甜宠", "古装"):
        return m + FEMALE[random.randint(0, len(FEMALE) - 1)], m + GIVEN[random.randint(0, len(GIVEN) - 1)]
    return m + GIVEN[random.randint(0, len(GIVEN) - 1)], m + FEMALE[random.randint(0, len(FEMALE) - 1)]


def _shot(scene_func: str, ep_idx: int, shot_idx: int, genre: dict, platform: dict, protag: str, antag: str) -> dict:
    size = random.choice(CAMERA_SIZE)
    is_character = random.random() > 0.35
    subject = f"人物镜头·{protag}" if is_character else f"路人/环境镜头·{random.choice(['街头','办公室','宴厅','车厢'])}群演"
    movement = random.choice(MOVEMENT)
    dialogue = ""
    os_text = ""
    psych = ""
    if scene_func in ("冲突", "高潮", "反转"):
        dialogue = f"（{protag}）「{random.choice(['你，配吗？','这场戏，该落幕了。','从今往后，抬头看我。','我忍你们很久了。'])}」"
        psych = f"（{protag}心理）终于，把压在心底三年的话，说了出来。"
    if scene_func in ("钩子", "铺垫"):
        os_text = f"画外音：{random.choice(SUBTITLE)}"
    marker = ""
    if scene_func == "高潮":
        marker = "爽点"
    elif scene_func == "反转":
        marker = "反转点"
    elif scene_func == "钩子":
        marker = "悬念"
    return {
        "镜号": f"{ep_idx+1}-{shot_idx+1}",
        "景别": size,
        "机位角度": random.choice(ANGLE),
        "运镜": movement,
        "构图": random.choice(COMPOSITION),
        "镜头标记": subject,
        "画面描述": f"{subject.split('·')[-1]}在{platform['name']}典型场景，{movement}运镜强调情绪，{random.choice(MOOD_COLOR)}色调。",
        "台词": dialogue,
        "OS旁白/内心独白": os_text,
        "人物心理活动": psych,
        "微表情/肢体": random.choice(["下巴微抬，眼神轻蔑", "指节捏白发白", "唇角勾起一抹冷笑", "垂眸，再抬眼已无波澜"]),
        "服化道": random.choice(["深色西装/战损铠甲", "素衣布鞋/工装", "华服高定/古装广袖", "日常卫衣/职业装"]),
        "色调": random.choice(MOOD_COLOR),
        "灯光": random.choice(LIGHT),
        "BGM": random.choice(BGM),
        "音效": random.choice(SFX),
        "字幕花字": random.choice(SUBTITLE) if random.random() > 0.5 else "",
        "单镜时长": f"{random.choice([2,3,4,5])}秒",
        "情绪强度": random.choice(["★★★", "★★★★", "★★★★★"]),
        "节拍": scene_func,
        "标记": marker,
        "负责Agent": ROLE_FILL["cameraman" if is_character else "writer"],
    }


def build_script(prompt: str, platform_key: str, genre_key: str, episode_count: int,
                 agent_key: str = "director", profile: dict | None = None,
                 kbdb: dict | None = None) -> dict[str, Any]:
    kb = retrieve(platform_key, genre_key)
    platform, genre = kb["platform"], kb["genre"]
    protag, antag = _name(genre_key)
    profile = profile or {}
    tags = profile.get("tags", [])
    kbdb = kbdb or {}
    case_refs = kbdb.get("case_refs", [])
    refs = kbdb.get("refs", [])

    title_base = (prompt.strip()[:18] if prompt.strip() else random.choice(genre["example_titles"]))
    title = f"《{title_base}》" if not title_base.startswith("《") else title_base

    # 知识库来源汇总（对外可宣讲）
    src_list = [r.get("source", "") for r in refs + case_refs if r.get("source")]
    src_text = "；".join(dict.fromkeys([s for s in src_list if s])) if src_list else "内置知识库（平台规则+类型套路）"
    opening_hint = case_refs[0]["kai_pian"] if case_refs else ""
    renshe_hint = case_refs[0]["ren_she"] if case_refs else ""

    project = {
        "项目名": title,
        "总集数": episode_count,
        "单集时长": platform["ep_duration"],
        "画幅": platform["aspect"],
        "目标平台": platform["name"],
        "类型": genre_key,
        "整体风格": "强钩子·快节奏·情绪浓烈",
        "内容分级": "12+",
        "用户偏好标签": tags,
        "前3秒钩子要求": platform["hook_3s"],
        "合规红线": platform["redlines"],
        "知识库参考(来源)": src_text,
    }
    if renshe_hint:
        project["参考爆款人设逻辑"] = renshe_hint

    structure = genre["structure"]
    episodes = []
    for ei in range(episode_count):
        step = structure[min(ei, len(structure) - 1)]
        n_scenes = random.randint(3, 4)
        scenes = []
        for si in range(n_scenes):
            sfunc = FUNCTION[min(si, len(FUNCTION) - 1)]
            if ei == 0 and si == 0:
                sfunc = "钩子"
            n_shots = random.randint(3, 5)
            shots = [_shot(sfunc, ei, sj, genre, platform, protag, antag) for sj in range(n_shots)]
            scenes.append({
                "场号": f"E{ei+1}-S{si+1}",
                "场景": f"{random.choice(['内景·豪宅客厅','外景·公司门口','内景·破旧出租屋','外景·街头','内景·会议室'])}·{random.choice(['日','夜','黄昏','雨'])}",
                "本场功能": sfunc,
                "镜头数": n_shots,
                "shots": shots,
            })
        episodes.append({
            "集号": ei + 1,
            "本集主线": f"{step}：{genre['emotion_curve'].split('→')[min(ei,4)]}",
            "scenes": scenes,
        })

    # 让开篇镜头借鉴真实爆款（更智能）：把参考爆款的开篇钩子写进第一镜画面描述
    if opening_hint and episodes and episodes[0]["scenes"]:
        first_scene = episodes[0]["scenes"][0]
        if first_scene["shots"]:
            first_shot = first_scene["shots"][0]
            first_shot["画面描述"] = f"【参考爆款开篇】{opening_hint} " + first_shot["画面描述"]

    script = {
        "project": project,
        "episodes": episodes,
        "参考爆款(知识库)": case_refs,
        "尾注": {
            "情绪曲线": genre["emotion_curve"],
            "结局套路": genre["ending"],
            "节拍模板": genre["beat"],
            "审核提示": f"已按{platform['name']}规范生成，发布前请人工复核：{platform['redlines']}",
            "主导角色(Agent)": ROLE_FILL.get(agent_key, "总导演"),
        },
    }
    return script


# ---------- 渲染为可读 Markdown ----------
def render_markdown(script: dict) -> str:
    p = script["project"]
    out = []
    out.append(f"# {p['项目名']}")
    out.append("")
    out.append("## 一、工程信息（A）")
    for k, v in p.items():
        out.append(f"- **{k}**：{v}")
    out.append("")
    # 创作依据：知识库参考 + 真实爆款来源（对外宣讲/透明）
    case_refs = script.get("参考爆款(知识库)", [])
    if case_refs:
        out.append("## 二、创作依据（知识库参考 · 带来源）")
        out.append("> 本剧由 AI 导演组基于内置专业知识库生成，自动参考以下真实爆款拆解：")
        for c in case_refs:
            out.append(f"- **{c.get('title','')}** ｜ 来源：{c.get('source','')}")
            if c.get("why"):
                out.append(f"  - 为什么爆：{c['why']}")
        out.append("")
    out.append("## 三、分集大纲（B）")
    for ep in script["episodes"]:
        out.append(f"### 第 {ep['集号']} 集 ｜ {ep['本集主线']}")
    out.append("")
    for ep in script["episodes"]:
        out.append(f"## 四、第 {ep['集号']} 集 分镜脚本（C/D/E/F/G）")
        for sc in ep["scenes"]:
            out.append(f"### 场 {sc['场号']} ｜ {sc['场景']} ｜ 功能：{sc['本场功能']}")
            for sh in sc["shots"]:
                out.append(f"**镜 {sh['镜号']}** 〔{sh['景别']}·{sh['机位角度']}·{sh['运镜']}·{sh['构图']}〕 {sh['镜头标记']}")
                out.append(f"- 画面：{sh['画面描述']}")
                if sh['台词']:
                    out.append(f"- 台词：{sh['台词']}")
                if sh['OS旁白/内心独白']:
                    out.append(f"- 旁白/独白：{sh['OS旁白/内心独白']}")
                if sh['人物心理活动']:
                    out.append(f"- 心理：{sh['人物心理活动']}")
                out.append(f"- 服化道：{sh['服化道']} ｜ 色调：{sh['色调']} ｜ 灯光：{sh['灯光']}")
                out.append(f"- 视听：BGM {sh['BGM']} ｜ 音效 {sh['音效']} ｜ 花字「{sh['字幕花字']}」")
                out.append(f"- 时长 {sh['单镜时长']} ｜ 情绪 {sh['情绪强度']} ｜ 节拍 {sh['节拍']} ｜ 标记 {sh['标记']} ｜ 负责 {sh['负责Agent']}")
                out.append("")
        out.append("")
    t = script["尾注"]
    out.append("## 五、尾注")
    out.append(f"- 情绪曲线：{t['情绪曲线']}")
    out.append(f"- 结局套路：{t['结局套路']}")
    out.append(f"- 节拍模板：{t['节拍模板']}")
    out.append(f"- 审核提示：{t['审核提示']}")
    out.append("")
    out.append("---")
    out.append("> 本剧本由 AI 生成，发布前请人工复核各平台规范与合规红线。")
    return "\n".join(out)


# ---------- token 级流式（模拟 LLM 逐字输出） ----------
def tokenize(text: str) -> list[str]:
    # 中文按字+标点成 token，英文/数字按词
    return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+|\s+|[^\s]", text)


def stream_markdown(script: dict) -> Iterator[str]:
    md = render_markdown(script)
    toks = tokenize(md)
    buf = ""
    for i, t in enumerate(toks):
        buf += t
        if len(buf) >= 4 or i == len(toks) - 1:
            yield buf
            buf = ""


# ---------------- 方舟真实生成（带兜底降级，且真读 AgentConfig） ----------------
def _ark_system_prompt(agent_key: str, profile: dict, kbdb: dict,
                       agent_cfg: dict | None = None) -> str:
    """构造方舟 system prompt：真读 AgentConfig（或传入的 cfg），不再是写死人设。

    agent_cfg: {persona_name, system_prompt, persona, tools, ...}，可选
    """
    refs = kbdb.get("refs", []) if kbdb else []
    cases = kbdb.get("case_refs", []) if kbdb else []
    src = "；".join(dict.fromkeys([r.get("source", "") for r in (refs + cases) if r.get("source")]))

    # 默认人设（数据库无配置时兜底）
    DEFAULT_PERSONA = {
        "director": "国家级总导演", "writer": "金牌编剧", "cameraman": "电影感分镜导演",
        "narration": "情绪旁白师", "reviewer": "平台合规审核",
    }
    DEFAULT_SYSTEM = {
        "director": "你是国家级短剧总导演，负责拆解需求、调度编剧/分镜/旁白/审核，总控全局。",
        "writer": "你是金牌编剧，专注故事/人物/台词/爽点/泪点，注重钩子密度。",
        "cameraman": "你是电影感分镜导演，负责镜头语言与视听设计。",
        "narration": "你是情绪旁白师，负责 OS/内心独白/潜台词/心理活动。",
        "reviewer": "你是平台合规审核，审查一致性/人设漂移/平台合规/敏感词。",
    }
    persona_name = (agent_cfg or {}).get("persona_name") or DEFAULT_PERSONA.get(agent_key, "国家级总导演")
    system_prompt = (agent_cfg or {}).get("system_prompt") or DEFAULT_SYSTEM.get(agent_key, DEFAULT_SYSTEM["director"])
    persona_desc = (agent_cfg or {}).get("persona") or ""

    return (
        f"{persona_desc}\n"
        f"{system_prompt}\n"
        f"你正在为红果/抖音/快手短剧平台创作专业剧本。\n"
        f"用户偏好标签：{profile.get('tags', [])}。\n"
        f"可参考的真实爆款来源（用于『创作依据』字段，照搬来源文字）：{src}\n"
        "请严格只输出一个 JSON 对象，结构如下（字段名必须完全一致，中文值）：\n"
        "{\n"
        '  "project": {"项目名":str,"总集数":int,"单集时长":str,"画幅":str,"目标平台":str,'
        '"类型":str,"整体风格":str,"内容分级":str,"用户偏好标签":[str],"前3秒钩子要求":str,'
        '"合规红线":str,"知识库参考(来源)":str},\n'
        '  "episodes":[{"集号":int,"本集主线":str,"scenes":[{"场号":str,"场景":str,'
        '"本场功能":str,"镜头数":int,"shots":[{"镜号":str,"景别":str,"机位角度":str,"运镜":str,'
        '"构图":str,"镜头标记":str,"画面描述":str,"台词":str,"OS旁白/内心独白":str,'
        '"人物心理活动":str,"微表情/肢体":str,"服化道":str,"色调":str,"灯光":str,"BGM":str,'
        '"音效":str,"字幕花字":str,"单镜时长":str,"情绪强度":str,"节拍":str,"标记":str,'
        '"负责Agent":str}]}]}],\n'
        '  "参考爆款(知识库)":[{"title":str,"source":str,"why":str}],\n'
        '  "尾注":{"情绪曲线":str,"结局套路":str,"节拍模板":str,"审核提示":str,"主导角色(Agent)":str}\n'
        "}\n"
        "要求：每集 3 个场景，每场景 3 个镜头；台词/心理/画面描述要专业、有电影感、强情绪；"
        "不要输出 JSON 以外的任何文字。"
    )


def _load_agent_cfg(db, agent_key: str) -> dict | None:
    """从数据库读 AgentConfig，构造生成器用的 cfg dict。"""
    from .models import AgentConfig
    row = db.query(AgentConfig).filter(AgentConfig.key == agent_key,
                                       AgentConfig.enabled.is_(True)).first()
    if not row:
        return None
    return {
        "persona_name": row.persona_name or row.name,
        "system_prompt": row.system_prompt or row.prompt or "",
        "persona": row.persona or "",
        "tools": row.tools or [],
        "bound_model": row.bound_model,
    }


def build_script_via_ark(prompt: str, platform_key: str, genre_key: str, episode_count: int,
                         agent_key: str = "director", profile: dict | None = None,
                         kbdb: dict | None = None, agent_cfg: dict | None = None,
                         db=None, on_token: Callable[[str], None] | None = None,
                         recent_history: str = "", rag_ctx: str = "") -> dict:
    from .clients import ark_chat
    from .config import settings
    if not settings.ark_enabled:
        raise RuntimeError("方舟未启用")
    if agent_cfg is None and db is not None:
        agent_cfg = _load_agent_cfg(db, agent_key)
    kb = kbdb or {}
    persona_name = (agent_cfg or {}).get("persona_name") or agent_key
    user_msg = (
        f"需求：{prompt}\n目标平台：{platform_key}\n类型：{genre_key}\n"
        f"集数：{episode_count}\n请以『{persona_name}』视角生成。"
    )
    # 【上下文补丁】传入会话最近对话，避免用户在多轮里说『接着聊』/『继续』Agent 却当失忆
    if recent_history:
        user_msg += (
            "\n\n【最近对话上下文（用于一致性参考）】\n"
            + recent_history[:1500]
            + "\n\n如果用户的需求与上文相关（如『继续/接着/同一世界观改 X 集/类似上一部』），"
              "请保留一致的人物、世界观、风格与节奏；如果需求是新主题，可不必强接上下文。"
        )
    system = _ark_system_prompt(agent_key, profile or {}, kb, agent_cfg)
    # 【RAG 补丁】注入知识库检索证据（类型套路/平台规则/风格样本），让剧本更贴平台与爆款方法论
    if rag_ctx:
        system += (
            "\n\n【检索证据（RAG）】以下是与本次创作相关的知识库内容，请优先参考其中的"
            "类型套路、平台规则、钩子公式与风格样本，让剧本更契合目标平台与爆款方法论：\n"
            + rag_ctx
        )
    text = ark_chat.chat_complete(
        system, user_msg,
        model=settings.ARK_MODEL_CHAT, max_tokens=4096, timeout=45.0,
        on_chunk=on_token)
    content = ark_chat.extract_json(text)
    # 基本校验
    if not isinstance(content, dict) or "project" not in content or "episodes" not in content:
        raise RuntimeError("方舟返回结构不合法")
    return content


def optimize_script_via_ark(last_content: dict, instruction: str, platform_key: str,
                            genre_key: str, episode_count: int, agent_key: str = "director",
                            profile: dict | None = None, kbdb: dict | None = None,
                            agent_cfg: dict | None = None, db=None,
                            on_token: Callable[[str], None] | None = None,
                            recent_history: str = "", rag_ctx: str = "") -> dict:
    """优化模式：基于上一条剧本做 patch（而非重新生成），保证上下文一致。

    把上一条剧本 JSON + 用户优化指令发给方舟，返回修改后的完整 JSON。
    """
    from .clients import ark_chat
    from .config import settings
    if not settings.ark_enabled:
        raise RuntimeError("方舟未启用")
    if agent_cfg is None and db is not None:
        agent_cfg = _load_agent_cfg(db, agent_key)
    persona_name = (agent_cfg or {}).get("persona_name") or agent_key
    last_json = json.dumps(last_content, ensure_ascii=False)
    user_msg = (
        f"已有剧本（JSON）：\n{last_json}\n\n"
        f"用户的优化要求：{instruction}\n\n"
        f"请以『{persona_name}』视角，在保留原剧本人物/主线/结构的前提下，"
        f"按照用户要求修改，返回【完整且合法的优化后 JSON 对象】（字段结构必须与输入完全一致，"
        f"只能输出 JSON，不要任何说明文字）。"
    )
    if recent_history:
        user_msg += (
            "\n\n【最近对话上下文（用于一致性参考）】\n"
            + recent_history[:1000]
            + "\n\n如果用户用了『这个/那段/刚才』等指代词，请结合上面对话历史明确指代对象。"
        )
    system = (
        _ark_system_prompt(agent_key, profile or {}, kbdb or {}, agent_cfg) +
        "\n注意：本次是对『已有剧本』做优化，必须返回完整 JSON（含 project/episodes/尾注），"
        "保持人物与主线连贯，只按用户指令改动对应部分。"
    )
    # 【RAG 补丁】注入知识库检索证据，让优化也参考类型套路/平台规则
    if rag_ctx:
        system += (
            "\n\n【检索证据（RAG）】以下相关知识库内容供参考（类型套路/平台规则/风格样本）：\n"
            + rag_ctx
        )
    text = ark_chat.chat_complete(system, user_msg, model=settings.ARK_MODEL_CHAT,
                                  max_tokens=4096, timeout=60.0, on_chunk=on_token)
    content = ark_chat.extract_json(text)
    if not isinstance(content, dict) or "project" not in content or "episodes" not in content:
        raise RuntimeError("优化返回结构不合法")
    return content


def optimize_script_fallback(last_content: dict, instruction: str) -> dict:
    """优化兜底：不调 LLM，在原剧本上做轻量标注式修改，保证永远有结果且上下文连贯。"""
    import copy
    new = copy.deepcopy(last_content)
    proj = new.get("project", {})
    title = proj.get("项目名", "剧本")
    proj["项目名"] = f"{title}（优化版）" if not title.endswith("优化版）") else title
    note = new.setdefault("尾注", {})
    prev = note.get("优化记录", "")
    note["优化记录"] = (prev + f"\n- {instruction}").strip()
    note["主导角色(Agent)"] = note.get("主导角色(Agent)", "总导演")
    return new


def generate_content(prompt: str, platform_key: str, genre_key: str, episode_count: int,
                     agent_key: str = "director", profile: dict | None = None,
                     kbdb: dict | None = None, agent_cfg: dict | None = None,
                     db=None) -> dict:
    """优先方舟真实生成；任何失败回退规则兜底，保证永远能出片。

    真读 AgentConfig（agent_cfg 或从 db 加载）。
    """
    try:
        if agent_cfg is None and db is not None:
            agent_cfg = _load_agent_cfg(db, agent_key)
        return build_script_via_ark(prompt, platform_key, genre_key, episode_count,
                                    agent_key, profile, kbdb, agent_cfg, db)
    except Exception as e:  # noqa
        # 兜底：沿用规则生成器
        return build_script(prompt=prompt, platform_key=platform_key, genre_key=genre_key,
                            episode_count=episode_count, agent_key=agent_key,
                            profile=profile, kbdb=kbdb)
