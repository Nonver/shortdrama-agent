"""知识库路由：4 子库 CRUD（用户可查，管理员可改）；二级导航分组。

二级导航 IA：
  L1 分组：platform（红果/抖音/快手/通用） + sublib（平台规则/类型套路/风格样本/剧本资产）
  L2 内容：条目列表 + CRUD
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .. import schemas
from ..db import get_db
from ..models import KnowledgeItem, User
from ..deps import get_current_user, require_admin
from ..config import settings

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# 二级导航分组：L1 平台 / L2 子库
PLATFORM_GROUPS = [
    {"key": "hongguo",  "name": "红果短剧",  "icon": "🍅"},
    {"key": "douyin",   "name": "抖音短剧",  "icon": "🎵"},
    {"key": "kuaishou", "name": "快手短剧",  "icon": "⚡"},
    {"key": "tencent",  "name": "腾讯视频",  "icon": "🐧"},
    {"key": "mango",    "name": "芒果TV",    "icon": "🥭"},
    {"key": "iqiyi",    "name": "爱奇艺",    "icon": "🎬"},
    {"key": "migu",     "name": "咪咕短剧",  "icon": "📡"},
    {"key": "dianzhong","name": "点众·河马", "icon": "🎯"},
    {"key": "general",  "name": "通用（跨平台）", "icon": "🌐"},
    {"key": "guide",    "name": "🤖 AI短剧知识库（向导）", "icon": "🤖", "special": True},
]
SUBLIB_GROUPS = [
    {"key": "platform", "name": "平台规则库",   "icon": "📜"},
    {"key": "genre",    "name": "类型套路库",   "icon": "🎭"},
    {"key": "style",    "name": "风格样本库",   "icon": "🎨"},
    {"key": "asset",    "name": "剧本资产库",   "icon": "📚"},
    {"key": "guide",    "name": "🤖 AI短剧知识库（向导）", "icon": "🤖"},
]


@router.get("/groups", response_model=dict)
def groups(_: User = Depends(require_admin)):
    """返回二级导航结构（后台内部用，含向导/平台/类型/风格/资产——机密，仅 admin）。"""
    return {"platforms": PLATFORM_GROUPS, "sublibs": SUBLIB_GROUPS}


@router.get("/by-group", response_model=list[schemas.KnowledgeItemOut])
def by_group(platform: str | None = None, sublib: str | None = None,
             db: Session = Depends(get_db),
             _: User = Depends(require_admin)):
    """按二级导航过滤：platform=hongguo/douyin/kuaishou/general/guide，sublib=platform/genre/style/asset/guide。
    规则：向导(guide)为跨平台通用知识，忽略 platform 维度；其他子库当 platform 非 general 时，
    同时展示平台专属 + 通用(general/null) 知识，避免用户在某平台下点开子库看到空白。"""
    q = db.query(KnowledgeItem)
    if sublib == "guide":
        # 向导是跨平台通用知识，直接按 sublib 过滤、忽略 platform
        q = q.filter(KnowledgeItem.sublib == "guide")
        return q.order_by(KnowledgeItem.sort_order, KnowledgeItem.id.asc()).all()
    if sublib:
        q = q.filter(KnowledgeItem.sublib == sublib)
    if platform and platform != "general":
        # 平台专属 + 通用（跨平台）知识都展示
        q = q.filter(or_(KnowledgeItem.platform == platform,
                         KnowledgeItem.platform == "general",
                         KnowledgeItem.platform.is_(None)))
    elif platform == "general":
        q = q.filter(KnowledgeItem.platform == "general")
    return q.order_by(KnowledgeItem.sort_order, KnowledgeItem.id.asc()).all()


@router.get("", response_model=list[schemas.KnowledgeItemOut])
def list_items(sublib: str | None = None, db: Session = Depends(get_db),
               _: User = Depends(require_admin)):
    q = db.query(KnowledgeItem)
    if sublib:
        q = q.filter(KnowledgeItem.sublib == sublib)
    return q.order_by(KnowledgeItem.id.desc()).all()


@router.get("/{iid}", response_model=schemas.KnowledgeItemOut)
def get_item(iid: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(KnowledgeItem, iid)
    if not obj:
        raise HTTPException(404, "不存在")
    return obj


@router.post("", response_model=schemas.KnowledgeItemOut)
def create(item: schemas.KnowledgeItemCreate, _: User = Depends(require_admin),
           db: Session = Depends(get_db)):
    if item.sublib not in ("platform", "genre", "style", "asset"):
        raise HTTPException(400, "sublib 必须是 platform/genre/style/asset")
    data = item.model_dump()
    data.setdefault("platform", "general")
    obj = KnowledgeItem(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/{iid}", response_model=schemas.KnowledgeItemOut)
def update(iid: int, item: schemas.KnowledgeItemCreate, _: User = Depends(require_admin),
           db: Session = Depends(get_db)):
    obj = db.get(KnowledgeItem, iid)
    if not obj:
        raise HTTPException(404, "不存在")
    for k, v in item.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{iid}")
def delete(iid: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    obj = db.get(KnowledgeItem, iid)
    if not obj:
        raise HTTPException(404, "不存在")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ---------------- AI 短剧知识库（向导）：用户不懂就问，解疑答惑 ----------------
import re as _re


def _tokenize(text: str) -> list[str]:
    """把问题拆分为检索词：英文/数字词 + 中文 unigram/bigram。"""
    text = (text or "").lower()
    toks: list[str] = []
    # 英文/数字词
    for m in _re.findall(r"[a-z0-9]{2,}", text):
        toks.append(m)
    # 中文片段：unigram + bigram
    for seg in _re.findall(r"[\u4e00-\u9fff]+", text):
        for ch in seg:
            toks.append(ch)
        for i in range(len(seg) - 1):
            toks.append(seg[i:i + 2])
    return toks


def _score_item(item: KnowledgeItem, qtoks: list[str]) -> float:
    title = (item.title or "").lower()
    content = (item.content or "").lower()
    tags = " ".join(item.tags or []).lower()
    score = 0.0
    for t in qtoks:
        if not t:
            continue
        if t in title:
            score += 3.0
        if t in tags:
            score += 2.0
        if t in content:
            score += 1.0
    return score


@router.post("/guide/ask", response_model=dict)
def guide_ask(body: dict = Body(...), db: Session = Depends(get_db),
              _: User = Depends(get_current_user)):
    """AI 向导答疑：基于 guide 子库检索 + 方舟 LLM 自然语言解答（断网关键词兜底）。

    body: {question: str}  返回 {answer, refs:[title], used_llm, fallback}
    """
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    guides = db.query(KnowledgeItem).filter(KnowledgeItem.sublib == "guide").all()
    qtoks = _tokenize(question)
    scored = sorted(guides, key=lambda it: _score_item(it, qtoks), reverse=True)
    top = [it for it in scored if _score_item(it, qtoks) > 0][:6] or scored[:4]

    refs = [it.title for it in top]
    used_llm = False
    fallback = False

    if settings.ark_enabled and top:
        try:
            from ..clients.ark_chat import chat_complete
            kb_text = "\n\n---\n\n".join(
                f"【{it.title}】\n{(it.content or '')[:1400]}" for it in top)
            system = (
                "你是『AI 短剧知识库向导』，一位亲切专业的产品引导员。"
                "请严格只依据下方『知识库参考』用简体中文回答用户问题，语气口语化、像在引导新手；"
                "不要编造知识库以外的数据；若参考里没有答案，坦诚说明『这方面知识库暂未覆盖』并给一条通用建议。"
                "回答控制在 280 字以内，结尾另起一行附『📚 相关参考：』并列出用到的条目标题。"
            )
            user = f"用户问题：{question}\n\n知识库参考：\n{kb_text}"
            answer = chat_complete(system, user, max_tokens=900, timeout=60).strip()
            used_llm = True
        except Exception:
            answer = None
    else:
        answer = None

    if not answer:
        # 断网 / 无 key / LLM 失败 → 关键词兜底：拼接最相关条目的精炼内容
        fallback = True
        if top:
            blocks = []
            for it in top[:3]:
                c = (it.content or "").strip()
                c = c[:600]
                blocks.append(f"【{it.title}】\n{c}")
            answer = ("（离线关键词答复）为你找到以下相关知识：\n\n" + "\n\n".join(blocks) +
                      "\n\n💡 联网后我将用更自然的语言为你讲解；你也可以在上方直接点开对应条目查看完整内容。")
        else:
            answer = ("知识库中暂未匹配到相关内容。你可以试试问：『新手怎么用 AI 做短剧？』"
                      "『选题怎么爆？』『怎么变现？』『AIGC 要怎么标识？』『平台怎么选？』")

    return {"answer": answer, "refs": refs, "used_llm": used_llm, "fallback": fallback}


# ---------------- 用户端公开资料库（对外，绝不含内部机密） ----------------
from fastapi import APIRouter as _APIRouter

public_router = _APIRouter(prefix="/api/user/knowledge", tags=["kb_public"])

# 用户端可对外公开的三大子库（与后台 internal 库完全隔离）
PUBLIC_SUBLIB_GROUPS = [
    {"key": "cases",      "name": "爆款拆解", "icon": "🔥",
     "desc": "公开爆款的类型、平台与钩子套路（方法论级，不搬运原文）"},
    {"key": "monetize",   "name": "变现地图", "icon": "💰",
     "desc": "分账 / 补贴 / 广告 / 电商 / 定制等变现路径"},
    {"key": "compliance", "name": "合规手册", "icon": "🛡️",
     "desc": "AIGC 标识、备案、版权、未成年人等红线"},
]
_ALLOWED = {"cases", "monetize", "compliance"}


@public_router.get("/public/groups", response_model=dict)
def public_groups(_: User = Depends(get_current_user)):
    """用户端资料库导航：仅返回可公开的三类。"""
    return {"sublibs": PUBLIC_SUBLIB_GROUPS}


@public_router.get("/public/by-group", response_model=list[schemas.KnowledgeItemOut])
def public_by_group(sublib: str, db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)):
    """按子库取公开条目。白名单拦截：任何非公开分类一律 400，绝不返回 internal 库。"""
    if sublib not in _ALLOWED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不支持的分类")
    items = (db.query(KnowledgeItem)
             .filter(KnowledgeItem.sublib == sublib,
                     KnowledgeItem.visibility == "public")
             .order_by(KnowledgeItem.sort_order, KnowledgeItem.id.asc()).all())
    return items
