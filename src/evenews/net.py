"""Small stdlib HTTP helper shared by feed collectors, search and LLM providers."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 EveNews/0.1"
    ),
    "Accept": "application/json, application/rss+xml, application/xml, text/xml, text/html, */*",
}


log = logging.getLogger("evenews.net")


class HttpError(Exception):
    pass


NO_PROXY_WORDS = {"none", "direct", "off", "no"}
# A proxy exit that answers these is not a network failure, but the origin is still reachable directly.
RETRY_DIRECT_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}
PROXY_HINT = "（网络不通时试试 collection.proxy：填代理地址，或填 none 强制不走代理；单个来源也可以写 proxy: none 单独直连）"
_OPENERS: dict[str, Any] = {}


def opener_for(proxy: str | None):
    """Empty means trust the environment; none/direct/off ignores proxies; otherwise use that proxy URL."""
    key = (proxy or "").strip()
    if key not in _OPENERS:
        if key.lower() in NO_PROXY_WORDS:
            built = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        elif key:
            built = urllib.request.build_opener(urllib.request.ProxyHandler({"http": key, "https": key}))
        else:
            built = urllib.request.build_opener()
        _OPENERS[key] = built
    return _OPENERS[key]



def _worth_a_direct_retry(exc: Exception, mode) -> bool:
    """True when dropping the proxy could plausibly fix this attempt."""
    if isinstance(exc, urllib.error.HTTPError):
        return mode is None and int(exc.code or 0) in RETRY_DIRECT_STATUS
    return isinstance(exc, OSError)


def _local_bytes(url: str) -> bytes | None:
    candidate = url[7:] if url.startswith("file://") else url
    if url.startswith(("http://", "https://")) or "://" in url:
        return None
    path = Path(candidate)
    return path.read_bytes() if path.is_file() else None


def fetch_bytes(
    url: str,
    *,
    timeout: int = 30,
    headers: dict[str, str] | None = None,
    payload: Any = None,
    method: str | None = None,
    retries: int = 1,
    proxy: str | None = None,
) -> bytes:
    if payload is None and method is None:
        cached = _local_bytes(url)
        if cached is not None:
            return cached

    body = None
    request_headers = {**DEFAULT_HEADERS, **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    verb = method or ("POST" if body is not None else "GET")

    modes = [proxy] if proxy is not None else [None, "none"]
    last_error: Exception | None = None
    for index, mode in enumerate(modes):
        opener = opener_for(mode)
        mode_retries = retries if index == 0 else 0
        mode_timeout = timeout if index == 0 else min(timeout, 12)
        for attempt in range(max(1, mode_retries + 1)):
            try:
                request = urllib.request.Request(url, data=body, headers=request_headers, method=verb)
                with opener.open(request, timeout=mode_timeout) as response:
                    return response.read()
            except Exception as exc:  # noqa: BLE001 - normalised for every caller
                last_error = exc
                if attempt < mode_retries:
                    time.sleep(1.5 * (attempt + 1))
                elif index < len(modes) - 1 and _worth_a_direct_retry(exc, mode):
                    log.warning("%s 经代理不可用（%s），改用直连再试一次", url, getattr(exc, "code", None) or exc)
    detail = getattr(last_error, "reason", None) or last_error
    if proxy is None and _worth_a_direct_retry(last_error, None):
        detail = f"{detail}{PROXY_HINT}"
    raise HttpError(f"{verb} {url} failed: {detail}") from last_error


def fetch_text(url: str, **kwargs: Any) -> str:
    raw = fetch_bytes(url, **kwargs)
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_json(url: str, **kwargs: Any) -> dict:
    raw = fetch_bytes(url, **kwargs)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise HttpError(f"{url} returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HttpError(f"{url} returned {type(parsed).__name__}, expected a JSON object")
    return parsed
