from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from evenews.curator import curate_section, dedupe_across_sections, similar
from evenews.feeds import harvest
from evenews.llm import MockLLM
from evenews.mailer import build_message
from evenews.models import Article
from evenews.pipeline import run_once
from evenews.state import StateStore

NOW = datetime(2026, 9, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_fixtures_parse_into_candidates(config, fixtures_dir):
    collected = harvest(config.sections, config.collection, now=NOW, fixtures_dir=fixtures_dir)
    assert collected.fetched >= 8
    assert collected.by_section["models"] and collected.by_section["wearables"]
    assert all(item.published for item in collected.by_section["models"])


def test_mock_model_writes_summaries_and_ranks(config, fixtures_dir):
    section = config.sections[0]
    collected = harvest([section], config.collection, now=NOW, fixtures_dir=fixtures_dir)
    digest = curate_section(
        section,
        collected.by_section[section.id],
        llm=MockLLM(config.llm),
        collection=config.collection,
        llm_cfg=config.llm,
        run_date="2026-09-25",
    )
    assert 0 < len(digest.items) <= section.max_items
    assert all(item.summary and item.why for item in digest.items)
    assert [item.score for item in digest.items] == sorted([item.score for item in digest.items], reverse=True)


def test_exclude_keywords_and_history_are_dropped(config):
    section = config.sections[0]
    articles = [
        Article(title="某公司大模型岗位招聘", url="https://a/1", source="demo", raw_summary="大模型 招聘 工程师"),
        Article(title="开源大模型发布新权重", url="https://a/2", source="demo", raw_summary="大模型 开源 权重"),
    ]
    state = StateStore(config.state_root / "state.json")
    state.mark_seen([articles[1].fingerprint], "2026-09-20")
    digest = curate_section(
        section,
        articles,
        llm=MockLLM(config.llm),
        collection=config.collection,
        llm_cfg=config.llm,
        state=state,
        run_date="2026-09-25",
    )
    assert digest.items == []


def test_similar_detects_reposts_only():
    assert similar("高通峰会公布骁龙 8 Gen6：端侧跑 7B 模型", "高通峰会公布骁龙8 Gen6——端侧跑7B模型")
    assert not similar("国产 GPU 集群调度平台上线", "AI 眼镜新品重量做到 38g")


def test_one_story_lands_in_one_section(config):
    from evenews.models import SectionDigest

    first = SectionDigest(section=deepcopy(config.sections[0]), items=[Article(title="同一篇新闻", url="https://a/9", source="demo", score=0.4)])
    second = SectionDigest(section=deepcopy(config.sections[1]), items=[Article(title="同一篇新闻", url="https://a/9", source="demo", score=0.8)])
    assert dedupe_across_sections([first, second]) == 1
    assert first.items == [] and [item.score for item in second.items] == [0.8]


def test_offline_run_writes_all_artifacts(config, fixtures_dir):
    report = run_once(config, when="2026-09-25", offline=True, fixtures=fixtures_dir, send=False)
    assert report.items > 0 and report.sent is False
    payload = json.loads(report.files["json"].read_text(encoding="utf-8"))
    assert payload["run_date"] == "2026-09-25" and payload["lead"]
    html = report.files["html"].read_text(encoding="utf-8")
    assert "DAILY AI BRIEFING" in html and "本次引用来源" in html
    assert report.files["markdown"].is_file() and report.files["text"].is_file()


def test_offline_run_can_target_one_section(config, fixtures_dir):
    report = run_once(config, when="2026-09-25", only=["wearables"], offline=True, fixtures=fixtures_dir, send=False)
    assert report.sections == ["wearables"]


def test_real_run_records_history_without_sending(config, fixtures_dir):
    report = run_once(config, when="2026-09-25", offline=False, fixtures=fixtures_dir, send=False)
    state_file = config.state_root / "state.json"
    assert state_file.is_file()
    history = json.loads(state_file.read_text(encoding="utf-8"))
    assert history["runs"][0]["run_date"] == "2026-09-25"
    rerun = run_once(config, when="2026-09-25", offline=False, fixtures=fixtures_dir, send=False)
    assert rerun.items == report.items  # a same-day rerun is not starved by dedupe
    next_day = run_once(config, when="2026-09-26", offline=False, fixtures=fixtures_dir, send=False)
    assert next_day.items < report.items  # yesterday's stories are skipped


def test_email_message_is_multipart(config):
    message = build_message(config.email, subject="s", html="<p>hi</p>", text="hi")
    assert message.get_content_type() == "multipart/alternative"
    assert "team@test" in message["To"]

def test_offline_run_is_clearly_marked_as_demo(config, fixtures_dir, tmp_path):
    report = run_once(config, when="2026-09-25", offline=True, fixtures=fixtures_dir, send=False, out_root=tmp_path / "out")
    assert report.demo is True and report.subject.startswith("[演示]")
    assert "演示数据" in report.summary()
    html = report.files["html"].read_text(encoding="utf-8")
    assert "不是真实新闻" in html
    assert "离线演示" in report.files["text"].read_text(encoding="utf-8")

from evenews import pipeline as pipeline_module
from evenews.config import Brand, Config
from evenews.curator import plain_summary
from evenews.models import Digest, Section, SectionDigest
from evenews.render import render_html, render_markdown, render_text

BRAND = Brand(company="测试公司", title="AI 每日资讯")


def _section(index: int, title: str) -> Section:
    return Section(id=f"s{index}", title=title, sources=[], max_items=3)


def _article(title: str, url: str) -> Article:
    return Article(
        title=title,
        url=url,
        source="qbitai",
        published="2026-09-25",
        raw_summary="量子位报道了这次发布的内容，包含参数与时间点。",
        summary="模型开放了权重，配套评测与部署文档一并放出。",
    )


def _digest(sections: list[SectionDigest]) -> Digest:
    return Digest(
        run_date="2026-09-25",
        generated_at="2026-09-25T09:00:00+08:00",
        timezone="Asia/Shanghai",
        lead="今日头条。",
        sections=sections,
    )


def test_a_section_with_no_items_is_not_printed():
    digest = _digest(
        [
            SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")]),
            SectionDigest(_section(2, "空掉的板块"), []),
            SectionDigest(_section(3, "算力与芯片"), [_article("芯片流片", "https://c/3")]),
        ]
    )
    for render in (render_html, render_markdown, render_text):
        page = render(digest, BRAND)
        assert "空掉的板块" not in page
        assert "没有筛选出符合条件" not in page
        assert "第 2 版 算力与芯片" in page or "算力与芯片（第 2 版）" in page or "第 2 版" in page


def test_an_issue_without_items_is_never_mailed(raw_config: dict, tmp_path, fixtures_dir, monkeypatch):
    raw = deepcopy(raw_config)
    raw["email"]["enabled"] = True
    raw["collection"]["require_keywords"] = ["绝不可能出现在样例里的词"]
    cfg = Config.from_dict(raw, tmp_path / "empty.yaml")
    calls: list = []
    monkeypatch.setattr(pipeline_module, "send_digest", lambda *args, **kwargs: calls.append(1) or ["team@test"])

    report = pipeline_module.run_once(cfg, when="2026-09-25", offline=False, fixtures=fixtures_dir, send=True)
    assert report.items == 0
    assert report.sent is False and not calls, "nothing to read, nothing to mail"
    assert any("入选条目" in error for error in report.errors)


def test_a_normal_issue_is_mailed(raw_config: dict, tmp_path, fixtures_dir, monkeypatch):
    raw = deepcopy(raw_config)
    raw["email"]["enabled"] = True
    cfg = Config.from_dict(raw, tmp_path / "ok.yaml")
    calls: list = []
    monkeypatch.setattr(pipeline_module, "send_digest", lambda *args, **kwargs: calls.append(1) or ["team@test"])

    report = pipeline_module.run_once(cfg, when="2026-09-25", offline=False, fixtures=fixtures_dir, send=True)
    assert report.items > 0 and report.sent and len(calls) == 1


def test_fallback_blurb_reads_as_a_whole_paragraph():
    article = Article(
        title="某模型发布",
        url="https://a/1",
        source="qbitai",
        raw_summary=(
            "公司在今日的技术发布会上正式公开了新一代开源模型，模型参数规模为 2350 亿，激活参数 210 亿。"
            "上下文窗口长度由原先的 32K 扩展到 128K，长文档检索的召回率提升约 18 个百分点。"
            "官方同时放出了基础权重、指令微调权重和一套量化版本，全部采用 Apache 2.0 许可。"
            "配套技术报告披露了训练数据配比与对齐流程，评测集覆盖数学、代码与多语言三大类共 42 个子任务。"
            "开发者在消费级显卡上即可完成 32K 上下文的本地部署，推理成本较上一代下降约三分之一。"
            "该模型已同步进入官方托管的推理服务，企业可以按 token 计费直接调用。"
        ),
    )
    blurb = plain_summary(article)
    assert len(blurb) > 130, "the offline fallback must not be a one-liner anymore"


def test_the_model_is_asked_for_a_longer_analysis(config, fixtures_dir):
    from evenews.config import Config

    recorded: list = []

    class Recorder(MockLLM):
        def json_task(self, task, payload):
            recorded.append(json.dumps({"task": task, **payload}, ensure_ascii=False))
            return super().json_task(task, payload)

    section = config.sections[0]
    collected = harvest([section], config.collection, now=NOW, fixtures_dir=fixtures_dir)
    curate_section(
        section,
        collected.by_section[section.id],
        llm=Recorder(config.llm),
        collection=config.collection,
        llm_cfg=config.llm,
        run_date="2026-09-25",
    )
    assert recorded, "the curator must actually consult the model"
    assert any("240-320 个汉字" in call for call in recorded), "the brief asks for a write-up that lands inside 300-400 字"
    assert any("超过 400 字" in call for call in recorded), "the ceiling is stated so the model stops writing"
    assert any("背景" in call for call in recorded), "the brief asks for context, not a rephrased headline"


def test_the_write_up_budget_follows_the_token_cap():
    from evenews.config import LLMConfig
    from evenews.curator import summary_rule

    roomy = summary_rule(MockLLM(LLMConfig(max_output_tokens=8000, batch_size=8)), 8)
    assert roomy.startswith("240-320 个汉字"), "the default asks for the 0.8 band"

    tuned = summary_rule(MockLLM(LLMConfig(summary_min=200, summary_max=260, max_output_tokens=32000)), 4)
    assert tuned.startswith("160-208 个汉字"), "the length dial is honoured"

    shrunk = summary_rule(MockLLM(LLMConfig(max_output_tokens=1500, batch_size=8)), 8)
    low, high = [int(part) for part in shrunk.split("个汉字")[0].split("-")]
    assert 120 <= low < high < 300, shrunk
    assert summary_rule(MockLLM(LLMConfig(max_output_tokens=0)), 0).startswith("240-320 个汉字")


def test_a_write_up_that_ran_long_is_trimmed_between_sentences():
    from evenews.curator import clamp_brief

    sentence = "这是一句足够长的介绍内容，用来模拟模型拿到材料之后一路写下去的句子。"
    long_brief = sentence * 10
    trimmed = clamp_brief(long_brief, 100, 200)
    assert len(trimmed) <= 200 and len(trimmed) >= 170, "keep whole sentences, drop the tail"
    assert trimmed.endswith("。"), "never cut in the middle of a sentence"
    assert clamp_brief("只有一句。", 300, 400) == "只有一句。", "short material stays short"
    runaway = ("没有句号的长串" * 40)[:250] + "。尾巴"
    assert len(clamp_brief(runaway, 100, 100)) <= 100, "a single monster sentence still gets capped"


def test_the_mark_follows_the_theme():
    from evenews.config import Brand
    from evenews.render import resolve_logo

    png = bytes([0x89, 0x50, 0x4E, 0x47])
    light, mime = resolve_logo(Brand(logo_file="brand-logo-kzhy.png"), "light")
    dark, dark_mime = resolve_logo(Brand(logo_file="brand-logo-kzhy.png"), "dark")
    assert light[:4] == png == dark[:4] and mime == dark_mime == "image/png"
    assert light != dark, "the dark brief gets the light-tinted twin, not a white square"
    assert len(dark) < len(light), "the flat tinted twin is the smaller file"

    fallback, _ = resolve_logo(Brand(logo_file="brand-logo-ctone.png"), "dark")
    assert fallback, "a mark without a dark twin still shows up"


def test_the_group_leads_the_company_in_the_header():
    from evenews.config import Brand

    brand = Brand(
        group="创通 CTONE",
        company="凯铮寰宇",
        kicker="算力驱动未来",
        footer_note="自动生成 · 仅供内部参考，转载请注明出处",
        site="https://www.kzhytech.com",
    )
    digest = Digest(run_date="2026-09-25", generated_at="2026-09-25T08:00:00", timezone="Asia/Shanghai")
    html = render_html(digest, brand)
    assert "创通 CTONE · 凯铮寰宇 · 算力驱动未来" in html
    assert "创通 CTONE · 凯铮寰宇" in html.split("转载请注明出处")[-1], "the footer signs group then company"


def test_a_cut_off_answer_keeps_the_items_that_did_arrive():
    from evenews.llm import extract_json

    half = '{"items": [{"ref": 0, "score": 0.8, "summary": "第一条的长介绍"}, {"ref": 1, "score": 0.7, "summ'
    data = extract_json(half)
    assert [item["ref"] for item in data.get("items") or []] == [0]
    assert data.get("truncated") is True
    assert extract_json('{"lead": "写到一半就断了') == {}


def test_a_thin_answer_is_asked_again_for_the_leftovers(config):
    asked: list = []

    class CuttingLLM(MockLLM):
        """Answers two candidates per call, as if the output budget ran out after each pair."""

        def json_task(self, task, payload):
            if task != "curate":
                return super().json_task(task, payload)
            refs = [candidate["ref"] for candidate in payload["candidates"]]
            asked.append(refs)
            keep = refs[:2]
            return {"items": [{"ref": ref, "score": 0.7, "summary": "综合介绍" + str(ref), "why": "值得看"} for ref in keep]}

    config.llm.batch_size = 4
    titles = [
        "国产大模型放出 32B 权重",
        "英伟达推理卡把大模型推理成本砍半",
        "欧盟人工智能法案细则落地，模型厂商需报备",
        "OpenAI 公布长上下文评测方法",
        "智谱开源多模态智能体模型",
        "阿里通义旗舰模型降价一半",
    ]
    articles = [
        Article(
            title=title,
            url=f"https://a/{index}",
            source="qbitai",
            published="2026-09-25",
            raw_summary="官方放出模型权重、评测集与技术报告，开发者可以直接本地部署该模型。",
        )
        for index, title in enumerate(titles)
    ]
    section = config.sections[0]
    digest = curate_section(
        section,
        articles,
        llm=CuttingLLM(config.llm),
        collection=config.collection,
        llm_cfg=config.llm,
        run_date="2026-09-25",
    )
    assert asked[0] == [0, 1, 2, 3], "one batch per call"
    assert asked[-1] == [4, 5], "the next batch is asked about as usual"
    assert [2] in asked and [3] in asked, "the two that came back missing are chased one by one"
    assert digest.items
    assert all(item.summary.startswith("综合介绍") for item in digest.items), "every item ends up with the model write-up"


def test_history_dedupe_only_clears_older_days(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.mark_seen(["abc123"], "2026-09-25")
    assert store.seen_before("abc123", "2026-09-15", "2026-09-25") is False, "a rerun today must still see it"
    assert store.seen_before("abc123", "2026-09-15", "2026-09-26") is True, "yesterdays brief must not repeat it"
    assert store.seen_before("abc123", "2026-09-26") is False, "outside the dedupe window"
    assert store.seen_before("unknown", "2026-09-15", "2026-09-26") is False


def test_the_footer_names_the_reason_a_source_failed():
    digest = _digest([SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")])])
    digest.stats = {"sources": 15, "failed_sources": ["modelscope"], "fetch_errors": ["modelscope: GET https://modelscope.cn/api failed: 403 Forbidden"]}
    page = render_html(digest, BRAND)
    assert "403 Forbidden" in page, "an operator must see why a source went missing"


def test_the_company_mark_is_embedded_in_the_brief():
    with_logo = Brand(company="凯铮寰宇", logo_text="CTONE", logo_file="brand-logo-ctone.png", site="https://www.kzhytech.com")
    page = render_html(_digest([SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")])]), with_logo)
    assert "data:image/png;base64," in page, "an email must not depend on external image hosts"
    assert "kzhytech.com" in page and "凯铮寰宇" in page
    assert "CTONE" not in page, "the mark carries the group name already - a text copy doubles up"


def test_a_missing_logo_file_degrades_to_text():
    broken = Brand(company="凯铮寰宇", logo_text="CTONE", logo_file="does-not-exist.png")
    page = render_html(_digest([SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")])]), broken)
    assert "data:image" not in page
    assert "CTONE" in page and "凯铮寰宇" in page


def test_the_dark_theme_uses_the_site_palette():
    page = render_html(_digest([SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")])]), Brand(theme="dark"))
    assert "#060b14" in page and "#f4f8fd" in page, "navy ground, near-white ink"
    light = render_html(_digest([SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")])]), Brand(theme="light"))
    assert "#f5f3ee" in light


def test_a_body_colour_override_reaches_the_summary():
    loud = Brand(theme="dark", body="#ffffff")
    page = render_html(_digest([SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")])]), loud)
    assert "color:#ffffff" in page


def test_the_sent_copy_uses_the_inline_logo_part():
    config = Config.from_dict({}, __import__("pathlib").Path("unused.yaml"))
    message = build_message(
        config.email,
        subject="s",
        html='<p><img src="data:image/jpeg;base64,QUJD"></p>',
        text="t",
        logo=(b"jpeg-bytes", "image/jpeg"),
    )
    html_part = [part.get_content() for part in message.walk() if part.get_content_type() == "text/html"][0]
    assert "cid:evenews-logo" in html_part and "data:image" not in html_part
    images = [part for part in message.walk() if part.get_content_maintype() == "image"]
    assert len(images) == 1 and images[0]["Content-ID"] == "<evenews-logo>"


def test_the_date_outsizes_the_fine_print_it_shares_a_strip_with():
    import re

    page = render_html(_digest([SectionDigest(_section(1, "大模型与开源生态"), [_article("模型发布", "https://a/1")])]), BRAND)
    date_cell = re.search(r"<td[^>]*>2026-09-25</td>", page).group(0)
    assert "font-size:19px" in date_cell, "the date is what people read first on the strip"
    assert "font-size:19px" not in page[page.index(date_cell) + len(date_cell):page.index("</tr>", page.index(date_cell))], "classification and timestamp stay small"
