"""方舟文生图客户端（Seedream）：生成分镜图，落盘并叠加合规角标。"""
from __future__ import annotations
import base64
import io
import os
import uuid

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..config import settings

ASSET_DIR = settings.ASSET_DIR
ASSET_DIR.mkdir(parents=True, exist_ok=True)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.ARK_API_KEY}",
            "Content-Type": "application/json"}


def generate_image(prompt: str, size: str = "2K", timeout: float = 90.0) -> bytes:
    """调用 Seedream 生成图片，返回图片二进制（已去方舟图章 watermark:false）。"""
    if not settings.ark_enabled:
        raise RuntimeError("方舟 API Key 未配置")
    payload = {
        "model": settings.ARK_MODEL_IMAGE,
        "prompt": prompt,
        "size": size,                 # "2K" / "4K"（Seedream 字符串档位）
        "watermark": False,           # 关方舟可见图章；隐式水印在方舟控制台开启
        "response_format": "url",     # 优先返回 url
    }
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{settings.ARK_BASE_URL}/images/generations",
                   headers=_headers(), json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"ark image {r.status_code}: {r.text[:300]}")
        data = r.json()
        item = (data.get("data") or [{}])[0]
        if item.get("url"):
            img_bytes = c.get(item["url"]).content
        elif item.get("b64_json"):
            img_bytes = base64.b64decode(item["b64_json"])
        else:
            raise RuntimeError("ark image: 未返回图片数据")
    return img_bytes


def _font(size: int):
    # 优先用系统中文字体，否则回退默认
    for p in [
        "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def add_badge(image_bytes: bytes, text: str = "AI 生成") -> bytes:
    """方案B：在图片右下角叠加合规角标（不破坏原图语义，可见可溯源）。"""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        draw = ImageDraw.Draw(img)
        fs = max(18, int(min(w, h) * 0.035))
        font = _font(fs)
        # 量角标尺寸
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = int(fs * 0.4)
        x0, y0 = w - tw - pad * 2 - 8, h - th - pad * 2 - 8
        # 半透明底
        draw.rectangle([x0, y0, x0 + tw + pad * 2, y0 + th + pad * 2],
                       fill=(0, 0, 0, 120))
        draw.text((x0 + pad, y0 + pad), text, font=font, fill=(255, 255, 255, 230))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes  # 角标失败不影响主产物


def save_image(prompt: str, size: str = "2K", badge_text: str = "AI 生成",
               with_badge: bool = True) -> str:
    """生成并落盘，返回可访问 URL（/static/assets/xxx.png）。"""
    raw = generate_image(prompt, size=size)
    if with_badge and badge_text:
        raw = add_badge(raw, badge_text)
    fname = f"img_{uuid.uuid4().hex}.png"
    (ASSET_DIR / fname).write_bytes(raw)
    return f"/static/assets/{fname}"
