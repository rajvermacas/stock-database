from __future__ import annotations

from datetime import timedelta

import numpy as np
import polars as pl
import talib

from stock_data.normalization import CANONICAL_SCHEMA

INDICATOR_COLUMNS = [
    "ema_10",
    "ema_20",
    "ema_50",
    "ema_100",
    "ema_200",
    "volume_ema_20",
    "relative_volume_20",
    "rsi_14",
    "atr_14",
    "atr_percent_14",
    "macd_12_26",
    "macd_signal_9",
    "macd_histogram",
    "adx_14",
    "plus_di_14",
    "minus_di_14",
    "band_upper_20_2",
    "band_middle_20",
    "band_lower_20_2",
    "band_width_20_2",
    "roc_20",
    "obv",
    "trailing_365d_high",
    "trailing_365d_low",
    "distance_from_365d_high_percent",
]
INDICATOR_SCHEMA = {
    "symbol": pl.String,
    "trade_timestamp": pl.Datetime(time_unit="us", time_zone="Asia/Kolkata"),
    **{column: pl.Float64 for column in INDICATOR_COLUMNS},
}


class IndicatorError(ValueError):
    """Raised when indicators cannot be calculated or validated."""


def calculate_indicators(prices: pl.DataFrame) -> pl.DataFrame | None:
    try:
        _validate_prices(prices)
        threshold = prices["trade_timestamp"].min() + timedelta(days=365)
        if prices["trade_timestamp"].max() < threshold:
            return None
        frame = _attach_talib_columns(prices)
        frame = _add_calendar_columns(frame)
        frame = _add_derived_columns(frame)
        result = frame.filter(pl.col("trade_timestamp") >= threshold).select(
            *INDICATOR_SCHEMA
        )
        result = result.cast(INDICATOR_SCHEMA, strict=True)
        _validate_result(result)
        return result
    except (TypeError, ValueError, pl.exceptions.PolarsError) as exc:
        if isinstance(exc, IndicatorError):
            raise
        raise IndicatorError(f"Unable to calculate indicators: {exc}") from exc


def _attach_talib_columns(prices: pl.DataFrame) -> pl.DataFrame:
    return prices.with_columns(
        [
            pl.Series(name, values, dtype=pl.Float64)
            for name, values in _talib_columns(prices).items()
        ]
    )


def _talib_columns(prices: pl.DataFrame) -> dict[str, np.ndarray]:
    close = prices["close"].to_numpy().astype(float)
    high = prices["high"].to_numpy().astype(float)
    low = prices["low"].to_numpy().astype(float)
    volume = prices["volume"].to_numpy().astype(float)
    macd, signal, histogram = talib.MACD(close, 12, 26, 9)
    return {
        "ema_10": talib.EMA(close, 10),
        "ema_20": talib.EMA(close, 20),
        "ema_50": talib.EMA(close, 50),
        "ema_100": talib.EMA(close, 100),
        "ema_200": talib.EMA(close, 200),
        "volume_ema_20": talib.EMA(volume, 20),
        "rsi_14": talib.RSI(close, 14),
        "atr_14": talib.ATR(high, low, close, 14),
        "macd_12_26": macd,
        "macd_signal_9": signal,
        "macd_histogram": histogram,
        "adx_14": talib.ADX(high, low, close, 14),
        "plus_di_14": talib.PLUS_DI(high, low, close, 14),
        "minus_di_14": talib.MINUS_DI(high, low, close, 14),
        "close_std_20": talib.STDDEV(close, 20),
        "roc_20": talib.ROC(close, 20),
        "obv": talib.OBV(close, volume),
    }


def _add_calendar_columns(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.col("high")
        .rolling_max_by("trade_timestamp", window_size="365d", closed="both")
        .alias("trailing_365d_high"),
        pl.col("low")
        .rolling_min_by("trade_timestamp", window_size="365d", closed="both")
        .alias("trailing_365d_low"),
    )


def _add_derived_columns(frame: pl.DataFrame) -> pl.DataFrame:
    frame = frame.with_columns(
        (pl.col("volume") / pl.col("volume_ema_20")).alias("relative_volume_20"),
        (pl.col("atr_14") / pl.col("close") * 100).alias("atr_percent_14"),
        pl.col("ema_20").alias("band_middle_20"),
        (pl.col("ema_20") + 2 * pl.col("close_std_20")).alias("band_upper_20_2"),
        (pl.col("ema_20") - 2 * pl.col("close_std_20")).alias("band_lower_20_2"),
        ((pl.col("close") / pl.col("trailing_365d_high") - 1) * 100).alias(
            "distance_from_365d_high_percent"
        ),
    )
    return frame.with_columns(
        (
            (pl.col("band_upper_20_2") - pl.col("band_lower_20_2"))
            / pl.col("band_middle_20")
            * 100
        ).alias("band_width_20_2")
    )


def _validate_prices(prices: pl.DataFrame) -> None:
    if prices.schema != CANONICAL_SCHEMA:
        raise IndicatorError(f"Unexpected price schema: {prices.schema}")
    if prices.is_empty():
        raise IndicatorError("Price data is empty")
    if prices.null_count().select(pl.sum_horizontal(pl.all())).item() > 0:
        raise IndicatorError("Price data contains nulls")
    if prices["symbol"].n_unique() != 1:
        raise IndicatorError("Price data contains multiple symbols")
    if prices["trade_timestamp"].n_unique() != prices.height:
        raise IndicatorError("Price data contains duplicate timestamps")
    if not prices["trade_timestamp"].is_sorted():
        raise IndicatorError("Price data is not sorted")


def _validate_result(result: pl.DataFrame) -> None:
    if result.is_empty():
        raise IndicatorError("Indicator result is empty")
    if result.schema != INDICATOR_SCHEMA:
        raise IndicatorError(f"Unexpected indicator schema: {result.schema}")
    if result.null_count().select(pl.sum_horizontal(pl.all())).item() > 0:
        raise IndicatorError("Indicator result contains nulls")
    if not np.isfinite(result.select(INDICATOR_COLUMNS).to_numpy()).all():
        raise IndicatorError("Indicator result contains non-finite values")
