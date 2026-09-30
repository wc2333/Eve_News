"""Curation: rules filter the noise, the model picks and writes, rules keep the result honest."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from .article import ENRICH_TIMEOUT, enrich_articles, material
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


def plain_summary(article: Article, limit: int = 360) -> str:
    """Fallback blurb when the model is off: stitch more sentences so it still reads whole."""
    body = (article.raw_summary or article.title).strip()
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(body) if s.strip()]
    text = "".join(sentences[:9]) if sentences else body
    if len(text) < limit * 2 and article.why:
        text = f"{text}{article.why}。"
    return text[:limit] or article.title[:limit]


def is_relevant(article: Article, cfg: CollectionConfig) -> bool:
    blob = f"{article.title} {article.raw_summary}".lower()
    if any(k.lower() in blob for k in cfg.exclude_keywords):
        return False
    if cfg.require_keywords and not any(k.lower() in blob for k in cfg.require_keywords):
        return False
    return True


SUMMARY_CHARS = (300, 400)
OVERSHOOT = 0.8   # 模型拿到材料就往长了写：实测目标 400 字，实收 510-580 字，所以按 0.8 要货
SENTENCE_END = re.compile(r"(?<=[。！？!?])")


def summary_rule(llm: BaseLLM, count: int) -> str:
    """How long one write-up may run, given what the model can hand back in a single call."""
    low = int(getattr(llm.cfg, "summary_min", SUMMARY_CHARS[0]) or SUMMARY_CHARS[0])
    high = max(low, int(getattr(llm.cfg, "summary_max", SUMMARY_CHARS[1]) or SUMMARY_CHARS[1]))
    asked_low = max(100, int(low * OVERSHOOT))
    asked_high = max(asked_low + 20, int(high * OVERSHOOT))
    budget = int(getattr(llm.cfg, "max_output_tokens", 0) or 0)
    if budget > 0 and count > 0:
        room = int(budget * 1.4 / count) - 60  # 汉字约 1.4 字/token，再扣掉分数与关键词等字段
        if room < asked_high:               # only bite when the model genuinely cannot write that much
            asked_high = max(100, room)
            asked_low = min(asked_low, max(100, asked_high - 60))
    return (
        f"{asked_low}-{asked_high} 个汉字（超过 {high} 字的部分会被裁掉，别白费笔墨）。一段连贯中文："
        "先用一句话交代背景（这件事此前是什么状态），"
        "再说清今天到底发生了什么、主体是谁、关键数字参数与时间点，紧接着就给出一句影响或对读者的意义，"
        "剩下的篇幅再补充可对比的数据、官方说法与各方回应（越靠后越可以被舍弃）。"
        "不要复述标题、不要分点、不要堆形容词；"
        f"来源给的材料撑不到 {low} 字就据实写短，写到 150 字左右即可，"
        "严禁用「材料未提及」「需进一步核实」「应关注官方口径」这类话凑篇幅"
    )


def clamp_brief(text: str, low: int, high: int) -> str:
    """Keep the write-up inside the band the reader agreed on, cutting between sentences."""
    text = (text or "").strip()
    if len(text) <= high:
        return text
    kept = ""
    for sentence in [part for part in SENTENCE_END.split(text) if part.strip()]:
        if len(sentence) > high:
            break
        if kept and len(kept) + len(sentence) > high:
            break
        kept += sentence
    if len(kept) < max(80, low // 2):
        head = text[:high]
        edge = max(head.rfind(chr(12290)), head.rfind(chr(65307)))
        kept = head[: edge + 1] if edge > 60 else head
    return kept.strip()


def _batches(items: list[Article], size: int) -> list[list[Article]]:
    size = max(4, size)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _ask_model(llm: BaseLLM, section: Section, pairs: list[tuple[int, Article]]) -> dict[int, dict]:
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
                "ref": ref,
                "title": article.title,
                "summary": material(article),
                "source": article.source,
                "published": article.published,
            }
            for ref, article in pairs
        ],
        "rules": {
            "score_range": "0-1，表示值得推送给同事的程度",
            "drop": "与板块无关、纯营销、重复内容请给 0-0.2 的低分",
            "summary": summary_rule(llm, len(pairs)),
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


def _collect(llm: BaseLLM, section: Section, pairs: list[tuple[int, Article]], *, depth: int = 0) -> dict[int, dict]:
    """Ask about a batch, then chase the leftovers in smaller batches.

    A long write-up per item is exactly what makes a model run out of output room mid-JSON, so a
    thin answer is treated as "keep what arrived, re-ask the rest" instead of losing the batch.
    """
    failure: Exception | None = None
    try:
        got = _ask_model(llm, section, pairs)
    except Exception as exc:  # noqa: BLE001 - handled below, one bad batch must not kill the digest
        got, failure = {}, exc
    left = [pair for pair in pairs if pair[0] not in got]
    if not left or depth >= 1 or len(pairs) <= 1:
        if failure is not None:
            raise failure
        return got
    half = max(1, len(left) // 2)
    log.warning(
        "板块 %s：%d 条里模型只交回 %d 条%r，拆成每批 %d 条补写",
        section.id,
        len(pairs),
        len(pairs) - len(left),
        "" if failure is None else "（" + str(failure) + "）",
        half,
    )
    for chunk in (left[:half], left[half:]):
        if not chunk:
            continue
        try:
            got.update(_collect(llm, section, chunk, depth=depth + 1))
        except Exception as exc:  # noqa: BLE001
            log.warning("板块 %s 补写仍失败，这部分改用规则打分：%s", section.id, exc)
    return got



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

    if section.skip_today:
        # 早报在清晨发：当天日期的条目才挂几个小时，热度与影响都还没定型，留给明天那一期。
        today_iso = today.date().isoformat()
        before = len(candidates)
        candidates = [a for a in candidates if not (a.published and a.published >= today_iso)]
        if len(candidates) < before:
            log.info("板块 %s：早报模式，跳过 %d 条当天日期的条目", section.id, before - len(candidates))

    if section.max_age_days > 0:
        # 新鲜窗口：只保留 published >= 今天-N 的条目。没有日期的（不少 JSON 源不带日期）不冤枉，照放。
        cutoff = (today - timedelta(days=section.max_age_days)).date().isoformat()
        before = len(candidates)
        candidates = [a for a in candidates if not a.published or a.published >= cutoff]
        if len(candidates) < before:
            log.info("板块 %s：新鲜窗口 %d 天，淘汰 %d 条早于 %s 的旧条目", section.id, section.max_age_days, before - len(candidates), cutoff)

    kept: list[tuple[Article, float]] = []
    for article in candidates:
        if not is_relevant(article, collection):
            continue
        if state is not None and state.seen_before(article.fingerprint, not_before, run_date or ""):
            continue
        hits = article.keywords or section.keyword_hits(article.title, article.raw_summary)
        article.keywords = hits
        kept.append((article, rule_score(article, hits, run_date)))

    if section.freshness_first:
        # 新模型速览这类板块看的是「有没有更新的」：先按发布日期倒序，分数只用于同日之内分高下。
        kept.sort(key=lambda pair: (pair[0].published or "", pair[1]), reverse=True)
    else:
        kept.sort(key=lambda pair: pair[1], reverse=True)
    pool = kept[: max(section.max_items * 3, llm_cfg.batch_size)]

    if collection.fetch_content:
        # Only the shortlist pays for this, and only when the feed gave us a one-liner.
        # 补抓是加料不是命根子：短超时封顶，别让死页面把早报拖成中午报。
        enrich_articles(
            [article for article, _ in pool],
            timeout=min(collection.timeout, ENRICH_TIMEOUT),
            proxy=collection.proxy,
            headers=collection.headers,
        )

    decisions: dict[int, dict] = {}
    if llm_cfg.task_on("select"):
        batches = _batches([article for article, _ in pool], llm_cfg.batch_size)
        offset = 0
        for batch_index, batch in enumerate(batches):
            try:
                decisions.update(_collect(llm, section, list(enumerate(batch, start=offset))))
            except Exception as exc:  # noqa: BLE001 - a model hiccup must not kill the digest
                log.warning("板块 %s 第 %d 批模型筛选失败，该批改用规则打分：%s", section.id, batch_index + 1, exc)
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
            article.summary = clamp_brief(str(decision["summary"]).strip(), llm_cfg.summary_min, llm_cfg.summary_max)
        else:
            article.summary = plain_summary(article)
        article.why = str(decision.get("why") or "").strip() or (
            ("命中关键词：" + "、".join(article.keywords[:3])) if article.keywords else "板块相关"
        )
        article.keywords = [str(k) for k in decision.get("keywords") or article.keywords][:6]
        article.score = round(final_score, 3)
        curated.append(article)

    if section.freshness_first:
        curated.sort(key=lambda a: (a.published or "", a.score), reverse=True)
    else:
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
