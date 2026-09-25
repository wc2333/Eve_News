"""Curation: rules filter the noise, the model picks and writes, rules keep the result honest."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from .config import CollectionConfig, LLMConfig
from .llm import BaseLLM
from .models import Article, Digest, Section, SectionDigest
from .state import StateStore

log = logging.getLogger("evenews.curator")

MIN_SCORE = 0.3
PUNCT_RE = re.compile(r"[\s\W_]+", re.U)
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])")


def normalize_title(title: str) -> str:
    return PUNCT_RE.sub("", (title or "").lower())


def similar(left: str, right: str) -> bool:
    """Cheap character-bigram similarity, good enough to catch re-posted stories."""
    a, b = normalize_title(left), normalize_title(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    def grams(text: str) -> set[str]:
        return {text[i : i + 2] for i in range(len(text) - 1)} if len(text) > 1 else {text}
    ga, gb = grams(a), grams(b)
    overlap = len(ga & gb) / max(1, min(len(ga), len(gb)))
    return overlap >= 0.72


def rule_score(article: Article, hits: list[str], run_date: str = "") -> float:
    digits = len(re.findall(r"\d", article.title))
    score = 0.35 + 0.1 * min(len(hits), 4) + 0.02 * min(digits, 5)
    if not article.published:
        score -= 0.05
    elif run_date and article.published >= run_date:
        score += 0.08  # 今天发生的往上抬
    elif run_date:
        score -= 0.06  # 昨天的往下压，别让旧闻占版面
    return round(min(score, 0.9), 3)


def plain_summary(article: Article, limit: int = 130) -> str:
    body = (article.raw_summary or article.title).strip()
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(body) if s.strip()]
    text = "".join(sentences[:2]) if sentences else body
    return text[:limit] or article.title[:limit]


def is_relevant(article: Article, cfg: CollectionConfig) -> bool:
    blob = f"{article.title} {article.raw_summary}".lower()
    if any(k.lower() in blob for k in cfg.exclude_keywords):
        return False
    if cfg.require_keywords and not any(k.lower() in blob for k in cfg.require_keywords):
        return False
    return True


def _batches(items: list[Article], size: int) -> list[list[Article]]:
    size = max(4, size)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _ask_model(llm: BaseLLM, section: Section, batch: list[Article], *, offset: int = 0) -> dict[int, dict]:
    payload = {
        "section": {
            "id": section.id,
            "title": section.title,
            "description": section.description,
            "extra_prompt": section.extra_prompt,
            "keywords": section.keywords[:24],
        },
        "today": datetime.now().date().isoformat(),
        "candidates": [
            {
                "ref": offset + index,
                "title": article.title,
                "summary": article.raw_summary[:400],
                "source": article.source,
                "published": article.published,
            }
            for index, article in enumerate(batch)
        ],
        "rules": {
            "score_range": "0-1，表示值得推送给同事的程度",
            "drop": "与板块无关、纯营销、重复内容请给 0-0.2 的低分",
            "summary": "80-140 个汉字，先说结论再补关键数字，不要开头复述标题",
            "why": "一句话说明为什么值得看，不超过 30 字",
            "output": '{"items":[{"ref":0,"score":0.0,"summary":"","why":"","keywords":[]}, ...]}',
        },
    }
    data = llm.json_task("curate", payload)
    parsed: dict[int, dict] = {}
    for entry in data.get("items") or []:
        if not isinstance(entry, dict):
            continue
        try:
            ref = int(entry.get("ref"))
        except (TypeError, ValueError):
            continue
        parsed[ref] = entry
    return parsed


def curate_section(
    section: Section,
    candidates: list[Article],
    *,
    llm: BaseLLM,
    collection: CollectionConfig,
    llm_cfg: LLMConfig,
    state: StateStore | None = None,
    run_date: str | None = None,
) -> SectionDigest:
    today = datetime.fromisoformat(run_date) if run_date else datetime.now()
    not_before = (today - timedelta(days=collection.dedupe_days)).date().isoformat()

    kept: list[tuple[Article, float]] = []
    for article in candidates:
        if not is_relevant(article, collection):
            continue
        if state is not None and state.seen_before(article.fingerprint, not_before):
            continue
        hits = article.keywords or section.keyword_hits(article.title, article.raw_summary)
        article.keywords = hits
        kept.append((article, rule_score(article, hits, run_date)))

    kept.sort(key=lambda pair: pair[1], reverse=True)
    pool = kept[: max(section.max_items * 3, llm_cfg.batch_size)]

    decisions: dict[int, dict] = {}
    if llm_cfg.task_on("select"):
        batches = _batches([article for article, _ in pool], llm_cfg.batch_size)
        offset = 0
        for batch_index, batch in enumerate(batches):
            try:
                decisions.update(_ask_model(llm, section, batch, offset=offset))
            except Exception as exc:  # noqa: BLE001 - a model hiccup must not kill the digest
                log.warning("板块 %s 第 %d 批模型筛选失败，该批改用规则打分：%s", section.id, batch_index + 1, exc)
                continue
            offset += len(batch)

    curated: list[Article] = []
    for index, (article, score) in enumerate(pool):
        decision = decisions.get(index) or {}
        try:
            model_score = float(decision.get("score"))
        except (TypeError, ValueError):
            model_score = score
        final_score = model_score if llm_cfg.task_on("select") and decision else score
        if final_score < MIN_SCORE:
            continue
        if llm_cfg.task_on("summarize") and str(decision.get("summary") or "").strip():
            article.summary = str(decision["summary"]).strip()
        else:
            article.summary = plain_summary(article)
        article.why = str(decision.get("why") or "").strip() or (
            ("命中关键词：" + "、".join(article.keywords[:3])) if article.keywords else "板块相关"
        )
        article.keywords = [str(k) for k in decision.get("keywords") or article.keywords][:6]
        article.score = round(final_score, 3)
        curated.append(article)

    curated.sort(key=lambda a: a.score, reverse=True)
    unique: list[Article] = []
    for article in curated:
        if any(similar(article.title, other.title) for other in unique):
            continue
        unique.append(article)
        if len(unique) >= section.max_items:
            break
    return SectionDigest(section=section, items=unique)


def dedupe_across_sections(section_digests: list[SectionDigest]) -> int:
    """A story belongs to a single section - the one that scored it highest."""
    best: dict[str, tuple[float, int]] = {}
    for order, section_digest in enumerate(section_digests):
        for item in section_digest.items:
            current = best.get(item.fingerprint)
            if current is None or item.score > current[0]:
                best[item.fingerprint] = (item.score, order)
    dropped = 0
    for order, section_digest in enumerate(section_digests):
        keep: list[Article] = []
        for item in section_digest.items:
            if best[item.fingerprint][1] == order:
                keep.append(item)
            else:
                dropped += 1
        section_digest.items = keep
    return dropped


def write_lead(llm: BaseLLM, llm_cfg: LLMConfig, digest: Digest) -> str:
    overview = [
        {
            "title": section_digest.section.title,
            "count": len(section_digest.items),
            "headlines": [item.title for item in section_digest.items[:3]],
        }
        for section_digest in digest.sections
    ]
    if not llm_cfg.task_on("lead"):
        return ""
    try:
        data = llm.json_task(
            "lead",
            {
                "date": digest.run_date,
                "item_count": digest.item_count,
                "sections": overview,
                "rules": {
                    "length": "120-220 个汉字",
                    "style": "先点出今天最重要的两三条主线，再说明各板块看点，不要堆形容词",
                    "output": '{"lead":""}',
                },
            },
        )
        lead = str(data.get("lead") or "").strip()
        if lead:
            return lead
    except Exception as exc:  # noqa: BLE001
        log.warning("导语生成失败，使用统计式导语：%s", exc)
    parts = [f"{row['title']} {row['count']} 条" for row in overview if row["count"]]
    return f"今日共整理 {digest.item_count} 条资讯：" + "；".join(parts) + "。"
