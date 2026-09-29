"""Optional web-search collector: lets the configured model go fetch news itself."""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlparse

from .config import LLMConfig
from .models import Section
from .net import HttpError, fetch_bytes, fetch_json

log = logging.getLogger("evenews.search")

ENDPOINTS = {
    "tavily": "https://api.tavily.com/search",
    "serper": "https://google.serper.dev/search",
    "bing": "https://www.bing.com/search",
}
KEYFREE_PROVIDERS = {"bing"}   # 免密钥：直接抓搜索结果页，不查任何 API Key


@dataclass
class SearchConfig:
    provider: str = "none"
    api_key: str = ""
    endpoint: str = ""
    region: str = "cn"
    language: str = "zh-cn"
    days: int = 2
    max_results: int = 12
    queries_per_section: int = 2
    timeout: int = 30
    proxy: str = ""
    headers: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "SearchConfig":
        env_name = str(raw.get("api_key_env") or "").strip()
        api_key = os.environ.get(env_name, "") if env_name else ""
        api_key = api_key or str(raw.get("api_key") or "")
        return cls(
            provider=str(raw.get("provider") or "none").lower(),
            proxy=str(raw.get("proxy") or os.environ.get("EVE_NEWS_PROXY") or "").strip(),
            api_key=api_key,
            endpoint=str(raw.get("endpoint") or "").rstrip("/"),
            region=str(raw.get("region") or "cn"),
            language=str(raw.get("language") or "zh-cn"),
            days=int(raw.get("days") or 2),
            max_results=int(raw.get("max_results") or 12),
            queries_per_section=int(raw.get("queries_per_section") or 2),
            timeout=int(raw.get("timeout") or 30),
            headers=dict(raw.get("headers") or {}),
        )

    @classmethod
    def from_llm(cls, llm_cfg: LLMConfig) -> "SearchConfig":
        return cls.from_dict(llm_cfg.search or {})

    @property
    def ready(self) -> bool:
        if self.provider in {"", "none", "off"}:
            return False
        return bool(self.api_key or self.endpoint) or self.provider in KEYFREE_PROVIDERS


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def run_search(query: str, cfg: SearchConfig, *, limit: int = 12) -> list[dict]:
    if not cfg.ready:
        log.info("未配置联网检索（llm.search.provider），跳过: %s", query)
        return []
    endpoint = cfg.endpoint or ENDPOINTS.get(cfg.provider, "")
    if not endpoint:
        log.warning("未知的检索供应商: %s", cfg.provider)
        return []
    try:
        if cfg.provider == "tavily":
            payload = {
                "api_key": cfg.api_key,
                "query": query,
                "max_results": min(limit, cfg.max_results),
                "topic": "news",
                "days": cfg.days,
                "include_answer": False,
            }
            headers = {"Authorization": f"Bearer {cfg.api_key}", **cfg.headers}
            data = fetch_json(endpoint, payload=payload, headers=headers, timeout=cfg.timeout, proxy=cfg.proxy or None)
            rows = data.get("results") or []
            return [
                {
                    "title": row.get("title") or "",
                    "url": row.get("url") or "",
                    "content": row.get("content") or "",
                    "published": (row.get("published_date") or "")[:10],
                    "source": _domain(row.get("url") or ""),
                }
                for row in rows
            ]
        if cfg.provider == "serper":
            payload = {
                "q": query,
                "gl": cfg.region,
                "hl": cfg.language,
                "num": min(limit, cfg.max_results),
                "tbs": "qdr:d" if cfg.days <= 1 else f"qdr:w",
            }
            headers = {"X-API-KEY": cfg.api_key, **cfg.headers}
            data = fetch_json(endpoint, payload=payload, headers=headers, timeout=cfg.timeout, proxy=cfg.proxy or None)
            rows = data.get("organic") or []
            return [
                {
                    "title": row.get("title") or "",
                    "url": row.get("link") or "",
                    "content": row.get("snippet") or "",
                    "published": row.get("date") or "",
                    "source": _domain(row.get("link") or ""),
                }
                for row in rows
            ]
        if cfg.provider == "bing":
            # 免密钥抓取：直接读 Bing 搜索结果页，带 24 小时 / 一周时间过滤。
            from .feeds import clean   # 函数内引入，别和 feeds 顶上来回绕

            params = f"?q={quote(query)}&count={min(limit, cfg.max_results)}"
            if (cfg.language or "").startswith("zh"):
                params += "&setlang=zh-hans"
            if cfg.days <= 1:
                params += "&filters=ex1%3a%22ez1%22"   # 24 小时内
            elif cfg.days <= 7:
                params += "&filters=ex1%3a%22ez2%22"   # 一周内
            raw = fetch_bytes(endpoint + params, timeout=cfg.timeout, retries=1,
                              proxy=cfg.proxy or None, headers=cfg.headers or None)
            page = raw.decode("utf-8", "replace")
            rows: list[dict] = []
            wanted = min(limit, cfg.max_results)
            for block in re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', page, re.S):
                head = re.search(r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S) \
                    or re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S)
                if not head:
                    continue
                url = html.unescape(head.group(1)).strip()
                # 标题里的 <strong>/<span> 直接去掉、不垫空格（中文标题垫了空格很难看）
                title = clean(re.sub(r"<[^>]+>", "", head.group(2)), 240)
                if not title or not url.startswith(("http://", "https://")):
                    continue
                snip = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
                content = clean(snip.group(1), 800) if snip else title
                content = re.sub(r"^\s*\d+\s*(分钟|小时|天|周)前\s*[·:，,]?\s*", "", content)
                stamp = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", block)
                published = f"{stamp.group(1)}-{int(stamp.group(2)):02d}-{int(stamp.group(3)):02d}" if stamp else ""
                rows.append({"title": title, "url": url, "content": content,
                             "published": published, "source": _domain(url)})
                if len(rows) >= wanted:
                    break
            if not rows:
                log.warning("Bing 检索没有解析到结果（页面改版或被拦）：[%s]", query)
            return rows
        log.warning("暂不支持的检索供应商: %s", cfg.provider)
    except HttpError as exc:
        log.warning("联网检索失败 [%s]: %s", query, exc)
    return []


def build_queries(section: Section, llm, cfg: SearchConfig) -> list[str]:
    """Ask the model for search queries; fall back to keyword templates when unavailable."""
    wanted = max(1, cfg.queries_per_section)
    try:
        data = llm.json_task(
            "queries",
            {
                "section": {
                    "id": section.id,
                    "title": section.title,
                    "description": section.description,
                    "keywords": section.keywords[:12],
                },
                "count": wanted,
                "instruction": "给出最近 24 小时内最值得检索的中文查询词，每个 6-14 个字，附带当前年份。",
            },
        )
        queries = [str(q).strip() for q in data.get("queries") or [] if str(q).strip()]
    except Exception as exc:  # noqa: BLE001
        log.warning("生成检索词失败（板块 %s）：%s", section.id, exc)
        queries = []
    if not queries:
        keywords = section.keywords[:3]
        queries = [f"{section.title} 最新 进展"] + [f"{section.title} {' '.join(keywords[:2])}"]
    return queries[:wanted]
