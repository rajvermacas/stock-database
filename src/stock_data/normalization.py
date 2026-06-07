from __future__ import annotations

from datetime import datetime

import pandas as pd
import polars as pl

from stock_data.intervals import IST, IntervalSpec

CANONICAL_COLUMNS = [
    "symbol",
    "trade_timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
]
CANONICAL_SCHEMA = {
    "symbol": pl.String,
    "trade_timestamp": pl.Datetime(time_unit="us", time_zone="Asia/Kolkata"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}
YAHOO_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


class NormalizationError(ValueError):
    """Raised when Yahoo data cannot be converted to the canonical schema."""


def split_batch_frame(
    frame: pd.DataFrame, symbols: list[str]
) -> dict[str, pd.DataFrame]:
    if frame.empty:
        return {}
    if not isinstance(frame.columns, pd.MultiIndex):
        return {symbols[0]: frame} if len(symbols) == 1 else {}
    output: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        for level in range(frame.columns.nlevels):
            if symbol in frame.columns.get_level_values(level):
                output[symbol] = frame.xs(symbol, axis=1, level=level, drop_level=True)
                break
    return output


def normalize_symbol(
    symbol: str, frame: pd.DataFrame, interval: IntervalSpec, now: datetime
) -> pl.DataFrame:
    try:
        prepared = _prepare_pandas(frame)
        timestamps = _timestamps_to_ist(prepared["trade_timestamp"])
        result = pl.DataFrame(
            {
                "symbol": [symbol] * len(prepared),
                "trade_timestamp": timestamps,
                "open": prepared["Open"].to_list(),
                "high": prepared["High"].to_list(),
                "low": prepared["Low"].to_list(),
                "close": prepared["Close"].to_list(),
                "volume": prepared["Volume"].to_list(),
            },
            schema=CANONICAL_SCHEMA,
            strict=True,
        )
        complete = [interval.is_complete(value, now) for value in timestamps]
        result = result.filter(pl.Series(complete))
        result = result.unique(["symbol", "trade_timestamp"], keep="last").sort(
            "trade_timestamp"
        )
        _validate_result(result)
        return result
    except (KeyError, TypeError, ValueError, pl.exceptions.PolarsError) as exc:
        raise NormalizationError(f"Invalid Yahoo data for {symbol}: {exc}") from exc


def _prepare_pandas(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("response is empty")
    missing = YAHOO_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    prepared = frame.reset_index()
    return prepared.rename(columns={prepared.columns[0]: "trade_timestamp"})


def _timestamps_to_ist(values: pd.Series) -> list[datetime]:
    index = pd.DatetimeIndex(pd.to_datetime(values))
    localized = index.tz_localize(IST) if index.tz is None else index.tz_convert(IST)
    return localized.to_pydatetime().tolist()


def _validate_result(frame: pl.DataFrame) -> None:
    if frame.is_empty():
        raise ValueError("no completed rows")
    if frame.null_count().select(pl.sum_horizontal(pl.all())).item() > 0:
        raise ValueError("required values contain nulls")
    if frame.schema != CANONICAL_SCHEMA:
        raise ValueError(f"unexpected schema: {frame.schema}")
