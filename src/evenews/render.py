"""Render the digest into email-safe HTML, Markdown and plain text."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .config import DATA_DIR, Brand
from .models import Digest, domain_of

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
LOGO_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}
MAX_LOGO_BYTES = 180_000

log = logging.getLogger("evenews.render")


# One place for every colour the email uses so a theme swap never leaves a light
# card floating on a dark page. Non-empty brand fields override the preset.
PALETTES = {
    "light": {
        "background": "#f5f3ee", "card": "#fffdf8", "plate": "#fffdf8", "plate_line": "#e7e1d6",
        "line": "#d9d4c9", "ink": "#1f2328", "body": "#24282f", "muted": "#71767e",
        "faint": "#a2a6ac", "number": "#bdb6a7", "lead_bg": "#efeadf", "lead_ink": "#1f2328",
        "accent": "#007492", "label": "#0092b5", "warn_bg": "#fcecea", "warn_line": "#e9b7b1",
        "warn_ink": "#8a2415", "fail_ink": "#b5716c",
    },
    "dark": {
        "background": "#060b14", "card": "#0a1226", "plate": "#f4f8fc", "plate_line": "#1d293d",
        "line": "#1d293d", "ink": "#f4f8fd", "body": "#dce6f3", "muted": "#93a6be",
        "faint": "#6d8098", "number": "#4c688a", "lead_bg": "#0d1526", "lead_ink": "#eef4fb",
        "accent": "#00a5ef", "label": "#43bdf0", "warn_bg": "#22151a", "warn_line": "#6f3833",
        "warn_ink": "#f2b8b1", "fail_ink": "#e79a92",
    },
}


def palette(brand: Brand) -> dict[str, str]:
    """The colour set the template paints with."""
    theme = str(brand.theme or "light").strip().lower()
    colors = dict(PALETTES.get(theme, PALETTES["light"]))
    overrides = {
        "background": brand.background,
        "card": brand.card,
        "ink": brand.text,
        "body": brand.body,
        "muted": brand.muted,
        "accent": brand.accent,
        "label": brand.label,
    }
    for key, value in overrides.items():
        if str(value or "").strip():
            colors[key] = str(value).strip()
    colors["theme"] = theme if theme in PALETTES else "light"
    return colors




def resolve_logo(brand: Brand, theme: str = "") -> tuple[bytes, str]:
    """The masthead mark: a path in the config, or a file shipped in evenews/data.

    A dark brief prefers a `<name>-dark.png` sibling: a mark cut out of a white square looks
    pasted onto #060b14, so the shipped marks carry a light-tinted twin next to the original.
    """
    name = str(brand.logo_file or "").strip()
    if not name:
        return b"", ""
    base = Path(name)
    wanted = [base.name]
    if str(theme or "").strip().lower() == "dark":
        wanted = [f"{base.stem}-dark{ext}" for ext in (".png", ".jpg", ".jpeg")] + wanted
    mime = ""
    for candidate_name in wanted:
        for candidate in (base.with_name(candidate_name), DATA_DIR / candidate_name):
            try:
                if not candidate.is_file():
                    continue
                raw = candidate.read_bytes()
            except OSError:
                continue
            mime = LOGO_MIME.get(candidate.suffix.lower(), "application/octet-stream")
            if len(raw) > MAX_LOGO_BYTES:
                log.warning("logo %s 有 %s 字节，超过 %s，邮件里就不放图了", candidate, len(raw), MAX_LOGO_BYTES)
                return b"", ""
            return raw, mime
    if name:
        log.warning("找不到品牌图标 %s，报头退回文字", name)
    return b"", ""


def logo_data_uri(brand: Brand, theme: str = "") -> str:
    raw, mime = resolve_logo(brand, theme)
    if not raw:
        return ""
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=lambda name: bool(name) and name.startswith("digest.html"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _date_label(iso_date: str) -> str:
    try:
        return datetime.fromisoformat(iso_date).strftime("%Y-%m-%d")
    except ValueError:
        return iso_date


def build_context(digest: Digest, brand: Brand) -> dict[str, Any]:
    """Empty sections are left out entirely: a blank page in a brief reads like a mistake."""
    groups = []
    filled = [section_digest for section_digest in digest.sections if section_digest.items]
    for index, section_digest in enumerate(filled, start=1):
        items = [
            {
                "number": f"{number:02d}",
                "title": article.title,
                "url": article.url,
                "source": article.source,
                "domain": article.domain,
                "published": article.published,
                "summary": article.summary or article.raw_summary[:340],
                "why": article.why,
                "score_label": f"{article.score:.1f}" if article.score else "",
            }
            for number, article in enumerate(section_digest.items, start=1)
        ]
        groups.append({"index": index, "section": section_digest.section, "entries": items})

    shown: dict[str, object] = {}
    for section_digest in filled:
        for source in section_digest.section.sources:
            shown[f"{source.name}|{source.url}"] = source
    sources = [
        {"name": source.name, "url": source.url, "domain": domain_of(source.url)}
        for source in sorted(shown.values(), key=lambda item: item.name)
    ]
    source_rows = [sources[i : i + 2] for i in range(0, len(sources), 2)]
    source_rows = [row + [None] * (2 - len(row)) for row in source_rows]

    colors = palette(brand)
    return {
        "digest": digest,
        "brand": brand,
        "logo": logo_data_uri(brand, colors["theme"]),
        "c": colors,
        "groups": groups,
        "sources": sources,
        "source_rows": source_rows,
        "date_cn": _date_label(digest.run_date),
    }


def render_html(digest: Digest, brand: Brand) -> str:
    return _environment().get_template("digest.html.j2").render(**build_context(digest, brand))


def render_markdown(digest: Digest, brand: Brand) -> str:
    return _environment().get_template("digest.md.j2").render(**build_context(digest, brand))


def render_text(digest: Digest, brand: Brand) -> str:
    return _environment().get_template("digest.txt.j2").render(**build_context(digest, brand))


def subject_for(digest: Digest, brand: Brand, template: str, prefix: str = "") -> str:
    subject = template.format(title=brand.title, date=_date_label(digest.run_date), count=digest.item_count)
    return f"{prefix}{subject}".strip()


def write_outputs(digest: Digest, brand: Brand, out_dir: Path) -> dict[str, Path]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written = {
        "html": target / "digest.html",
        "markdown": target / "digest.md",
        "text": target / "digest.txt",
        "json": target / "digest.json",
    }
    written["html"].write_text(render_html(digest, brand), encoding="utf-8")
    written["markdown"].write_text(render_markdown(digest, brand), encoding="utf-8")
    written["text"].write_text(render_text(digest, brand), encoding="utf-8")
    written["json"].write_text(json.dumps(digest.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written
