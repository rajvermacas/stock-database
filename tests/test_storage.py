from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_data.normalization import CANONICAL_SCHEMA
from stock_data.storage import PriceStore, StorageError


def frame(close: float, day: date = date(2026, 6, 5)) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "symbol": "TCS.NS",
                "trade_date": day,
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": close,
                "volume": 1000,
            }
        ],
        schema=CANONICAL_SCHEMA,
    )


def test_upsert_replaces_matching_date_with_new_row(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    store.write_atomic("TCS.NS", frame(100.0))
    result = store.upsert("TCS.NS", frame(105.0))
    assert result.changed is True
    assert store.read("TCS.NS")["close"].to_list() == [105.0]  # type: ignore[index]


def test_upsert_reports_unchanged_and_latest_date(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    store.write_atomic("TCS.NS", frame(100.0))
    result = store.upsert("TCS.NS", frame(100.0))
    assert result.changed is False
    assert store.latest_date("TCS.NS") == date(2026, 6, 5)


def test_read_rejects_existing_duplicate_dates(tmp_path: Path) -> None:
    path = tmp_path / "TCS.NS.parquet"
    pl.concat([frame(100.0), frame(101.0)]).write_parquet(path)
    with pytest.raises(StorageError, match="duplicate dates"):
        PriceStore(tmp_path).read("TCS.NS")
