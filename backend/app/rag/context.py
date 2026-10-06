"""RAG 上下文控制器（单点接入）：组装所有 Agent 的检索增强上下文。

_load_rag_context(agent_key, user_msg, ctx, user, db, recent_history)
  → 返回可注入 system prompt 的上下文字符串（含引用编号【KB-xx】【剧本-xx】）

组成：
- L0 记忆：用户画像(tags/habits) + 跨会话摘要(cross_agent_summary) + 最近产出(last_*)
- L1 检索：kb_chunks + script_chunks（向量语义流 + BM25 关键词流 + RRF 融合，元数据硬过滤）
- L2 重排：LLM rerank top-20 → top-4（按相关性/平台契合/时效），附引用编号

所有 Agent 入口统一调本函数，未来调优只改这里。
"""
from __future__ import annotations

from ..clients import ark_chat
from ..config import settings
from .retrieve import retrieve, Hit


def _build_l0(user, ctx: dict, recent_history: str) -> str:
    """L0 记忆层：把『用户是谁 / 聊到哪了 / 最近产出』压成文本。"""
    lines = []
    if user and (user.tags or user.habits):
        tags = "、".join(user.tags or [])
        hab = user.habits or {}
        hab_s = "；".join(f"{k}={v}" for k, v in hab.items() if v) if isinstance(hab, dict) else ""
        if tags:
            lines.append(f"【用户画像】偏好标签：{tags}")
        if hab_s:
            lines.append(f"【用户习惯】{hab_s}")
    last_title = ctx.get("last_title") or ctx.get("last_script_title")
    if last_title:
        lines.append(f"【最近产出】上一条剧本《{last_title}》(id={ctx.get('last_script_id')})，"
                     f"平台={ctx.get('last_platform','')}，类型={ctx.get('last_genre','')}")
    summary = ctx.get("cross_agent_summary") or ""
    if summary:
        lines.append(f"【跨会话摘要】{summary}")
    if recent_history:
        lines.append(f"【最近对话】\n{recent_history}")
    return "\n".join(lines)


def _rerank(user_msg: str, hits: list[Hit], top_k: int = 4) -> list[Hit]:
    """L2 重排：LLM 按相关性 + 平台契合 + 时效重排 top-20 → top-4。失败则保留 RRF 顺序。"""
    if not hits:
        return []
    if not settings.ark_enabled or len(hits) <= top_k:
        return hits[:top_k]
    cand = hits[:20]
    block = "\n\n".join(
        f"[{i}] ({h.source}/{h.sublib}) {h.title}\n{h.content[:500]}"
        for i, h in enumerate(cand))
    sys_p = (
        f"你是短剧 RAG 重排器。下面是一组知识候选，请按与【用户问题】的相关性、"
        f"平台契合度、时效，选出最相关的 {top_k} 条。只输出编号列表（如 3,1,0,7），"
        f"不要解释。"
    )
    # 【修复】原 f-string + %d 混用在 Python 3.13 下会被 KB 文本里的 '%' 字符引爆
    # (ValueError: unsupported format character)。改用纯 f-string 防患。
    user_p = (
        f"【用户问题】{user_msg}\n\n【候选】\n{block}\n\n"
        f"最相关编号（最多 {top_k} 个）："
    )
    try:
        out = ark_chat.chat_complete(sys_p, user_p, model=settings.ARK_MODEL_MINI,
                                     temperature=0.0, max_tokens=40, timeout=12)
        picked = []
        for tok in out.replace("，", ",").split(","):
            tok = tok.strip()
            if tok.isdigit():
                idx = int(tok)
                if 0 <= idx < len(cand):
                    picked.append(cand[idx])
        if picked:
            return picked[:top_k]
    except Exception:
        pass
    return cand[:top_k]


def _format(hits: list[Hit]) -> str:
    """把重排结果拼成可注入 system 的上下文（带引用编号）。"""
    if not hits:
        return ""
    blocks = []
    for i, h in enumerate(hits):
        ref = f"KB-{h.ref_id}" if h.source == "kb" else f"剧本-{h.ref_id}"
        blocks.append(f"【{ref}】（{h.title}）\n{h.content[:700]}")
    head = ("以下是与用户问题相关的检索证据，**请优先依据这些证据回答**，并在引用处标注来源编号；"
            "若证据不足，可基于你的领域知识补充，但需说明：")
    return head + "\n\n" + "\n\n".join(blocks)


def load_rag_context(agent_key: str, user_msg: str, ctx: dict, user, db,
                     recent_history: str = "", platform: str = None,
                     sublib: str = None, top_k: int = 4) -> str:
    """单点 RAG 上下文装配。返回注入 system 的字符串（空串=无证据）。"""
    l0 = _build_l0(user, ctx, recent_history)
    # L1 检索（向量流 + BM25 流 + RRF）；embedding 不可用时自动降级 BM25
    try:
        hits = retrieve(user_msg, db, top_k=20, platform=platform, sublib=sublib,
                        owner_id=user.id if user else None, scope="all")
    except Exception:
        hits = []
    # L2 重排
    hits = _rerank(user_msg, hits, top_k=top_k)
    l1l2 = _format(hits)
    parts = [p for p in (l0, l1l2) if p]
    return "\n\n".join(parts)
