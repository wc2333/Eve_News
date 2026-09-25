"""Data structures shared by collectors, the curation stage and the renderer."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse


def fingerprint(url: str, title: str) -> str:
    """Stable identity for an article, used to avoid repeating the same news."""
    key = (url or "").strip().lower().rstrip("/")
    if not key:
        key = "title:" + (title or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def domain_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


@dataclass
class Source:
    name: str
    url: str
    type: str = "rss"
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url, "type": self.type}


@dataclass
class Section:
    id: str
    title: str
    description: str = ""
    enabled: bool = True
    keywords: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    extra_prompt: str = ""
    max_items: int = 6

    def keyword_hits(self, *texts: str) -> list[str]:
        blob = " ".join(t for t in texts if t).lower()
        return [kw for kw in self.keywords if kw and kw.lower() in blob]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "enabled": self.enabled,
            "keywords": list(self.keywords),
            "max_items": self.max_items,
            "sources": [s.to_dict() for s in self.sources],
        }


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: str = ""
    raw_summary: str = ""
    section: str = ""
    summary: str = ""
    why: str = ""
    score: float = 0.0
    keywords: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.url, self.title)

    @property
    def domain(self) -> str:
        return domain_of(self.url)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SectionDigest:
    section: Section
    items: list[Article] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"section": self.section.to_dict(), "items": [i.to_dict() for i in self.items]}


@dataclass
class Digest:
    run_date: str
    generated_at: str
    timezone: str
    lead: str = ""
    sections: list[SectionDigest] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def item_count(self) -> int:
        return sum(len(sd.items) for sd in self.sections)

    @property
    def sources_used(self) -> list[Source]:
        unique: dict[str, Source] = {}
        for section_digest in self.sections:
            for source in section_digest.section.sources:
                unique[f"{source.name}|{source.url}"] = source
        return sorted(unique.values(), key=lambda s: s.name)

    def to_dict(self) -> dict:
        return {
            "run_date": self.run_date,
            "generated_at": self.generated_at,
            "timezone": self.timezone,
            "lead": self.lead,
            "stats": self.stats,
            "sources": [s.to_dict() for s in self.sources_used],
            "sections": [sd.to_dict() for sd in self.sections],
        }
