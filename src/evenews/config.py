"""Configuration: YAML file plus environment secrets, with cross-platform defaults."""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Section, Source

ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_NAMES = ("config.yaml", "config.yml", "evenews.yaml")


class ConfigError(Exception):
    pass


def default_config_text() -> str:
    return (DATA_DIR / "config.example.yaml").read_text(encoding="utf-8")


def write_default_config(path: Path, *, force: bool = False) -> Path:
    target = Path(path)
    if target.exists() and not force:
        raise ConfigError(f"{target} already exists; pass --force to overwrite it")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(default_config_text(), encoding="utf-8")
    return target


def find_config(start: Path | None = None) -> Path | None:
    base = Path(start or Path.cwd()).resolve()
    for folder in [base, *base.parents]:
        for name in CONFIG_NAMES:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


def load_dotenv(path: Path) -> int:
    """Load KEY=value lines from a .env file without overriding real env vars."""
    if not Path(path).is_file():
        return 0
    loaded = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def _merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _expand_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, str):
        return ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    return value


def _secret(mapping: dict, inline_key: str, env_key: str) -> str:
    env_name = str(mapping.get(env_key) or "").strip()
    if env_name:
        return os.environ.get(env_name, "") or str(mapping.get(inline_key) or "")
    return str(mapping.get(inline_key) or "")


def _proxy(raw: dict) -> str:
    """Empty = follow the environment; none = force a direct connection; anything else is a proxy URL."""
    env_name = str(raw.get("proxy_env") or "EVE_NEWS_PROXY").strip()
    return str(raw.get("proxy") or os.environ.get(env_name) or "").strip()


def _source_pool(raw: Any) -> dict[str, dict]:
    """The source pool may be written as a mapping (name: {url}) or as a list of named dicts."""
    pool: dict[str, dict] = {}
    if isinstance(raw, dict):
        for name, item in raw.items():
            pool[str(name)] = item if isinstance(item, dict) else {"url": str(item)}
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                pool[str(item["name"])] = item
    return pool


@dataclass
class Brand:
    group: str = ""               # 集团名，排在子公司名前面
    company: str = ""
    logo_text: str = ""
    logo_file: str = ""
    site: str = ""
    theme: str = "light"          # light 纸白 / dark 官网深色；空着按 light
    kicker: str = "DAILY AI BRIEFING"
    title: str = "AI 每日资讯"
    classification: str = "内部参考"
    footer_note: str = "自动生成 · 仅供内部参考，转载请注明出处"
    background: str = ""
    accent: str = ""
    label: str = ""
    text: str = ""
    card: str = ""
    body: str = ""
    muted: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Brand":
        fields = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**fields)


@dataclass
class ScheduleConfig:
    time: str = "08:00"
    timezone: str = "Asia/Shanghai"
    weekday_only: bool = False

    @classmethod
    def from_dict(cls, raw: dict) -> "ScheduleConfig":
        return cls(
            time=str(raw.get("time") or "08:00"),
            timezone=str(raw.get("timezone") or "Asia/Shanghai"),
            weekday_only=bool(raw.get("weekday_only", False)),
        )


@dataclass
class EmailConfig:
    enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 465
    security: str = "ssl"
    username: str = ""
    password: str = ""
    from_address: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    subject_template: str = "{title} · {date}"
    subject_prefix: str = ""
    attach_html: bool = False
    attach_logo: bool = True
    timeout: int = 30
    retries: int = 2

    @classmethod
    def from_dict(cls, raw: dict) -> "EmailConfig":
        return cls(
            enabled=bool(raw.get("enabled", True)),
            smtp_host=str(raw.get("smtp_host") or ""),
            smtp_port=int(raw.get("smtp_port") or 465),
            security=str(raw.get("security") or "ssl").lower(),
            username=str(raw.get("username") or ""),
            password=_secret(raw, "password", "password_env"),
            from_address=str(raw.get("from") or raw.get("from_address") or ""),
            to=[str(x) for x in raw.get("to") or []],
            cc=[str(x) for x in raw.get("cc") or []],
            subject_template=str(raw.get("subject_template") or "{title} · {date}"),
            subject_prefix=str(raw.get("subject_prefix") or ""),
            attach_html=bool(raw.get("attach_html", False)),
            attach_logo=bool(raw.get("attach_logo", True)),
            timeout=int(raw.get("timeout") or 30),
            retries=int(raw.get("retries") or 0),
        )

    def problems(self) -> list[str]:
        if not self.enabled:
            return []
        issues = []
        if not self.smtp_host:
            issues.append("email.smtp_host 未配置")
        if not self.from_address:
            issues.append("email.from 未配置")
        if not self.to:
            issues.append("email.to 至少需要一个收件人")
        if not self.password:
            issues.append("email 密码为空（检查 email.password 或 password_env 指向的环境变量）")
        if self.username and not self.username.isascii():
            issues.append(
                "email.username 含中文：SMTP 登录名必须是邮箱地址（如 xxx@qq.com），协议不收中文；"
                "显示名请写进 email.from：AI 每日资讯 <xxx@qq.com>"
            )
        if self.from_address and "@" not in self.from_address:
            issues.append("email.from 里必须含邮箱地址（显示名写在地址前面的尖括号里）")
        if self.security not in {"ssl", "starttls", "none"}:
            issues.append("email.security 只能是 ssl / starttls / none")
        return issues


