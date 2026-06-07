from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from stock_data.intervals import IST, get_interval
from stock_data.normalization import CANONICAL_SCHEMA
from stock_data.storage import PriceStore, StorageError


def frame(close: float, timestamp: datetime | None = None) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "symbol": "TCS.NS",
                "trade_timestamp": timestamp or datetime(2026, 6, 5, tzinfo=IST),
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": close,
                "volume": 1000,
            }
        ],
        schema=CANONICAL_SCHEMA,
    )


def test_path_for_includes_interval_directory(tmp_path: Path) -> None:
    assert PriceStore(tmp_path, get_interval("30m")).path_for("TCS.NS") == (
        tmp_path / "30m" / "TCS.NS.parquet"
    )


def test_upsert_replaces_matching_timestamp(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("1d"))
    store.write_atomic("TCS.NS", frame(100.0))
    result = store.upsert("TCS.NS", frame(105.0))
    assert result.changed is True
    assert store.read("TCS.NS")["close"].to_list() == [105.0]  # type: ignore[index]


def test_latest_timestamp_and_duplicate_validation(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("1h"))
    store.write_atomic("TCS.NS", frame(100.0))
    assert store.latest_timestamp("TCS.NS") == datetime(2026, 6, 5, tzinfo=IST)
    pl.concat([frame(100.0), frame(101.0)]).write_parquet(store.path_for("TCS.NS"))
    with pytest.raises(StorageError, match="duplicate timestamps"):
        store.read("TCS.NS")
