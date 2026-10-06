"""后台：意图识别测试台 + RAG 监控 + 用户反馈。

提供：
- POST /api/admin/intent-probe  批量测意图分类器（给样本+期望，看命中率）
- GET  /api/admin/rag-stats     RAG 入库统计（kb/script 块数、向量覆盖率、子库分布）
- POST /api/admin/rag-probe     单条 query 检索召回预览（看 top 命中与引用）
- POST /api/feedback            用户对话反馈（赞/踩 + 备注）
- GET  /api/admin/feedback      后台查看反馈汇总与明细
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import KbChunk, ScriptChunk, Feedback, User
from ..deps import require_admin, get_current_user
from ..clients.intent_classifier import classify_intent, INTENTS

router = APIRouter(prefix="/api", tags=["admin-rag"])


# ---------------- Schemas ----------------
class IntentSample(BaseModel):
    text: str
    expect: str | None = None
    ctx: dict = {}
    recent: str = ""


class IntentProbeReq(BaseModel):
    samples: list[IntentSample]


class RagProbeReq(BaseModel):
    query: str
    top_k: int = 10
    platform: str | None = None
    sublib: str | None = None
    owner_id: int | None = None


class FeedbackReq(BaseModel):
    session_id: int | None = None
    agent_key: str = ""
    rating: int = 0          # 1 赞 / -1 踩
    note: str = ""
    meta: dict = {}


# ---------------- 意图测试台 ----------------
@router.post("/admin/intent-probe")
def intent_probe(req: IntentProbeReq, user: User = Depends(require_admin)):
    """批量跑意图分类器，返回每条预测 + 与 expect 的命中情况 + 总体命中率。"""
    results = []
    correct = 0
    total = 0
    for s in req.samples:
        predicted = classify_intent(s.text, s.ctx or {}, recent_history=s.recent or "")
        ok = None
        if s.expect:
            total += 1
            ok = (predicted == s.expect)
            if ok:
                correct += 1
        results.append({"text": s.text, "predicted": predicted,
                        "expect": s.expect, "ok": ok})
    return {
        "intents": sorted(INTENTS),
        "total": len(results),
        "labeled": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else None,
        "results": results,
    }


# ---------------- RAG 监控统计 ----------------
@router.get("/admin/rag-stats")
def rag_stats(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """RAG 入库与向量覆盖统计。"""
    kb_total = db.scalar(select(func.count()).select_from(KbChunk)) or 0
    kb_vec = db.scalar(
        select(func.count()).select_from(KbChunk).where(KbChunk.embedding.isnot(None))) or 0
    sc_total = db.scalar(select(func.count()).select_from(ScriptChunk)) or 0
    sc_vec = db.scalar(
        select(func.count()).select_from(ScriptChunk).where(ScriptChunk.embedding.isnot(None))) or 0
    # 子库分布
    from sqlalchemy import text as _text
    sublib_rows = db.execute(
        _text("SELECT sublib, COUNT(*) FROM kb_chunks GROUP BY sublib")).fetchall()
    kb_model = (db.scalar(
        select(KbChunk.embedding_model).select_from(KbChunk).limit(1)) or "") if kb_total else ""
    return {
        "kb_chunks": kb_total,
        "kb_chunks_with_vector": kb_vec,
        "kb_vector_coverage": round(kb_vec / kb_total, 3) if kb_total else 0.0,
        "script_chunks": sc_total,
        "script_chunks_with_vector": sc_vec,
        "script_vector_coverage": round(sc_vec / sc_total, 3) if sc_total else 0.0,
        "kb_by_sublib": {r[0] or "": r[1] for r in sublib_rows},
        "embedding_model": kb_model or "未记录",
        "note": ("向量流已启用（向量+BM25+RRF 融合）；如需切换纯文本 embedding，"
                 "在方舟「在线推理」建接入点拿到 ep-xxx 后改 .env 的 ARK_MODEL_EMBEDDING 即可。"
                 ) if kb_total and kb_vec == kb_total else "向量覆盖不足，重跑 seed_rag --all 补向量。",
    }


# ---------------- RAG 检索预览 ----------------
@router.post("/admin/rag-probe")
def rag_probe(req: RagProbeReq, db: Session = Depends(get_db),
              user: User = Depends(require_admin)):
    """单条 query 检索召回预览（看 top 命中与引用编号）。"""
    from ..rag.retrieve import retrieve
    hits = retrieve(req.query, db, top_k=req.top_k, platform=req.platform,
                    sublib=req.sublib, owner_id=req.owner_id, scope="all")
    out = []
    for h in hits:
        ref = f"KB-{h.ref_id}" if h.source == "kb" else f"剧本-{h.ref_id}"
        out.append({
            "ref": ref, "source": h.source, "sublib": h.sublib,
            "platform": h.platform, "title": h.title,
            "score": round(h.score, 4), "content": h.content[:240],
        })
    return {"query": req.query, "count": len(out), "hits": out}


# ---------------- 用户反馈 ----------------
@router.post("/feedback")
def submit_feedback(req: FeedbackReq, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """用户对话反馈（赞/踩 + 备注），写入 feedbacks 表供后台监控。"""
    fb = Feedback(owner_id=user.id, session_id=req.session_id,
                  agent_key=req.agent_key, rating=req.rating,
                  note=req.note or "", meta=req.meta or {})
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"ok": True, "id": fb.id}


@router.get("/admin/feedback")
def list_feedback(limit: int = 50, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    """后台查看反馈明细 + 赞踩汇总。"""
    rows = (db.query(Feedback).order_by(Feedback.created_at.desc())
            .limit(max(1, min(limit, 200))).all())
    up = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.rating == 1)) or 0
    down = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.rating == -1)) or 0
    return {
        "summary": {"up": up, "down": down, "total": up + down},
        "items": [{
            "id": r.id, "owner_id": r.owner_id, "session_id": r.session_id,
            "agent_key": r.agent_key, "rating": r.rating, "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        } for r in rows],
    }
