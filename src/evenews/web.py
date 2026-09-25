"""Local settings console: a browser UI over the same config.yaml the CLI uses.

    evenews web        # http://127.0.0.1:8765

Deliberately dependency-free: stdlib http.server plus one self-contained HTML
page. Binds to localhost by default because it can read and write secrets.
"""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from .config import Config, ConfigError, load_dotenv
from .mailer import send_digest
from .pipeline import SAMPLE_FEEDS, run_once
from .state import StateStore

log = logging.getLogger("evenews.web")

WEB_DIR = Path(__file__).resolve().parent / "webui"
DEFAULT_PORT = 8765
CANDIDATE_NAME = ".config.candidate.yaml"
DATE_DIR = re.compile(r"\d{4}-\d{2}-\d{2}$")
ENV_FILE = ".env"


class WebError(Exception):
    pass


def env_file(config_dir: Path) -> Path:
    return Path(config_dir) / ENV_FILE


def read_env_file(config_dir: Path) -> dict[str, str]:
    path = env_file(config_dir)
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_file(config_dir: Path, updates: dict[str, str]) -> list[str]:
    """Upsert KEY=value lines into .env; empty value clears the entry."""
    path = env_file(config_dir)
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    touched: list[str] = []
    for key, value in updates.items():
        key = key.strip()
        if not key:
            continue
        touched.append(key)
        replaced = False
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[index] = f"{key}={value}" if value else f"# {key}="
                replaced = True
                break
        if not replaced and value:
            lines.append(f"{key}={value}")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", errors="replace")
    path.chmod(0o600) if hasattr(os, "chmod") and os.name != "nt" else None
    return touched


def secret_status(config: Config) -> list[dict[str, Any]]:
    stored = read_env_file(config_dir(config))
    email_raw = config.raw.get("email") or {}
    llm_raw = config.raw.get("llm") or {}
    search_raw = llm_raw.get("search") or {}
    entries = [
        ("SMTP 邮箱密码 / 授权码", email_raw, "EVE_NEWS_SMTP_PASSWORD"),
        ("模型 API Key", llm_raw, "EVE_NEWS_LLM_API_KEY"),
        ("联网检索 API Key", search_raw, "EVE_NEWS_SEARCH_API_KEY"),
    ]
    result: list[dict[str, Any]] = []
    for label, mapping, default_env in entries:
        name = str(mapping.get("password_env") or mapping.get("api_key_env") or "").strip() or default_env
        value = os.environ.get(name) or stored.get(name, "")
        result.append({"label": label, "env": name, "set": bool(value), "length": len(value or "")})
    return result

def config_dir(config: Config) -> Path:
    return Path(config.path).parent if config.path else Path.cwd()


def redact(raw: dict) -> dict:
    """Never echo secrets back to the browser, only whether they are set."""
    safe = json.loads(json.dumps(raw, ensure_ascii=False))
    email = safe.get("email") or {}
    if isinstance(email, dict):
        email["password"] = ""
    llm = safe.get("llm") or {}
    if isinstance(llm, dict):
        llm["api_key"] = ""
        search = llm.get("search")
        if isinstance(search, dict):
            search["api_key"] = ""
    return safe

def merge(base: dict, patch: dict) -> dict:
    merged = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def save_raw(config_path: Path, raw: dict) -> list[str]:
    """Validate through the real loader first so the UI can never brick the config."""
    config_path = Path(config_path)
    text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=100)
    candidate = config_path.parent / CANDIDATE_NAME
    try:
        candidate.write_text(text, encoding="utf-8")
        probe = Config.load(candidate)
    except Exception as exc:  # noqa: BLE001 - a bad YAML shape must read as a 400, not a 500
        raise WebError(f"配置校验未通过，未保存：{exc}") from exc
    finally:
        candidate.unlink(missing_ok=True)
    backup = config_path.parent / (config_path.name + ".bak")
    if config_path.is_file():
        backup.write_bytes(config_path.read_bytes())
    config_path.write_text(text, encoding="utf-8")
    return probe.problems(need_email=False)


def state_summary(config: Config) -> dict:
    store = StateStore(config.state_root / "state.json")
    return {"seen": len(store.data.get("seen", {})), "runs": list(store.data.get("runs", []))[-10:]}


