from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class UnsupportedIntervalError(ValueError):
    """Raised when an interval is not native to Yahoo."""


class IntervalCategory(StrEnum):
    INTRADAY = "intraday"
    DAILY = "daily"
    MULTI_DAY = "multi_day"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


@dataclass(frozen=True)
class IntervalSpec:
    name: str
    category: IntervalCategory
    duration: timedelta | None

    def is_complete(self, candle_start: datetime, now: datetime) -> bool:
        candle, current = _as_ist(candle_start), _as_ist(now)
        if self.category in {IntervalCategory.INTRADAY, IntervalCategory.MULTI_DAY}:
            assert self.duration is not None
            return candle + self.duration <= current
        if self.category == IntervalCategory.DAILY:
            return candle.date() < current.date() or (
                candle.date() == current.date() and current.time() >= time(16, 0)
            )
        if self.category == IntervalCategory.WEEKLY:
            return candle.date().isocalendar()[:2] != current.date().isocalendar()[:2]
        if self.category == IntervalCategory.MONTHLY:
            return (candle.year, candle.month) != (current.year, current.month)
        return _quarter(candle) != _quarter(current)

    def next_request_start(self, latest: datetime) -> datetime:
        if self.duration is not None:
            return latest + self.duration
        return latest + timedelta(days=1)


def _as_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(IST)


def _quarter(value: datetime) -> tuple[int, int]:
    return value.year, ((value.month - 1) // 3) + 1


def _spec(
    name: str, category: IntervalCategory, minutes: int | None = None
) -> IntervalSpec:
    duration = None if minutes is None else timedelta(minutes=minutes)
    return IntervalSpec(name, category, duration)


INTERVALS = {
    name: _spec(name, IntervalCategory.INTRADAY, minutes)
    for name, minutes in {
        "1m": 1,
        "2m": 2,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "90m": 90,
        "1h": 60,
    }.items()
}
INTERVALS.update(
    {
        "1d": _spec("1d", IntervalCategory.DAILY, 1440),
        "5d": _spec("5d", IntervalCategory.MULTI_DAY, 7200),
        "1wk": _spec("1wk", IntervalCategory.WEEKLY),
        "1mo": _spec("1mo", IntervalCategory.MONTHLY),
        "3mo": _spec("3mo", IntervalCategory.QUARTERLY),
    }
)


def get_interval(name: str) -> IntervalSpec:
    try:
        return INTERVALS[name]
    except KeyError as exc:
        raise UnsupportedIntervalError(f"Unsupported Yahoo interval: {name}") from exc
