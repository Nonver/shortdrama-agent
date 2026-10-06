"""Agent 聊天路由：5 个独立聊天窗 + 流式输出 + @Agent 召唤协作 + 工具调度。

这是把『首页 5 卡片 → 进入 Agent 聊天』的核心路由。
数据互通：跨 Agent 上下文摘要共享 (Conversation.cross_agent_summary)，
协作机制：用户可在任一 Agent 聊天内 @其他 Agent，被召唤的 Agent 接力回应。
工具调度：聊天中可触发 image_generate / video_generate / tts / script_generate，
权限校验在工具触发时进行（不是进入聊天时），符合『按需权限校验』的设计。
"""
from __future__ import annotations
import json
import re
import time
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db, SessionLocal
from ..models import User, Conversation, AgentConfig, Script, Asset
from ..deps import get_current_user, require_feature
from ..generator import generate_content, _load_agent_cfg
from ..knowledge import retrieve_kb
from ..exports import to_markdown

router = APIRouter(prefix="/api", tags=["chat"])

# SSE 流僵尸锁超时（秒）：超过此时间仍 is_streaming=True 视为客户端断开未归零，自动复位避免反复 409
_ZOMBIE_TIMEOUT = 90


# ---------- 意图识别与工具/向导辅助（聊天即 Agent 大脑） ----------
import re as _re

# 文本产物：用户要的是『提示词/文案/咒语』等文本，不是调底层生图/视频/TTS
# 注意：『配音/视频/图』等词必须配合『词/文案/台词/稿/脚本』或『写/一段』等创作动词，
#       否则（裸『配音』『生成视频』）仍走 TOOL_*（真调底层出片）。
_INTENT_TEXT_PROMPT = _re.compile(
    r"(提示词|提示文案|prompt|prompts|咒语|描述词|文生图|图生图|分镜词|分镜脚本|"
    r"口播文案|广告文案|旁白文案|视频文案|脚本词|台词稿|解说词|"
    r"配音词|配音台词|配音文稿|配音稿|配音脚本|写配音|一段配音|给段配音|"
    r"写视频|写段视频|写图|写张图|写段图|"
    r"一段文案|一句文案|文案|给个词|写段词|出个词)")
# 工具强动词：真要调底层生图/视频/配音
_INTENT_TOOL = _re.compile(r"(生成视频|做个视频|出视频|做段视频|生成.*视频|配.*视频|视频.*生成|"
                           r"生成图|生图|出图|配图|配个图|做个图|生成图片|生成一张图|"
                           r"配音|读一下|生成音频|朗读|生成语音|来段音频)")
_INTENT_OPT = _re.compile(r"(优化|改一下|改一版|改一改|调整|修改|完善|润色|精修|再改|第二版|"
                           r"换个结尾|换个开头|加一场|加一集|缩短|扩写|重新调整|打磨|升一版|升级|微调)")
_INTENT_GEN = _re.compile(r"(写|生成|做|创作|来一|一部|个剧本|短剧|拍|编|构思|帮我做|给我写|来个)")
_INTENT_GUIDE = _re.compile(r"(怎么|如何|为什么|啥是|什么是|步骤|教程|教我|流程|注意什么|"
                            r"有啥风险|风险|版权|aigc|平台.*?选|变现|过审|分镜|合规|"
                            r"红线|知识|怎么用|啥|哪)")


def classify_intent(text: str, ctx: dict, recent_history: str = "") -> str:
    """意图识别：把每条用户消息分流到正确链路（聊天即 Agent 大脑）。

    **主路径 = 轻量 LLM 分类器**（clients/intent_classifier）：真正理解语义/指代/复合句；
    LLM 超时或不可用时自动降级为正则兜底（见 intent_classifier._fallback_regex）。

    返回：TEXT_PROMPT / GENERATE / OPTIMIZE_LAST / GUIDE_QUESTION / TOOL_IMAGE /
          TOOL_VIDEO / TOOL_TTS / UNKNOWN（意图不清 → 主动追问澄清）。
    """
    from ..clients.intent_classifier import classify_intent as _llm_classify
    return _llm_classify(text, ctx, recent_history)


def _prompt_kind_of(text: str) -> str:
    """从文本产物意图里推断产物类型：video / image / tts / text。"""
    t = (text or "").lower()
    if "视频" in t or "短片" in t:
        return "video"
    if "图" in t or "海报" in t:
        return "image"
    if "配音" in t or "台词" in t or "音频" in t or "朗读" in t or "解说" in t or "口播" in t:
        return "tts"
    return "text"


def _gen_prompt_text(user_text: str, ctx: dict, db, on_token=None, recent_history: str = "",
                     rag_ctx: str = "") -> str:
    """用 LLM 生成『提示词/文案/台词』等文本产物（不调底层生图/视频/TTS）。

    recent_history: 会话最近对话文本（解决上下文接不住）。
    rag_ctx: RAG 检索增强上下文（知识库/剧本证据，单点注入）。
    """
    from ..clients import ark_chat
    from ..config import settings
    from ..generator import _load_agent_cfg
    if not settings.ark_enabled:
        return _gen_prompt_fallback(user_text, recent_history)
    agent_cfg = _load_agent_cfg(db, ctx.get("agent_key") or "director")
    persona = agent_cfg.get("persona_name") or "AI 短剧导演"
    kind = _prompt_kind_of(user_text)
    kind_cn = {"video": "视频提示词", "image": "图片提示词",
               "tts": "配音/台词文案", "text": "文案/提示词"}[kind]
    system = (
        f"你是『{persona}』，擅长为 AI 短剧创作可直接使用的生产物料。"
        f"用户现在要的是【{kind_cn}】这一类『文本产物』，不是让你调底层模型去真出片。"
        "输出要求（直接给可用内容，不要客套）：\n"
        "1）先用一句话中文描述画面/内容；\n"
        "2）再给【英文 Prompt】（适合文生视频/图模型，如 Seedance/Seedream）；\n"
        "3）再给【参数建议】（时长/比例/运镜/风格/色调）；\n"
        "4）最后给【中文改写版】便于二次调整。\n"
        "若用户要的是文案/台词，则给出可直接用的成片文案，并标注情绪/节奏。\n"
        "【上下文约束】用户当下处于多轮对话中。如果下方有『最近对话』，"
        "请让你的产物自然承接上文的主角/时代/视觉/情绪，不要突然跳到无关题材。"
    )
    if rag_ctx:
        system += "\n\n" + rag_ctx
    user_msg = f"需求：{user_text}"
    if recent_history:
        user_msg = f"【最近对话】\n{recent_history}\n\n【当前需求】\n{user_text}"
    try:
        text = ark_chat.chat_complete(system, user_msg, model=settings.ARK_MODEL_CHAT,
                                     max_tokens=1500, timeout=40.0, on_chunk=on_token)
        return text.strip() or _gen_prompt_fallback(user_text, recent_history)
    except Exception:
        return _gen_prompt_fallback(user_text, recent_history)


