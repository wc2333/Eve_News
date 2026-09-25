from __future__ import annotations

import io
import sys

import pytest

from evenews.cli import _configure_console, main
from evenews.config import default_config_text


def test_console_output_survives_a_narrow_codepage():
    """Windows CI runs on cp1252; printing Chinese must not raise."""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sys, "stdout", stream)
        _configure_console()
        print("已生成 config.yaml · 板块 6 个")
        sys.stdout.flush()
    assert buffer.getvalue().decode("utf-8").startswith("已生成")


def test_preview_command_writes_a_digest_off_disk(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(default_config_text(), encoding="utf-8")
    out_dir = tmp_path / "artifacts"
    code = main(["-c", str(config_path), "preview", "--offline", "--out", str(out_dir)])
    assert code == 0
    produced = sorted(out_dir.glob("digest.*"))
    assert {path.suffix for path in produced} == {".html", ".md", ".txt", ".json"}


def test_unknown_section_fails_cleanly(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(default_config_text(), encoding="utf-8")
    assert main(["-c", str(config_path), "disable", "does_not_exist"]) == 2
