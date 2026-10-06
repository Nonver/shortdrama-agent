"""RAG 网络爬虫：抓取权威短剧资料 → 清洗 → 归类 → 幂等导入知识库。

用途：知识库里还有空位的子库（平台规则/类型/风格/剧本资产/AI短剧知识库向导），
      本脚本按 curated 来源列表联网爬取，HTML→纯文本，按章节切分，自动归类到
      platform/genre/style/asset/guide 子库，按 URL 哈希幂等 upsert 入库。

运行：
    cd backend
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/crawl_kb.py
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/crawl_kb.py --dry-run   # 只抓取不写库

依赖：仅标准库（urllib / ssl / html / re）+ 项目 app（SQLAlchemy）。无第三方包。
注意：部分新闻站点会拦截爬虫 UA，抓取失败会记录并跳过，不影响其他来源。
"""
from __future__ import annotations
import argparse
import hashlib
import html as _html
import re as _re
import ssl
import sys
import time
import urllib.request
from datetime import datetime, date
from pathlib import Path

# ---- 项目路径（脚本位于 backend/scripts，需能 import app） ----
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import SessionLocal  # noqa: E402
from app.models import KnowledgeItem  # noqa: E402

COLLECTED_AT = date.today().isoformat()

# 抓取后落库的目录（便于人工抽检原始抓取文本）
CRAWLED_DIR = Path(__file__).resolve().parent.parent / "data" / "crawled"
CRAWLED_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- curated 来源列表（权威：广电总局 / 各平台官方 / 行业报告） ----------------
# sublib: platform | genre | style | asset | guide
# platform: hongguo/douyin/kuaishou/tencent/mango/iqiyi/migu/dianzhong/general
SOURCES = [
    {"url": "https://www.news.cn/politics/20260731/f9760507db5c45d0a04196a2821be1aa/c.html",
     "sublib": "platform", "platform": "general",
     "title": "《微短剧发展管理办法》（2026-09-01 施行）要点",
     "tags": ["广电总局", "备案", "合规", "管理办法"]},
    {"url": "https://www.thepaper.cn/newsDetail_forward_32465752",
     "sublib": "platform", "platform": "tencent",
     "title": "腾讯视频短剧分账与扶持新政（2026）",
     "tags": ["腾讯视频", "分账", "厂牌激励", "系列化"]},
    {"url": "https://finance.sina.cn/2026-05-25/detail-inhzcpii2783965.d.html",
     "sublib": "platform", "platform": "mango",
     "title": "芒果TV女频情感短剧分账与千部IP计划",
     "tags": ["芒果TV", "女频", "保底摸高", "千部IP"]},
    {"url": "https://yule.sohu.com/a/1066836741_122475349",
     "sublib": "platform", "platform": "iqiyi",
     "title": "爱奇艺创作者大会：全额分账 + AIGC 野火计划",
     "tags": ["爱奇艺", "全额分账", "纳逗Pro", "AIGC"]},
    {"url": "https://www.tvoao.com/a/224259.aspx",
     "sublib": "platform", "platform": "general",
     "title": "六大平台微短剧扶持细则汇总（含咪咕/点众/优酷）",
     "tags": ["扶持", "分账", "咪咕", "点众", "优酷", "行业"]},
    {"url": "https://www.toutiao.com/a7663466183340900890",
     "sublib": "guide", "platform": "general",
     "title": "2026 AI短剧制作教程（零成本单人实操）",
     "tags": ["向导", "制作流程", "新手", "教程", "工具链"]},
    {"url": "https://m.toutiao.com/article/7625220965479367219",
     "sublib": "guide", "platform": "general",
     "title": "AI短剧变现指南（分账/付费/带货/出海）",
     "tags": ["向导", "变现", "分账", "付费", "出海", "IAP"]},
]


