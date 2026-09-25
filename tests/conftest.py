from __future__ import annotations

import pytest
import yaml

from evenews.config import Config
from evenews.pipeline import SAMPLE_FEEDS


@pytest.fixture()
def raw_config() -> dict:
    """A two-section config whose sources are backed by the bundled sample feeds."""
    return yaml.safe_load(
        """
        log_level: WARNING
        brand:
          company: 测试公司
          title: AI 每日资讯
        schedule:
          time: "07:30"
          timezone: Asia/Shanghai
        email:
          enabled: false
          smtp_host: smtp.test
          from: "bot <bot@test>"
          to: [team@test]
        llm:
          provider: mock
          tasks: {select: true, classify: true, summarize: true, lead: true}
        collection:
          mode: feeds
          lookback_hours: 0
          dedupe_days: 7
          require_keywords: [AI, 大模型, 算力, 模型, 机器人]
          exclude_keywords: [招聘]
        sources:
          qbitai: {url: "https://www.qbitai.com/feed"}
          ithome: {url: "https://www.ithome.com/rss/"}
          ifanr: {url: "https://www.ifanr.com/feed"}
          huxiu: {url: "https://www.huxiu.com/rss/0.xml"}
        sections:
          - id: models
            title: 大模型与开源生态
            enabled: true
            max_items: 3
            sources: [qbitai, huxiu]
            keywords: [大模型, 开源, 权重, 模型]
          - id: wearables
            title: 智能眼镜与可穿戴
            enabled: false
            max_items: 3
            sources: [ifanr, ithome]
            keywords: [眼镜, 手表, 可穿戴]
        """
    )


@pytest.fixture()
def config(raw_config: dict, tmp_path) -> Config:
    return Config.from_dict(raw_config, tmp_path / "config.yaml")


@pytest.fixture()
def fixtures_dir():
    return SAMPLE_FEEDS
