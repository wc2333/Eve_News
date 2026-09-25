"""Source handling: one dead feed must not sink the brief, and dead knobs must be honoured."""

from __future__ import annotations

import json
import io
import urllib.error
import urllib.request
from email.message import Message
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from evenews.config import Config
from evenews.curator import rule_score
from evenews import feeds
from evenews.models import Article
from evenews.net import HttpError, opener_for

NOW = datetime(2026, 9, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def proxies_of(opener) -> dict | None:
    for handler in opener.handlers:
        if type(handler).__name__ == "ProxyHandler":
            return handler.proxies
    return None


def test_dead_source_is_isolated(raw_config: dict, tmp_path, fixtures_dir, monkeypatch):
    raw = deepcopy(raw_config)
    raw["sources"]["dead"] = {"url": "https://dead.example/feed"}
    raw["sections"][0]["sources"].append("dead")
    cfg = Config.from_dict(raw, tmp_path / "config.yaml")

    real_fetch = feeds.fetch_bytes

    def flaky(url, **kwargs):
        if "dead.example" in str(url):
            raise HttpError("simulated outage")
        return real_fetch(url, **kwargs)

    monkeypatch.setattr(feeds, "fetch_bytes", flaky)
    result = feeds.harvest(cfg.sections, cfg.collection, now=NOW, fixtures_dir=fixtures_dir)

    assert result.failed == ["dead"]
    assert any("simulated outage" in error for error in result.errors)
    assert result.by_section["models"], "healthy sources still fill the section"


def test_html_answer_is_reported_as_broken_feed():
    with pytest.raises(HttpError):
        feeds.parse_feed(b"<html><body>moved</body></html>", source_name="x", limit=10)


def test_disabled_source_is_skipped(raw_config: dict, tmp_path):
    raw = deepcopy(raw_config)
    raw["sources"]["huxiu"]["enabled"] = False
    cfg = Config.from_dict(raw, tmp_path / "config.yaml")
    assert [source.name for source in cfg.sections[0].sources] == ["qbitai"]


def test_rule_score_lifts_todays_story_above_yesterdays():
    hits = ["大模型"]
    today = Article(title="某模型发布", url="https://a/1", source="s", published="2026-09-25", raw_summary="大模型发布")
    yesterday = Article(title="某模型发布", url="https://a/2", source="s", published="2026-09-24", raw_summary="大模型发布")
    assert rule_score(today, hits, "2026-09-25") > rule_score(yesterday, hits, "2026-09-25")
    assert rule_score(today, hits) == rule_score(yesterday, hits)


def test_proxy_knob_selects_the_right_opener():
    assert proxies_of(opener_for("none")) is None, "none must not route through a proxy"
    assert proxies_of(opener_for("direct")) is None
    assert proxies_of(opener_for("http://127.0.0.1:7890")) == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    assert proxies_of(opener_for("")) == proxies_of(urllib.request.build_opener()), "empty keeps urllib defaults"


class _StubResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _StubOpener:
    def __init__(self, broken: bool) -> None:
        self.broken = broken

    def open(self, request, timeout=None):
        if self.broken:
            raise OSError("[WinError 10061] connection refused")
        return _StubResponse(b"<rss><channel></channel></rss>")


def test_auto_mode_falls_back_to_a_direct_connection(monkeypatch):
    from evenews import net

    seen: list = []

    def fake_opener_for(mode):
        seen.append(mode)
        return _StubOpener(broken=mode is None)

    monkeypatch.setattr(net, "opener_for", fake_opener_for)
    assert net.fetch_bytes("https://example.com/feed", retries=0)
    assert seen == [None, "none"], "system proxy first, then a direct retry"


def test_pinned_proxy_does_not_silently_go_direct(monkeypatch):
    from evenews import net

    seen: list = []

    def fake_opener_for(mode):
        seen.append(mode)
        return _StubOpener(broken=True)

    monkeypatch.setattr(net, "opener_for", fake_opener_for)
    with pytest.raises(HttpError):
        net.fetch_bytes("https://example.com/feed", retries=0, proxy="http://127.0.0.1:7890")
    assert seen == ["http://127.0.0.1:7890"]


def test_a_declared_source_overrides_the_disabled_default(raw_config: dict, tmp_path):
    """The shipped template ships a few dead feeds as enabled:false; a file that names one is in charge of it."""
    default_names = [source.name for source in Config.from_dict(raw_config, tmp_path / "a.yaml").sections[0].sources]
    assert "huxiu" in default_names, "the test file declares huxiu itself"

    raw = deepcopy(raw_config)
    raw["sources"]["huxiu"]["enabled"] = False
    opted_out = [source.name for source in Config.from_dict(raw, tmp_path / "b.yaml").sections[0].sources]
    assert "huxiu" not in opted_out


MODELSCOPE_FIXTURE = (
    '{\n'
    '  "Data": {\n'
    '    "Articles": [\n'
    '      {"Title": "Qwen3.5 开源 27B 权重", "Desc": "同步放出推理与量化版本", "GmtPublished": 1758729600,'
    ' "IsPGC": true, "ContentUrl": "/collections/qwen35"},\n'
    '      {"Title": "我的个人随笔", "Desc": "日常记录", "GmtPublished": 1758729600,'
    ' "IsPGC": false, "ContentUrl": "/posts/private"}\n'
    '    ]\n'
    '  }\n'
    '}'.encode("utf-8")
)

MODELSCOPE_SPEC = {
    "items": "Data.Articles",
    "title": "Title",
    "summary": ["Desc"],
    "url": ["ContentUrl", "Url"],
    "date": "GmtPublished",
    "base_url": "https://modelscope.cn",
    "require": ["IsPGC"],
}


def test_json_source_maps_the_api_and_drops_personal_posts():
    items = feeds.parse_json_items(MODELSCOPE_FIXTURE, source_name="modelscope", limit=10, spec=MODELSCOPE_SPEC)
    assert [article.title for article in items] == ["Qwen3.5 开源 27B 权重"]
    assert items[0].url == "https://modelscope.cn/collections/qwen35"
    assert items[0].published == datetime.fromtimestamp(1758729600).strftime("%Y-%m-%d")


def test_json_source_without_an_array_is_a_failure_not_an_empty_pass():
    with pytest.raises(HttpError):
        feeds.parse_json_items(b'{"Data": {}}', source_name="modelscope", limit=5, spec=MODELSCOPE_SPEC)


def test_json_block_reaches_the_fetcher_with_its_spec(raw_config: dict, tmp_path, monkeypatch):
    raw = deepcopy(raw_config)
    raw["sources"]["modelscope"] = {
        "url": "https://modelscope.cn/api/v1/articles?PageSize=30",
        "type": "json",
        "json": MODELSCOPE_SPEC,
    }
    raw["sections"][0]["sources"].append("modelscope")
    cfg = Config.from_dict(raw, tmp_path / "c.yaml")
    source = next(s for s in cfg.sections[0].sources if s.name == "modelscope")
    assert source.type == "json" and source.spec["require"] == ["IsPGC"]

    monkeypatch.setattr(feeds, "fetch_bytes", lambda origin, **kwargs: MODELSCOPE_FIXTURE)
    articles = feeds.fetch_source(source, cfg.collection)
    assert len(articles) == 1 and articles[0].source == "modelscope"


def test_shipped_template_swapped_huggingface_for_modelscope():
    import yaml

    from evenews.config import default_config_text

    template = yaml.safe_load(default_config_text())
    assert "modelscope" in template["sources"]
    assert template["sources"]["modelscope"]["type"] == "json"
    assert template["sources"]["huggingface"]["enabled"] is False, "blocked on the mainland network"
    for name in ("sspai", "juejin"):
        assert template["sources"][name]["enabled"] is False, "personal write-ups stay out of a company brief"
    for section in template["sections"]:
        assert "huggingface" not in section.get("sources", [])


def test_the_offline_demo_reads_the_json_sample(raw_config: dict, tmp_path, fixtures_dir):
    raw = deepcopy(raw_config)
    raw["sources"]["modelscope"] = {
        "url": "https://modelscope.cn/api/v1/articles?PageSize=30",
        "type": "json",
        "json": MODELSCOPE_SPEC,
    }
    raw["sections"][0]["sources"].append("modelscope")
    cfg = Config.from_dict(raw, tmp_path / "d.yaml")
    collected = feeds.harvest(cfg.sections, cfg.collection, now=NOW, fixtures_dir=fixtures_dir, fixtures_only=True)

    picked = [article for article in collected.by_section["models"] if article.source == "modelscope"]
    assert len(picked) == 2, "the personal post is filtered out by require"
    assert picked[0].url.startswith("https://modelscope.cn/"), "relative links get the base back"
    assert not collected.failed, "a JSON sample must not be parsed as a feed"


def test_require_rules_accept_thresholds_and_lists():
    payload = (
        "{"
        '"models":['
        '{"modelId":"big-org/RealModel","tags":["llama.cpp","gguf","quantized"],"likes":2194,"downloads":37618,"trendingScore":2049},'
        '{"modelId":"someone/weekend-test","tags":["pytorch"],"likes":0,"downloads":2,"trendingScore":0}'
        "]}"
    ).encode("utf-8")
    spec = {
        "items": "models",
        "title": "modelId",
        "url": ["modelId"],
        "base_url": "https://hf-mirror.com",
        "date": "createdAt",
        "summary": ["tags"],
        "facts": ["likes", "downloads", "trendingScore"],
        "require": ["likes>=100", "trendingScore>=1"],
    }
    items = feeds.parse_json_items(payload, source_name="hf_trending", limit=10, spec=spec)
    assert [article.title for article in items] == ["big-org/RealModel"], "hobby uploads get filtered out"
    assert items[0].url == "https://hf-mirror.com/big-org/RealModel", "a bare id becomes a real link"
    assert "llama.cpp, gguf, quantized" in items[0].raw_summary, "tag lists become model material"
    assert "likes=2194" in items[0].raw_summary and "downloads=37618" in items[0].raw_summary


def test_a_broken_threshold_is_a_failed_rule_not_a_crash():
    payload = b'{"rows":[{"title":"x","url":"https://a/1","stars":"n/a"}]}'
    spec = {"items": "rows", "require": ["stars>=10"]}
    assert feeds.parse_json_items(payload, source_name="x", limit=5, spec=spec) == []


def test_a_source_can_widen_the_freshness_window(raw_config: dict, tmp_path, monkeypatch):
    raw = deepcopy(raw_config)
    raw["collection"]["lookback_hours"] = 24
    payload = json.dumps(
        {"rows": [{"t": "上周开源的推理模型", "u": "https://api.example/m1", "d": "2026-09-10"}]},
        ensure_ascii=False,
    ).encode("utf-8")
    raw["sources"]["old_wide"] = {
        "url": "https://api.example/models?wide",
        "type": "json",
        "lookback_hours": 720,
        "json": {"items": "rows", "title": "t", "url": "u", "date": "d"},
    }
    raw["sources"]["old_strict"] = {
        "url": "https://api.example/models?strict",
        "type": "json",
        "json": {"items": "rows", "title": "t", "url": "u", "date": "d"},
    }
    raw["sections"][0]["sources"] = ["old_wide", "old_strict"]
    cfg = Config.from_dict(raw, tmp_path / "window.yaml")

    real_fetch = feeds.fetch_bytes

    def fake_fetch(url, **kwargs):
        if "api.example" in str(url):
            return payload
        return real_fetch(url, **kwargs)

    monkeypatch.setattr(feeds, "fetch_bytes", fake_fetch)
    collected = feeds.harvest(cfg.sections, cfg.collection, now=NOW)

    picked = [article for article in collected.by_section["models"]]
    assert [article.source for article in picked] == ["old_wide"], "only the widened source keeps a 15-day-old item"


class _StatusOpener:
    def __init__(self, code) -> None:
        self.code = code

    def open(self, request, timeout=None):
        if self.code:
            raise urllib.error.HTTPError(request.full_url, self.code, "blocked", Message(), io.BytesIO(b""))
        return _StubResponse(b'<rss><channel></channel></rss>')


def test_a_proxy_that_answers_5xx_is_escalated_to_a_direct_try(monkeypatch):
    from evenews import net

    seen: list = []

    def fake_opener_for(mode):
        seen.append(mode)
        return _StatusOpener(503 if mode is None else None)

    monkeypatch.setattr(net, "opener_for", fake_opener_for)
    assert net.fetch_bytes("https://modelscope.cn/api/v1/articles", retries=0)
    assert seen == [None, "none"], "a blocked proxy exit must not be the end of the story"


def test_a_pinned_proxy_still_reports_the_status(monkeypatch):
    from evenews import net

    monkeypatch.setattr(net, "opener_for", lambda mode: _StatusOpener(403))
    with pytest.raises(HttpError):
        net.fetch_bytes("https://example.com/feed", retries=0, proxy="http://127.0.0.1:7890")


def test_a_source_can_pin_its_own_proxy(raw_config: dict, tmp_path, monkeypatch):
    raw = deepcopy(raw_config)
    raw["collection"]["proxy"] = "http://127.0.0.1:7890"
    raw["sources"]["domestic"] = {
        "url": "https://modelscope.cn/api/v1/articles?PageSize=30",
        "type": "json",
        "proxy": "none",
        "json": {"items": "rows", "title": "t", "url": "u"},
    }
    raw["sources"]["abroad"] = {"url": "https://example.com/api", "type": "json", "json": {"items": "rows", "title": "t", "url": "u"}}
    raw["sections"][0]["sources"] = ["domestic", "abroad"]
    cfg = Config.from_dict(raw, tmp_path / "proxy.yaml")

    used: list = []

    def fake_fetch(url, **kwargs):
        used.append(kwargs.get("proxy"))
        return b'{"rows":[]}'

    monkeypatch.setattr(feeds, "fetch_bytes", fake_fetch)
    for source in cfg.sections[0].sources:
        feeds.fetch_source(source, cfg.collection)

    assert used == ["none", "http://127.0.0.1:7890"], "the source wins over the collection default"
