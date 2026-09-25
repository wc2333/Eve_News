"""Fetch the article page when the feed only handed over one thin sentence.

RSS descriptions range from a full article (qbitai, ithome) to a single line (arXiv, InfoQ).
A one-line blurb cannot support a 300 字 brief no matter how good the model is, so anything
thinner than THIN_MATERIAL gets its page pulled once, at curation time, for the shortlist only.
"""

from __future__ import annotations

import html
import logging
import re

from .models import Article
from .net import HttpError, fetch_bytes

log = logging.getLogger("evenews.article")

THIN_MATERIAL = 320          # 来源正文少于这么多字才值得去抓原页
MAX_BODY_CHARS = 4000        # 抓回来的正文最多留这么多
MAX_PAGE_BYTES = 3_000_000   # 比这还大的页面不是文章，是下载页或者图片

SCRIPT_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.I | re.S)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
PARAGRAPH_RE = re.compile(r"<(p|li|blockquote|h2|h3)[^>]*>(.*?)</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BODIES: dict[str, str] = {}


def html_to_text(raw: bytes | str, limit: int = MAX_BODY_CHARS) -> str:
    """Prose out of an article page: paragraphs first, whole-page text if that comes up empty."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = COMMENT_RE.sub(" ", SCRIPT_RE.sub(" ", text))
    parts: list[str] = []
    total = 0
    for _, inner in PARAGRAPH_RE.findall(text):
        piece = SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", inner))).strip()
        if len(piece) < 24:
            continue
        parts.append(piece)
        total += len(piece)
        if total >= limit:
            break
    body = "\n".join(parts)
    if len(body) < 200:
        # Either the page really is short, or it puts prose in divs instead of <p>.
        whole = SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", text))).strip()
        if len(whole) > max(600, len(body) * 3):
            body = whole
    return body[:limit]


def fetch_body(url: str, *, timeout: int = 25, proxy: str = "", headers: dict | None = None) -> str:
    raw = fetch_bytes(url, timeout=timeout, retries=0, proxy=proxy or None, headers=headers)
    if len(raw) > MAX_PAGE_BYTES:
        return ""
    return html_to_text(raw)


def enrich_articles(
    articles: list[Article],
    *,
    timeout: int = 25,
    proxy: str = "",
    headers: dict | None = None,
) -> int:
    """Put page text into `article.body` for the thin ones. A dead page just keeps the RSS blurb."""
    filled = 0
    for article in articles:
        if article.body or len(article.raw_summary or "") >= THIN_MATERIAL or not article.url:
            continue
        if article.url not in _BODIES:
            try:
                _BODIES[article.url] = fetch_body(article.url, timeout=timeout, proxy=proxy, headers=headers)
            except (HttpError, OSError, ValueError) as exc:
                log.info("抓不到 %s 的正文，沿用订阅里的摘要：%s", article.url, exc)
                _BODIES[article.url] = ""
        article.body = _BODIES[article.url]
        if article.body:
            filled += 1
    if filled:
        log.info("补抓正文：%d 条来源订阅太短，已取回原文", filled)
    return filled


def material(article: Article, limit: int = 2600) -> str:
    """What the model actually gets to read about one item."""
    return (article.body or article.raw_summary or article.title).strip()[:limit]
