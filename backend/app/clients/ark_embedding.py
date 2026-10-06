"""方舟 Embedding 客户端：把文本/批量文本转成向量，供 RAG 语义检索。

两种调用路径（自动按 model 识别）：
1. 多模态向量模型（doubao-embedding-vision-*）：走 /embeddings/multimodal，
   文本需包成 {"type":"text","text":...}；该接口每次返回「单一融合向量」，
   所以批量时逐条请求再拼回等长列表。账号对 vision-251215/250615 已开通，可直调。
2. 纯文本 / Endpoint ID（ep-xxx 或 doubao-embedding-text-*）：走标准 /embeddings，
   支持批量（一次最多 16 条）。若账号未建推理接入点，文本模型 Model ID 直调会 404，
   此时应改用多模态路径或在方舟「在线推理」建 ep 接入点。

失败抛 RuntimeError（调用方应捕获并降级到 BM25/关键词检索）。
"""
from __future__ import annotations

import json

import httpx

from ..config import settings


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.ARK_API_KEY}",
            "Content-Type": "application/json"}


def _is_multimodal(model: str) -> bool:
    """多模态向量模型（vision 系列）走 /embeddings/multimodal 且返回单向量。"""
    return "embedding-vision" in model


def _embed_multimodal(texts: list[str], model: str, timeout: float) -> list[list[float]]:
    """多模态接口：逐条文本 → 单向量。返回与输入等长的向量列表。

    该接口每次返回「单一融合向量」，故逐条请求；服务端对高频连接会 reset（10054），
    故每条独立重试 + 新连接 + 轻节流。
    """
    import time
    out: list[list[float]] = []
    for t in texts:
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                # 每条新建 client，避免复用被服务端关闭的 keep-alive 连接
                with httpx.Client(timeout=timeout) as c:
                    payload = {
                        "model": model,
                        "encoding_format": "float",
                        "input": [{"type": "text", "text": t[:4000]}],
                    }
                    resp = c.post(f"{settings.ARK_BASE_URL}/embeddings/multimodal",
                                  headers=_headers(), json=payload)
                if resp.status_code == 200:
                    emb = resp.json().get("data", {}).get("embedding")
                    if emb:
                        out.append(emb)
                        break
                    last_err = RuntimeError("ark multimodal embedding 返回为空")
                else:
                    last_err = RuntimeError(f"ark multimodal embedding {resp.status_code}: {resp.text[:200]}")
            except Exception as e:  # 含 10054 连接 reset
                last_err = e
            time.sleep(0.4 * (attempt + 1))  # 退避
        else:
            # 3 次都失败 → 整批无法完成，抛出由调用方降级 BM25
            raise RuntimeError(f"multimodal embed 重试失败: {last_err}")
        time.sleep(0.08)  # 轻节流，避免 RPM 限流
    return out


def embed(texts: list[str], model: str | None = None, timeout: float = 30.0) -> list[list[float]]:
    """批量嵌入。返回与输入等长的向量列表。

    texts: 1~16 条文本
    失败抛 RuntimeError（调用方应捕获并降级到 BM25/关键词检索）。
    """
    if not texts:
        return []
    if not settings.ark_enabled:
        raise RuntimeError("ARK_API_KEY 未配置，embedding 不可用")
    model = model or settings.ARK_MODEL_EMBEDDING

    # 多模态路径（vision 模型）：逐条请求
    if _is_multimodal(model):
        return _embed_multimodal(texts, model, timeout)

    # 标准文本路径（Model ID 或 ep-xxx），支持批量
    payload = {
        "model": model,
        "input": [t[:4000] for t in texts],  # 单条上限保护
    }
    with httpx.Client(timeout=timeout) as c:
        resp = c.post(f"{settings.ARK_BASE_URL}/embeddings",
                      headers=_headers(), json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"ark embedding {resp.status_code}: {resp.text[:300]}")
        data = resp.json().get("data", [])
        # 方舟返回按 index 排序，归一化
        vecs = {}
        for item in data:
            idx = item.get("index", len(vecs))
            vecs[idx] = item.get("embedding") or item.get("vector")
        out = [vecs[i] for i in range(len(texts))]
        if any(v is None for v in out):
            raise RuntimeError("ark embedding 返回不完整")
        return out


def embed_one(text: str, model: str | None = None, timeout: float = 30.0) -> list[float]:
    """单条嵌入便捷方法。"""
    return embed([text], model=model, timeout=timeout)[0]
