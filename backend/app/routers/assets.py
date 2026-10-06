"""资产路由：生图（会员）、生视频（会员Pro，内含分角色配音）。"""
from __future__ import annotations
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import User, Script, Asset
from ..deps import require_feature, get_membership_config, level_ge
from ..clients import ark_image, ark_video, tts_client
from ..config import settings

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("/image")
def gen_image(req: schemas.ImageGenReq, user: User = Depends(require_feature("image_generate")),
              db: Session = Depends(get_db)):
    cfg = get_membership_config(db)
    size = "2K"
    want_4k = req.quality == "4K"
    if want_4k:
        if not cfg.get("image_4k_enabled"):
            raise HTTPException(403, "4K 生图暂未开放（后台未开启）")
        if not level_ge(user.membership_level, cfg["feature_min_level"].get("image_quality_4k", "pro")):
            raise HTTPException(403, "4K 生图需「会员Pro」")
        size = "4K"
    prompt = req.prompt.strip() or "短剧分镜画面"
    try:
        url = ark_image.save_image(prompt, size=size,
                                   badge_text=cfg.get("badge_text", "AI 生成"),
                                   with_badge=cfg.get("watermark_badge", True))
    except Exception as e:
        raise HTTPException(502, f"生图失败：{e}")
    db.add(Asset(owner_id=user.id, kind="image", url=url,
                 prompt=prompt, meta={"size": size}))
    db.commit()
    return {"url": url, "size": size}


@router.post("/video")
def gen_video(req: schemas.VideoGenReq, user: User = Depends(require_feature("video_generate")),
              db: Session = Depends(get_db)):
    s = db.query(Script).filter(Script.id == req.script_id, Script.owner_id == user.id).first()
    if not s or not s.content_json:
        raise HTTPException(404, "剧本不存在")
    cj = s.content_json
    proj = cj.get("project", {})
    # 视频提示词：项目名 + 类型 + 首场画面描述
    first_shot = ""
    try:
        first_shot = cj["episodes"][0]["scenes"][0]["shots"][0]["画面描述"]
    except Exception:
        first_shot = ""
    vprompt = req.prompt.strip() or (
        f"{proj.get('项目名','')}：{proj.get('类型','')}短剧，{proj.get('目标平台','')}竖屏风格。"
        f"画面参考：{first_shot}"
    )
    try:
        video_url = ark_video.generate_video(vprompt)
    except Exception as e:
        raise HTTPException(502, f"生视频失败：{e}")
    db.add(Asset(owner_id=user.id, kind="video", url=video_url,
                 prompt=vprompt, meta={}))
    db.commit()

    # 分角色多条配音：抽取台词，最多 3 条，轮流用不同音色
    audios = []
    lines = []
    try:
        for ep in cj.get("episodes", []):
            for sc in ep.get("scenes", []):
                for sh in sc.get("shots", []):
                    t = sh.get("台词", "") or ""
                    if t:
                        lines.append(t)
                    if len(lines) >= 3:
                        break
                if len(lines) >= 3:
                    break
            if len(lines) >= 3:
                break
    except Exception:
        lines = []
    voices = list(tts_client.VOICE_BY_ROLE.values())
    for i, line in enumerate(lines):
        try:
            aurl = tts_client.synthesize(line, voice_type=voices[i % len(voices)])
            db.add(Asset(owner_id=user.id, kind="audio", url=aurl,
                         prompt=line, meta={"video_script": s.id}))
            audios.append({"text": line, "url": aurl})
        except Exception:
            continue
    db.commit()
    return {"video_url": video_url, "audio": audios}


@router.get("/mine", response_model=list[dict])
def my_assets(user: User = Depends(require_feature("script_generate")),
              db: Session = Depends(get_db)):
    rows = db.query(Asset).filter(Asset.owner_id == user.id).order_by(Asset.id.desc()).all()
    return [{"id": r.id, "kind": r.kind, "url": r.url, "prompt": r.prompt,
            "meta": r.meta, "created_at": r.created_at} for r in rows]