def _gen_prompt_fallback(user_text: str, recent_history: str = "") -> str:
    """兜底：规则生成提示词（不依赖 LLM，保证永远有结果）。"""
    subject = _strip_instr_words(user_text) or user_text
    if recent_history:
        # 把最近一段的关键视觉/主体拼进英文 prompt，避免失忆跑题
        ctx_keywords = _re.sub(r"[\s，,。.!！?？]+", " ", recent_history)
        ctx_keywords = _re.sub(r"\s+", " ", ctx_keywords).strip()
        if ctx_keywords:
            subject = f"{ctx_keywords[:160]}, featuring: {subject}"
    return ("【中文描述】" + user_text + "\n" +
            "【英文 Prompt】" + subject + ", cinematic, high quality, short drama style, 9:16 vertical\n" +
            "【参数建议】时长 5s，比例 9:16，运镜 推近+手持，风格 电影感/高饱和，色调 冷调\n" +
            "【中文改写】请基于以上内容调整画面主体、情绪与节奏后使用。")


def _tool_err_friendly(err: Exception) -> str:
    """把底层生图/视频/配音报错包装成 Agent 口吻的中文引导。"""
    msg = str(err)
    low = msg.lower()
    if "setlimitexceeded" in low or "inference limit" in low or "额度" in msg or "quota" in low \
       or "体验模式" in msg or "safe experience" in low:
        return ("视频/图片生成额度已用完（火山方舟该模型服务已暂停）。"
                "请到『火山方舟控制台 → 模型激活页』关闭『安全体验模式』或调整配额；"
                "额度一般月底重置。本次先不真出片，已为你生成可直接手动出片的提示词文本 ↑")
    if "403" in msg or "forbidden" in low or "无权限" in msg or "未授权" in msg:
        return "该能力需对应会员等级（生图需 member、生视频/配音需 Pro），请升级会员后再试。"
    if "429" in msg or "rate" in low or "限流" in msg or "too many" in low:
        return "请求太频繁被限流了，稍等几秒再试一次～"
    if "400" in msg or "敏感" in msg or "违规" in msg or "content policy" in low or "block" in low:
        return "提示词触发了内容安全策略，已自动替换敏感词；换种更安全的描述再试一次。"
    if "500" in msg or "502" in msg or "503" in msg or "timeout" in low or "超时" in msg or "服务" in msg:
        return "底层模型服务暂时抽风/超时，请稍后再试一次～"
    return f"出片失败：{msg[:200]}"


def _tool_err_kind(msg: str) -> str:
    """把错误字符串分类成枚举，方便前端按类别做不同动作（禁用按钮 vs 复制提示词）。"""
    low = msg.lower()
    if "setlimitexceeded" in low or "inference limit" in low or "额度" in msg or "quota" in low \
       or "体验模式" in msg or "safe experience" in low:
        return "quota"
    if "403" in msg or "forbidden" in low or "无权限" in msg or "未授权" in msg:
        return "permission"
    if "429" in msg or "rate" in low or "限流" in msg or "too many" in low:
        return "rate"
    if "400" in msg or "敏感" in msg or "违规" in msg or "content policy" in low or "block" in low:
        return "safety"
    if "500" in msg or "502" in msg or "503" in msg or "timeout" in low or "超时" in msg or "服务" in msg:
        return "service"
    return "other"


def _clarify_text(text: str, ctx: dict, recent_history: str = "") -> str:
    """意图不清（UNKNOWN）时，Agent 主动追问澄清。

    主路径用 LLM 基于【最近对话】猜用户最可能的意图并追问（不再回 hardcode 四选一模板）；
    LLM 不可用时降级为结构化的澄清话术。
    """
    if settings_ark_enabled() and recent_history:
        try:
            from ..clients import ark_chat
            sys_p = ("你是短剧创作 Agent。用户刚发了一条意图不清的消息，你没有把握。"
                     "请先基于【最近对话】判断用户『最可能在问什么』（生成剧本/优化上一条/问知识/出图出视频配音/"
                     "写提示词文案），然后用一句口语化、带猜测的话追问澄清，给用户 2-3 个具体选项。"
                     "控制在 80 字以内，像真人助手在确认。不要解释、不要客套。")
            user_p = f"【最近对话】\n{recent_history}\n\n【用户最新消息】\n{text}\n\n你的追问："
            out = ark_chat.chat_complete(sys_p, user_p, model=settings.ARK_MODEL_MINI,
                                         temperature=0.6, max_tokens=160, timeout=12)
            if out and out.strip():
                return out.strip()
        except Exception:
            pass
    # 降级：结构化澄清
    if ctx.get("last_script_id"):
        # 【修复】原 "%s" 占位在 Python 3.13 下会被 last_title 里的 '%' 字符引爆
        # 改用 f-string 占位，title 内出现 '%' 也安全。
        title = ctx.get("last_title") or "上一个剧本"
        return (
            "我有点拿不准你的意思～你是想：\n"
            "① 基于上一条《{title}》做优化/调整（说『优化…/改一下…』）？\n"
            "② 问 AI 短剧相关问题（如『怎么过审/怎么变现』）？\n"
            "③ 让我生成图片/视频/配音（说『生成视频/配图/配音』）？\n"
            "④ 还是开启一个全新剧本（说『写一部…短剧』）？\n告诉我方向就行～"
        ).format(title=title)
    return ("我可以帮你：① 写一部 AI 短剧剧本（说『写一部《…》的 N 集短剧』）；"
            "② 回答 AI 短剧相关问题（如『新手怎么用 AI 做短剧』）；"
            "③ 基于剧本生成图片/视频/配音（说『生成视频/配图/配音』）。\n"
            "你想要哪个？说具体点我马上办～")


def settings_ark_enabled() -> bool:
    from ..config import settings
    return settings.ark_enabled


def _guide_answer(question: str, db) -> tuple[str, list[str]]:
    """复用知识库向导答疑（检索 guide 子库 + 方舟 LLM，断网关键词兜底）。"""
    from ..routers.knowledge import guide_ask  # 复用检索+LLM 逻辑
    try:
        res = guide_ask({"question": question}, db)
        return res.get("answer", ""), res.get("refs", [])
    except Exception:
        return "（知识库暂时查不到，请稍后再试）", []


def _extract_refs(rag_ctx: str) -> list[str]:
    """从 RAG 上下文中提取引用编号（【KB-xx】/【剧本-xx】）。"""
    if not rag_ctx:
        return []
    import re as _r
    return _r.findall(r"【(KB-\d+|剧本-\d+)】", rag_ctx)


def _rag_guide_answer(question: str, rag_ctx: str, db) -> tuple[str, list[str]]:
    """向导答疑：直接复用 RAG 检索上下文（KB 证据 + 引用）生成自然语言回答。

    比旧 _guide_answer 的关键词检索更准（RAG 已做向量+BM25 融合 + 重排）。
    """
    from ..clients import ark_chat
    from ..config import settings
    if not settings.ark_enabled:
        return _guide_answer(question, db)
    sys_p = ("你是『AI 短剧知识库向导』，一位亲切专业的产品引导员。"
             "请严格只依据下方『检索证据』用简体中文回答用户问题，语气口语化、像在引导新手；"
             "不要编造证据以外的数据；若证据里没有答案，坦诚说明『这方面知识库暂未覆盖』并给一条通用建议。"
             "回答控制在 280 字以内，结尾另起一行附『📚 相关参考：』并列出用到的证据编号（如【KB-23】）。")
    if rag_ctx:
        sys_p += "\n\n" + rag_ctx
    try:
        answer = ark_chat.chat_complete(sys_p, question, max_tokens=900, timeout=60).strip()
        refs = _extract_refs(rag_ctx)
        return answer, refs
    except Exception:
        return _guide_answer(question, db)


