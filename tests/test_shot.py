"""长图导出：引擎探测 + 真渲染（没装引擎就跳过渲染断言）。"""

from __future__ import annotations

from evenews.cli import build_parser
from evenews.shot import DATE_DIR, MAX_SCALE, engine_status, latest_html


def test_shot_subcommand_registered():
    parser = build_parser()
    args = parser.parse_args(["shot", "--date", "2026-09-29", "--scale", "3"])
    assert args.command == "shot"
    assert args.date == "2026-09-29"
    assert args.scale == 3 and args.width == 720


def test_latest_html_picks_newest_dated_folder(tmp_path):
    (tmp_path / "2026-09-01").mkdir()
    (tmp_path / "2026-09-01" / "digest.html").write_text("x", encoding="utf-8")
    (tmp_path / "2026-09-30").mkdir()
    assert latest_html(tmp_path).name == "digest.html"
    assert latest_html(tmp_path).parent.name == "2026-09-01"  # 只有它真有 digest.html
    assert DATE_DIR.match("2026-09-30")


def test_engine_status_shape():
    ok, why = engine_status()
    assert isinstance(ok, bool)
    assert bool(why) != ok, "可用时不带原因，不可用时必须说明缺什么"


def test_render_png_at_requested_dpi(tmp_path):
    ok, why = engine_status()
    if not ok:
        import pytest
        pytest.skip(f"长图引擎未安装：{why}")
    from evenews.shot import render_png

    page = tmp_path / "digest.html"
    page.write_text(
        "<html><body style='margin:0;background:#fffdf8'>"
        "<p style='font:44px serif;padding:20px'>高质量长图测试 High Quality</p>"
        "<p style='height:2600px'>整页高度</p></body></html>",
        encoding="utf-8",
    )
    out = render_png(page, tmp_path / "shot.png", width=720, scale=2)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "必须产出真 PNG"
    width = int.from_bytes(data[16:20], "big")
    assert width == 720 * 2, "2× DPI 应该是 1440 像素宽"
    assert out.stat().st_size > 10_000
