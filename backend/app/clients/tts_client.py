"""豆包语音（配音）客户端：同步 HTTP，base64 解码落盘为 mp3。随视频生成内部调用。"""
from __future__ import annotations
import base64
import time
import uuid

import httpx

from ..config import settings

ASSET_DIR = settings.ASSET_DIR
ASSET_DIR.mkdir(parents=True, exist_ok=True)

TTS_URL = "https://openspeech.bytedance.com/api/v1/tts"
# 本账号实测唯一被授权的音色；其余角色音色（男主/旁白等）若未授权会自动回退到它，
# 保证「分角色多条配音」永远能出片（多条独立音频），不因某个音色 403 而中断。
DEFAULT_VOICE = "zh_female_gaolengyujie_uranus_bigtts"


def synthesize(text: str, voice_type: str = DEFAULT_VOICE, speed: float = 1.0,
               timeout: float = 60.0) -> str:
    """合成一段配音，落盘返回 /static/assets/xxx.mp3。

    若指定音色未被授权（403/code!=3000），自动回退到 DEFAULT_VOICE 重试一次，
    确保视频配音流程不中断。
    """
    if not settings.tts_enabled:
        raise RuntimeError("豆包语音 API Key 未配置")
    payload = {
        "app": {
            "appid": settings.VOLC_TTS_APP_ID,
            "token": settings.VOLC_TTS_API_KEY,
            "cluster": settings.VOLC_TTS_CLUSTER,
        },
        "user": {"uid": "shortdrama_agent"},
        "audio": {"voice_type": voice_type, "encoding": "mp3", "speed_ratio": speed},
        "request": {
            "reqid": uuid.uuid4().hex,
            "text": text,
            "text_type": "plain",
            "operation": "query",
        },
    }
    headers = {"X-Api-Key": settings.VOLC_TTS_API_KEY, "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as c:
        r = c.post(TTS_URL, headers=headers, json=payload)
        if r.status_code != 200:
            # 指定音色可能未授权：回退到默认授权音色重试
            if voice_type != DEFAULT_VOICE:
                return synthesize(text, voice_type=DEFAULT_VOICE, speed=speed, timeout=timeout)
            raise RuntimeError(f"tts {r.status_code}: {r.text[:200]}")
        j = r.json()
        if j.get("code") != 3000:
            if voice_type != DEFAULT_VOICE:
                return synthesize(text, voice_type=DEFAULT_VOICE, speed=speed, timeout=timeout)
            raise RuntimeError(f"tts error code={j.get('code')} msg={j.get('message')}")
        mp3_b64 = j.get("data")
        if not mp3_b64:
            raise RuntimeError("tts: 未返回音频数据")
        mp3 = base64.b64decode(mp3_b64)
    fname = f"tts_{uuid.uuid4().hex}.mp3"
    (ASSET_DIR / fname).write_bytes(mp3)
    return f"/static/assets/{fname}"


# 分角色可选音色（配音粒度=分角色多条）
VOICE_BY_ROLE = {
    "男主": "zh_male_qingjun_yuxuan_emo_v2",
    "女主": "zh_female_gaolengyujie_uranus_bigtts",
    "旁白": "zh_male_awen_emo_v2",
}
