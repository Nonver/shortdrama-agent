"""RAG 语义检索器：向量语义流 + jieba BM25 关键词流 + RRF 融合 + 元数据硬过滤。

设计（MVP）：
- 数据源：kb_chunks（公开知识库）+ script_chunks（用户剧本，按 owner/session 隔离）
- 向量：sqlite BLOB 存 float32，检索时在内存用 numpy 算余弦相似度（数据量 < 1万条，< 50ms，足够）
  —— 量大（> 50w）时切换到 sqlite-vec 虚拟表 KNN，接口不变
- BM25：jieba 中文分词 + IDF（模块级缓存）
- 融合：Reciprocal Rank Fusion（RRF），关键词吃专有名词、语义吃类似套路
- 元数据过滤：platform / sublib 硬过滤（如 user 平台=红果 → 只检索红果+通用）

返回：[{chunk_id, source, ref_id, title, content, score, sublib, platform, meta}]
"""
from __future__ import annotations

import math
import re as _re
from dataclasses import dataclass, field

import numpy as np

from ..models import KbChunk, ScriptChunk
from ..clients import ark_embedding

# ---------------- BM25 模块级缓存 ----------------
_BM25_READY = False
_DF: dict[str, int] = {}        # term -> 文档频率
_N_DOCS = 0
_AVGDL = 0.0
_DOC_TOKENS: list[list[str]] = []   # 各 chunk 的 token 列表（与 _POOL 对齐）
_POOL: list[dict] = []              # 检索候选池（chunk 行投影）

try:
    import jieba
    _JIEBA_OK = True
except Exception:
    _JIEBA_OK = False


def _tokenize(text: str) -> list[str]:
    if _JIEBA_OK:
        return [t for t in jieba.lcut((text or "").lower()) if len(t) > 1]
    # 兜底：unigram + bigram
    toks = []
    for seg in _re.findall(r"[\u4e00-\u9fff]+", (text or "").lower()):
        for ch in seg:
            toks.append(ch)
        for i in range(len(seg) - 1):
            toks.append(seg[i:i + 2])
    for m in _re.findall(r"[a-z0-9]{2,}", (text or "").lower()):
        toks.append(m)
    return toks


@dataclass
class Hit:
    chunk_id: int
    source: str
    ref_id: int
    title: str
    content: str
    score: float = 0.0
    sublib: str = ""
    platform: str = ""
    meta: dict = field(default_factory=dict)


def _deserialize(vec_blob: bytes | None) -> np.ndarray | None:
    if not vec_blob:
        return None
    try:
        return np.frombuffer(vec_blob, dtype=np.float32)
    except Exception:
        return None


def _build_pool(db, platform=None, sublib=None, owner_id=None, scope="all"):
    """构建检索候选池 + BM25 索引（按元数据过滤）。"""
    global _BM25_READY, _DF, _N_DOCS, _AVGDL, _DOC_TOKENS, _POOL
    q = db.query(KbChunk)
    if platform and platform != "general":
        q = q.filter(KbChunk.platform.in_([platform, "general"]))
    if sublib:
        q = q.filter(KbChunk.sublib == sublib)
    kb_rows = q.all()

    sc_rows = []
    if scope in ("all", "script"):
        sq = db.query(ScriptChunk)
        if owner_id:
            # 只取自己剧本 + 高分公开剧本（隐私隔离）
            sq = sq.filter(ScriptChunk.owner_id == owner_id)
        if platform:
            sq = sq.filter(ScriptChunk.platform.in_([platform, ""]))
        if sublib == "script" or not sublib:
            sc_rows = sq.all()

    pool = []
    doc_tokens = []
    for r in kb_rows:
        pool.append({"id": r.id, "source": "kb", "ref_id": r.ref_id,
                     "title": r.title, "content": r.content, "sublib": r.sublib,
                     "platform": r.platform, "meta": r.meta or {}, "emb": _deserialize(r.embedding)})
        doc_tokens.append(_tokenize(r.title + " " + r.content))
    for r in sc_rows:
        pool.append({"id": r.id, "source": "script", "ref_id": r.script_id,
                     "title": r.title, "content": r.content, "sublib": "script",
                     "platform": r.platform, "meta": r.meta or {}, "emb": _deserialize(r.embedding)})
        doc_tokens.append(_tokenize(r.title + " " + r.content))

    n = len(pool)
    df: dict[str, int] = {}
    dl_sum = 0
    for toks in doc_tokens:
        dl_sum += len(toks)
        seen = set(toks)
        for t in seen:
            df[t] = df.get(t, 0) + 1
    _DF, _N_DOCS, _AVGDL = df, n, (dl_sum / n if n else 0.0)
    _DOC_TOKENS, _POOL = doc_tokens, pool
    _BM25_READY = True


