from datetime import datetime

import pandas as pd
import polars as pl
import pytest

from stock_data.intervals import IST, get_interval
from stock_data.normalization import (
    CANONICAL_COLUMNS,
    NormalizationError,
    normalize_symbol,
)


def yahoo_frame(index: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0] * len(index),
            "High": [105.0] * len(index),
            "Low": [99.0] * len(index),
            "Close": [104.0] * len(index),
            "Volume": [1000] * len(index),
        },
        index=pd.DatetimeIndex(index, name="Datetime"),
    )


def test_normalize_intraday_converts_timestamp_to_ist_and_filters_active() -> None:
    frame = yahoo_frame(["2026-06-08 04:15:00+00:00", "2026-06-08 04:45:00+00:00"])
    result = normalize_symbol(
        "TCS.NS", frame, get_interval("30m"), datetime(2026, 6, 8, 10, 30, tzinfo=IST)
    )
    assert result.columns == CANONICAL_COLUMNS
    assert result["trade_timestamp"].to_list() == [
        datetime(2026, 6, 8, 9, 45, tzinfo=IST)
    ]
    assert result.schema["trade_timestamp"] == pl.Datetime("us", "Asia/Kolkata")


def test_normalize_daily_localizes_naive_timestamp() -> None:
    result = normalize_symbol(
        "TCS.NS",
        yahoo_frame(["2026-06-05"]),
        get_interval("1d"),
        datetime(2026, 6, 6, tzinfo=IST),
    )
    assert result["trade_timestamp"].to_list() == [datetime(2026, 6, 5, tzinfo=IST)]


def test_normalize_symbol_rejects_missing_required_column() -> None:
    frame = yahoo_frame(["2026-06-05"]).drop(columns="Volume")
    with pytest.raises(NormalizationError, match="missing columns"):
        normalize_symbol(
            "TCS.NS", frame, get_interval("1d"), datetime(2026, 6, 6, tzinfo=IST)
        )


def test_normalize_drops_wholly_empty_batch_alignment_rows() -> None:
    frame = yahoo_frame(["2026-06-04", "2026-06-05"])
    frame.loc[pd.Timestamp("2026-06-04")] = float("nan")
    frame["Volume"] = frame["Volume"].astype("float64")
    result = normalize_symbol(
        "TCS.NS",
        frame,
        get_interval("1d"),
        datetime(2026, 6, 6, tzinfo=IST),
    )
    assert result.height == 1
    assert result["volume"].to_list() == [1000]


def test_normalize_rejects_partially_missing_candle() -> None:
    frame = yahoo_frame(["2026-06-05"])
    frame.loc[pd.Timestamp("2026-06-05"), "Volume"] = float("nan")
    with pytest.raises(NormalizationError, match="partially missing"):
        normalize_symbol(
            "TCS.NS",
            frame,
            get_interval("1d"),
            datetime(2026, 6, 6, tzinfo=IST),
        )
