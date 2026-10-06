"""RAG 入库脚本：把知识库 + 历史剧本切块并嵌入向量，写入 kb_chunks / script_chunks。

用法：
    PYTHONPATH=backend python -m app.rag.seed_rag            # 清库 + 索引 KB(全部) + demo 剧本
    PYTHONPATH=backend python -m app.rag.seed_rag --all       # 额外索引所有用户剧本（成本高）
    PYTHONPATH=backend python -m app.rag.seed_rag --reset     # 只清空不索引

切块策略：
- KnowledgeItem：每条 = 1 块（全量 embed）
- Script.content_json：按 集→场→镜头 切，每镜头 1 块（附集/场上下文），上限 800 字
"""
from __future__ import annotations

import argparse

from ..db import SessionLocal
from ..models import KnowledgeItem, Script, KbChunk, ScriptChunk
from ..clients import ark_embedding


def _chunk_kb_item(it: KnowledgeItem) -> list[dict]:
    """KB 条目 → 1 块（内容本身通常 < 800 字）。"""
    content = (it.content or "").strip()
    if not content:
        return []
    return [{
        "chunk_index": 0,
        "title": it.title or "",
        "content": content,
        "tags": it.tags or [],
        "sublib": it.sublib,
        "platform": it.platform or "general",
        "meta": it.meta or {},
    }]


def _chunk_script(content_json: dict) -> list[dict]:
    """剧本 → 按 镜头 切块，附集/场上下文。"""
    chunks = []
    episodes = content_json.get("episodes", []) or []
    for ei, ep in enumerate(episodes, 1):
        ep_title = ep.get("集名") or ep.get("title") or f"第{ei}集"
        for si, sc in enumerate(ep.get("scenes", []), 1):
            sc_title = sc.get("场名") or sc.get("title") or f"第{si}场"
            for ki, sh in enumerate(sc.get("shots", []), 1):
                text = sh.get("画面描述") or sh.get("content") or ""
                if not text:
                    continue
                mark = sh.get("标记", "")
                body = f"【{ep_title}】【{sc_title}】{text}"
                if mark:
                    body += f"（标记：{mark}）"
                if len(body) > 800:
                    body = body[:800]
                chunks.append({
                    "chunk_index": len(chunks),
                    "episode": ei, "scene": si,
                    "title": f"{ep_title}-{sc_title}-镜头{ki}",
                    "content": body,
                    "meta": {"episode": ei, "scene": si, "mark": mark},
                })
    # 若剧本没有标准 shots 结构，退化为整段 1 块
    if not chunks and content_json.get("project"):
        proj = content_json.get("project", {})
        title = proj.get("项目名") or "剧本"
        body = (proj.get("简介") or "")
        if body:
            chunks.append({"chunk_index": 0, "episode": 0, "scene": 0,
                           "title": title, "content": body[:800], "meta": {}})
    return chunks


def _embed_and_write(db, rows, make_chunk_fn, is_script: bool, model: str,
                      reset: bool, include_all_scripts: bool):
    """通用：切块 → 批量 embed → 写 chunks 表。"""
    total = 0
    batch_texts: list[str] = []
    batch_meta: list[dict] = []

    def flush():
        nonlocal total
        if not batch_texts:
            return
        try:
            vecs = ark_embedding.embed(batch_texts, model=model)
        except Exception as e:
            print(f"  ⚠️ embedding 失败（本批降级为无向量，BM25 关键词检索仍可用）：{e}")
            vecs = [None] * len(batch_texts)
        for meta, vec in zip(batch_meta, vecs):
            if is_script:
                obj = ScriptChunk(
                    script_id=meta["script_id"], owner_id=meta["owner_id"],
                    session_id=meta["session_id"], chunk_index=meta["chunk_index"],
                    platform=meta["platform"], genre=meta["genre"],
                    episode=meta.get("episode", 0), scene=meta.get("scene", 0),
                    is_gold=meta.get("is_gold", False), title=meta["title"],
                    content=meta["content"], embedding=_to_blob(vec),
                    embedding_model=model, meta=meta.get("meta", {}))
            else:
                obj = KbChunk(
                    ref_id=meta["ref_id"], chunk_index=meta["chunk_index"],
                    sublib=meta["sublib"], platform=meta["platform"], title=meta["title"],
                    content=meta["content"], tags=meta["tags"], embedding=_to_blob(vec),
                    embedding_model=model, meta=meta.get("meta", {}))
            db.add(obj)
            total += 1
        db.commit()
        batch_texts.clear(); batch_meta.clear()

    for row in rows:
        if is_script:
            chunks = _chunk_script(row.content_json or {})
            owner = row.owner_id
            sess = row.session_id
            platform = row.platform
            genre = row.genre
            is_gold = bool(row.is_demo)
        else:
            chunks = _chunk_kb_item(row)
            owner = None; sess = None; platform = row.platform or "general"
            genre = ""; is_gold = False
        for c in chunks:
            if is_script:
                batch_meta.append({"script_id": row.id, "owner_id": owner, "session_id": sess,
                                   "chunk_index": c["chunk_index"], "platform": platform, "genre": genre,
                                   "is_gold": is_gold, "title": c["title"], "content": c["content"],
                                   "meta": c.get("meta", {})})
            else:
                batch_meta.append({"ref_id": row.id, "chunk_index": c["chunk_index"],
                                   "sublib": c["sublib"], "platform": c["platform"], "title": c["title"],
                                   "content": c["content"], "tags": c["tags"], "meta": c.get("meta", {})})
            batch_texts.append(c["content"])
            if len(batch_texts) >= 16:
                flush()
    flush()
    return total


def _to_blob(vec) -> bytes:
    import numpy as np
    if vec is None:
        return None
    return np.array(vec, dtype=np.float32).tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="额外索引所有用户剧本（成本高）")
    ap.add_argument("--reset", action="store_true", help="只清空 chunks 表，不索引")
    args = ap.parse_args()

    db = SessionLocal()
    model = ark_embedding.__dict__.get("MODEL") or "doubao-embedding"
    # 读真实模型名
    from ..config import settings
    model = settings.ARK_MODEL_EMBEDDING

    if args.reset:
        db.query(KbChunk).delete(); db.query(ScriptChunk).delete()
        db.commit(); print("已清空 kb_chunks / script_chunks"); db.close(); return

    # 清旧（先清后写，保证幂等）
    db.query(KbChunk).delete(); db.query(ScriptChunk).delete()
    db.commit()
    print("已清空旧 chunks，开始索引…")

    # 1) KB 全量
    kb_rows = db.query(KnowledgeItem).all()
    n_kb = _embed_and_write(db, kb_rows, _chunk_kb_item, is_script=False,
                            model=model, reset=False, include_all_scripts=False)
    print(f"KB 入库：{n_kb} 块（来自 {len(kb_rows)} 条）")

    # 2) 剧本：先 demo（系统预置），再按需 --all
    if args.all:
        sc_rows = db.query(Script).all()
        label = "全部"
    else:
        sc_rows = db.query(Script).filter(Script.is_demo == True).all()
        label = "demo 预置"
    n_sc = _embed_and_write(db, sc_rows, _chunk_script, is_script=True,
                            model=model, reset=False, include_all_scripts=args.all)
    print(f"剧本入库（{label}）：{n_sc} 块（来自 {len(sc_rows)} 部）")

    print("✅ RAG 索引完成")
    db.close()


if __name__ == "__main__":
    main()