@dataclass
class LLMConfig:
    provider: str = "mock"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    temperature: float = 0.2
    timeout: int = 180
    retries: int = 2
    json_mode: bool = True
    max_output_tokens: int = 32000
    batch_size: int = 8
    summary_min: int = 300          # 每条介绍的目标字数区间
    summary_max: int = 400
    proxy: str = ""
    tasks: dict = field(default_factory=dict)
    search: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    extra_body: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "LLMConfig":
        return cls(
            provider=str(raw.get("provider") or "mock").lower(),
            base_url=str(raw.get("base_url") or "").rstrip("/"),
            model=str(raw.get("model") or ""),
            api_key=_secret(raw, "api_key", "api_key_env"),
            proxy=_proxy(raw),
            temperature=float(raw.get("temperature") or 0.2),
            timeout=int(raw.get("timeout") or 180),
            retries=int(raw.get("retries") or 0),
            json_mode=bool(raw.get("json_mode", True)),
            max_output_tokens=int(raw.get("max_output_tokens") or 32000),
            batch_size=int(raw.get("batch_size") or 8),
            summary_min=max(80, int(raw.get("summary_min") or 300)),
            summary_max=max(120, int(raw.get("summary_max") or 400)),
            tasks=dict(raw.get("tasks") or {}),
            search=dict(raw.get("search") or {}),
            headers=dict(raw.get("headers") or {}),
            extra_body=dict(raw.get("extra_body") or {}),
        )

    def task_on(self, name: str) -> bool:
        return bool(self.tasks.get(name, True))

    def problems(self) -> list[str]:
        provider = self.provider
        if provider in {"mock", "off"}:
            return []
        issues = []
        if provider not in {"openai", "openai-compatible", "anthropic", "ollama", "deepseek", "moonshot", "dashscope", "siliconflow"}:
            issues.append(f"llm.provider 不支持: {provider}")
        if provider in {"openai", "openai-compatible", "anthropic", "deepseek", "moonshot", "dashscope", "siliconflow"}:
            if not self.api_key:
                issues.append("llm api_key 为空（检查 llm.api_key 或 api_key_env 指向的环境变量）")
            if not self.model:
                issues.append("llm.model 未配置")
        if provider in {"openai", "openai-compatible", "anthropic", "deepseek", "moonshot", "dashscope", "siliconflow"} and not self.base_url:
            issues.append("llm.base_url 未配置")
        if provider == "ollama" and not self.base_url:
            issues.append("llm.base_url 未配置（ollama 一般为 http://127.0.0.1:11434）")
        return issues


@dataclass
class CollectionConfig:
    mode: str = "feeds"
    lookback_hours: int = 30
    per_source_limit: int = 25
    headers: dict = field(default_factory=dict)
    require_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    dedupe_days: int = 10
    timeout: int = 25
    retries: int = 1
    proxy: str = ""
    fetch_content: bool = True    # 订阅正文太短的来源，去抓一次原文页面

    @classmethod
    def from_dict(cls, raw: dict) -> "CollectionConfig":
        return cls(
            mode=str(raw.get("mode") or "feeds").lower(),
            lookback_hours=int(raw.get("lookback_hours") or 30),
            per_source_limit=int(raw.get("per_source_limit") or 25),
            headers=dict(raw.get("headers") or {}),
            require_keywords=[str(x) for x in raw.get("require_keywords") or []],
            exclude_keywords=[str(x) for x in raw.get("exclude_keywords") or []],
            dedupe_days=int(raw.get("dedupe_days") or 10),
            timeout=int(raw.get("timeout") or 25),
            retries=int(raw.get("retries") or 1),
            fetch_content=bool(raw.get("fetch_content", True)),
            proxy=_proxy(raw),
        )


