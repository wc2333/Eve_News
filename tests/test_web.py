"""Tests for the browser settings console: it must never lose or leak the config."""

from __future__ import annotations

import http.client
import json
import os
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from evenews import web

HOST = "127.0.0.1"
SECRET_ENVS = ["EVE_NEWS_SMTP_PASSWORD", "EVE_NEWS_LLM_API_KEY", "EVE_NEWS_SEARCH_API_KEY"]


class Client:
    """Talk raw HTTP so a system proxy cannot swallow localhost requests."""

    def __init__(self, port: int) -> None:
        self.port = port

    def call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        connection = http.client.HTTPConnection(HOST, self.port, timeout=120)
        body = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        headers = {"Content-Type": "application/json; charset=utf-8"} if body else {}
        connection.request(method, path, body=body.encode("utf-8") if body else None, headers=headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8")
        connection.close()
        try:
            return int(response.status), json.loads(text)
        except ValueError:
            return int(response.status), text


class SettingsHandler(web.RequestHandler):
    """Shadows the class attribute the CLI sets, so tests never touch the repo config."""

    config_path = Path("unused.yaml")


@pytest.fixture(autouse=True)
def _secrets_are_isolated(monkeypatch):
    for name in SECRET_ENVS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def site(raw_config: dict, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw_config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    SettingsHandler.config_path = config_path
    server = ThreadingHTTPServer((HOST, 0), SettingsHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield Client(server.server_address[1]), config_path, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def saved(config_path: Path) -> dict:
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def test_page_and_state_hide_secrets(site):
    client, _, _ = site
    status, page = client.call("GET", "/")
    assert status == 200 and "<html" in page.lower()

    status, state = client.call("GET", "/api/state")
    assert status == 200
    assert [section["id"] for section in state["sections"]] == ["models", "wearables"]
    assert state["sections"][1]["sources"]
    assert state["problems"] == []
    assert [row["env"] for row in state["secrets"]] == SECRET_ENVS
    assert all(row["set"] is False for row in state["secrets"])
    assert state["raw"]["email"]["password"] == ""
    assert state["raw"]["llm"]["api_key"] == ""


def test_unknown_route_returns_json_error(site):
    client, _, _ = site
    status, body = client.call("POST", "/api/whatever", {})
    assert status == 400 and body["ok"] is False and "未知接口" in body["error"]


def test_sections_toggle_persists(site):
    client, config_path, _ = site
    status, body = client.call(
        "POST",
        "/api/sections",
        {"updates": [{"id": "wearables", "enabled": True, "max_items": 4, "keywords": ["眼镜", "手表"]}]},
    )
    assert status == 200 and body["ok"] is True
    after = saved(config_path)
    assert [section["id"] for section in after["sections"]] == ["models", "wearables"]
    assert after["sections"][1]["enabled"] is True
    assert after["sections"][1]["max_items"] == 4
    assert after["sections"][1]["keywords"] == ["眼镜", "手表"]

    before = config_path.read_bytes()
    status, body = client.call("POST", "/api/sections", {"updates": [{"id": "no-such-section", "enabled": True}]})
    assert status == 400 and config_path.read_bytes() == before


def test_settings_deep_merge_keeps_unrelated_keys(site):
    client, config_path, _ = site
    before = saved(config_path)
    status, body = client.call("POST", "/api/settings", {"settings": {"collection": {"lookback_hours": 48}}})
    assert status == 200 and body["ok"] is True
    after = saved(config_path)
    assert after["collection"]["lookback_hours"] == 48
    assert after["collection"]["dedupe_days"] == before["collection"]["dedupe_days"]
    assert after["brand"]["company"] == before["brand"]["company"]


def test_secrets_only_land_in_env_file(site):
    client, config_path, tmp_path = site
    status, body = client.call("POST", "/api/secrets", {"values": {"EVE_NEWS_LLM_API_KEY": "sk-test-1234"}})
    assert status == 200 and body["written"] == ["EVE_NEWS_LLM_API_KEY"]
    assert "EVE_NEWS_LLM_API_KEY=sk-test-1234" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert os.environ["EVE_NEWS_LLM_API_KEY"] == "sk-test-1234"
    assert "sk-test-1234" not in config_path.read_text(encoding="utf-8")

    status, state = client.call("GET", "/api/state")
    row = [item for item in state["secrets"] if item["env"] == "EVE_NEWS_LLM_API_KEY"][0]
    assert row["set"] is True and row["length"] == len("sk-test-1234")
    assert "sk-test-1234" not in json.dumps(state, ensure_ascii=False)

    client.call("POST", "/api/secrets", {"values": {"EVE_NEWS_LLM_API_KEY": ""}})
    status, state = client.call("GET", "/api/state")
    row = [item for item in state["secrets"] if item["env"] == "EVE_NEWS_LLM_API_KEY"][0]
    assert row["set"] is False and os.environ.get("EVE_NEWS_LLM_API_KEY") is None


def test_bad_yaml_is_validated_before_writing(site):
    client, config_path, tmp_path = site
    before = config_path.read_bytes()
    for payload in ({"yaml": "email: [oops]\n"}, {"yaml": "just a string\n"}, {"yaml": "email: {"}):
        status, body = client.call("PUT", "/api/yaml", payload)
        assert status == 400 and body["ok"] is False
        assert config_path.read_bytes() == before
        assert not (tmp_path / web.CANDIDATE_NAME).exists()

    status, body = client.call(
        "PUT",
        "/api/yaml",
        {"yaml": "log_level: WARNING\nsections:\n  - id: only\n    title: 唯一板块\n    sources: []\n"},
    )
    assert status == 200 and body["ok"] is True
    status, state = client.call("GET", "/api/state")
    assert [section["id"] for section in state["sections"]] == ["only"]
    assert (tmp_path / (config_path.name + ".bak")).is_file()


def test_offline_preview_and_model_check(site):
    client, _, tmp_path = site
    status, body = client.call("POST", "/api/action", {"action": "preview", "offline": True})
    assert status == 200 and body["ok"] is True and body["errors"] == []
    html = Path(body["files"]["html"])
    assert html.is_file() and html.parent.parent == tmp_path / "out"

    status, page = client.call("GET", "/api/preview")
    assert status == 200 and "<!DOCTYPE html>" in page

    status, body = client.call("POST", "/api/action", {"action": "test-model"})
    assert status == 200 and body["summary"].startswith("mock")

    status, body = client.call("POST", "/api/action", {"action": "teleport"})
    assert status == 400 and "未知操作" in body["error"]


def test_latest_output_prefers_real_dates(site):
    client, _, tmp_path = site
    day = tmp_path / "out" / "2026-09-20"
    day.mkdir(parents=True)
    (day / "digest.html").write_text("<html></html>", encoding="utf-8")
    stray = tmp_path / "out" / "zzz-stray"
    stray.mkdir(parents=True)
    (stray / "notes.txt").write_text("x", encoding="utf-8")

    status, state = client.call("GET", "/api/state")
    assert status == 200 and state["latest"]["date"] == "2026-09-20"
    status, page = client.call("GET", "/api/preview")
    assert status == 200 and page == "<html></html>"


def test_the_settings_page_serves_the_brand_logo(site, tmp_path):
    client, config_path, _ = site
    status, body = client.call("GET", "/api/brand-logo")
    assert status == 400 and "logo_file" in body["error"], "no logo configured must read as a clear answer"

    mark = tmp_path / "mark.svg"
    mark.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>', encoding="utf-8")
    status, body = client.call("PUT", "/api/settings", {"settings": {"brand": {"company": "凯铮寰宇", "logo_file": str(mark)}}})
    assert status == 200 and body["ok"] is True

    status, body = client.call("GET", "/api/brand-logo")
    assert status == 200 and "<svg" in body


def test_a_second_window_on_a_taken_port_says_so(raw_config: dict, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw_config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    holder = socket.socket()
    holder.bind((HOST, 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    outcome: list = []

    def run() -> None:
        outcome.append(web.serve(config_path, host=HOST, port=port, open_browser=False))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=8)
    holder.close()

    assert outcome == [2], "a silent second copy would keep serving the old code"


def test_the_snapshot_shares_the_email_palette(site):
    client, _, _ = site
    status, state = client.call("GET", "/api/state")
    assert status == 200
    assert state["palettes"]["dark"]["background"] == "#060b14"
    assert state["palettes"]["light"]["background"] == "#f5f3ee"
