import os
from pathlib import Path

import polars as pl
import pytest

from stock_data.indicator_storage import (
    IndicatorStorageError,
    IndicatorStore,
    source_fingerprint,
)
from stock_data.indicators import calculate_indicators
from stock_data.intervals import get_interval
from test_indicators import price_history, weekly_history


def test_paths_include_selected_interval(tmp_path: Path) -> None:
    store = IndicatorStore(tmp_path, get_interval("30m"))
    assert store.path_for("TCS.NS") == tmp_path / "30m" / "TCS.NS.parquet"
    assert store.metadata_path_for("TCS.NS") == (
        tmp_path / "30m" / "TCS.NS.metadata.json"
    )


def test_source_fingerprint_changes_for_historical_revision() -> None:
    prices = price_history()
    revised = prices.with_columns(
        pl.when(pl.int_range(pl.len()) == 10)
        .then(pl.col("close") + 1)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    assert source_fingerprint(prices) != source_fingerprint(revised)


def test_publish_and_read_metadata(tmp_path: Path) -> None:
    prices = price_history()
    indicators = calculate_indicators(prices)
    assert indicators is not None
    store = IndicatorStore(tmp_path, get_interval("1d"))
    fingerprint = source_fingerprint(prices)
    store.publish("TCS.NS", indicators, fingerprint)
    stored = store.read("TCS.NS")
    assert stored is not None and stored.equals(indicators)
    assert store.is_current("TCS.NS", fingerprint)


def test_publish_and_read_frame_with_nulls(tmp_path: Path) -> None:
    prices = weekly_history(120)
    indicators = calculate_indicators(prices)
    assert indicators is not None
    # ema_200 is null for every row (only 120 weekly bars); storage must accept
    # and round-trip per-cell nulls.
    assert indicators["ema_200"].null_count() == indicators.height
    store = IndicatorStore(tmp_path, get_interval("1wk"))
    fingerprint = source_fingerprint(prices)
    store.publish("TCS.NS", indicators, fingerprint)
    stored = store.read("TCS.NS")
    assert stored is not None and stored.equals(indicators)


def test_missing_pair_is_not_current(tmp_path: Path) -> None:
    store = IndicatorStore(tmp_path, get_interval("1d"))
    assert store.is_current("TCS.NS", "fingerprint") is False


def test_remove_deletes_parquet_and_metadata(tmp_path: Path) -> None:
    prices = price_history()
    indicators = calculate_indicators(prices)
    assert indicators is not None
    store = IndicatorStore(tmp_path, get_interval("1d"))
    store.publish("TCS.NS", indicators, source_fingerprint(prices))
    assert store.remove("TCS.NS") is True
    assert not store.path_for("TCS.NS").exists()
    assert not store.metadata_path_for("TCS.NS").exists()


def test_corrupt_metadata_fails_fast(tmp_path: Path) -> None:
    prices = price_history()
    indicators = calculate_indicators(prices)
    assert indicators is not None
    store = IndicatorStore(tmp_path, get_interval("1d"))
    store.publish("TCS.NS", indicators, source_fingerprint(prices))
    store.metadata_path_for("TCS.NS").write_text("{}", encoding="utf-8")
    with pytest.raises(IndicatorStorageError, match="Invalid indicator metadata"):
        store.is_current("TCS.NS", source_fingerprint(prices))


def test_publish_failure_preserves_previous_pair(mocker, tmp_path: Path) -> None:
    prices = price_history()
    indicators = calculate_indicators(prices)
    assert indicators is not None
    store = IndicatorStore(tmp_path, get_interval("1d"))
    fingerprint = source_fingerprint(prices)
    store.publish("TCS.NS", indicators, fingerprint)
    original_frame = store.path_for("TCS.NS").read_bytes()
    original_metadata = store.metadata_path_for("TCS.NS").read_bytes()
    real_replace = os.replace

    def fail_new_metadata(source, destination):
        if Path(destination) == store.metadata_path_for(
            "TCS.NS"
        ) and ".backup" not in str(source):
            raise OSError("metadata replace failed")
        real_replace(source, destination)

    mocker.patch(
        "stock_data.indicator_storage.os.replace", side_effect=fail_new_metadata
    )
    with pytest.raises(IndicatorStorageError, match="Unable to publish"):
        store.publish("TCS.NS", indicators, "new-fingerprint")
    assert store.path_for("TCS.NS").read_bytes() == original_frame
    assert store.metadata_path_for("TCS.NS").read_bytes() == original_metadata
