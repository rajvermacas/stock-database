import os
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from stock_data.intervals import IST, get_interval
from stock_data.normalization import CANONICAL_SCHEMA
from stock_data.storage import PriceStore, StorageError, WriteResult


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


def test_replace_removes_rows_absent_from_full_download(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("1d"))
    old = pl.concat(
        [
            frame(100.0, datetime(2026, 6, 4, tzinfo=IST)),
            frame(101.0, datetime(2026, 6, 5, tzinfo=IST)),
        ]
    )
    replacement = frame(105.0, datetime(2026, 6, 5, tzinfo=IST))
    store.write_atomic("TCS.NS", old)
    result = store.replace("TCS.NS", replacement)
    assert result.changed is True
    assert result.downloaded_rows == 1
    assert result.stored_rows == 1
    assert store.read("TCS.NS").equals(replacement)  # type: ignore[union-attr]


def test_replace_equal_history_is_unchanged(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("1d"))
    prices = frame(100.0)
    store.write_atomic("TCS.NS", prices)
    original = store.path_for("TCS.NS").read_bytes()
    result = store.replace("TCS.NS", prices)
    assert result == WriteResult(False, 1, 1)
    assert store.path_for("TCS.NS").read_bytes() == original


def test_replace_write_failure_preserves_existing_file(
    mocker, tmp_path: Path
) -> None:
    store = PriceStore(tmp_path, get_interval("1d"))
    store.write_atomic("TCS.NS", frame(100.0))
    original = store.path_for("TCS.NS").read_bytes()
    real_replace = os.replace
    failed = False

    def fail_destination_publish(source, destination):
        nonlocal failed
        if Path(destination) == store.path_for("TCS.NS") and not failed:
            failed = True
            raise OSError("disk full")
        real_replace(source, destination)

    mocker.patch("stock_data.storage.os.replace", side_effect=fail_destination_publish)
    with pytest.raises(StorageError, match="disk full"):
        store.replace("TCS.NS", frame(105.0))
    assert store.path_for("TCS.NS").read_bytes() == original


def test_replace_changes_only_configured_interval(tmp_path: Path) -> None:
    daily = PriceStore(tmp_path, get_interval("1d"))
    hourly = PriceStore(tmp_path, get_interval("1h"))
    hourly.write_atomic("TCS.NS", frame(100.0))
    hourly_original = hourly.path_for("TCS.NS").read_bytes()
    daily.replace("TCS.NS", frame(105.0))
    assert daily.path_for("TCS.NS").exists()
    assert hourly.path_for("TCS.NS").read_bytes() == hourly_original


def test_duplicate_validation(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("1h"))
    store.interval_dir.mkdir(parents=True)
    pl.concat([frame(100.0), frame(101.0)]).write_parquet(store.path_for("TCS.NS"))
    with pytest.raises(StorageError, match="duplicate timestamps"):
        store.read("TCS.NS")
