"""方舟文生视频客户端（Seedance）：异步提交 + 轮询，落盘返回 URL。"""
from __future__ import annotations
import time
import uuid

import httpx

from ..config import settings

ASSET_DIR = settings.ASSET_DIR
ASSET_DIR.mkdir(parents=True, exist_ok=True)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.ARK_API_KEY}",
            "Content-Type": "application/json"}


def generate_video(prompt: str, timeout: float = 180.0,
                   poll_interval: float = 5.0, max_poll: int = 36) -> str:
    """提交 Seedance 视频生成任务，轮询至成功，下载落盘，返回 /static/assets/xxx.mp4。"""
    if not settings.ark_enabled:
        raise RuntimeError("方舟 API Key 未配置")
    payload = {
        "model": settings.ARK_MODEL_VIDEO,
        "content": [{"type": "text", "text": prompt}],
    }
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{settings.ARK_BASE_URL}/contents/generations/tasks",
                   headers=_headers(), json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"ark video submit {r.status_code}: {r.text[:300]}")
        task_id = r.json().get("id")
        if not task_id:
            raise RuntimeError("ark video: 未返回 task_id")
        # 轮询
        for _ in range(max_poll):
            time.sleep(poll_interval)
            pr = c.get(f"{settings.ARK_BASE_URL}/contents/generations/tasks/{task_id}",
                       headers=_headers())
            if pr.status_code != 200:
                continue
            j = pr.json()
            st = j.get("status")
            if st == "succeeded":
                url = (j.get("content") or {}).get("video_url") or (j.get("video_url"))
                if not url:
                    # 部分返回嵌套在 data
                    url = ((j.get("data") or {}).get("content") or {}).get("video_url")
                if not url:
                    raise RuntimeError("ark video: 成功但未返回视频地址")
                video_bytes = c.get(url).content
                fname = f"video_{uuid.uuid4().hex}.mp4"
                (ASSET_DIR / fname).write_bytes(video_bytes)
                return f"/static/assets/{fname}"
            elif st in ("failed", "cancelled"):
                raise RuntimeError(f"ark video task {st}: {j.get('error', '')}")
        raise RuntimeError("ark video: 轮询超时未完成")
