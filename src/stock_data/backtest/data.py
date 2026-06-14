from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.backtest.errors import DataWindowError

LOGGER = logging.getLogger(__name__)

PRICE_COLS = ["trade_timestamp", "open", "high", "low", "close", "volume"]


def load_symbol_frame(
    prices_dir: Path, indicators_dir: Path, symbol: str
) -> pl.DataFrame:
    """Inner-join price OHLCV onto the indicator frame for one symbol."""
    ind_path = indicators_dir / "1d" / f"{symbol}.parquet"
    price_path = prices_dir / "1d" / f"{symbol}.parquet"
    if not ind_path.exists() or not price_path.exists():
        raise DataWindowError(f"Missing parquet for {symbol}")
    indicators = pl.read_parquet(ind_path)
    prices = pl.read_parquet(price_path).select(PRICE_COLS)
    frame = indicators.join(prices, on="trade_timestamp", how="inner").sort(
        "trade_timestamp"
    )
    if frame.height == 0:
        raise DataWindowError(f"Empty joined frame for {symbol}")
    return add_weekly_uptrend(frame)


def add_weekly_uptrend(frame: pl.DataFrame) -> pl.DataFrame:
    """Add look-ahead-safe `weekly_uptrend` (previous completed week)."""
    weekly = (
        frame.sort("trade_timestamp")
        .group_by_dynamic("trade_timestamp", every="1w", label="left")
        .agg(pl.col("close").last().alias("w_close"))
        .sort("trade_timestamp")
    )
    weekly = weekly.with_columns(
        pl.col("w_close").ewm_mean(span=30, adjust=False).alias("w_ema30")
    )
    weekly = weekly.with_columns(
        (
            (pl.col("w_close") > pl.col("w_ema30"))
            & (pl.col("w_ema30") > pl.col("w_ema30").shift(1))
        )
        .shift(1)                       # use PREVIOUS completed week -> no look-ahead
        .fill_null(False)
        .alias("weekly_uptrend")
    ).select(["trade_timestamp", "weekly_uptrend"])
    # Map each daily bar to its week bucket, then attach that week's flag.
    daily = frame.with_columns(
        pl.col("trade_timestamp").dt.truncate("1w").alias("week_start")
    )
    weekly = weekly.rename({"trade_timestamp": "week_start"})
    joined = daily.join(weekly, on="week_start", how="left").with_columns(
        pl.col("weekly_uptrend").fill_null(False)
    )
    return joined.drop("week_start").sort("trade_timestamp")


def slice_window(frame: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    """Return rows whose date is within [start, end] (inclusive)."""
    return frame.filter(
        (pl.col("trade_timestamp").dt.date() >= start)
        & (pl.col("trade_timestamp").dt.date() <= end)
    )


def available_symbols(
    symbols: list[str], indicators_dir: Path, prices_dir: Path
) -> list[str]:
    """Keep only symbols that have both parquet files."""
    keep = [
        s
        for s in symbols
        if (indicators_dir / "1d" / f"{s}.parquet").exists()
        and (prices_dir / "1d" / f"{s}.parquet").exists()
    ]
    if not keep:
        raise DataWindowError("No symbols have both price and indicator parquet")
    LOGGER.info("Backtest universe: %d of %d symbols usable", len(keep), len(symbols))
    return keep
