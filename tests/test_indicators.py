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


def test_requires_full_365_calendar_days() -> None:
    prices = price_history(367)
    result = calculate_indicators(prices)
    assert result is not None
    assert result["trade_timestamp"].min() == prices["trade_timestamp"][365]


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


def test_output_has_strict_finite_schema() -> None:
    result = calculate_indicators(price_history())
    assert result is not None
    assert result.schema == INDICATOR_SCHEMA
    assert result.null_count().select(pl.sum_horizontal(pl.all())).item() == 0
    assert np.isfinite(result.select(INDICATOR_COLUMNS).to_numpy()).all()


def test_non_finite_indicator_rows_are_excluded() -> None:
    prices = price_history().with_columns(
        pl.when(pl.int_range(pl.len()) < 400)
        .then(0)
        .otherwise(pl.col("volume"))
        .alias("volume")
    )
    result = calculate_indicators(prices)
    assert result is not None
    assert result["trade_timestamp"].min() == prices["trade_timestamp"][400]
    assert np.isfinite(result.select(INDICATOR_COLUMNS).to_numpy()).all()


def test_insufficient_history_returns_none() -> None:
    assert calculate_indicators(price_history(365)) is None


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
