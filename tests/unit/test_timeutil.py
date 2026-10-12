from datetime import UTC, date, datetime, timedelta, timezone

from aipulse.core.timeutil import (
    age_hours,
    day_window,
    ensure_utc,
    format_local,
    last_hours,
    now_local,
    parse_duration,
    to_local,
    today_local,
    utcnow,
    window_since,
)


def test_utcnow_is_timezone_aware():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_to_local_shifts_to_shanghai():
    dt = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)
    assert to_local(dt).hour == 0  # UTC+8
    assert to_local(dt).date() == date(2026, 10, 13)


def test_ensure_utc_treats_naive_as_utc():
    naive = datetime(2026, 10, 12, 16, 0)
    assert ensure_utc(naive).tzinfo == UTC
    aware = datetime(2026, 10, 12, 16, 0, tzinfo=timezone(timedelta(hours=8)))
    assert ensure_utc(aware).hour == 8


def test_parse_duration_units():
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("24h") == timedelta(hours=24)
    assert parse_duration("7d") == timedelta(days=7)
    assert parse_duration("2w") == timedelta(weeks=2)
    assert parse_duration("90s") == timedelta(seconds=90)
    assert parse_duration(timedelta(hours=1)) == timedelta(hours=1)


def test_parse_duration_invalid():
    import pytest

    with pytest.raises(ValueError):
        parse_duration("abc")


def test_window_since_and_last_hours():
    until = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    start, end = window_since("24h", until=until)
    assert (end - start) == timedelta(hours=24)
    assert end == until
    start2, end2 = last_hours(6, until=until)
    assert (end2 - start2) == timedelta(hours=6)


def test_day_window_uses_local_midnight():
    # 北京 10-13 的 00:00 = UTC 10-12 16:00（直接按 UTC 切日会错 8 小时）
    start, end = day_window(date(2026, 10, 13))
    assert start == datetime(2026, 10, 12, 16, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 13, 16, 0, tzinfo=UTC)


def test_age_hours_and_local_helpers():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    assert age_hours(datetime(2026, 10, 12, 6, 0, tzinfo=UTC), now=now) == 6.0
    assert age_hours(datetime(2026, 10, 13, 0, 0, tzinfo=UTC), now=now) == 0.0
    assert isinstance(now_local(), datetime)
    assert isinstance(today_local(), date)
    assert format_local(now) == "2026-10-12 20:00:00"