@dataclass
class Config:
    path: Path | None = None
    raw: dict = field(default_factory=dict)
    brand: Brand = field(default_factory=Brand)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    collection: CollectionConfig = field(default_factory=CollectionConfig)
    sections: list[Section] = field(default_factory=list)
    out_dir: Path = Path("out")
    state_dir: Path = Path("state")
    log_level: str = "INFO"

    @classmethod
    def from_dict(cls, raw: dict, path: Path | None = None) -> "Config":
        base = yaml.safe_load(default_config_text()) or {}
        merged = _merge(base, {k: v for k, v in raw.items() if v is not None})
        merged = _expand_env(merged)
        pool = _source_pool(merged.get("sources"))
        declared = _source_pool(raw.get("sources"))
        sections: list[Section] = []
        for entry in merged.get("sections") or []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            resolved: list[Source] = []
            for ref in entry.get("sources") or []:
                if isinstance(ref, str):
                    item = pool.get(ref)
                    if item is None:
                        raise ConfigError(f"板块 {entry['id']} 引用了未定义的来源: {ref}")
                    spec = {"name": ref, **item}
                    if ref in declared:  # the file names this source itself, so it decides whether it is on
                        spec["enabled"] = declared[ref].get("enabled", True) if isinstance(declared[ref], dict) else True
                elif isinstance(ref, dict) and ref.get("url"):
                    spec = {"name": str(ref.get("name") or ref["url"]), **ref}
                else:
                    continue
                if not spec.get("enabled", True):
                    continue
                resolved.append(
                    Source(
                        name=str(spec["name"]),
                        url=str(spec.get("url") or ""),
                        type=str(spec.get("type") or "rss"),
                        headers=dict(spec.get("headers") or {}),
                        spec=dict(spec.get("json") or {}),
                        lookback_hours=int(spec.get("lookback_hours") or 0),
                        proxy=str(spec.get("proxy") or ""),
                    )
                )
            sections.append(
                Section(
                    id=str(entry["id"]),
                    title=str(entry.get("title") or entry["id"]),
                    description=str(entry.get("description") or ""),
                    enabled=bool(entry.get("enabled", True)),
                    keywords=[str(k) for k in entry.get("keywords") or []],
                    sources=resolved,
                    extra_prompt=str(entry.get("extra_prompt") or ""),
                    max_items=int(entry.get("max_items") or 6),
                    skip_today=bool(entry.get("skip_today", False)),
                    freshness_first=bool(entry.get("freshness_first", False)),
                    max_age_days=max(0, int(entry.get("max_age_days") or 0)),
                )
            )
        if not sections:
            raise ConfigError("配置里没有 sections，请先运行 evenews init 生成配置")
        root = Path(path).parent if path else Path.cwd()
        return cls(
            path=Path(path) if path else None,
            raw=merged,
            brand=Brand.from_dict(merged.get("brand") or {}),
            schedule=ScheduleConfig.from_dict(merged.get("schedule") or {}),
            email=EmailConfig.from_dict(merged.get("email") or {}),
            llm=LLMConfig.from_dict(merged.get("llm") or {}),
            collection=CollectionConfig.from_dict(merged.get("collection") or {}),
            sections=sections,
            out_dir=Path(str(merged.get("out_dir") or "out")),
            state_dir=Path(str(merged.get("state_dir") or "state")),
            log_level=str(merged.get("log_level") or "INFO"),
        )

    @classmethod
    def load(cls, path: Path | None = None, *, cwd: Path | None = None) -> "Config":
        target = Path(path) if path else find_config(cwd)
        if target is None or not Path(target).is_file():
            raise ConfigError("找不到 config.yaml，请先运行: evenews init")
        target = Path(target).resolve()
        load_dotenv(target.parent / ".env")
        try:
            raw = yaml.safe_load(target.read_text(encoding="utf-8-sig")) or {}
        except ValueError as exc:
            raise ConfigError(f"YAML 解析失败 ({target}): {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"{target} 顶层必须是一个 mapping")
        return cls.from_dict(raw, target)

    def enabled_sections(self, only: list[str] | None = None) -> list[Section]:
        if only:
            wanted = [s.strip() for s in only if s.strip()]
            known = {s.id: s for s in self.sections}
            missing = [s for s in wanted if s not in known]
            if missing:
                raise ConfigError("未知板块: " + ", ".join(missing) + "；可用: " + ", ".join(known))
            return [known[s] for s in wanted]
        return [s for s in self.sections if s.enabled]

    def set_section_enabled(self, section_id: str, enabled: bool) -> Section:
        for section in self.sections:
            if section.id == section_id:
                section.enabled = enabled
                entry = next((e for e in (self.raw.get("sections") or []) if str(e.get("id")) == section_id), None)
                if entry is not None:
                    entry["enabled"] = enabled
                return section
        raise ConfigError(f"未知板块: {section_id}；可用: " + ", ".join(s.id for s in self.sections))

    def save(self, path: Path | None = None) -> Path:
        target = Path(path or self.path)
        target.write_text(
            yaml.safe_dump(self.raw, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )
        self.path = target
        return target

    def problems(self, *, need_email: bool = True) -> list[str]:
        issues: list[str] = []
        if not TIME_PATTERN.match(self.schedule.time):
            issues.append("schedule.time 需要 HH:MM 格式")
        if not self.enabled_sections():
            issues.append("所有板块都被禁用了，至少勾选一个（evenews enable <板块>）")
        issues += self.llm.problems()
        if need_email:
            issues += self.email.problems()
        if self.collection.mode not in {"feeds", "llm", "hybrid"}:
            issues.append("collection.mode 只能是 feeds / llm / hybrid")
        for section in self.sections:
            if section.enabled and not section.sources:
                issues.append(f"板块 {section.id} 已启用但抓不到来源（检查 sources 里的 enabled 是否为 false）")
        return issues

    @property
    def out_root(self) -> Path:
        base = self.path.parent if self.path else Path.cwd()
        return base / self.out_dir

    @property
    def state_root(self) -> Path:
        base = self.path.parent if self.path else Path.cwd()
        return base / self.state_dir