def _extract_video_prompt(ctx: dict, db, user_text: str, recent_history: str = "", rag_ctx: str = "") -> str:
    """从最近一条剧本提取多镜头视频 prompt（前3秒 + 高潮 + 结尾），保证视频对得上剧本。

    recent_history：让 LLM 改写 prompt 时紧扣上下文（避免『聊嫦娥奔月，结果拍九尾狐变身』）。
    rag_ctx：注入 KB 短视频公式/风格样本，让出片风格更贴平台爆款方法论。
    """
    script_id = ctx.get("last_script_id")
    if script_id:
        sc = db.get(Script, int(script_id)) if str(script_id).isdigit() else None
        if sc and sc.content_json:
            eps = sc.content_json.get("episodes", [])
            parts = []
            try:
                parts.append("【开场】" + eps[0]["scenes"][0]["shots"][0].get("画面描述", ""))
            except Exception:
                pass
            for ep in eps:
                for scn in ep.get("scenes", []):
                    for sh in scn.get("shots", []):
                        if sh.get("标记") in ("爽点", "高潮", "反转点"):
                            parts.append("【高潮】" + sh.get("画面描述", ""))
                            break
                    else:
                        continue
                    break
                else:
                    continue
                break
            try:
                parts.append("【结尾】" + eps[-1]["scenes"][-1]["shots"][-1].get("画面描述", ""))
            except Exception:
                pass
            prompt = "；".join([p for p in parts if p])
            if prompt:
                return prompt[:900]
    # 兜底：用 LLM 把用户口述（"帮我生成一段嫦娥奔月的视频"）改写为 Seedance 友好的英文 prompt
    return _llm_to_seedance_prompt(user_text, recent_history, rag_ctx)


# ---------- Seedance 友好 prompt 改写（让方舟出片对得上用户意图） ----------
_INSTR_WORDS = _re.compile(
    "[帮请辛麻]|[生来搞弄赶立]|生成[一段个张]|一[段个]|张[个]?|视频|短片|拍|做|出|"
    "马上|来一|搞个|弄个|赶紧|立刻|想看|想用"
)


def _strip_instr_words(user_text: str) -> str:
    """去指令词，保留主体关键词；老式兜底（不再 base64 走 LLM 时）。"""
    cleaned = _INSTR_WORDS.sub(" ", user_text or "")
    cleaned = _re.sub(r"[\s，,。.!！?？]+", " ", cleaned).strip()
    # 去除"的"
    cleaned = cleaned.replace("的", " ")
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or (user_text or "")


def _recent_history_text(messages: list, n: int = 8, each_cap: int = 200) -> str:
    """把会话最近 n 条对话压成一段文本（注入到所有 LLM prompt 中，让 Agent 接住上下文）。

    解决"上下文是傻子"的根因：之前 chat.py 只把 user_msg_text 一句话喂给 LLM，
    完全不传历史，所以 Agent 每次都"失忆"。这里给所有 prompt 类调用打补丁。
    """
    if not messages:
        return ""
    tail = list(messages)[-n:]
    lines = []
    for m in tail:
        role = "用户" if m.get("role") == "user" else (m.get("persona_name") or "Agent")
        c = (m.get("content") or "").strip()
        if not c:
            continue
        if len(c) > each_cap:
            c = c[:each_cap] + "…"
        lines.append(f"[{role}] {c}")
    return "\n".join(lines)


def _llm_to_seedance_prompt(user_text: str, recent_history: str = "", rag_ctx: str = "") -> str:
    """调方舟 LLM 把用户中文口述改写为 1 句英文 Seedance 友好 prompt。
    含主体/动作/场景/风格/运镜/色调/比例(9:16)/时长(5s)。失败时走老式去词兜底。
    """
    from ..clients import ark_chat
    from ..config import settings
    text = (user_text or "").strip()
    if not text:
        return text
    # 若用户已经是很干净的描述（无指令词、无"帮我"等），跳过 LLM 节省 token
    if not _re.search(r"(帮我|请|想要|一下|一段|帮我|马上|立刻|视频|短片|拍|做|出个)", text):
        if len(text) <= 80 and _re.search(r"[\u4e00-\u9fff]", text):
            return text  # 中文短句，保持原样
    if not settings.ark_enabled:
        return _strip_instr_words(text)
    sys_p = ("You're an AI video prompt engineer. Rewrite the user's Chinese description into ONE concise English prompt "
             "for Seedance (Doubao) text-to-video. Must include: subject, action, scene, style, camera move, "
             "color tone, 9:16 vertical aspect ratio, 5-second duration. No Chinese, no explanation, only the prompt.")
    # 上下文补丁：用户最新一句可能跟上面剧本/对话相关（"把上面那段话拍成视频"），把 recent_history 注入
    # 让 prompt 真正接住上下文，避免瞎跑题（如聊嫦娥奔月，结果拍出九尾狐变身）。
    if recent_history:
        sys_p += ("\n\nIMPORTANT: The user is in an ongoing conversation. Above is recent context — "
                  "your prompt MUST be coherent with the subject/style described in the recent history, "
                  "NOT a random topic. Honour the protagonist, era, and visual motifs established.")
    # 【RAG 补丁】注入 KB 短视频公式/风格样本，让出片更贴平台爆款方法论
    if rag_ctx:
        sys_p += ("\n\nREFERENCE (knowledge base, RAG) — style/formula samples to follow for a "
                  "platform-winning short video:\n" + rag_ctx)
    user_p = (f"Recent conversation:\n{recent_history}\n\n" if recent_history else "") \
        + f"User's latest message: {text}\nEnglish prompt:"
    try:
        out = ark_chat.chat_complete(sys_p, user_p, max_tokens=240, temperature=0.65, timeout=30)
        out = (out or "").strip().strip('"').strip("'").strip()
        # 排除空、过短、或包含中文的回复
        if not out or len(out) < 12 or _re.search(r"[\u4e00-\u9fff]", out):
            return _strip_instr_words(text)
        return out[:900]
    except Exception:
        return _strip_instr_words(text)


def _extract_image_prompt(user_text: str, ctx: dict, db, recent_history: str = "", rag_ctx: str = "") -> str:
    """生图 prompt：有最近剧本则取首镜画面描述，否则用用户原话（去指令词）。

    rag_ctx：注入 KB 海报/分镜风格样本，让出片风格更贴平台爆款方法论。
    """
    script_id = ctx.get("last_script_id")
    if script_id:
        sc = db.get(Script, int(script_id)) if str(script_id).isdigit() else None
        if sc and sc.content_json:
            try:
                return sc.content_json["episodes"][0]["scenes"][0]["shots"][0].get("画面描述", "")
            except Exception:
                pass
    cleaned = _re.sub(r"(生成图|生图|出图|配图|配个图|做个图|生成图片|生成一张图)", "", user_text).strip() or user_text
    parts = [cleaned]
    if recent_history:
        # 简单兜底：把最近一段尾句拼接成补充上下文（避免 LLM 失忆）
        parts.append(f"(Context: {recent_history[-120:]})")
    if rag_ctx:
        # 注入知识库风格样本（海报/分镜构图方法论），截断避免污染生图 prompt
        parts.append(f"(Style reference / RAG: {rag_ctx[:300]})")
    return " ".join(p for p in parts if p)


