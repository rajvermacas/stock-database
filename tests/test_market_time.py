from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from stock_data.market_time import latest_completed_date


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(15, date(2026, 6, 6)), (16, date(2026, 6, 7))],
)
def test_latest_completed_date_uses_four_pm_ist(hour: int, expected: date) -> None:
    now = datetime(2026, 6, 7, hour, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert latest_completed_date(now) == expected


def test_latest_completed_date_converts_timezone() -> None:
    now = datetime(2026, 6, 7, 10, 31, tzinfo=timezone.utc)
    assert latest_completed_date(now) == date(2026, 6, 7)


def test_latest_completed_date_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        latest_completed_date(datetime(2026, 6, 7, 16))
