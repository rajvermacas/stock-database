import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

from stock_data.indicator_storage import IndicatorStore, source_fingerprint
from stock_data.indicators import calculate_indicators
from stock_data.intervals import IST, get_interval
from stock_data.storage import PriceStore
from test_indicators import price_history

SCRIPT = Path(".agents/skills/talk-to-stock-data/scripts/stock_frame.py")
SPEC = importlib.util.spec_from_file_location("stock_frame", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
stock_frame = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stock_frame
SPEC.loader.exec_module(stock_frame)


def write_data(tmp_path: Path) -> tuple[Path, Path]:
    interval = get_interval("1d")
    prices = price_history()
    prices_root = tmp_path / "prices"
    indicators_root = tmp_path / "indicators"
    PriceStore(prices_root, interval).write_atomic("TCS.NS", prices)
    indicators = calculate_indicators(prices)
    assert indicators is not None
    IndicatorStore(indicators_root, interval).publish(
        "TCS.NS", indicators, source_fingerprint(prices)
    )
    return prices_root, indicators_root


def test_load_indicators_filters_exact_interval(tmp_path: Path) -> None:
    _, indicators_root = write_data(tmp_path)
    result = stock_frame.load_indicators(
        "1d",
        indicators_root,
        ["TCS.NS"],
        datetime(2025, 1, 1, tzinfo=IST),
        None,
    ).collect()
    assert result["symbol"].unique().to_list() == ["TCS.NS"]
    assert result["trade_timestamp"].min() >= datetime(2025, 1, 1, tzinfo=IST)
    assert "ema_200" in result.columns


def test_load_prices_with_indicators_joins_keys(tmp_path: Path) -> None:
    prices_root, indicators_root = write_data(tmp_path)
    result = stock_frame.load_prices_with_indicators(
        "1d", prices_root, indicators_root, ["TCS.NS"], None, None
    ).collect()
    assert {"close", "ema_200", "rsi_14"}.issubset(result.columns)
    assert result.height > 0


def test_join_rejects_derived_interval(tmp_path: Path) -> None:
    prices_root, indicators_root = write_data(tmp_path)
    with pytest.raises(stock_frame.StockFrameError, match="derived interval"):
        stock_frame.load_prices_with_indicators(
            "1wk", prices_root, indicators_root, None, None, None
        )


def test_missing_exact_indicators_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(stock_frame.StockFrameError, match="No indicators"):
        stock_frame.load_indicators("1d", tmp_path, None, None, None)
