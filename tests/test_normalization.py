from datetime import date

import pandas as pd
import polars as pl
import pytest

from stock_data.normalization import (
    CANONICAL_COLUMNS,
    NormalizationError,
    normalize_symbol,
)


def yahoo_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [99.0, 100.0],
            "Close": [104.0, 105.0],
            "Volume": [1000, 1100],
        },
        index=pd.DatetimeIndex(["2026-06-05", "2026-06-06"], name="Date"),
    )


def test_normalize_symbol_returns_canonical_schema_and_applies_cutoff() -> None:
    result = normalize_symbol("TCS.NS", yahoo_frame(), date(2026, 6, 5))
    assert result.columns == CANONICAL_COLUMNS
    assert result["trade_date"].to_list() == [date(2026, 6, 5)]
    assert result.schema["volume"] == pl.Int64


def test_normalize_symbol_rejects_missing_required_column() -> None:
    with pytest.raises(NormalizationError, match="missing columns"):
        normalize_symbol(
            "TCS.NS", yahoo_frame().drop(columns="Volume"), date(2026, 6, 5)
        )
