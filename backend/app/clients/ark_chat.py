"""方舟对话客户端：剧本主生成 / 角色化 / 轻量抽取。带超时与降级提示。"""
from __future__ import annotations
import json
from typing import Callable

import httpx

from ..config import settings


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.ARK_API_KEY}",
            "Content-Type": "application/json"}


def chat_complete(system: str, user: str, model: str | None = None,
                  temperature: float = 0.85, max_tokens: int = 4096,
                  timeout: float = 90.0, on_chunk: Callable[[str], None] | None = None) -> str:
    """同步一次性对话，返回文本内容。失败抛异常（由调用方降级）。

    内部走流式读取并拼接：避免长输出（seed 模型出 token 慢）触发单次 read 超时。
    对调用方 API 不变（仍返回完整文本），所有调用方无需改动。
    若提供 on_chunk，每到一个 token 增量即回调（on_chunk(delta)），可用于实时进度。
    """
    model = model or settings.ARK_MODEL_CHAT
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    # connect 10s；read 取调用方超时与 600s 的较大值，长文也不超时
    cto = (10.0, max(float(timeout), 600.0))
    with httpx.Client(timeout=cto) as c:
        with c.stream("POST", f"{settings.ARK_BASE_URL}/chat/completions",
                      headers=_headers(), json=payload) as resp:
            if resp.status_code != 200:
                body = resp.read().decode("utf-8", "ignore")
                raise RuntimeError(f"ark chat {resp.status_code}: {body[:300]}")
            parts: list[str] = []
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    chunk = line[len("data:"):].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = obj["choices"][0]["delta"].get("content", "")
                        if delta:
                            parts.append(delta)
                            if on_chunk:
                                on_chunk(delta)
                    except Exception:
                        continue
            return "".join(parts)


def chat_stream(system: str, user: str, model: str | None = None,
               temperature: float = 0.85, max_tokens: int = 4096,
               timeout: float = 120.0):
    """同步流式对话，yield 文本增量（真实 token 级）。"""
    model = model or settings.ARK_MODEL_CHAT
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    with httpx.Client(timeout=timeout) as c:
        with c.stream("POST", f"{settings.ARK_BASE_URL}/chat/completions",
                      headers=_headers(), json=payload) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"ark chat {resp.status_code}: {resp.text[:300]}")
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    chunk = line[len("data:"):].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = obj["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue


def extract_json(text: str) -> dict:
    """从模型输出中尽量抽取 JSON（兼容 ```json 包裹 / 前后多余文本）。"""
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    # 取首个 { 到末个 }
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        s = s[a:b + 1]
    return json.loads(s)
