"""One digest run: collect -> curate -> render -> mail -> archive."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import Config
from .curator import curate_section, dedupe_across_sections, write_lead
from .feeds import Harvest, harvest
from .llm import build_llm
from .mailer import MailError, send_digest
from .models import Digest, Section, Source
from .render import render_html, render_markdown, render_text, subject_for, write_outputs
from .search import SearchConfig, build_queries
from .state import StateStore

log = logging.getLogger("evenews.pipeline")

SAMPLE_FEEDS = Path(__file__).resolve().parent / "sample" / "feeds"


@dataclass
class RunReport:
    run_date: str
    sections: list[str] = field(default_factory=list)
    candidates: int = 0
    items: int = 0
    files: dict[str, Path] = field(default_factory=dict)
    subject: str = ""
    recipients: list[str] = field(default_factory=list)
    sent: bool = False
    demo: bool = False
    failed_sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.run_date}",
            f"候选 {self.candidates} 条",
            f"入选 {self.items} 条",
            f"板块 {len(self.sections)} 个",
        ]
        if self.files:
            parts.append(f"输出 {self.files.get('html')}")
        if self.demo:
            parts.insert(1, "演示数据（内置样例，非真实新闻）")
        if self.failed_sources:
            parts.append(f"失败来源 {len(self.failed_sources)} 个")
        parts.append("已发送 → " + ", ".join(self.recipients) if self.sent else "未发送")
        return " | ".join(parts)


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("找不到时区 %s，改用 UTC", name)
        return ZoneInfo("UTC")


def attach_search_sources(sections: list[Section], llm, config: Config) -> list[Section]:
    """mode = llm / hybrid: let the model write the queries, then feed them to the search provider."""
    search_cfg = SearchConfig.from_llm(config.llm)
    if not search_cfg.ready:
        log.info("llm.search 未配置密钥，跳过联网检索")
        return sections
    enriched: list[Section] = []
    for section in sections:
        clone = deepcopy(section)
        for query in build_queries(section, llm, search_cfg):
            clone.sources.append(_search_source(query, config))
        enriched.append(clone)
    return enriched


def _search_source(query: str, config: Config) -> Source:
    return Source(name=f"检索·{query}", url=query, type="search", headers={"query": query, "search": config.llm.search})


def run_once(
    config: Config,
    *,
    when: str | datetime | None = None,
    only: list[str] | None = None,
    offline: bool = False,
    fixtures: Path | None = None,
    send: bool = True,
    out_root: Path | None = None,
) -> RunReport:
    tz = _timezone(config.schedule.timezone)
    if isinstance(when, str):
        now = datetime.fromisoformat(when).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
    elif isinstance(when, datetime):
        now = when if when.tzinfo else when.replace(tzinfo=tz)
    else:
        now = datetime.now(tz)
    run_date = now.date().isoformat()

    sections = config.enabled_sections(only)
    if offline:
        config.llm.provider = "mock"
        fixtures = Path(fixtures) if fixtures else SAMPLE_FEEDS
        config.collection.lookback_hours = 0
        log.info("离线演示模式：使用 mock 模型 + 样例来源 %s", fixtures)
    demo = fixtures is not None
    llm = build_llm(config.llm)
    if config.collection.mode in {"llm", "hybrid"}:
        sections = attach_search_sources(sections, llm, config)

    collected: Harvest = harvest(
        sections, config.collection, now=now, fixtures_dir=fixtures, fixtures_only=bool(offline)
    )
    state = StateStore(config.state_root / "state.json") if not offline else None

    section_digests = [
        curate_section(
            section,
            collected.by_section.get(section.id, []),
            llm=llm,
            collection=config.collection,
            llm_cfg=config.llm,
            state=state,
            run_date=run_date,
        )
        for section in sections
    ]
    dedupe_across_sections(section_digests)
    digest = Digest(
        run_date=run_date,
        generated_at=now.replace(microsecond=0).isoformat(),
        timezone=config.schedule.timezone,
        sections=section_digests,
        stats={
            "mode": config.collection.mode,
            "model": llm.label,
            "sources": len(collected.sources_used),
            "fetched": collected.fetched,
            "candidates": len(collected.candidates),
            "failed_sources": collected.failed,
            "fetch_errors": [error[:170] for error in collected.errors],
            "demo": demo,
        },
    )
    digest.lead = write_lead(llm, config.llm, digest)

    target_root = Path(out_root) if out_root else config.out_root / run_date
    files = write_outputs(digest, config.brand, target_root)
    subject = subject_for(digest, config.brand, config.email.subject_template, config.email.subject_prefix)
    if demo:
        subject = f"[演示] {subject}"

    html = files["html"].read_text(encoding="utf-8") if files["html"].is_file() else render_html(digest, config.brand)
    text = render_text(digest, config.brand)

    report = RunReport(
        run_date=run_date,
        sections=[sd.section.id for sd in section_digests],
        candidates=len(collected.candidates),
        items=digest.item_count,
        files=files,
        subject=subject,
        errors=list(collected.errors),
        demo=demo,
        failed_sources=list(collected.failed),
    )

    if send and config.email.enabled and not digest.item_count:
        report.errors.append("本期没有任何入选条目，已跳过发送（检查来源与 require_keywords）")
        log.error("本期没有入选条目，跳过发送")
    elif send and config.email.enabled:
        try:
            report.recipients = send_digest(
                config.email,
                subject=subject,
                html=html,
                text=text,
                attachments=[files["html"]] if config.email.attach_html else None,
            )
            report.sent = True
        except MailError as exc:
            report.errors.append(str(exc))
            log.error("邮件发送失败：%s", exc)
    elif not report.sent and not report.errors:
        log.info("跳过发送（dry-run 或 email.enabled=false）")

    if digest.item_count and state is not None:
        published = [item.fingerprint for sd in section_digests for item in sd.items]
        state.mark_seen(published, run_date)
        state.prune(run_date, config.collection.dedupe_days + 5)
        state.record_run(
            {
                "run_date": run_date,
                "items": digest.item_count,
                "candidates": len(collected.candidates),
                "sent": report.sent,
                "subject": subject,
            }
        )
        state.save()
    return report
