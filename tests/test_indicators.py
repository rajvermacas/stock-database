from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest
import talib

from stock_data.indicators import (
    INDICATOR_COLUMNS,
    INDICATOR_SCHEMA,
    IndicatorError,
    calculate_indicators,
)
from stock_data.intervals import IST
from stock_data.normalization import CANONICAL_SCHEMA


def price_history(days: int = 500) -> pl.DataFrame:
    closes = [100.0 + index * 0.2 + (index % 7) for index in range(days)]
    return pl.DataFrame(
        {
            "symbol": ["TCS.NS"] * days,
            "trade_timestamp": [
                datetime(2024, 1, 1, tzinfo=IST) + timedelta(days=index)
                for index in range(days)
            ],
            "open": [value - 0.5 for value in closes],
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000 + index * 10 for index in range(days)],
        },
        schema=CANONICAL_SCHEMA,
    )


def weekly_history(weeks: int) -> pl.DataFrame:
    closes = [100.0 + index * 0.2 + (index % 7) for index in range(weeks)]
    return pl.DataFrame(
        {
            "symbol": ["TCS.NS"] * weeks,
            "trade_timestamp": [
                datetime(2015, 1, 1, tzinfo=IST) + timedelta(weeks=index)
                for index in range(weeks)
            ],
            "open": [value - 0.5 for value in closes],
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000 + index * 10 for index in range(weeks)],
        },
        schema=CANONICAL_SCHEMA,
    )


def test_standard_indicators_match_talib() -> None:
    prices = price_history()
    result = calculate_indicators(prices)
    assert result is not None
    last = result.row(-1, named=True)
    close = np.asarray(prices["close"], dtype=float)
    high = np.asarray(prices["high"], dtype=float)
    low = np.asarray(prices["low"], dtype=float)
    volume = np.asarray(prices["volume"], dtype=float)
    assert last["ema_200"] == pytest.approx(talib.EMA(close, 200)[-1])
    assert last["rsi_14"] == pytest.approx(talib.RSI(close, 14)[-1])
    assert last["atr_14"] == pytest.approx(talib.ATR(high, low, close, 14)[-1])
    assert last["adx_14"] == pytest.approx(talib.ADX(high, low, close, 14)[-1])
    assert last["obv"] == pytest.approx(talib.OBV(close, volume)[-1])


def test_derived_columns_use_ema_center() -> None:
    result = calculate_indicators(price_history())
    assert result is not None
    last = result.row(-1, named=True)
    assert last["band_middle_20"] == last["ema_20"]
    assert last["atr_percent_14"] == pytest.approx(
        last["atr_14"] / price_history()["close"][-1] * 100
    )


def test_trailing_365d_null_until_full_calendar_year() -> None:
    prices = price_history(500)
    result = calculate_indicators(prices)
    assert result is not None
    assert result.height == prices.height  # no rows dropped
    threshold = prices["trade_timestamp"][0] + timedelta(days=365)
    early = result.filter(pl.col("trade_timestamp") < threshold)
    full = result.filter(pl.col("trade_timestamp") >= threshold)
    assert early.height > 0 and full.height > 0
    # The 365d-window indicators wait for a full year; shorter ones do not.
    assert early["trailing_365d_high"].null_count() == early.height
    assert full["trailing_365d_high"].null_count() == 0
    assert early["ema_10"].null_count() < early.height


def test_trailing_high_uses_calendar_days_not_candle_count() -> None:
    prices = price_history(500).with_columns(
        pl.when(pl.int_range(pl.len()) == 100)
        .then(1000.0)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    result = calculate_indicators(prices)
    assert result is not None
    assert result.row(-1, named=True)["trailing_365d_high"] < 1000.0


def test_output_has_no_non_finite_values() -> None:
    result = calculate_indicators(price_history())
    assert result is not None
    assert result.schema == INDICATOR_SCHEMA
    # Cells may be null where a lookback is unmet, but never NaN or inf.
    for column in INDICATOR_COLUMNS:
        series = result[column]
        assert (series.is_finite() | series.is_null()).all()
    # The latest row is fully warmed up: every indicator is populated.
    assert result.tail(1).null_count().select(pl.sum_horizontal(pl.all())).item() == 0


def test_zero_volume_rows_keep_null_relative_volume() -> None:
    prices = price_history().with_columns(
        pl.when(pl.int_range(pl.len()) < 400)
        .then(0)
        .otherwise(pl.col("volume"))
        .alias("volume")
    )
    result = calculate_indicators(prices)
    assert result is not None
    # Zero-volume rows keep relative_volume_20 null (undefined); warmed-up
    # price-based indicators stay finite.
    assert result["relative_volume_20"].null_count() > 0
    warmed = result.filter(pl.col("ema_200").is_not_null())
    assert warmed.height > 0
    assert warmed["rsi_14"].null_count() == 0
    assert np.isfinite(warmed["ema_200"].to_numpy()).all()


def test_zero_volume_instrument_nulls_relative_volume() -> None:
    prices = price_history().with_columns((pl.col("volume") * 0).alias("volume"))
    result = calculate_indicators(prices)
    assert result is not None
    assert not result.is_empty()
    # An index has no volume at all: relative_volume_20 is null for every row,
    # all price-based indicators remain finite once warmed up.
    assert result["relative_volume_20"].null_count() == result.height
    warmed = result.filter(pl.col("ema_200").is_not_null())
    assert warmed.height > 0
    assert warmed["rsi_14"].null_count() == 0
    assert np.isfinite(warmed["ema_200"].to_numpy()).all()


def test_short_history_nulls_only_insufficient_indicators() -> None:
    # 365 daily bars span 364 calendar days (< 1 year), so no row earns a full
    # 365d window, but bar-count indicators still populate per their own lookback.
    result = calculate_indicators(price_history(365))
    assert result is not None
    assert result.height == 365  # symbol not failed, no rows dropped
    assert result["trailing_365d_high"].null_count() == result.height
    assert result["trailing_365d_low"].null_count() == result.height
    assert result["distance_from_365d_high_percent"].null_count() == result.height
    last = result.row(-1, named=True)
    assert last["ema_10"] is not None
    assert last["ema_200"] is not None  # 365 bars >= 200
    assert last["rsi_14"] is not None


def test_weekly_history_nulls_ema200_keeps_short_indicators() -> None:
    # 120 weekly bars span >2 years (trailing-365d valid) but < 200 bars, so
    # ema_200 can never be computed and must stay null while shorter indicators
    # populate -- the reported weekly/monthly failure mode.
    result = calculate_indicators(weekly_history(120))
    assert result is not None
    assert result["ema_200"].null_count() == result.height
    last = result.row(-1, named=True)
    assert last["ema_50"] is not None  # 120 >= 50 bars
    assert last["rsi_14"] is not None
    assert last["trailing_365d_high"] is not None  # > 1 year of weeks


def test_invalid_source_fails_fast() -> None:
    with pytest.raises(IndicatorError, match="multiple symbols"):
        calculate_indicators(
            price_history().with_columns(
                pl.when(pl.int_range(pl.len()) == 0)
                .then(pl.lit("INFY.NS"))
                .otherwise(pl.col("symbol"))
                .alias("symbol")
            )
        )
