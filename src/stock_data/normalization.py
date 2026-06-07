from __future__ import annotations

from datetime import date

import pandas as pd
import polars as pl

CANONICAL_COLUMNS = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]
CANONICAL_SCHEMA = {
    "symbol": pl.String,
    "trade_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}
YAHOO_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


class NormalizationError(ValueError):
    """Raised when Yahoo data cannot be converted to the canonical schema."""


def split_batch_frame(frame: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
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


def normalize_symbol(symbol: str, frame: pd.DataFrame, cutoff: date) -> pl.DataFrame:
    try:
        normalized = _prepare_pandas(frame)
        result = pl.from_pandas(normalized).select(
            pl.lit(symbol).alias("symbol"),
            pl.col("trade_date").cast(pl.Date),
            pl.col("Open").cast(pl.Float64).alias("open"),
            pl.col("High").cast(pl.Float64).alias("high"),
            pl.col("Low").cast(pl.Float64).alias("low"),
            pl.col("Close").cast(pl.Float64).alias("close"),
            pl.col("Volume").cast(pl.Int64).alias("volume"),
        )
        result = result.filter(pl.col("trade_date") <= cutoff)
        result = result.unique(["symbol", "trade_date"], keep="last").sort("trade_date")
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
    index_name = frame.index.name or "Date"
    prepared = frame.reset_index().rename(columns={index_name: "trade_date"})
    if "trade_date" not in prepared:
        prepared = prepared.rename(columns={prepared.columns[0]: "trade_date"})
    return prepared


def _validate_result(frame: pl.DataFrame) -> None:
    if frame.is_empty():
        raise ValueError("no completed rows")
    if frame.null_count().select(pl.sum_horizontal(pl.all())).item() > 0:
        raise ValueError("required values contain nulls")
    if frame.schema != CANONICAL_SCHEMA:
        raise ValueError(f"unexpected schema: {frame.schema}")
