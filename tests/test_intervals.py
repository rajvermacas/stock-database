from datetime import datetime, timedelta

import pytest

from stock_data.intervals import IST, INTERVALS, UnsupportedIntervalError, get_interval

ALL_INTERVALS = {
    "1m",
    "2m",
    "5m",
    "15m",
    "30m",
    "60m",
    "90m",
    "1h",
    "1d",
    "5d",
    "1wk",
    "1mo",
    "3mo",
}


def test_registry_supports_all_native_intervals() -> None:
    assert set(INTERVALS) == ALL_INTERVALS
    assert get_interval("1h").duration == timedelta(hours=1)
    assert get_interval("60m").duration == timedelta(hours=1)


def test_intraday_excludes_active_candle() -> None:
    interval = get_interval("30m")
    now = datetime(2026, 6, 8, 10, 47, tzinfo=IST)
    assert interval.is_complete(datetime(2026, 6, 8, 10, 0, tzinfo=IST), now)
    assert not interval.is_complete(datetime(2026, 6, 8, 10, 30, tzinfo=IST), now)


def test_daily_uses_four_pm_cutoff() -> None:
    candle = datetime(2026, 6, 8, tzinfo=IST)
    assert not get_interval("1d").is_complete(
        candle, datetime(2026, 6, 8, 15, 59, tzinfo=IST)
    )
    assert get_interval("1d").is_complete(
        candle, datetime(2026, 6, 8, 16, 0, tzinfo=IST)
    )


@pytest.mark.parametrize("name", ["5d", "1wk", "1mo", "3mo"])
def test_longer_intervals_exclude_current_period(name: str) -> None:
    now = datetime(2026, 6, 8, 16, 0, tzinfo=IST)
    assert not get_interval(name).is_complete(now, now)


def test_invalid_interval_fails() -> None:
    with pytest.raises(UnsupportedIntervalError, match="2h"):
        get_interval("2h")
