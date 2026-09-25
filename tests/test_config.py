from __future__ import annotations

import pytest

from evenews.config import Config, ConfigError, default_config_text


def test_example_config_is_loadable(tmp_path):
    config = Config.from_dict({}, tmp_path / "config.yaml")
    assert [section.id for section in config.sections] == [
        "llm_oss",
        "model_releases",
        "edge_ai",
        "domestic_compute",
        "devices_robotics",
        "wearables",
        "industry_capital",
    ]
    assert all(section.sources for section in config.sections)


def test_missing_source_reference_raises(tmp_path, raw_config):
    raw_config["sections"][0]["sources"] = ["nope"]
    with pytest.raises(ConfigError):
        Config.from_dict(raw_config, tmp_path / "config.yaml")


def test_toggle_sections_round_trip(tmp_path, config):
    config.set_section_enabled("wearables", True)
    saved = config.save()
    assert "wearables" in saved.read_text(encoding="utf-8")
    reloaded = Config.load(saved)
    assert [s.id for s in reloaded.enabled_sections()] == ["models", "wearables"]
    reloaded.set_section_enabled("wearables", False)
    assert [s.id for s in reloaded.enabled_sections()] == ["models"]


def test_env_secret_and_problems(tmp_path, config, monkeypatch):
    monkeypatch.setenv("EVE_NEWS_SMTP_PASSWORD", "s3cret")
    config.email.password = ""
    from evenews.config import EmailConfig

    with_env = EmailConfig.from_dict({"smtp_host": "h", "from": "a@b", "to": ["c@d"], "password_env": "EVE_NEWS_SMTP_PASSWORD"})
    assert with_env.password == "s3cret"
    assert with_env.problems() == []
    assert config.email.problems() == []  # disabled email never blocks a run


def test_unknown_section_id(config):
    with pytest.raises(ConfigError):
        config.enabled_sections(["does_not_exist"])


def test_default_template_mentions_every_knob():
    text = default_config_text()
    for needle in ("schedule:", "email:", "llm:", "collection:", "sections:", "sources:"):
        assert needle in text


def test_shipped_defaults_carry_the_company_identity(tmp_path):
    config = Config.from_dict({}, tmp_path / "config.yaml")
    assert config.brand.company == "凯铮寰宇"
    assert config.brand.logo_file == "brand-logo-kzhy.jpg"
    assert "kzhytech.com" in config.brand.site
    assert config.brand.theme == "dark"
    assert not config.brand.background, "colours come from the theme palette unless overridden"
