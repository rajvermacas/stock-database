from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

PRICE_COLUMNS = [
    "symbol",
    "trade_timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
]
INDICATOR_KEY_COLUMNS = ["symbol", "trade_timestamp"]
FIXED_PATTERN = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>m|h|d)$")
CALENDAR_INTERVALS = {"1wk": "1w", "1mo": "1mo", "3mo": "1q", "1y": "1y"}


class StockFrameError(ValueError):
    """Raised when local stock data cannot satisfy a query."""


@dataclass(frozen=True)
class Resolution:
    requested_interval: str
    source_interval: str
    derived: bool


def discover_intervals(prices_root: Path) -> list[str]:
    if not prices_root.is_dir():
        raise StockFrameError(f"Price root does not exist: {prices_root}")
    intervals = sorted(
        path.name for path in prices_root.iterdir() if any(path.glob("*.parquet"))
    )
    if not intervals:
        raise StockFrameError(f"No Parquet price data found under: {prices_root}")
    return intervals


def load_prices(
    requested_interval: str,
    prices_root: str | Path,
    symbols: list[str] | None,
    start: datetime | None,
    end: datetime | None,
) -> tuple[pl.LazyFrame, Resolution]:
    root = Path(prices_root)
    resolution = resolve_interval(requested_interval, root)
    source = _scan_source(resolution.source_interval, root, symbols, start, end)
    if not resolution.derived:
        return source, resolution
    return _resample(source, requested_interval), resolution


def load_indicators(
    interval: str,
    indicators_root: str | Path,
    symbols: list[str] | None,
    start: datetime | None,
    end: datetime | None,
) -> pl.LazyFrame:
    root = Path(indicators_root)
    interval_dir = root / interval
    if not interval_dir.is_dir() or not any(interval_dir.glob("*.parquet")):
        raise StockFrameError(f"No indicators found for exact interval: {interval}")
    frame = pl.scan_parquet(interval_dir / "*.parquet")
    return _apply_filters(frame, symbols, start, end)


def load_prices_with_indicators(
    interval: str,
    prices_root: str | Path,
    indicators_root: str | Path,
    symbols: list[str] | None,
    start: datetime | None,
    end: datetime | None,
) -> pl.LazyFrame:
    resolution = resolve_interval(interval, Path(prices_root))
    if resolution.derived:
        raise StockFrameError(
            f"Cannot join precalculated indicators to derived interval: {interval}"
        )
    prices, _ = load_prices(interval, prices_root, symbols, start, end)
    indicators = load_indicators(interval, indicators_root, symbols, start, end)
    return prices.join(indicators, on=INDICATOR_KEY_COLUMNS, how="inner").sort(
        INDICATOR_KEY_COLUMNS
    )


def resolve_interval(requested_interval: str, prices_root: Path) -> Resolution:
    available = discover_intervals(prices_root)
    if requested_interval in available:
        return Resolution(requested_interval, requested_interval, False)
    candidates = _compatible_sources(requested_interval, available)
    if not candidates:
        message = (
            f"Cannot derive interval {requested_interval!r} from stored intervals: "
            f"{', '.join(available)}"
        )
        raise StockFrameError(message)
    source = max(candidates, key=lambda value: _interval_minutes(value))
    return Resolution(requested_interval, source, True)


def _scan_source(
    interval: str,
    prices_root: Path,
    symbols: list[str] | None,
    start: datetime | None,
    end: datetime | None,
) -> pl.LazyFrame:
    pattern = prices_root / interval / "*.parquet"
    frame = pl.scan_parquet(pattern).select(PRICE_COLUMNS)
    return _apply_filters(frame, symbols, start, end)


def _apply_filters(
    frame: pl.LazyFrame,
    symbols: list[str] | None,
    start: datetime | None,
    end: datetime | None,
) -> pl.LazyFrame:
    if symbols is not None:
        if not symbols:
            raise StockFrameError("Symbol filter must not be empty")
        frame = frame.filter(pl.col("symbol").is_in(symbols))
    if start is not None:
        frame = frame.filter(pl.col("trade_timestamp") >= start)
    if end is not None:
        frame = frame.filter(pl.col("trade_timestamp") <= end)
    return frame.sort(["symbol", "trade_timestamp"])


def _compatible_sources(requested: str, available: list[str]) -> list[str]:
    if requested in CALENDAR_INTERVALS:
        return [value for value in available if _is_daily_or_finer(value)]
    requested_minutes = _interval_minutes(requested)
    return [
        value
        for value in available
        if _is_fixed(value)
        and _interval_minutes(value) <= requested_minutes
        and requested_minutes % _interval_minutes(value) == 0
    ]


def _resample(frame: pl.LazyFrame, requested: str) -> pl.LazyFrame:
    if requested in CALENDAR_INTERVALS:
        return _aggregate_dynamic(frame, CALENDAR_INTERVALS[requested], "window")
    every = _polars_duration(requested)
    start_by = "datapoint" if _interval_minutes(requested) < 1440 else "window"
    return _aggregate_dynamic(frame, every, start_by)


def _aggregate_dynamic(frame: pl.LazyFrame, every: str, start_by: str) -> pl.LazyFrame:
    return (
        frame.group_by_dynamic(
            "trade_timestamp",
            every=every,
            group_by="symbol",
            start_by=start_by,
        )
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
        )
        .sort(["symbol", "trade_timestamp"])
    )


def _interval_minutes(interval: str) -> int:
    match = FIXED_PATTERN.fullmatch(interval)
    if match is None:
        raise StockFrameError(f"Unsupported or ambiguous interval: {interval!r}")
    count = int(match.group("count"))
    multipliers = {"m": 1, "h": 60, "d": 1440}
    return count * multipliers[match.group("unit")]


def _is_fixed(interval: str) -> bool:
    return FIXED_PATTERN.fullmatch(interval) is not None


def _is_daily_or_finer(interval: str) -> bool:
    return _is_fixed(interval) and _interval_minutes(interval) <= 1440


def _polars_duration(interval: str) -> str:
    minutes = _interval_minutes(interval)
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"