def _vec_search(query_emb: np.ndarray, top_k: int, scope="all") -> list[Hit]:
    """向量流：余弦相似度 top_k。"""
    hits = []
    for p in _POOL:
        if p["emb"] is None:
            continue
        if scope == "kb" and p["source"] != "kb":
            continue
        if scope == "script" and p["source"] != "script":
            continue
        sim = float(np.dot(query_emb, p["emb"]) / (np.linalg.norm(query_emb) * np.linalg.norm(p["emb"]) + 1e-9))
        hits.append(Hit(p["id"], p["source"], p["ref_id"], p["title"], p["content"],
                        sim, p["sublib"], p["platform"], p["meta"]))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


def _bm25_search(query: str, top_k: int, scope="all") -> list[Hit]:
    """BM25 流。"""
    if not _BM25_READY or _N_DOCS == 0:
        return []
    q_toks = _tokenize(query)
    if not q_toks:
        return []
    k1, b = 1.5, 0.75
    hits = []
    for i, p in enumerate(_POOL):
        if scope == "kb" and p["source"] != "kb":
            continue
        if scope == "script" and p["source"] != "script":
            continue
        toks = _DOC_TOKENS[i]
        dl = len(toks) or 1
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for qt in set(q_toks):
            if qt not in _DF:
                continue
            idf = math.log((_N_DOCS - _DF[qt] + 0.5) / (_DF[qt] + 0.5) + 1.0)
            f = tf.get(qt, 0)
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / (_AVGDL or 1)))
        if score > 0:
            hits.append(Hit(p["id"], p["source"], p["ref_id"], p["title"], p["content"],
                            score, p["sublib"], p["platform"], p["meta"]))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


def rrf_fuse(vec_hits: list[Hit], bm25_hits: list[Hit], top_k: int, k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion：融合两个排序流。"""
    fused: dict[int, Hit] = {}
    for rank, h in enumerate(vec_hits):
        key = (h.source, h.chunk_id)
        fused.setdefault(key, h).score += 1.0 / (rank + k)
    for rank, h in enumerate(bm25_hits):
        key = (h.source, h.chunk_id)
        if key in fused:
            fused[key].score += 1.0 / (rank + k)
        else:
            fused[key] = h
            fused[key].score = 1.0 / (rank + k)
    out = sorted(fused.values(), key=lambda h: h.score, reverse=True)
    return out[:top_k]


def retrieve(query: str, db, top_k: int = 20, platform=None, sublib=None,
             owner_id=None, scope="all") -> list[Hit]:
    """主检索入口：建池 → 向量流 + BM25 流 → RRF 融合。

    scope: "all" | "kb" | "script"
    platform/sublib: 元数据硬过滤
    """
    _build_pool(db, platform=platform, sublib=sublib, owner_id=owner_id, scope=scope)
    if not _POOL:
        return []
    # 向量流
    try:
        q_emb = np.array(ark_embedding.embed_one(query), dtype=np.float32)
        vec_hits = _vec_search(q_emb, top_k * 2, scope=scope)
    except Exception:
        vec_hits = []  # embedding 失败 → 仅 BM25
    # BM25 流
    bm25_hits = _bm25_search(query, top_k * 2, scope=scope)
    return rrf_fuse(vec_hits, bm25_hits, top_k)