def _fetch(url: str, timeout: int = 25) -> tuple[str, str | None]:
    """返回 (clean_text, title)。失败返回 ('', None)。"""
    req = urllib.request.Request(
        url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(2_000_000)
            enc = resp.headers.get_content_charset() or "utf-8"
    except Exception as e:  # noqa
        # 部分站点拦截，再试一次（不带自定义 context）
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(2_000_000)
                enc = resp.headers.get_content_charset() or "utf-8"
        except Exception as e2:  # noqa
            return "", f"fetch-failed: {e2}"
    # 多编码兜底：优先信任声明编码；仅当其 replacement 比例过高（说明实为非 UTF-8）才回退 GBK/GB18030。
    # 避免把真正的 UTF-8 页面误判为 GBK（GBK 解码 UTF-8 字节也会产出大量『看似中文』的乱码）。
    cands = []
    seen = set()
    for cand in [enc, "utf-8", "gb18030", "gbk"]:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            t = raw.decode(cand, "ignore")
        except Exception:
            continue
        cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
        rep = t.count("\ufffd")
        ratio = rep / max(1, len(t))
        cands.append({"enc": cand, "text": t, "cjk": cjk, "ratio": ratio})

    html_bytes = None
    # 1) 声明/utf-8 可信：含中文且 replacement 比例低 → 采用（按候选顺序优先）
    for c in cands:
        if c["cjk"] >= 30 and c["ratio"] < 0.02:
            html_bytes = c["text"]
            break
    # 2) 兜底：在含中文的候选里选 replacement 比例最低
    if html_bytes is None:
        valid = [c for c in cands if c["cjk"] >= 30]
        if valid:
            html_bytes = min(valid, key=lambda c: c["ratio"])["text"]
        elif cands:
            html_bytes = min(cands, key=lambda c: c["ratio"])["text"]
        else:
            html_bytes = raw.decode("utf-8", "ignore")
    # 抽取 <title>
    mtitle = _re.search(r"<title[^>]*>(.*?)</title>", html_bytes, _re.S | _re.I)
    title = _html.unescape(_re.sub(r"\s+", " ", mtitle.group(1)).strip()) if mtitle else ""
    # 去 script/style/noscript
    body = _re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_bytes, flags=_re.S | _re.I)
    # 标签→换行/空格
    body = _re.sub(r"<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", body, flags=_re.I)
    body = _re.sub(r"<[^>]+>", " ", body)
    body = _html.unescape(body)
    # 清洗空白
    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if len(ln) > 1]
    text = "\n".join(lines)
    text = _re.sub(r"[ \t]+", " ", text)
    text = _re.sub(r"\n{2,}", "\n", text).strip()
    return text, title


def _classify(text: str, src: dict) -> tuple[str, str]:
    """已 curated，但做轻量兜底：若来源未指定平台，从文本猜平台。"""
    sublib = src.get("sublib", "general")
    platform = src.get("platform", "general")
    if platform == "general" and sublib == "platform":
        for kw, pk in [("腾讯视频", "tencent"), ("芒果", "mango"), ("爱奇艺", "iqiyi"),
                       ("咪咕", "migu"), ("点众", "dianzhong"), ("红果", "hongguo"),
                       ("抖音", "douyin"), ("快手", "kuaishou")]:
            if kw in text:
                return sublib, pk
    return sublib, platform


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只抓取不写库")
    args = ap.parse_args()

    db = None if args.dry_run else SessionLocal()
    imported = skipped = failed = 0
    print(f"== RAG 知识库爬虫 @ {COLLECTED_AT} ==")
    for src in SOURCES:
        url = src["url"]
        text, title = _fetch(url)
        if not text:
            failed += 1
            print(f"[跳过] 抓取失败 {url}  ({title})")
            continue
        sublib, platform = _classify(text, src)
        # 标题优先用页面 <title>，否则用 curated
        page_title = title or src.get("title", url)
        # 内容截断（避免单条过大）
        content = text[:4000]
        key = "crawl_" + hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        tags = list(src.get("tags", []))
        meta = {"source": url, "source_title": page_title, "crawled_at": COLLECTED_AT, "crawler": True}

        # 原始抓取存档（便于抽检）
        try:
            (CRAWLED_DIR / (key + ".txt")).write_text(
                f"# {page_title}\n# {url}\n# sublib={sublib} platform={platform}\n\n{text}",
                encoding="utf-8")
        except Exception:
            pass

        if args.dry_run:
            imported += 1
            print(f"[dry] {sublib}/{platform} 《{page_title[:30]}》 {len(content)} 字")
            continue

        row = db.query(KnowledgeItem).filter(
            KnowledgeItem.sublib == sublib, KnowledgeItem.key == key).first()
        if row:
            row.content = content
            row.title = page_title
            row.platform = platform
            row.tags = tags
            row.meta = meta
            row.updated_at = datetime.now()
            skipped += 1
            print(f"[更新] {sublib}/{platform} 《{page_title[:30]}》")
        else:
            db.add(KnowledgeItem(sublib=sublib, key=key, platform=platform,
                                 title=page_title, content=content, tags=tags,
                                 meta=meta, sort_order=100))
            imported += 1
            print(f"[新增] {sublib}/{platform} 《{page_title[:30]}》 {len(content)} 字")
        db.commit()
        time.sleep(0.5)  # 礼貌限速

    if db:
        db.close()
    print(f"== 完成：新增 {imported} / 更新 {skipped} / 失败 {failed} ==")


if __name__ == "__main__":
    main()
