"""Collect candidate articles from RSS/Atom feeds, local fixtures and web search."""

from __future__ import annotations

import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from copy import deepcopy
from urllib.parse import urlparse

import feedparser

from .config import CollectionConfig
from .models import Article, Section, Source
from .net import HttpError, fetch_bytes

log = logging.getLogger("evenews.feeds")

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SLUG_RE = re.compile(r"[^0-9A-Za-z]+")


def clean(text: str, limit: int = 800) -> str:
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return SPACE_RE.sub(" ", text).strip()[:limit]


def slugify(source: Source) -> str:
    ascii_slug = SLUG_RE.sub("_", source.name).strip("_").lower()
    if len(ascii_slug) >= 3:
        return ascii_slug
    host = urlparse(source.url).netloc.lower().replace("www.", "")
    return SLUG_RE.sub("_", host).strip("_").lower() or "source"


def entry_published(entry: dict) -> str:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        stamp = entry.get(key)
        if stamp:
            return datetime.fromtimestamp(time.mktime(stamp)).date().isoformat()
    return ""


def in_window(published: str, hours: int, now: datetime) -> bool:
    if not published or hours <= 0:
        return True
    try:
        published_day = datetime.fromisoformat(published).date()
    except ValueError:
        return True
    return published_day >= (now - timedelta(hours=hours)).date()


def parse_feed(raw: bytes, *, source_name: str, limit: int) -> list[Article]:
    parsed = feedparser.parse(raw)
    head = raw[:600].lower()
    if not parsed.entries and (b"<html" in head or b"<!doctype" in head):
        raise HttpError(f"{source_name}: 返回的是网页而不是 feed，地址多半已失效或需要代理")
    articles: list[Article] = []
    for entry in parsed.entries:
        title = clean(entry.get("title", ""), 240)
        url = (entry.get("link") or "").strip()
        if not title or not url:
            continue
        summary = clean(entry.get("summary") or entry.get("description") or "", 900)
        articles.append(
            Article(
                title=title,
                url=url,
                source=source_name,
                published=entry_published(entry),
                raw_summary=summary or title,
            )
        )
        if len(articles) >= limit:
            break
    return articles


def fixture_path(fixtures_dir: Path | None, source: Source) -> Path | None:
    if fixtures_dir is None:
        return None
    slug = slugify(source)
    for candidate in (Path(fixtures_dir) / f"{slug}.xml", Path(fixtures_dir) / f"{slug}.rss"):
        if candidate.is_file():
            return candidate
    return None


def fetch_source(
    source: Source,
    cfg: CollectionConfig,
    *,
    fixtures_dir: Path | None = None,
    fixtures_only: bool = False,
) -> list[Article]:
    fixture = fixture_path(fixtures_dir, source)
    if fixtures_only and fixture is None:
        log.info("离线模式：跳过没有本地样例的来源 %s", source.name)
        return []
    if source.type in {"rss", "atom", "feed", "file"} or fixture is not None:
        origin = str(fixture) if fixture is not None else source.url
        raw = fetch_bytes(
            origin,
            timeout=cfg.timeout,
            headers=cfg.headers,
            retries=int(getattr(cfg, "retries", 1) or 1),
            proxy=getattr(cfg, "proxy", "") or None,
        )
        return parse_feed(raw, source_name=source.name, limit=cfg.per_source_limit)
    if source.type in {"search", "web"}:
        return search_source(source, cfg)
    log.warning("忽略未知来源类型: %s (%s)", source.type, source.url)
    return []


def search_source(source: Source, cfg: CollectionConfig) -> list[Article]:
    """A source of type search: one query per entry, resolved through llm.search provider."""
    from . import search as search_module  # imported late to keep the offline path dependency-free

    query = source.headers.get("query") or source.url
    try:
        results = search_module.run_search(
            query,
            cfg=search_module.SearchConfig.from_dict(source.headers.get("search") or {}),
            limit=cfg.per_source_limit,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("联网检索失败 [%s]: %s", query, exc)
        return []
    return [
        Article(
            title=clean(r.get("title", ""), 240),
            url=r.get("url", ""),
            source=r.get("source") or source.name,
            published=(r.get("published") or "")[:10],
            raw_summary=clean(r.get("content", ""), 900),
        )
        for r in results
        if r.get("url")
    ]


@dataclass
class Harvest:
    by_section: dict[str, list[Article]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    fetched: int = 0
    sources_used: list[Source] = field(default_factory=list)

    @property
    def candidates(self) -> list[Article]:
        seen: dict[str, Article] = {}
        for items in self.by_section.values():
            for item in items:
                seen.setdefault(item.fingerprint, item)
        return list(seen.values())


def harvest(
    sections: list[Section],
    cfg: CollectionConfig,
    *,
    now: datetime,
    fixtures_dir: Path | None = None,
    fixtures_only: bool = False,
    max_workers: int = 8,
) -> Harvest:
    """Fetch every source once, then attach the results to every section that asked for it."""
    by_key: dict[str, Source] = {}
    owners: dict[str, list[str]] = {}
    for section in sections:
        for source in section.sources:
            key = f"{source.name}|{source.url}|{source.type}"
            by_key.setdefault(key, source)
            owners.setdefault(key, []).append(section.id)

    harvest_result = Harvest(sources_used=list(by_key.values()))

    def load(key: str) -> tuple[str, list[Article], str]:
        try:
            return key, fetch_source(by_key[key], cfg, fixtures_dir=fixtures_dir, fixtures_only=fixtures_only), ""
        except Exception as exc:  # noqa: BLE001 - one unreachable source must not sink the whole brief
            log.warning("来源抓取失败 [%s]: %s", by_key[key].name, exc)
            return key, [], str(exc)

    results: dict[str, tuple[list[Article], str]] = {}
    if by_key:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(by_key))) as pool:
            for key, articles, error in pool.map(load, list(by_key)):
                results[key] = (articles, error)

    for key, (articles, error) in results.items():
        if error:
            harvest_result.errors.append(f"{by_key[key].name}: {error}")
            harvest_result.failed.append(by_key[key].name)
        elif not articles:
            if fixtures_only and fixture_path(fixtures_dir, by_key[key]) is None:
                continue
            harvest_result.errors.append(f"{by_key[key].name}: 没有取到条目")
            harvest_result.failed.append(by_key[key].name)
        harvest_result.fetched += len(articles)
        for section_id in owners[key]:
            harvest_result.by_section.setdefault(section_id, [])
            harvest_result.by_section[section_id].extend(articles)

    for section in sections:
        fresh: dict[str, Article] = {}
        window_hours = cfg.lookback_hours
        for original in harvest_result.by_section.get(section.id, []):
            if not in_window(original.published, window_hours, now):
                continue
            scoped = deepcopy(original)
            scoped.section = section.id
            scoped.keywords = section.keyword_hits(original.title, original.raw_summary)
            fresh.setdefault(scoped.fingerprint, scoped)
        harvest_result.by_section[section.id] = sorted(fresh.values(), key=lambda a: a.published, reverse=True)
    return harvest_result
