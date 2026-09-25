"""Model access: one chat abstraction for many providers, plus a deterministic offline mock."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import LLMConfig
from .net import HttpError, fetch_json

log = logging.getLogger("evenews.llm")

SYSTEM_PROMPT = (
    "你是公司内部《AI 每日资讯》的资深编辑助手。"
    "用户消息是一个 JSON 任务，你必须只输出 JSON 本体，不要 Markdown 代码块、不要多余说明。"
    "文字用简体中文，客观、克制、保留原文中的数字与主体名称，绝不编造任务数据之外的信息。"
)

PROVIDER_FAMILY = {
    "openai": "openai",
    "openai-compatible": "openai",
    "deepseek": "openai",
    "moonshot": "openai",
    "dashscope": "openai",
    "siliconflow": "openai",
    "anthropic": "anthropic",
    "ollama": "ollama",
    "mock": "mock",
    "off": "mock",
}

DEFAULT_BASE_URL = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://127.0.0.1:11434",
}

JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMError(Exception):
    pass


def extract_json(text: str) -> dict:
    if not text:
        return {}
    fenced = JSON_FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class BaseLLM:
    name = "base"

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg

    @property
    def label(self) -> str:
        return f"{self.name}:{self.cfg.model or 'default'}"

    def chat(self, system: str, user: str) -> str:
        raise NotImplementedError

    def json_task(self, task: str, payload: dict) -> dict:
        user = json.dumps({"task": task, **payload}, ensure_ascii=False)
        raw = self.chat(SYSTEM_PROMPT, user)
        data = extract_json(raw)
        if not data:
            raise LLMError(f"{self.label} 没有返回可解析的 JSON（任务 {task}）")
        return data


class OpenAIChat(BaseLLM):
    """Works with OpenAI and every OpenAI-compatible gateway (DeepSeek、Moonshot、通义、硅基流动 …)."""

    name = "openai"

    def _endpoint(self) -> str:
        return f"{self.cfg.base_url}/chat/completions"

    def chat(self, system: str, user: str) -> str:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_output_tokens,
        }
        if self.cfg.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", **self.cfg.headers}
        optional_order = ["response_format", "temperature", "max_tokens"]
        last_error: Exception | None = None
        for _ in range(len(optional_order) + 1):
            try:
                data = fetch_json(self._endpoint(), payload=payload, headers=headers, timeout=self.cfg.timeout, retries=self.cfg.retries)
                choices = data.get("choices") or []
                if not choices:
                    raise LLMError(f"{self.label} 返回里没有 choices")
                return (choices[0].get("message") or {}).get("content") or ""
            except (HttpError, LLMError) as exc:
                last_error = exc
                dropped = next((key for key in optional_order if key in payload), None)
                if dropped is None:
                    break
                log.warning("%s 拒绝了参数 %s，去掉后重试：%s", self.label, dropped, exc)
                payload.pop(dropped)
        raise LLMError(f"{self.label} 调用失败: {last_error}")


class AnthropicChat(BaseLLM):
    name = "anthropic"

    def chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.cfg.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": self.cfg.max_output_tokens,
            "temperature": self.cfg.temperature,
        }
        headers = {
            "x-api-key": self.cfg.api_key,
            "anthropic-version": "2023-06-01",
            **self.cfg.headers,
        }
        try:
            data = fetch_json(f"{self.cfg.base_url}/messages", payload=payload, headers=headers, timeout=self.cfg.timeout, retries=self.cfg.retries)
        except HttpError as exc:
            raise LLMError(f"{self.label} 调用失败: {exc}") from exc
        parts = [block.get("text", "") for block in data.get("content", []) if isinstance(block, dict)]
        return "\n".join(p for p in parts if p)


class OllamaChat(BaseLLM):
    name = "ollama"

    def chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.cfg.model or "qwen2.5:7b",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": self.cfg.temperature},
            "format": "json" if self.cfg.json_mode else "",
        }
        try:
            data = fetch_json(f"{self.cfg.base_url}/api/chat", payload=payload, timeout=self.cfg.timeout, retries=self.cfg.retries, headers=self.cfg.headers)
        except HttpError as exc:
            raise LLMError(f"{self.label} 调用失败: {exc}") from exc
        return (data.get("message") or {}).get("content", "")


SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])")


class MockLLM(BaseLLM):
    """Rule-based stand-in so the whole pipeline runs without an API key (offline demo & tests)."""

    name = "mock"

    def chat(self, system: str, user: str) -> str:
        return json.dumps({"note": "mock provider", "received": user[:80]}, ensure_ascii=False)

    def json_task(self, task: str, payload: dict) -> dict:
        if task == "queries":
            section = payload.get("section") or {}
            keywords = [k for k in section.get("keywords", [])[:4]]
            base = section.get("title") or "AI"
            return {"queries": [f"{base} 最新 发布", f"{base} {' '.join(keywords[:3])}"]}
        if task == "curate":
            section = payload.get("section") or {}
            keywords = [str(k).lower() for k in section.get("keywords", [])]
            items = []
            for candidate in payload.get("candidates", []):
                blob = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
                hits = [k for k in keywords if k and k in blob]
                body = str(candidate.get("summary") or candidate.get("title") or "").strip()
                sentences = [s.strip() for s in SENTENCE_SPLIT.split(body) if s.strip()]
                summary = "".join(sentences[:2])[:130] or body[:130]
                digits = len(re.findall(r"\d", str(candidate.get("title", ""))))
                score = round(min(0.95, 0.35 + 0.12 * min(len(hits), 4) + 0.02 * min(digits, 5)), 3)
                items.append(
                    {
                        "ref": candidate.get("ref"),
                        "score": score,
                        "summary": summary,
                        "why": ("命中关键词：" + "、".join(hits[:4])) if hits else "与板块主题相关",
                        "keywords": hits[:5],
                    }
                )
            return {"items": items}
        if task == "lead":
            sections = payload.get("sections") or []
            total = int(payload.get("item_count") or sum(int(s.get("count") or 0) for s in sections))
            parts = [f"「{s.get('title')}」{s.get('count')} 条" for s in sections if s.get("count")]
            headline = ""
            for section in sections:
                if section.get("headlines"):
                    headline = str(section["headlines"][0])
                    break
            lead = f"今日共整理 {total} 条资讯，覆盖 {len(sections)} 个板块：" + "，".join(parts) + "。"
            if headline:
                lead += f"重点：{headline}。"
            return {"lead": lead, "source": "mock"}
        raise LLMError(f"mock 供应商不支持任务: {task}")


def build_llm(cfg: LLMConfig) -> BaseLLM:
    family = PROVIDER_FAMILY.get(cfg.provider, "openai")
    if family == "mock" or cfg.provider in {"mock", "off"}:
        return MockLLM(cfg)
    if not cfg.api_key and family in {"openai", "anthropic"}:
        log.warning("%s 缺少 api_key，退回离线 mock 模型（结果仅供演示）", cfg.provider)
        return MockLLM(cfg)
    base = cfg.base_url
    default_base = DEFAULT_BASE_URL.get(cfg.provider) or DEFAULT_BASE_URL.get(family, "")
    if not base or (cfg.provider != "openai-compatible" and default_base and "api.openai.com" in base and cfg.provider != "openai"):
        base = default_base
    cfg.base_url = base.rstrip("/")
    if family == "anthropic":
        return AnthropicChat(cfg)
    if family == "ollama":
        return OllamaChat(cfg)
    return OpenAIChat(cfg)
