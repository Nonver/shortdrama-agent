"""重新采集/写入知识库：把 knowledge.py 中专业带源内容 upsert 进数据库。

用法（在 backend 目录，用项目 venv）：
    python collect_knowledge.py

特性：按 (sublib, key) 幂等更新，已存在的覆盖、不存在的插入；
      不删除后台手动新增的其它条目。
"""
from __future__ import annotations
import sys
from pathlib import Path

# 允许以脚本方式运行（backend 目录）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import SessionLocal
from app.models import KnowledgeItem
from app.knowledge import seed_items


def main() -> None:
    items = seed_items()
    db = SessionLocal()
    inserted = 0
    updated = 0
    try:
        for it in items:
            existing = (
                db.query(KnowledgeItem)
                .filter(KnowledgeItem.sublib == it["sublib"],
                        KnowledgeItem.key == it["key"])
                .first()
            )
            if existing:
                existing.title = it["title"]
                existing.content = it["content"]
                existing.tags = it.get("tags", [])
                existing.meta = it.get("meta", {})
                updated += 1
            else:
                db.add(KnowledgeItem(
                    sublib=it["sublib"], key=it["key"], title=it["title"],
                    content=it["content"], tags=it.get("tags", []),
                    meta=it.get("meta", {}),
                ))
                inserted += 1
        db.commit()
        # 统计
        total = db.query(KnowledgeItem).count()
        from sqlalchemy import func
        by_sub = dict(
            (r[0], r[1]) for r in
            db.query(KnowledgeItem.sublib, func.count()).group_by(KnowledgeItem.sublib).all()
        )
        print(f"[collect] 新增 {inserted} 条，更新 {updated} 条")
        print(f"[collect] 知识库总条数：{total}")
        for k, v in by_sub.items():
            print(f"           - {k}: {v}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
