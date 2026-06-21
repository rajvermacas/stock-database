from pathlib import Path

import pytest

from stock_data.indicator_service import IndicatorUpdateError, IndicatorUpdater
from stock_data.indicator_storage import IndicatorStore
from stock_data.intervals import get_interval
from stock_data.storage import PriceStore
from test_indicators import price_history


class FakePriceStore:
    def __init__(self, prices):
        self.prices = prices
        self.interval = get_interval("1d")

    def read(self, symbol):
        return self.prices


class FakeIndicatorStore:
    def __init__(self, current=False):
        self.current = current
        self.published_symbols = []
        self.removed_symbols = []
        self.frame = None

    def is_current(self, symbol, fingerprint):
        return self.current

    def read(self, symbol):
        return self.frame

    def publish(self, symbol, frame, fingerprint):
        self.published_symbols.append(symbol)
        self.frame = frame

    def remove(self, symbol):
        self.removed_symbols.append(symbol)
        return True


def build_updater(current=False, sufficient=True):
    prices = price_history() if sufficient else price_history(100)
    indicator_store = FakeIndicatorStore(current)
    if current:
        indicator_store.frame = price_history(2)
    return IndicatorUpdater(FakePriceStore(prices), indicator_store), indicator_store


def test_missing_indicator_is_backfilled_when_price_unchanged() -> None:
    updater, indicator_store = build_updater(current=False)
    result = updater.refresh("TCS.NS", prices_changed=False)
    assert result.changed is True
    assert indicator_store.published_symbols == ["TCS.NS"]


def test_current_indicator_is_skipped_when_price_unchanged() -> None:
    updater, indicator_store = build_updater(current=True)
    result = updater.refresh("TCS.NS", prices_changed=False)
    assert result.changed is False
    assert indicator_store.published_symbols == []


def test_changed_price_forces_recalculation() -> None:
    updater, indicator_store = build_updater(current=True)
    updater.refresh("TCS.NS", prices_changed=True)
    assert indicator_store.published_symbols == ["TCS.NS"]


def test_short_history_publishes_partial_indicators() -> None:
    updater, indicator_store = build_updater(current=False, sufficient=False)
    result = updater.refresh("TCS.NS", prices_changed=False)
    assert result.changed is True
    assert indicator_store.published_symbols == ["TCS.NS"]
    assert indicator_store.removed_symbols == []
    # Short history publishes a partial frame: long-lookback indicators are
    # null while short ones populate, instead of removing the symbol.
    frame = indicator_store.frame
    assert frame is not None
    assert frame["trailing_365d_high"].null_count() == frame.height
    assert frame["ema_10"][-1] is not None


def test_missing_price_fails_fast() -> None:
    updater = IndicatorUpdater(FakePriceStore(None), FakeIndicatorStore())
    with pytest.raises(IndicatorUpdateError, match="Price data does not exist"):
        updater.refresh("TCS.NS", prices_changed=False)


def test_storage_failure_includes_context() -> None:
    updater, indicator_store = build_updater()
    indicator_store.publish = lambda *args: (_ for _ in ()).throw(OSError("disk full"))
    with pytest.raises(IndicatorUpdateError, match="symbol=TCS.NS.*disk full"):
        updater.refresh("TCS.NS", prices_changed=False)


def test_refresh_does_not_modify_price_file(tmp_path: Path) -> None:
    interval = get_interval("1d")
    price_store = PriceStore(tmp_path / "prices", interval)
    price_store.write_atomic("TCS.NS", price_history())
    price_path = price_store.path_for("TCS.NS")
    original = price_path.read_bytes()
    indicator_store = IndicatorStore(tmp_path / "indicators", interval)
    IndicatorUpdater(price_store, indicator_store).refresh(
        "TCS.NS", prices_changed=True
    )
    assert price_path.read_bytes() == original
    assert indicator_store.path_for("TCS.NS").exists()
    assert indicator_store.metadata_path_for("TCS.NS").exists()
