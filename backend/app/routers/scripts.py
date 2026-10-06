"""剧本路由：SSE 流式生成、列表、查看、下载、删除。"""
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db, SessionLocal
from ..models import User, Script
from ..deps import get_current_user
from ..generator import generate_content, render_markdown, stream_markdown
from ..knowledge import retrieve_kb
from ..exports import to_markdown, to_json, to_docx, to_xlsx, to_pdf
from ..deps import require_feature

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


def _build(req: schemas.GenerateReq, user: User, db: Session) -> dict:
    kbdb = None
    try:
        kbdb = retrieve_kb(db, req.platform, req.genre)
    except Exception:
        kbdb = None
    return generate_content(
        prompt=req.prompt, platform_key=req.platform, genre_key=req.genre,
        episode_count=req.episode_count, agent_key=req.agent_key,
        profile={"tags": user.tags or [], "habits": user.habits or {}},
        kbdb=kbdb,
    )


@router.post("/generate")
def generate(req: schemas.GenerateReq, user: User = Depends(require_feature("script_generate"))):
    """token 级 SSE 流式生成（方舟真实生成 + 兜底降级），结束后落库并返回 scriptId。"""
    def event_stream():
        db = SessionLocal()
        try:
            script = Script(owner_id=user.id, title="生成中…", platform=req.platform,
                            genre=req.genre, episode_count=req.episode_count,
                            prompt=req.prompt, status="draft", content_json={})
            db.add(script)
            db.commit()
            db.refresh(script)
            sid = script.id

            content = _build(req, user, db)
            for chunk in stream_markdown(content):
                yield f"data: {json.dumps({'type': 'token', 'text': chunk}, ensure_ascii=False)}\n\n"
            script.content_json = content
            script.title = content["project"]["项目名"]
            script.status = "done"
            db.commit()
            yield f"event: done\ndata: {json.dumps({'id': sid, 'title': script.title}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa
            yield f"event: error\ndata: {json.dumps({'msg': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("", response_model=list[schemas.ScriptOut])
def list_mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Script).filter(Script.owner_id == user.id).order_by(Script.id.desc()).all()
    return rows


@router.get("/demo")
def demo_list(db: Session = Depends(get_db)):
    """公开：系统预置示例剧本（免登录），用于首页『看示例』演示。"""
    rows = db.query(Script).filter(Script.is_demo.is_(True)).order_by(Script.id.asc()).all()
    return [{
        "id": r.id, "title": r.title, "platform": r.platform, "genre": r.genre,
        "markdown": to_markdown(r.content_json) if r.content_json else "",
    } for r in rows]


@router.get("/{sid}", response_model=schemas.ScriptOut)
def get_one(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Script).filter(Script.id == sid, Script.owner_id == user.id).first()
    if not s:
        raise HTTPException(404, "剧本不存在")
    return s


@router.get("/{sid}/content")
def get_content(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Script).filter(Script.id == sid, Script.owner_id == user.id).first()
    if not s:
        raise HTTPException(404, "剧本不存在")
    return {"id": s.id, "title": s.title, "content": s.content_json,
            "markdown": to_markdown(s.content_json) if s.content_json else ""}


FMT_MEDIA = {
    "md": ("text/markdown", "md"),
    "json": ("application/json", "json"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}


@router.get("/{sid}/download")
def download(sid: int, fmt: str = "md",
             user: User = Depends(require_feature("script_download")),
             db: Session = Depends(get_db)):
    s = db.query(Script).filter(Script.id == sid, Script.owner_id == user.id).first()
    if not s or not s.content_json:
        raise HTTPException(404, "剧本不存在")
    if fmt not in FMT_MEDIA:
        raise HTTPException(400, "不支持的格式")
    media, ext = FMT_MEDIA[fmt]
    data = {
        "md": to_markdown, "json": to_json, "docx": to_docx, "xlsx": to_xlsx, "pdf": to_pdf,
    }[fmt](s.content_json)
    from urllib.parse import quote
    fname = f"{s.title}.{ext}"
    disp = f"attachment; filename=\"download.{ext}\"; filename*=UTF-8''{quote(fname)}"
    return Response(content=data, media_type=media, headers={"Content-Disposition": disp})


@router.delete("/{sid}")
def delete(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Script).filter(Script.id == sid, Script.owner_id == user.id).first()
    if not s:
        raise HTTPException(404, "剧本不存在")
    db.delete(s)
    db.commit()
    return {"ok": True}
