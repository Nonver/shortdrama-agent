"""动态图形验证码（自托管，无短信/无第三方，每次请求都不同）。"""
from __future__ import annotations
import random
import io
import base64

from PIL import Image, ImageDraw, ImageFont

from .config import settings
from .security import kv, new_id


def _font(size: int):
    # 优先用系统常见字体，失败则退化为默认
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_captcha() -> tuple[str, str]:
    """返回 (captcha_id, base64_data_url)。答案存进程内 KV，TTL 内一次性有效。"""
    code = "".join(random.choices(settings.CAPTCHA_CHARS, k=settings.CAPTCHA_LEN))
    cid = new_id()

    w, h = 120, 44
    img = Image.new("RGB", (w, h), (245, 247, 250))
    draw = ImageDraw.Draw(img)
    font = _font(30)

    # 干扰线
    for _ in range(4):
        draw.line(
            [(random.randint(0, w), random.randint(0, h)),
             (random.randint(0, w), random.randint(0, h))],
            fill=(random.randint(150, 210), random.randint(150, 210), random.randint(150, 210)),
            width=1,
        )
    # 字符
    x = 12
    for ch in code:
        y = random.randint(2, 10)
        draw.text((x, y), ch, font=font,
                  fill=(random.randint(30, 110), random.randint(30, 110), random.randint(120, 200)))
        x += 24

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    kv.set(cid, code.upper(), ttl=settings.CAPTCHA_TTL)
    return cid, data_url


def verify_captcha(captcha_id: str, code: str) -> bool:
    stored = kv.get(captcha_id, pop=True)  # 一次性失效
    if not stored:
        return False
    return stored == code.strip().upper()