def _run_tool(intent: str, user_text: str, ctx: dict, user, db, sid: int,
              recent_history: str = "", rag_ctx: str = "") -> dict:
    """在聊天流内自动调工具（生图/视频/配音）。用户说『生成视频』即自动生成，不需点击。"""
    from ..clients import ark_image, ark_video, tts_client
    from ..config import settings
    from ..deps import get_membership_config, level_ge
    cfg = get_membership_config(db)
    if intent == "TOOL_IMAGE" and not level_ge(user.membership_level, "member"):
        return {"error": "生图需会员（member）及以上"}
    if intent in ("TOOL_VIDEO", "TOOL_TTS") and not level_ge(user.membership_level, "pro"):
        return {"error": "生视频/配音需会员 Pro"}
    script_id = ctx.get("last_script_id")
    if intent == "TOOL_IMAGE":
        prompt = _extract_image_prompt(user_text, ctx, db, recent_history, rag_ctx)
        url = ark_image.save_image(prompt, size="2K",
                                   badge_text=cfg.get("badge_text", "AI 生成"),
                                   with_badge=cfg.get("watermark_badge", True))
        asset = Asset(owner_id=user.id, kind="image", url=url, prompt=prompt,
                      meta={"session_id": sid, "from": "chat_auto", "script_id": script_id})
        db.add(asset); db.commit()
        return {"kind": "image", "url": url, "prompt": prompt, "script_id": script_id, "asset_id": asset.id}
    if intent == "TOOL_VIDEO":
        prompt = _extract_video_prompt(ctx, db, user_text, recent_history, rag_ctx)
        if not prompt:
            return {"error": "没有可生成的剧本内容，请先生成剧本或描述视频画面"}
        url = ark_video.generate_video(prompt)
        asset = Asset(owner_id=user.id, kind="video", url=url, prompt=prompt,
                      meta={"session_id": sid, "from": "chat_auto", "script_id": script_id})
        db.add(asset); db.commit()
        return {"kind": "video", "url": url, "prompt": prompt, "script_id": script_id, "asset_id": asset.id}
    # TTS
    text = _re.sub(r"(配音|读一下|生成音频|朗读|生成语音|来段音频)", "", user_text).strip() or user_text
    if script_id:
        sc = db.get(Script, int(script_id)) if str(script_id).isdigit() else None
        if sc and not text.strip():
            text = sc.title or user_text
    mp3 = tts_client.synthesize(text, voice_type="default")
    import base64
    url_b64 = "data:audio/mp3;base64," + base64.b64encode(mp3).decode()
    return {"kind": "audio", "url": url_b64, "text": text[:80], "script_id": script_id}


# ---------- Agent 配置（前台用，公开：仅返回元数据，真正聊天才需登录） ----------
@router.get("/agents", response_model=list[dict])
def list_agents(db: Session = Depends(get_db)):
    """列出所有启用的 Agent（前台 Agent 卡片用，公开）。"""
    rows = (db.query(AgentConfig)
              .filter(AgentConfig.enabled.is_(True))
              .order_by(AgentConfig.sort_order).all())
    return [{
        "key": r.key,
        "name": r.name,
        "persona_name": r.persona_name,
        "avatar": r.avatar,
        "description": r.description,
        "tools": r.tools or [],
        "example_dialogue": r.example_dialogue or [],
    } for r in rows]


@router.get("/agents/{key}", response_model=dict)
def get_agent(key: str, db: Session = Depends(get_db)):
    """获取单个 Agent 详情（公开元数据）。"""
    r = db.query(AgentConfig).filter(AgentConfig.key == key,
                                     AgentConfig.enabled.is_(True)).first()
    if not r:
        raise HTTPException(404, "Agent 不存在或未启用")
    return {
        "key": r.key, "name": r.name, "persona_name": r.persona_name,
        "avatar": r.avatar, "description": r.description, "persona": r.persona,
        "system_prompt": r.system_prompt, "tools": r.tools or [],
        "bound_model": r.bound_model, "example_dialogue": r.example_dialogue or [],
        "version": r.version,
    }


