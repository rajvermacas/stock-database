from datetime import datetime, timedelta

import polars as pl
import pytest

from stock_data.intervals import IST
from stock_data.pullback.errors import PullbackDataError
from stock_data.pullback.quality import resolve_common_as_of, validate_prices


def test_common_as_of_is_unique_modal_latest_timestamp() -> None:
    first = datetime(2026, 1, 1, tzinfo=IST)
    second = datetime(2026, 1, 2, tzinfo=IST)
    assert resolve_common_as_of({"A": second, "B": second, "C": first}) == second


def test_common_as_of_rejects_tied_modes() -> None:
    first = datetime(2026, 1, 1, tzinfo=IST)
    second = datetime(2026, 1, 2, tzinfo=IST)
    with pytest.raises(PullbackDataError, match="common as-of"):
        resolve_common_as_of({"A": first, "B": second})


def test_validate_prices_flags_stale_duplicate_and_invalid_ohlc(price_frame) -> None:
    frame = price_frame([100.0, 101.0, 102.0])
    duplicate = frame[1].with_columns(
        pl.lit(90.0).alias("high"),
        pl.lit(110.0).alias("low"),
    )
    invalid = pl.concat([frame, duplicate])
    common_as_of = frame["trade_timestamp"].max() + timedelta(hours=1)
    result = validate_prices(invalid, common_as_of)
    assert {"stale", "duplicate_timestamp", "invalid_ohlc"} <= {
        issue.code for issue in result.issues
    }


def test_validate_prices_accepts_structurally_valid_frame(price_frame) -> None:
    frame = price_frame([100.0, 101.0, 102.0])
    result = validate_prices(frame, frame["trade_timestamp"].max())
    assert result.valid
    assert result.cadence_seconds == 3600.0
