"""意图分类器：轻量 LLM 分类器（主） + 正则兜底（二元） + 缓存。

设计目标：
- 主路径用方舟 chat 单次推理（temperature=0, max_tokens=10），返回 8 类 enum 单词
- 缓存：hash(user_msg + ctx + recent_history) 命中直接返回，省成本
- 兜底：LLM 超时/失败/不可用 → 正则二元判定（TOOL_* vs 其他），消除歧义
- 解决 chat.py 原纯正则"看字面不懂语义/指代/复合句"的体感问题

调用约定：
    from ..clients.intent_classifier import classify_intent
    intent = classify_intent(user_msg, ctx, recent_history="")
"""
from __future__ import annotations

import re as _re
import hashlib
import time

from ..config import settings
from ..clients import ark_chat

# 8 类意图枚举
INTENTS = {
    "TEXT_PROMPT", "GENERATE", "OPTIMIZE_LAST", "GUIDE_QUESTION",
    "TOOL_IMAGE", "TOOL_VIDEO", "TOOL_TTS", "UNKNOWN",
}

# 兜底正则（精简二元：强 TOOL 动作 vs 其他）
_INTENT_TOOL = _re.compile(
    r"(生成视频|做个视频|出视频|做段视频|生成.*视频|配.*视频|视频.*生成|"
    r"生成图|生图|出图|配图|配个图|做个图|生成图片|生成一张图|"
    r"配音|读一下|生成音频|朗读|生成语音|来段音频)")
_INTENT_GEN = _re.compile(
    r"(写一|生成一|来一|创作一|做一[部集]|一部.*短剧$|给我写|帮我生成|"
    r"帮我做|来个.*短剧|构思一|写一部|生成一部|拍一部|写个|编一|写篇|创作)")
_INTENT_OPT = _re.compile(
    r"(优化|改一下|改一版|改一改|调整|修改|完善|润色|精修|再改|第二版|"
    r"换个结尾|换个开头|加一场|加一集|缩短|扩写|重新调整|打磨|升一版|升级|微调|"
    r"换风格|改风格|改调|改掉|改成|调成|重做|翻新)")


def _fallback_regex(text: str, ctx: dict) -> str:
    """LLM 不可用时的兜底：结合 ctx.last_script_id 走原优先级逻辑（简化）。"""
    t = (text or "").lower().strip()
    has_last = bool(ctx.get("last_script_id"))
    # 1) 文本产物（提示词/文案）
    if _re.search(r"(提示词|prompt|咒语|描述词|文生图|图生图|分镜词|分镜脚本|"
                  r"口播文案|广告文案|旁白文案|视频文案|脚本词|台词稿|解说词|"
                  r"配音词|配音台词|配音文稿|配音稿|配音脚本|写配音|一段配音|给段配音|"
                  r"写视频|写段视频|写图|写张图|写段图|一段文案|一句文案|文案|给个词|"
                  r"写段词|出个词|口播|旁白|解说|台词)", t):
        return "TEXT_PROMPT"
    # 2) 强疑问/咨询
    if _re.search(r"(怎么|如何|为什么|啥是|什么是|步骤|教程|教我|流程|注意什么|"
                  r"有啥风险|风险|版权|aigc|平台.*?选|变现|过审|分镜|合规|红线|"
                  r"知识|怎么用|啥|哪|哪里|哪个)", t):
        return "GUIDE_QUESTION"
    # 3) 工具强动作
    m = _INTENT_TOOL.search(t)
    if m:
        g = m.group()
        if "视频" in g:
            return "TOOL_VIDEO"
        if "图" in g:
            return "TOOL_IMAGE"
        return "TOOL_TTS"
    # 4) 优化（需有上一条）
    if has_last and _INTENT_OPT.search(t):
        return "OPTIMIZE_LAST"
    if has_last and _re.search(r"(再|加|长|短|快|慢|多|少|改|换|去|添|补|增强|弱化|续|重|调)", t):
        return "OPTIMIZE_LAST"
    # 5) 生成
    if _INTENT_GEN.search(t):
        return "GENERATE"
    return "UNKNOWN"


# ----------------- 缓存 -----------------
_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 300.0          # 5 分钟
_CACHE_MAX = 2000


def _cache_key(text: str, ctx: dict, recent_history: str) -> str:
    raw = f"{text}|{sorted(ctx.items())}|{recent_history}"
    return hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()


def _cache_get(key: str) -> str | None:
    v = _CACHE.get(key)
    if not v:
        return None
    ts, intent = v
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return intent


def _cache_set(key: str, intent: str) -> None:
    if len(_CACHE) > _CACHE_MAX:
        # 简单清理：弹出最早一条
        try:
            _CACHE.pop(next(iter(_CACHE)))
        except Exception:
            pass
    _CACHE[key] = (time.time(), intent)


def _classify_by_llm(text: str, ctx: dict, recent_history: str) -> str | None:
    """调方舟单次推理分类。返回合法 enum 或 None（失败）。"""
    if not settings.ark_enabled:
        return None
    last_title = ctx.get("last_title") or ctx.get("last_script_title") or ""
    sys_p = (
        "你是短剧创作 Agent 的意图路由器。根据用户【最近对话】和【用户最新消息】，"
        "把意图归类为下列 8 类之一。**只输出一个英文单词**（不要解释、不要标点、不要引号）：\n"
        "TEXT_PROMPT（要提示词/文案/台词等纯文本产物，不调底层出片）\n"
        "GENERATE（要生成一部新剧本）\n"
        "OPTIMIZE_LAST（要修改/优化/调整上一条剧本或产物）\n"
        "GUIDE_QUESTION（问短剧相关知识，如怎么过审/怎么变现/平台怎么选）\n"
        "TOOL_IMAGE（要真调模型出图）\n"
        "TOOL_VIDEO（要真调模型出视频）\n"
        "TOOL_TTS（要真调模型配音）\n"
        "UNKNOWN（意图不清）\n"
        "注意：用户若说『这个/刚才/那段/帮我改/优化一下』等指代，结合【最近对话】判断——"
        "若上文在聊某剧本，则大概率是 OPTIMIZE_LAST；若上文在聊知识，则可能是 GUIDE_QUESTION。"
    )
    hist_block = f"【最近对话】\n{recent_history}\n" if recent_history else ""
    if last_title:
        hist_block += f"（上下文：上一条剧本是《{last_title}》）\n"
    user_p = f"{hist_block}\n【用户最新消息】\n{text}\n\n意图："
    try:
        out = ark_chat.chat_complete(sys_p, user_p, model=settings.ARK_MODEL_MINI,
                                     temperature=0.0, max_tokens=12, timeout=8.0)
    except Exception:
        return None
    # 解析：取返回文本中第一个匹配枚举的单词
    out_u = (out or "").strip().upper()
    for it in INTENTS:
        if it in out_u:
            return it
    return None


def classify_intent(text: str, ctx: dict, recent_history: str = "") -> str:
    """意图分流主入口：LLM 分类器（带缓存）→ 失败降级正则兜底。"""
    key = _cache_key(text, ctx, recent_history)
    cached = _cache_get(key)
    if cached:
        return cached
    intent = _classify_by_llm(text, ctx, recent_history)
    if intent and intent in INTENTS:
        _cache_set(key, intent)
        return intent
    # 降级：正则兜底
    fb = _fallback_regex(text, ctx)
    _cache_set(key, fb)
    return fb


def clear_cache() -> None:
    _CACHE.clear()
