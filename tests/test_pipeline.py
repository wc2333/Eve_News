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
    assert rerun.items < report.items  # already published stories are skipped


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
