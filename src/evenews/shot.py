"""长图导出：把 digest.html 渲染成高质量 PNG（真浏览器内核 + 高 DPI）。

    evenews shot                      # 最新一期 → out/<日期>/digest.png
    evenews shot --date 2026-09-29 --scale 3

依赖可选安装包：pip install "eve-news[shot]" 之后
playwright install chromium 下载浏览器内核；缺了会在报错里教你装。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("evenews.shot")

DATE_DIR = re.compile(r"\d{4}-\d{2}-\d{2}$")
MIN_SCALE, MAX_SCALE = 1, 4


def latest_html(out_root: Path) -> Path | None:
    """out/ 里最近一天的 digest.html。兼容两种落盘：嵌套的 out/<日期>/digest.html，
    和显式 --out 时的平铺 out/digest.html（pipeline 用 out_root 时不分日期目录）。"""
    root = Path(out_root)
    if not root.is_dir():
        return None
    flat = root / "digest.html"
    if flat.is_file():
        return flat
    folders = [item for item in root.iterdir() if item.is_dir()]
    days = sorted([item for item in folders if DATE_DIR.match(item.name)], reverse=True)
    candidates = [item / "digest.html" for item in (days or sorted(folders, reverse=True))]
    return next((c for c in candidates if c.is_file()), None)


def engine_status() -> tuple[bool, str]:
    """Playwright + Chromium 是否可用；返回 (可用?, 缺什么)。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "缺少 playwright：pip install \"eve-news[shot]\""
    try:
        with sync_playwright() as p:
            executable = p.chromium.executable_path
    except Exception as exc:  # noqa: BLE001
        return False, f"Chromium 内核未就绪：跑 .venv/bin/playwright install chromium（{exc}）"
    if not executable or not Path(executable).is_file():
        return False, "Chromium 内核未就绪：跑 .venv/bin/playwright install chromium"
    return True, ""


def render_png(html_file: Path, out_png: Path, *, width: int = 720, scale: int = 2) -> Path:
    """整页长图：宽度按 email 版式，scale 是 DPI 倍数（2 起步才叫高质量）。"""
    scale = max(MIN_SCALE, min(MAX_SCALE, int(scale)))
    ok, why = engine_status()
    if not ok:
        raise RuntimeError(f"长图渲染引擎不可用：{why}")
    from playwright.sync_api import sync_playwright

    html_file = Path(html_file).resolve()
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])
        try:
            page = browser.new_page(viewport={"width": int(width), "height": 1024}, device_scale_factor=scale)
            page.goto(html_file.as_uri())
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(out_png), full_page=True)
        finally:
            browser.close()
    size_mb = out_png.stat().st_size / 1_048_576
    log.info("长图已生成：%s（%.1f MB）", out_png, size_mb)
    return out_png