def latest_output(config: Config) -> dict:
    root = Path(config.out_root)
    if not root.is_dir():
        return {}
    folders = [item for item in root.iterdir() if item.is_dir()]
    days = sorted([item for item in folders if DATE_DIR.match(item.name)], reverse=True)
    candidates = days or sorted(folders, key=lambda item: item.name, reverse=True)
    if not candidates:
        return {}
    newest = candidates[0]
    return {"date": newest.name, "files": [item.name for item in sorted(newest.iterdir())]}


def read_text_tail(path: Path, limit: int = 6000) -> str:
    path = Path(path)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]

class SettingsServer(ThreadingHTTPServer):
    """Never share the port: on Windows SO_REUSEADDR lets a stale copy keep the connections."""

    allow_reuse_address = False


class RequestHandler(BaseHTTPRequestHandler):
    """Small JSON API behind the settings page; localhost-only by default."""

    config_path = Path("config.yaml")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        log.debug("%s - %s", self.address_string(), format % args)

    def _config(self) -> Config:
        load_dotenv(Path(self.config_path).parent)
        return Config.load(self.config_path)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError as exc:
            raise WebError(f"请求体不是合法 JSON：{exc}") from exc
        return parsed if isinstance(parsed, dict) else {}

    def _error(self, exc: Exception) -> None:
        status = 400 if isinstance(exc, (WebError, ConfigError)) else 500
        if status == 500:
            log.error("接口异常：%s%s", exc, traceback.format_exc())
        self._json({"ok": False, "error": str(exc)}, status)

    def _snapshot(self) -> dict:
        config = self._config()
        return {
            "config_path": str(self.config_path),
            "env_path": str(env_file(config_dir(config))),
            "yaml": Path(self.config_path).read_text(encoding="utf-8"),
            "raw": redact(config.raw),
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "description": section.description,
                    "enabled": section.enabled,
                    "keywords": section.keywords,
                    "max_items": section.max_items,
                    "sources": [source.name for source in section.sources],
                }
                for section in config.sections
            ],
            "problems": config.problems(need_email=False),
            "secrets": secret_status(config),
            "state": state_summary(config),
            "latest": latest_output(config),
            "log_tail": read_text_tail(config_dir(config) / "logs" / "daily.log"),
            "version": __import__("evenews").__version__,
        }

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        try:
            route = urlparse(self.path)
            path, query = route.path.rstrip("/"), parse_qs(route.query)
            if path in {"", "/"}:
                page = WEB_DIR / "index.html"
                if not page.is_file():
                    raise WebError(f"缺少页面文件 {page}")
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(self._snapshot())
            if path == "/api/brand-logo":
                from .render import resolve_logo

                raw, mime = resolve_logo(self._config().brand)
                if not raw:
                    raise WebError("没有配置 brand.logo_file")
                return self._send(200, raw, mime)
            if path == "/api/preview":
                config = self._config()
                date = (query.get("date") or [""])[0] or latest_output(config).get("date", "")
                html = Path(config.out_root) / str(date) / "digest.html"
                if not html.is_file():
                    raise WebError(f"还没有生成 {date or '任何一天'} 的简报")
                return self._send(200, html.read_bytes(), "text/html; charset=utf-8")
            raise WebError(f"未知接口：{path}")
        except Exception as exc:  # noqa: BLE001 - one error shape for the whole page
            self._error(exc)

    def do_PUT(self) -> None:  # noqa: N802 - stdlib name
        self._write()

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        self._write()

    def _write(self) -> None:
        try:
            path = urlparse(self.path).path.rstrip("/")
            body = self._body()
            if path == "/api/yaml":
                try:
                    raw = yaml.safe_load(str(body.get("yaml") or ""))
                except (ValueError, yaml.YAMLError) as exc:
                    raise WebError(f"YAML 解析失败：{exc}") from exc
                if not isinstance(raw, dict):
                    raise WebError("YAML 顶层必须是一个 mapping")
                problems = save_raw(Path(self.config_path), raw)
                return self._json({"ok": True, "saved": str(self.config_path), "problems": problems})
            if path == "/api/settings":
                config = self._config()
                merged = merge(config.raw, body.get("settings") or {})
                problems = save_raw(Path(self.config_path), merged)
                return self._json({"ok": True, "saved": str(self.config_path), "problems": problems})
            if path == "/api/sections":
                config = self._config()
                raw = json.loads(json.dumps(config.raw, ensure_ascii=False))
                entries = {str(entry.get("id")): entry for entry in raw.get("sections") or [] if isinstance(entry, dict)}
                for update in body.get("updates") or []:
                    if not isinstance(update, dict) or not update.get("id"):
                        continue
                    entry = entries.get(str(update["id"]))
                    if entry is None:
                        raise WebError(f"未知板块：{update['id']}")
                    for field in ("enabled", "keywords", "max_items", "extra_prompt", "title", "description"):
                        if field in update:
                            entry[field] = update[field]
                problems = save_raw(Path(self.config_path), raw)
                return self._json({"ok": True, "saved": str(self.config_path), "problems": problems})
            if path == "/api/secrets":
                config = self._config()
                updates = {str(key): str(value) for key, value in (body.get("values") or {}).items()}
                touched = write_env_file(config_dir(config), updates)
                return self._json({"ok": True, "written": touched, "env_path": str(env_file(config_dir(config)))})
            if path == "/api/action":
                return self._json(self._action(body))
            raise WebError(f"未知接口：{path}")
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _action(self, payload: dict) -> dict:
        action = str(payload.get("action") or "preview")
        config = self._config()
        only = [str(item).strip() for item in payload.get("sections") or [] if str(item).strip()] or None
        offline = bool(payload.get("offline"))

        if action in {"preview", "send"}:
            report = run_once(config, only=only, offline=offline, send=action == "send")
            return {
                "ok": bool(report.sent) if action == "send" else True,
                "summary": report.summary(),
                "errors": report.errors,
                "files": {key: str(value) for key, value in report.files.items()},
                "latest": latest_output(config),
            }
        if action == "test-email":
            recipients = [str(item).strip() for item in payload.get("to") or [] if str(item).strip()] or None
            send_digest(
                config.email,
                subject=f"[测试] {config.brand.title} 邮件通道检查",
                html="<p>这是一封来自 Eve_News 设置页面的测试邮件。</p>",
                text="这是一封来自 Eve_News 设置页面的测试邮件。",
                to=recipients,
            )
            return {"ok": True, "summary": f"测试邮件已发送给 {len(recipients or config.email.to)} 位收件人"}
        if action == "test-model":
            from .llm import build_llm

            llm = build_llm(config.llm)
            data = llm.json_task(
                "lead",
                {
                    "date": "2026-01-01",
                    "item_count": 1,
                    "sections": [{"title": "连通性测试", "count": 1, "headlines": ["你好"]}],
                    "rules": {"length": "20 字以内", "output": '{"lead":""}'},
                },
            )
            return {"ok": True, "summary": f"{llm.label} 返回：{str(data.get('lead') or data)[:90]}"}
        if action == "test-sources":
            from .feeds import fetch_source

            seen: set[str] = set()
            rows: list[dict] = []
            for section in config.enabled_sections():
                for source in section.sources:
                    key = f"{source.name}|{source.url}"
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        articles = fetch_source(
                            source,
                            config.collection,
                            fixtures_dir=SAMPLE_FEEDS if offline else None,
                            fixtures_only=offline,
                        )
                        rows.append({"name": source.name, "items": len(articles), "error": ""})
                    except Exception as exc:  # noqa: BLE001
                        rows.append({"name": source.name, "items": 0, "error": str(exc)[:120]})
            return {"ok": True, "sources": rows, "summary": f"{len(rows)} 个来源，共 {sum(row['items'] for row in rows)} 条候选"}
        raise WebError(f"未知操作：{action}")


def serve(config_path: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT, open_browser: bool = True) -> int:
    RequestHandler.config_path = Path(config_path).resolve()
    load_dotenv(RequestHandler.config_path.parent)
    url = f"http://{host}:{port}"
    try:
        server = SettingsServer((host, int(port)), RequestHandler)
    except OSError as exc:
        message = (
            f"端口 {port} 上已经有一个设置页在跑（{exc}），它读的是旧代码。"
            f"关掉那个窗口再开，或换端口：evenews web --port {int(port) + 3}"
        )
        print(message)
        log.error(message)
        return 2
    print(f"设置页面：{url}   配置文件：{RequestHandler.config_path}")
    log.info("设置页面已启动：%s （Ctrl+C 停止）", url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless machines simply have no browser
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("已停止设置页面")
    finally:
        server.server_close()
    return 0
