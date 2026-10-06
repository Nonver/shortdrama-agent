"""跨会话记忆与用户习惯自动提炼（L0 记忆的写入端）。

设计：在每次聊天 turn 结束后由 stream_chat 起一个【后台守护线程】调用本模块的
schedule_learn，不阻塞 SSE。线程内独立开 SessionLocal，做两件事：
  1) 提炼用户稳定创作习惯 → 合并写回 User.habits（最新偏好优先，空值不覆盖）
  2) 生成本次会话的精炼摘要 → 追加到 Conversation.cross_agent_summary
两者随后被 rag/context.py 的 _build_l0 注入到所有 Agent 的 system prompt，
实现"跨会话不失忆 / 越用越懂用户"。

节流：每 3 条用户消息才学一次，避免每个 token 都打 LLM。
ark 未启用时直接跳过（零成本降级）。
"""
from __future__ import annotations

import threading

from ..db import SessionLocal
from ..clients import ark_chat
from ..config import settings


def _extract_habits_llm(history_text: str) -> dict:
    """调方舟 mini 从对话历史提炼用户稳定创作偏好，返回 dict（只填高置信字段）。"""
    sys_p = (
        "你是『AI 短剧创作』用户习惯提炼器。从对话历史中提取该用户的稳定创作偏好，"
        "只输出 JSON，可用字段：episode_count(整数), genre(字符串), platform(字符串), "
        "hook_style(字符串), tone(字符串), language(字符串)。"
        "只填你高置信度观察到的字段，没观察到的绝对不要编造。示例：{\"genre\":\"逆袭\",\"platform\":\"红果\"}"
    )
    try:
        out = ark_chat.chat_complete(sys_p, history_text[-1500:], model=settings.ARK_MODEL_MINI,
                                     temperature=0.0, max_tokens=200, timeout=15)
        obj = ark_chat.extract_json(out)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _summarize_llm(agent_key: str, history_text: str) -> str:
    """生成本次会话精炼摘要（2-3 句中文，纯文本）。"""
    sys_p = (
        f"你是短剧创作 Agent（{agent_key}）的会话记忆器。用 2-3 句中文概括本次会话的核心："
        "用户在做什么项目、关键决策、未决问题。只输出纯文本，不要标题、不要编号。"
    )
    try:
        return (ark_chat.chat_complete(sys_p, history_text[-1500:], model=settings.ARK_MODEL_MINI,
                                        temperature=0.0, max_tokens=200, timeout=15) or "").strip()
    except Exception:
        return ""


def learn_from_turn(user_id: int, agent_key: str, conversation_id: int, history_text: str) -> None:
    """后台线程体：提炼 habits + 跨会话摘要并写库。失败静默回滚。"""
    if not settings.ark_enabled:
        return
    db = SessionLocal()
    try:
        from ..models import User, Conversation
        user = db.get(User, user_id)
        conv = db.get(Conversation, conversation_id)
        if not user or not conv:
            return
        # 1) habits 合并（最新非空值优先）
        new_h = _extract_habits_llm(history_text)
        if isinstance(new_h, dict) and new_h:
            merged = dict(user.habits or {})
            for k, v in new_h.items():
                if v not in (None, "", [], {}):
                    merged[k] = v
            if merged != (user.habits or {}):
                user.habits = merged
        # 2) 会话摘要追加
        s = _summarize_llm(agent_key, history_text)
        if s:
            prev = conv.cross_agent_summary or ""
            conv.cross_agent_summary = (prev + f"\n[{agent_key}] {s}")[-1500:]
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def schedule_learn(user_id: int, agent_key: str, conversation_id: int, messages: list) -> None:
    """在 stream_chat 的 done 后调用：节流 + 起后台线程（不阻塞 SSE）。"""
    user_msgs = [m for m in (messages or []) if m.get("role") == "user"]
    # 节流：每 3 条用户消息才学一次
    if len(user_msgs) % 3 != 0:
        return
    history = "\n".join(
        f"[{'用户' if m.get('role') == 'user' else (m.get('persona_name') or 'Agent')}] "
        f"{(m.get('content') or '')[:300]}"
        for m in (messages or [])[-12:]
    )
    if not history.strip():
        return
    t = threading.Thread(target=learn_from_turn,
                         args=(user_id, agent_key, conversation_id, history),
                         daemon=True)
    t.start()
