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
    assert config.brand.group == "创通 CTONE", "the group leads the subsidiary"
    assert config.brand.company == "凯铮寰宇"
    assert config.brand.kicker == "算力驱动未来"
    assert config.brand.logo_file == "brand-logo-kzhy.png", "a transparent mark, not a white square"
    assert "kzhytech.com" in config.brand.site
    assert config.brand.theme == "light"
    assert not config.brand.background, "colours come from the theme palette unless overridden"


def test_section_flags_default_and_parse(tmp_path, raw_config):
    config = Config.from_dict({}, tmp_path / "config.yaml")
    by_id = {s.id: s for s in config.sections}
    # 新模型速览是早报板块：模板默认就带早报模式
    assert by_id["model_releases"].skip_today is True
    assert by_id["model_releases"].freshness_first is True
    # 其他板块默认不启用，配置写了才生效，且能随 save 往返
    assert by_id["llm_oss"].skip_today is False
    raw_config["sections"][0]["skip_today"] = True
    raw_config["sections"][0]["freshness_first"] = True
    config = Config.from_dict(raw_config, tmp_path / "config.yaml")
    saved = config.save()
    reloaded = Config.load(saved)
    assert reloaded.sections[0].skip_today is True
    assert reloaded.sections[0].freshness_first is True


def test_email_guardrails_catch_display_name_misplaced_as_login():
    from evenews.config import EmailConfig

    bad = EmailConfig(smtp_host="smtp.qq.com", from_address="bot@qq.com",
                      to=["a@b.c"], password="x", username="AI 每日资讯")
    problems = bad.problems()
    assert any("email.username" in p and "邮箱地址" in p for p in problems), \
        "中文登录名必须被 problems() 拦下并给出改法"

    # 正确写法：登录名是纯邮箱地址，中文显示名放进 from 的尖括号前。
    good = EmailConfig(smtp_host="smtp.qq.com", from_address="AI 每日资讯 <bot@qq.com>",
                       to=["a@b.c"], password="x", username="bot@qq.com")
    assert good.problems() == []
