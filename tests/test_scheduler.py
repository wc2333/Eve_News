from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from evenews.scheduler import (
    cron_line,
    next_fire,
    systemd_service,
    systemd_timer,
    windows_task_command,
    windows_wrapper,
)

TZ = ZoneInfo("Asia/Shanghai")


def make(tmp_path, weekday_only: bool = False):
    from evenews.config import Config

    config = Config.from_dict({}, tmp_path / "config.yaml")
    config.schedule.time = "08:00"
    config.schedule.weekday_only = weekday_only
    config.path = tmp_path / "config.yaml"
    return config


def test_next_fire_is_tomorrow_when_time_passed():
    now = datetime(2026, 9, 25, 9, 0, tzinfo=TZ)
    assert next_fire(now, time_of_day="08:00", timezone="Asia/Shanghai") == datetime(2026, 9, 26, 8, 0, tzinfo=TZ)


def test_next_fire_same_day_when_time_pending():
    now = datetime(2026, 9, 25, 6, 0, tzinfo=TZ)
    assert next_fire(now, time_of_day="08:00", timezone="Asia/Shanghai") == datetime(2026, 9, 25, 8, 0, tzinfo=TZ)


def test_weekday_only_skips_weekend():
    friday_evening = datetime(2026, 9, 25, 23, 0, tzinfo=TZ)  # 2026-09-25 is a Friday
    fired = next_fire(friday_evening, time_of_day="08:00", timezone="Asia/Shanghai", weekday_only=True)
    assert fired.weekday() == 0 and fired.date().isoformat() == "2026-09-28"


def test_bad_time_raises():
    import pytest

    from evenews.scheduler import next_fire as nf

    with pytest.raises(ValueError):
        nf(datetime(2026, 9, 25, tzinfo=TZ), time_of_day="8am")


def test_installers_render_paths(tmp_path):
    config = make(tmp_path)
    command = windows_task_command(config)
    wrapper = windows_wrapper(config)
    assert "run_daily.cmd" in command and wrapper.is_file()
    assert "-m evenews run" in wrapper.read_text(encoding="gbk")
    assert "0 8 * * *" in cron_line(config)
    assert "-m evenews daemon" in systemd_service(config)
    assert "OnCalendar=*-*-* 08:00:00" in systemd_timer(config)


def test_weekday_cron_and_calendar(tmp_path):
    config = make(tmp_path, weekday_only=True)
    assert "0 8 * * 1-5" in cron_line(config)
    assert "Mon-Fri" in systemd_timer(config)
