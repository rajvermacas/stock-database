from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

from stock_data.normalization import CANONICAL_SCHEMA
from stock_data.pullback.errors import PullbackDataError
from stock_data.pullback.models import QualityIssue, QualityResult

PRICE_COLUMNS = ("open", "high", "low", "close")


def resolve_common_as_of(latest_by_symbol: dict[str, datetime]) -> datetime:
    if not latest_by_symbol:
        raise PullbackDataError("cannot resolve common as-of from no symbols")
    counts = Counter(latest_by_symbol.values())
    highest = max(counts.values())
    modes = [timestamp for timestamp, count in counts.items() if count == highest]
    if len(modes) != 1:
        raise PullbackDataError("unable to establish unique common as-of timestamp")
    return modes[0]


def validate_prices(frame: pl.DataFrame, common_as_of: datetime) -> QualityResult:
    symbol = _single_symbol(frame)
    issues = _structural_issues(symbol, frame, common_as_of)
    timestamps = frame["trade_timestamp"]
    return QualityResult(
        symbol=symbol,
        rows=frame.height,
        first_timestamp=timestamps.min(),
        last_timestamp=timestamps.max(),
        cadence_seconds=_median_cadence_seconds(timestamps),
        issues=tuple(issues),
    )


def validate_universe(prices_root: Path, interval: str) -> tuple[QualityResult, ...]:
    paths = sorted((prices_root / interval).glob("*.parquet"))
    if not paths:
        raise PullbackDataError(f"no parquet files for interval {interval}")
    summaries = _collect_universe_summaries(paths)
    latest = dict(zip(summaries["symbol"], summaries["last"], strict=True))
    common_as_of = resolve_common_as_of(latest)
    return tuple(validate_prices(pl.read_parquet(path), common_as_of) for path in paths)


def _collect_universe_summaries(paths: list[Path]) -> pl.DataFrame:
    return (
        pl.scan_parquet(paths)
        .group_by("symbol")
        .agg(
            pl.col("trade_timestamp").max().alias("last"),
            pl.len().alias("rows"),
        )
        .collect(engine="streaming")
    )


def _single_symbol(frame: pl.DataFrame) -> str:
    if frame.is_empty():
        raise PullbackDataError("price data is empty")
    if "symbol" not in frame.columns:
        raise PullbackDataError("price data has no symbol column")
    symbols = frame["symbol"].unique().to_list()
    if len(symbols) != 1:
        raise PullbackDataError("price data must contain exactly one symbol")
    return symbols[0]


def _structural_issues(
    symbol: str, frame: pl.DataFrame, common_as_of: datetime
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    _append(issues, symbol, "schema", frame.schema != CANONICAL_SCHEMA)
    _append(issues, symbol, "null_value", _has_nulls(frame))
    _append(issues, symbol, "duplicate_timestamp", _has_duplicates(frame))
    _append(issues, symbol, "unordered_timestamp", not _is_sorted(frame))
    _append(issues, symbol, "non_finite_price", _has_non_finite_prices(frame))
    _append(issues, symbol, "invalid_ohlc", _has_invalid_ohlc(frame))
    _append(issues, symbol, "stale", frame["trade_timestamp"].max() != common_as_of)
    return issues


def _append(
    issues: list[QualityIssue], symbol: str, code: str, condition: bool
) -> None:
    if condition:
        issues.append(QualityIssue(symbol, code, f"{symbol}: {code.replace('_', ' ')}"))


def _has_nulls(frame: pl.DataFrame) -> bool:
    return frame.null_count().select(pl.sum_horizontal(pl.all())).item() > 0


def _has_duplicates(frame: pl.DataFrame) -> bool:
    return frame["trade_timestamp"].n_unique() != frame.height


def _is_sorted(frame: pl.DataFrame) -> bool:
    return frame["trade_timestamp"].is_sorted()


def _has_non_finite_prices(frame: pl.DataFrame) -> bool:
    if any(column not in frame.columns for column in PRICE_COLUMNS):
        return True
    return not np.isfinite(frame.select(PRICE_COLUMNS).to_numpy()).all()


def _has_invalid_ohlc(frame: pl.DataFrame) -> bool:
    if any(column not in frame.columns for column in PRICE_COLUMNS):
        return True
    invalid = frame.select(
        (
            (pl.col("high") < pl.col("low"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
        ).any()
    ).item()
    return bool(invalid)


def _median_cadence_seconds(timestamps: pl.Series) -> float | None:
    if len(timestamps) < 2:
        return None
    diffs = timestamps.sort().diff().drop_nulls().dt.total_seconds()
    return float(diffs.median())