# ---------- 聊天会话 CRUD ----------
@router.get("/chat/sessions", response_model=list[dict])
def list_sessions(agent_key: str | None = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """按 uid 列出聊天会话，可按 agent_key 过滤。"""
    q = db.query(Conversation).filter(Conversation.owner_id == user.id)
    if agent_key:
        q = q.filter(Conversation.agent_key == agent_key)
    rows = q.order_by(Conversation.updated_at.desc()).limit(100).all()
    return [{
        "id": r.id,
        "agent_key": r.agent_key,
        "title": r.title or "新会话",
        "message_count": len(r.messages or []),
        "is_streaming": r.is_streaming,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in rows]


@router.post("/chat/sessions", response_model=dict)
def create_session(body: dict, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """新建一个会话。body: {agent_key, title?}"""
    agent_key = body.get("agent_key", "director")
    # 验证 Agent 存在
    if not db.query(AgentConfig).filter(AgentConfig.key == agent_key,
                                         AgentConfig.enabled.is_(True)).first():
        raise HTTPException(400, f"Agent 不存在或未启用: {agent_key}")
    sess = Conversation(
        owner_id=user.id, agent_key=agent_key,
        title=body.get("title") or f"与{agent_key}的会话",
        messages=[], snapshot={}, cross_agent_summary="", is_streaming=False,
    )
    db.add(sess); db.commit(); db.refresh(sess)
    return {"id": sess.id, "agent_key": sess.agent_key, "title": sess.title,
            "created_at": sess.created_at.isoformat() if sess.created_at else None}


@router.get("/chat/sessions/{sid}", response_model=dict)
def get_session(sid: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    sess = db.query(Conversation).filter(
        Conversation.id == sid, Conversation.owner_id == user.id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")
    return {
        "id": sess.id, "agent_key": sess.agent_key, "title": sess.title,
        "messages": sess.messages or [], "snapshot": sess.snapshot or {},
        "cross_agent_summary": sess.cross_agent_summary or "",
        "is_streaming": sess.is_streaming,
        "created_at": sess.created_at.isoformat() if sess.created_at else None,
        "updated_at": sess.updated_at.isoformat() if sess.updated_at else None,
    }


@router.delete("/chat/sessions/{sid}")
def delete_session(sid: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    sess = db.query(Conversation).filter(
        Conversation.id == sid, Conversation.owner_id == user.id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")
    db.delete(sess); db.commit()
    return {"ok": True}


@router.patch("/chat/sessions/{sid}")
def rename_session(sid: int, body: dict, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    sess = db.query(Conversation).filter(
        Conversation.id == sid, Conversation.owner_id == user.id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")
    if "title" in body and body["title"]:
        sess.title = body["title"][:200]
    db.commit()
    return {"ok": True, "title": sess.title}


# ---------- 核心：SSE 流式聊天 ----------
@router.post("/chat/sessions/{sid}/stream")
def stream_chat(sid: int, body: dict, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """SSE 流式聊天：聊天即 Agent 大脑。每条消息先意图识别再分流：
    GENERATE 新生成 / OPTIMIZE_LAST 优化上一条 / GUIDE_QUESTION 向导答疑 /
    TOOL_* 自动生图视频配音 / UNKNOWN 主动追问澄清。

    body: {message: str, mentions?: [agent_key,...], platform?, genre?, episode_count?}
    """
    sess = db.query(Conversation).filter(
        Conversation.id == sid, Conversation.owner_id == user.id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")
    # 僵尸锁自动复位：若上一次 SSE 流在客户端断开（未收到 done）导致 is_streaming 永久卡死，
    # 超过 _ZOMBIE_TIMEOUT 秒则视为过期，自动归零让新请求进入，避免反复 409 把用户卡死。
    if sess.is_streaming:
        age = (datetime.utcnow() - (sess.updated_at or datetime.utcnow())).total_seconds()
        if age > _ZOMBIE_TIMEOUT:
            sess.is_streaming = False
            db.commit()
        else:
            raise HTTPException(409, "会话正在生成中，请等待完成")

    agent_cfg_row = db.query(AgentConfig).filter(
        AgentConfig.key == sess.agent_key, AgentConfig.enabled.is_(True)).first()
    if not agent_cfg_row:
        raise HTTPException(400, "该 Agent 未启用")

    user_msg_text = (body.get("message") or "").strip()
    if not user_msg_text:
        raise HTTPException(400, "消息不能为空")
    mentions = body.get("mentions") or []
    platform = body.get("platform") or (sess.snapshot or {}).get("last_platform") or "douyin"
    genre = body.get("genre") or (sess.snapshot or {}).get("last_genre") or "逆袭"
    episode_count = int(body.get("episode_count") or 1)

    def event_stream():
        local_db = SessionLocal()
        try:
            local_sess = local_db.get(Conversation, sid)
            if not local_sess:
                yield f"event: error\ndata: {json.dumps({'msg':'会话不存在'}, ensure_ascii=False)}\n\n"
                return
            local_sess.is_streaming = True
            local_db.commit()

            # 用户消息落库 + 推送
            ts_now = datetime.utcnow().isoformat()
            local_sess.messages = (local_sess.messages or []) + [{
                "role": "user", "agent_key": local_sess.agent_key,
                "content": user_msg_text, "mentions": mentions, "ts": ts_now,
            }]
            local_db.commit()
            yield f"event: user_msg\ndata: {json.dumps({'content': user_msg_text, 'ts': ts_now}, ensure_ascii=False)}\n\n"

            agent_cfg = {
                "persona_name": agent_cfg_row.persona_name or agent_cfg_row.name,
                "system_prompt": agent_cfg_row.system_prompt or agent_cfg_row.prompt or "",
                "persona": agent_cfg_row.persona or "",
                "tools": agent_cfg_row.tools or [],
            }
            ctx = dict(local_sess.snapshot or {})
            # 【跨会话记忆补丁】把本会话已沉淀的 cross_agent_summary 注入 ctx，
            # 让 _build_l0 能把它带进所有 Agent 的 system prompt（跨 turn / 跨 Agent 不失忆）。
            ctx["cross_agent_summary"] = local_sess.cross_agent_summary or ""
            # 【上下文补丁】把本会话最近 8 条对话压成 recent_history 注入所有后续 LLM/工具调用。
            # 之前所有路径只把 user_msg_text 单句喂给 LLM，结果 Agent 每次都"失忆"——
            # 用户在"嫦娥奔月"的对话里点生成视频，结果拍出来的是别的剧本内容。
            recent_history = _recent_history_text((local_sess.messages or []), n=8, each_cap=200)
            # 意图识别主路径切到 LLM 分类器（带 recent_history 以解析指代/复合句/口语化）；
            # LLM 不可用时自动降级正则兜底。
            intent = classify_intent(user_msg_text, ctx, recent_history=recent_history)
            yield f"event: agent_start\ndata: {json.dumps({'agent_key': local_sess.agent_key, 'persona_name': agent_cfg['persona_name'], 'intent': intent}, ensure_ascii=False)}\n\n"

            kbdb = retrieve_kb(local_db, platform, genre)
            profile = {"tags": user.tags or [], "habits": user.habits or {}}

            # 【RAG 单点接入】构造检索增强上下文（L0 记忆 + L1 检索 + L2 重排），供所有分支复用
            from ..rag.context import load_rag_context
            rag_ctx = load_rag_context(local_sess.agent_key, user_msg_text, ctx, user,
                                      local_db, recent_history=recent_history, platform=platform)

            # ----- 1) 文本产物（提示词/文案/咒语）：LLM 生成文本，不调底层生图/视频/TTS -----
            if intent == "TEXT_PROMPT":
                kind = _prompt_kind_of(user_msg_text)
                kind_cn = {"video": "视频提示词", "image": "图片提示词",
                           "tts": "配音/台词文案", "text": "文案/提示词"}[kind]
                yield f"event: agent_thinking\ndata: {json.dumps({'stage':'understanding','text':f'明白！你要的是一段【{kind_cn}】文本给你参考，我直接帮你写，不调底层出片～'}, ensure_ascii=False)}\n\n"
                from ..config import settings
                import queue as _queue, threading as _threading
                _q: "_queue.Queue" = _queue.Queue(); _err = [None]; _content = [None]
                def _prompt_worker():
                    try:
                        if settings.ark_enabled:
                            _content[0] = _gen_prompt_text(user_msg_text, ctx, local_db,
                                                          on_token=lambda tt: _q.put(("token", tt)),
                                                          recent_history=recent_history,
                                                          rag_ctx=rag_ctx)
                        else:
                            raise RuntimeError("方舟未启用")
                    except Exception as e:  # noqa
                        _err[0] = e
                    finally:
                        _q.put(("DONE", None))
                _th = _threading.Thread(target=_prompt_worker, daemon=True); _th.start()
                _first = True
                while True:
                    k, payload = _q.get()
                    if k == "DONE":
                        break
                    if k == "token":
                        if _first:
                            _first = False
                            yield f"event: agent_thinking\ndata: {json.dumps({'stage':'writing','text':f'正在为你写《{kind_cn}》…'}, ensure_ascii=False)}\n\n"
                        yield f"event: token\ndata: {json.dumps({'type':'token','text': payload}, ensure_ascii=False)}\n\n"
                prompt_text = _content[0] if not _err[0] else _gen_prompt_fallback(user_msg_text, recent_history)
                md = f"### 📝 {kind_cn}\n\n" + prompt_text
                yield f"event: done\ndata: {json.dumps({'intent': 'TEXT_PROMPT', 'prompt_kind': kind, 'prompt_text': prompt_text, 'markdown': md}, ensure_ascii=False)}\n\n"
                local_sess.messages = (local_sess.messages or []) + [{
                    "role": "agent", "agent_key": local_sess.agent_key,
                    "persona_name": agent_cfg["persona_name"], "content": md,
                    "prompt_kind": kind, "prompt_text": prompt_text,
                    "ts": datetime.utcnow().isoformat()}]
                local_sess.is_streaming = False
                local_db.commit()
                return

            # ----- 2) 工具意图：用户说『生成视频/配图/配音』即自动生成，不需点击 -----
            if intent in ("TOOL_IMAGE", "TOOL_VIDEO", "TOOL_TTS"):
                label = {"TOOL_IMAGE": "图片", "TOOL_VIDEO": "视频", "TOOL_TTS": "配音"}[intent]
                yield f"event: agent_thinking\ndata: {json.dumps({'stage':'planning','text':f'好的，这就帮你【真调底层模型】生成{label}出片～'}, ensure_ascii=False)}\n\n"
                try:
                    res = _run_tool(intent, user_msg_text, ctx, user, local_db, sid,
                                    recent_history=recent_history, rag_ctx=rag_ctx)
                except Exception as e:  # noqa
                    # 底层出错：友好引导 + 自动降级给提示词文本（不直接失败）
                    friendly = _tool_err_friendly(e)
                    yield f"event: agent_thinking\ndata: {json.dumps({'stage':'understanding','text': friendly}, ensure_ascii=False)}\n\n"
                    fb_text = _gen_prompt_text(user_msg_text, ctx, local_db,
                                              recent_history=recent_history) or _gen_prompt_fallback(user_msg_text, recent_history)
                    fb_md = f"### ⚠️ {label}出片失败，已为你降级生成提示词\n\n{fb_text}"
                    yield f"event: done\ndata: {json.dumps({'intent': intent, 'tool_error': True, 'prompt_kind': _prompt_kind_of(user_msg_text), 'prompt_text': fb_text, 'markdown': fb_md}, ensure_ascii=False)}\n\n"
                    local_sess.messages = (local_sess.messages or []) + [{
                        "role": "agent", "agent_key": local_sess.agent_key,
                        "persona_name": agent_cfg["persona_name"], "content": fb_md,
                        "prompt_kind": _prompt_kind_of(user_msg_text), "prompt_text": fb_text,
                        "ts": datetime.utcnow().isoformat(), "kind": "tool_error"}]
                    local_sess.is_streaming = False
                    local_db.commit()
                    return
                if "error" in res:
                    # 权限/配额等业务错误（_run_tool 主动返回）
                    yield f"event: error\ndata: {json.dumps({'msg': res['error']}, ensure_ascii=False)}\n\n"
                    local_sess.messages = (local_sess.messages or []) + [{
                        "role": "agent", "agent_key": local_sess.agent_key,
                        "persona_name": agent_cfg["persona_name"], "content": res["error"],
                        "ts": datetime.utcnow().isoformat(), "kind": "error"}]
                else:
                    yield f"event: tool_result\ndata: {json.dumps(res, ensure_ascii=False)}\n\n"
                    local_sess.messages = (local_sess.messages or []) + [{
                        "role": "agent", "agent_key": local_sess.agent_key,
                        "persona_name": agent_cfg["persona_name"], "content": f"已为你生成{label}",
                        "tool": res, "ts": datetime.utcnow().isoformat()}]
                local_sess.is_streaming = False
                local_db.commit()
                yield f"event: done\ndata: {json.dumps({'intent': intent}, ensure_ascii=False)}\n\n"
                return

            # ----- 2) 向导问答：旁路入聊天流，自然语言答疑，不写剧本 -----
            if intent == "GUIDE_QUESTION":
                yield f"event: agent_thinking\ndata: {json.dumps({'stage':'understanding','text':'这个问题我帮你查一下知识库～'}, ensure_ascii=False)}\n\n"
                # 直接复用 RAG 上下文（含 KB 检索证据 + 引用），让向导回答"基于证据"
                answer = _rag_guide_answer(user_msg_text, rag_ctx, local_db)
                refs = _extract_refs(rag_ctx)
                yield f"event: guide_answer\ndata: {json.dumps({'answer': answer, 'refs': refs}, ensure_ascii=False)}\n\n"
                local_sess.messages = (local_sess.messages or []) + [{
                    "role": "agent", "agent_key": local_sess.agent_key,
                    "persona_name": agent_cfg["persona_name"], "content": answer,
                    "refs": refs, "kind": "guide_answer", "ts": datetime.utcnow().isoformat()}]
                local_sess.is_streaming = False
                local_db.commit()
                yield f"event: done\ndata: {json.dumps({'intent': intent}, ensure_ascii=False)}\n\n"
                return

            # ----- 3) 优化上一条剧本（上下文一致，patch 而非重生成） -----
            if intent == "OPTIMIZE_LAST":
                last_id = ctx.get("last_script_id")
                last_sc = local_db.get(Script, int(last_id)) if last_id and str(last_id).isdigit() else None
                if not last_sc:
                    clarify = "我找不到上一条剧本啦～先生成一部，或告诉我你想优化哪部？"
                    yield f"event: agent_thinking\ndata: {json.dumps({'stage':'understanding','text':clarify}, ensure_ascii=False)}\n\n"
                    local_sess.messages = (local_sess.messages or []) + [{
                        "role": "agent", "agent_key": local_sess.agent_key,
                        "persona_name": agent_cfg["persona_name"], "content": clarify,
                        "ts": datetime.utcnow().isoformat()}]
                    local_sess.is_streaming = False
                    local_db.commit()
                    yield f"event: done\ndata: {json.dumps({'intent': intent}, ensure_ascii=False)}\n\n"
                    return
                last_title = last_sc.title
                last_base = last_title.strip("《》") if last_title else "上一条剧本"
                yield f"event: agent_thinking\ndata: {json.dumps({'stage':'understanding','text':f'明白，我基于《{last_base}》帮你优化：{user_msg_text}'}, ensure_ascii=False)}\n\n"
                from ..generator import optimize_script_via_ark, optimize_script_fallback, render_markdown
                from ..config import settings
                import queue as _queue, threading as _threading
                _q: "_queue.Queue" = _queue.Queue(); _err = [None]; _content = [None]
                def _opt_worker():
                    try:
                        if settings.ark_enabled:
                            _content[0] = optimize_script_via_ark(
                                last_sc.content_json, user_msg_text, last_sc.platform, last_sc.genre,
                                last_sc.episode_count, local_sess.agent_key, profile, kbdb,
                                agent_cfg, db=None, on_token=lambda t: _q.put(("token", t)),
                                recent_history=recent_history, rag_ctx=rag_ctx)
                        else:
                            raise RuntimeError("方舟未启用")
                    except Exception as e:  # noqa
                        _err[0] = e
                    finally:
                        _q.put(("DONE", None))
                _th = _threading.Thread(target=_opt_worker, daemon=True); _th.start()
                _first = True
                while True:
                    kind, payload = _q.get()
                    if kind == "DONE":
                        break
                    if kind == "token":
                        if _first:
                            _first = False
                            yield f"event: agent_thinking\ndata: {json.dumps({'stage':'writing','text':f'正在为你打磨《{last_title}》…'}, ensure_ascii=False)}\n\n"
                        yield f"event: token\ndata: {json.dumps({'type':'token','text': payload}, ensure_ascii=False)}\n\n"
                content = _content[0] if not _err[0] else optimize_script_fallback(last_sc.content_json, user_msg_text)
                sc = Script(owner_id=user.id, creator_username=user.username,
                            title=content["project"]["项目名"], platform=last_sc.platform,
                            genre=last_sc.genre, episode_count=last_sc.episode_count,
                            prompt=user_msg_text, status="done", content_json=content,
                            is_demo=False, agent_key=local_sess.agent_key,
                            collaborator_agent_keys=mentions, session_id=local_sess.id,
                            parent_id=last_sc.id)
                local_db.add(sc); local_db.commit(); local_db.refresh(sc)
                md = render_markdown(content)
                yield f"event: done\ndata: {json.dumps({'script_id': sc.id, 'title': sc.title, 'agent_key': local_sess.agent_key, 'markdown': md, 'parent_id': last_sc.id, 'is_optimize': True}, ensure_ascii=False)}\n\n"
                local_sess.messages = (local_sess.messages or []) + [{
                    "role": "agent", "agent_key": local_sess.agent_key,
                    "persona_name": agent_cfg["persona_name"], "content": md, "script_id": sc.id,
                    "parent_id": last_sc.id, "is_optimize": True, "ts": datetime.utcnow().isoformat()}]
                local_sess.snapshot = {**(local_sess.snapshot or {}),
                                       "last_script_id": sc.id, "last_title": sc.title,
                                       "last_platform": last_sc.platform, "last_genre": last_sc.genre}
                yield from _finish_collab(local_sess, local_db, agent_cfg, mentions, content)
                local_sess.is_streaming = False
                local_db.commit()
                return

            # ----- 4) 新生成 -----
            if intent == "GENERATE":
                base = (user_msg_text[:18]) or "新剧本"
                yield f"event: agent_thinking\ndata: {json.dumps({'stage':'understanding','text':f'好的，我先理一下需求：{user_msg_text}（平台 {platform} / 类型 {genre}）'}, ensure_ascii=False)}\n\n"
                from ..generator import build_script_via_ark, build_script, render_markdown
                from ..config import settings
                import queue as _queue, threading as _threading
                _q: "_queue.Queue" = _queue.Queue(); _err = [None]; _content = [None]
                def _gen_worker():
                    try:
                        if settings.ark_enabled:
                            _content[0] = build_script_via_ark(
                                prompt=user_msg_text, platform_key=platform, genre_key=genre,
                                episode_count=episode_count, agent_key=local_sess.agent_key,
                                profile=profile, kbdb=kbdb, agent_cfg=agent_cfg, db=None,
                                on_token=lambda t: _q.put(("token", t)),
                                recent_history=recent_history, rag_ctx=rag_ctx)
                        else:
                            raise RuntimeError("方舟未启用")
                    except Exception as e:  # noqa
                        _err[0] = e
                    finally:
                        _q.put(("DONE", None))
                _th = _threading.Thread(target=_gen_worker, daemon=True); _th.start()
                _first = True
                while True:
                    kind, payload = _q.get()
                    if kind == "DONE":
                        break
                    if kind == "token":
                        if _first:
                            _first = False
                            yield f"event: agent_thinking\ndata: {json.dumps({'stage':'writing','text':f'正在为你写《{base}》的开场…'}, ensure_ascii=False)}\n\n"
                        yield f"event: token\ndata: {json.dumps({'type':'token','text': payload}, ensure_ascii=False)}\n\n"
                content = build_script(prompt=user_msg_text, platform_key=platform, genre_key=genre,
                                       episode_count=episode_count, agent_key=local_sess.agent_key,
                                       profile=profile, kbdb=kbdb) if _err[0] else _content[0]
                sc = Script(owner_id=user.id, creator_username=user.username,
                            title=content["project"]["项目名"], platform=platform, genre=genre,
                            episode_count=episode_count, prompt=user_msg_text, status="done",
                            content_json=content, is_demo=False, agent_key=local_sess.agent_key,
                            collaborator_agent_keys=mentions, session_id=local_sess.id)
                local_db.add(sc); local_db.commit(); local_db.refresh(sc)
                md = render_markdown(content)
                yield f"event: done\ndata: {json.dumps({'script_id': sc.id, 'title': sc.title, 'agent_key': local_sess.agent_key, 'markdown': md}, ensure_ascii=False)}\n\n"
                local_sess.messages = (local_sess.messages or []) + [{
                    "role": "agent", "agent_key": local_sess.agent_key,
                    "persona_name": agent_cfg["persona_name"], "content": md, "script_id": sc.id,
                    "ts": datetime.utcnow().isoformat()}]
                local_sess.snapshot = {**(local_sess.snapshot or {}),
                                       "last_script_id": sc.id, "last_title": sc.title,
                                       "last_platform": platform, "last_genre": genre}
                yield from _finish_collab(local_sess, local_db, agent_cfg, mentions, content)
                local_sess.is_streaming = False
                local_db.commit()
                return

            # ----- 5) UNKNOWN：主动追问澄清（不默认猜测） -----
            clarify = _clarify_text(user_msg_text, ctx, recent_history=recent_history)
            yield f"event: agent_thinking\ndata: {json.dumps({'stage':'understanding','text': clarify}, ensure_ascii=False)}\n\n"
            local_sess.messages = (local_sess.messages or []) + [{
                "role": "agent", "agent_key": local_sess.agent_key,
                "persona_name": agent_cfg["persona_name"], "content": clarify,
                "ts": datetime.utcnow().isoformat()}]
            local_sess.is_streaming = False
            local_db.commit()
            yield f"event: done\ndata: {json.dumps({'intent': intent}, ensure_ascii=False)}\n\n"
            return
        except Exception as e:  # noqa
            try:
                local_sess.is_streaming = False
                local_db.commit()
            except Exception:
                pass
            yield f"event: error\ndata: {json.dumps({'msg': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            # 【跨会话记忆】turn 结束后后台异步提炼：用户习惯 + 会话摘要（不阻塞 SSE）
            try:
                from ..rag.memory import schedule_learn
                schedule_learn(user.id, local_sess.agent_key, local_sess.id,
                               (local_sess.messages or []))
            except Exception:
                pass
            local_db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- 主动解除会话的 SSE 僵尸锁（前端遇到 409 时一键解锁） ----------
@router.post("/chat/sessions/{sid}/reset-streaming")
def reset_streaming(sid: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """主动把会话 is_streaming 复位为 False（前端捕获 409 冲突后调用，解除卡死的锁）。"""
    sess = db.query(Conversation).filter(
        Conversation.id == sid, Conversation.owner_id == user.id).first()
    if not sess:
        raise HTTPException(404, "会话不存在")
    was = bool(sess.is_streaming)
    if sess.is_streaming:
        sess.is_streaming = False
        db.commit()
    return {"ok": True, "was_streaming": was}


def _finish_collab(local_sess, local_db, agent_cfg, mentions, content) -> "generator":
    """@Agent 召唤：被召唤 Agent 在同一会话接力追加批注（仅生成/优化剧本后生效）。"""
    for m in mentions:
        if m == local_sess.agent_key:
            continue
        m_row = local_db.query(AgentConfig).filter(
            AgentConfig.key == m, AgentConfig.enabled.is_(True)).first()
        if not m_row:
            continue
        collab_note = _collab_note(m_row, content, (local_sess.messages or [{}])[-1].get("content", ""))
        local_sess.messages = (local_sess.messages or []) + [{
            "role": "agent", "agent_key": m,
            "persona_name": m_row.persona_name or m_row.name,
            "content": collab_note, "ts": datetime.utcnow().isoformat(),
            "summoned_by": local_sess.agent_key,
        }]
        local_sess.cross_agent_summary = (
            (local_sess.cross_agent_summary or "") + f"\n[{m} 协作批注]"
        )[-1000:]
        yield f"event: collab\ndata: {json.dumps({'agent_key': m, 'persona_name': m_row.persona_name or m_row.name, 'content': collab_note}, ensure_ascii=False)}\n\n"


def _collab_note(agent_row, content: dict, user_msg: str) -> str:
    """被召唤 Agent 给出的协作批注。"""
    persona_name = agent_row.persona_name or agent_row.name
    key = agent_row.key
    proj = content.get("project", {})
    title = proj.get("项目名", "")
    if key == "reviewer":
        return (f"【{persona_name} 协作批注】\n"
                f"已快速复核《{title}》：\n"
                f"• 类型与平台匹配度：OK\n"
                f"• 合规红线：已对照『{proj.get('合规红线','')}』扫描，主流桥段风险低\n"
                f"• 建议：发布前请人工复核敏感词与价值观引导，避免极端化表达。")
    if key == "cameraman":
        return (f"【{persona_name} 协作批注】\n"
                f"镜头语言已就位；建议在高潮场次加重：特写→大特写递进 + 鼓点 BGM + 暖橙→高饱和爆发；\n"
                f"路人环境镜头建议每个冲突场至少 1 个围观/环境反衬镜头。")
    if key == "writer":
        return (f"【{persona_name} 协作批注】\n"
                f"故事骨架 OK；建议钩子密度再加密一档（前 3 秒一定要暴力破题），\n"
                f"集尾留 1 个明确悬念引全集。")
    if key == "narration":
        return (f"【{persona_name} 协作批注】\n"
                f"已识别 2 处关键心理时刻，可补 OS/内心独白（建议配大特写 + 心跳音效）。")
    return f"【{persona_name} 协作批注】\n已阅。"


# ---------- 跨 Agent 共享上下文（数据互通） ----------
@router.get("/me/cross-context", response_model=dict)
def my_cross_context(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """返回用户所有会话的跨 Agent 摘要合集（供新建会话时注入上下文）。"""
    rows = db.query(Conversation).filter(
        Conversation.owner_id == user.id).order_by(Conversation.updated_at.desc()).limit(20).all()
    merged = []
    for r in rows:
        if r.cross_agent_summary:
            merged.append({"agent_key": r.agent_key, "summary": r.cross_agent_summary})
    return {"items": merged, "merged": "\n".join(x["summary"] for x in merged)}


# ---------- 聊天中按需触发的工具（带权限校验） ----------
@router.post("/chat/sessions/{sid}/tool/image")
def chat_tool_image(sid: int, body: dict, db: Session = Depends(get_db),
                    user: User = Depends(require_feature("image_generate"))):
    """聊天中触发生图：先校验登录+会员+配额，再调用 Seedream。"""
    from ..clients import ark_image
    from ..config import settings
    prompt = (body.get("prompt") or "").strip()
    quality = body.get("quality") or "2K"
    if quality == "4K":
        # 二次校验 4K 权限
        from ..deps import get_membership_config
        cfg = get_membership_config(db)
        if not cfg.get("image_4k_enabled", False):
            raise HTTPException(403, "后台未开启 4K 选项")
        from ..deps import require_feature as _rf
        # 显式校验 4K 档位
        from ..deps import level_ge
        if not level_ge(user.membership_level, "pro"):
            raise HTTPException(403, "4K 生图需会员Pro")
    if not prompt:
        raise HTTPException(400, "prompt 不能为空")
    from ..deps import get_membership_config
    cfg = get_membership_config(db)
    try:
        url = ark_image.save_image(prompt, size=quality,
                                   badge_text=cfg.get("badge_text", "AI 生成"),
                                   with_badge=cfg.get("watermark_badge", True))
    except Exception as e:
        # 统一结构化错误：前端拿到 JSON {error, error_kind, prompt}，不再显示 raw
        msg = _tool_err_friendly(e)
        return JSONResponse({"error": msg, "error_kind": _tool_err_kind(str(e)),
                             "prompt": prompt, "kind": "image", "quality": quality},
                            status_code=200)
    asset = Asset(owner_id=user.id, kind="image", url=url, prompt=prompt,
                  meta={"quality": quality, "session_id": sid, "from": "chat_tool"})
    db.add(asset); db.commit()
    return {"url": url, "kind": "image", "asset_id": asset.id}


@router.post("/chat/sessions/{sid}/tool/video")
def chat_tool_video(sid: int, body: dict, db: Session = Depends(get_db),
                    user: User = Depends(require_feature("video_generate"))):
    """聊天中触发生视频：仅会员Pro，调用 Seedance。"""
    from ..clients import ark_video
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt 不能为空")
    try:
        url = ark_video.generate_video(prompt)
    except Exception as e:
        msg = _tool_err_friendly(e)
        return JSONResponse({"error": msg, "error_kind": _tool_err_kind(str(e)),
                             "prompt": prompt, "kind": "video"},
                            status_code=200)
    asset = Asset(owner_id=user.id, kind="video", url=url, prompt=prompt,
                  meta={"session_id": sid, "from": "chat_tool"})
    db.add(asset); db.commit()
    return {"url": url, "kind": "video", "asset_id": asset.id}


@router.post("/chat/sessions/{sid}/tool/tts")
def chat_tool_tts(sid: int, body: dict, db: Session = Depends(get_db),
                  user: User = Depends(require_feature("video_generate"))):
    """聊天中触发 TTS（仅 Pro，与视频功能同档）。
    注：tts_client.synthesize 已把 mp3 落盘到 /static/assets/，返回的是 URL 字符串。
    """
    from ..clients import tts_client
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    voice = body.get("voice") or "default"
    try:
        url = tts_client.synthesize(text, voice_type=voice)
    except Exception as e:
        msg = _tool_err_friendly(e)
        return JSONResponse({"error": msg, "error_kind": _tool_err_kind(str(e)),
                             "prompt": text, "kind": "audio"},
                            status_code=200)
    asset = Asset(owner_id=user.id, kind="audio", url=url, prompt=text,
                  meta={"session_id": sid, "from": "chat_tool"})
    db.add(asset); db.commit()
    return {"url": url, "kind": "audio", "text": text[:60]}