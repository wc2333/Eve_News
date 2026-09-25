"""Source handling: one dead feed must not sink the brief, and dead knobs must be honoured."""

from __future__ import annotations

import urllib.request
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
