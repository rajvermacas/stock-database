from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

IST = ZoneInfo("Asia/Kolkata")
SCRIPT = Path(".agents/skills/analyze-chart-structure/scripts/analyze_structure.py")
SPEC = importlib.util.spec_from_file_location("analyze_structure", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
structure = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = structure
SPEC.loader.exec_module(structure)


def price_frame(closes: list[float]) -> pl.LazyFrame:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=IST)
    timestamps = pl.datetime_range(
        start,
        start + timedelta(hours=len(closes) - 1),
        interval="1h",
        eager=True,
    )
    return pl.DataFrame(
        {
            "symbol": ["TEST.NS"] * len(closes),
            "trade_timestamp": timestamps,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        }
    ).lazy()


def pivot_path(pivots: list[float], steps: int = 7) -> list[float]:
    return [
        left + (right - left) * offset / steps
        for left, right in zip(pivots, pivots[1:], strict=False)
        for offset in range(steps)
    ] + [pivots[-1]]


def ascending_channel_path() -> list[float]:
    return pivot_path([100, 108, 104, 112, 108, 116, 112, 120])


def descending_channel_path() -> list[float]:
    return pivot_path([120, 112, 116, 108, 112, 104, 108, 100])


def double_bottom_path() -> list[float]:
    return pivot_path([125, 108, 118, 108.5, 116, 114, 115])


def double_top_path() -> list[float]:
    return pivot_path([95, 112, 102, 111.5, 104, 106, 105])


def head_shoulders_path() -> list[float]:
    return pivot_path([100, 112, 105, 120, 105, 112, 100])


def inverse_head_shoulders_path() -> list[float]:
    return pivot_path([120, 108, 115, 100, 115, 108, 120])


def ascending_triangle_path() -> list[float]:
    return pivot_path([100, 112, 104, 112, 107, 112, 109, 111])


def descending_triangle_path() -> list[float]:
    return pivot_path([112, 100, 108, 100, 105, 100, 103, 101])


def symmetrical_triangle_path() -> list[float]:
    return pivot_path([112, 100, 109, 103, 107, 105, 106, 105.5])


def range_path() -> list[float]:
    return pivot_path([100, 110, 100.5, 109.5, 100, 110, 100.5, 109.5])


def metadata() -> dict[str, object]:
    return {
        "symbol": "TEST.NS",
        "requested_interval": "1h",
        "source_interval": "1h",
        "derived": False,
    }


def pattern_named(result: dict, name: str) -> dict:
    return next(pattern for pattern in result["patterns"] if pattern["name"] == name)


def write_price_fixture(tmp_path: Path, closes: list[float]) -> Path:
    prices_root = tmp_path / "prices"
    interval_root = prices_root / "1h"
    interval_root.mkdir(parents=True)
    price_frame(closes).collect().write_parquet(interval_root / "TEST.NS.parquet")
    return prices_root


def test_validate_request_uses_documented_default_window() -> None:
    request = structure.validate_request("TEST.NS", "1h", None, None, None)
    assert request.periods == 120


def test_validate_request_rejects_short_period_count() -> None:
    with pytest.raises(structure.StructureError, match="at least"):
        structure.validate_request("TEST.NS", "1h", None, None, 20)


def test_add_features_calculates_finite_atr_and_tolerance() -> None:
    result = structure.add_features(price_frame(list(range(100, 150)))).collect()
    assert result["atr_14"].drop_nulls().is_finite().all()
    assert result["tolerance"].drop_nulls().min() > 0


@pytest.mark.parametrize(
    ("closes", "trend", "sequence"),
    [
        (ascending_channel_path(), "bullish", "higher-highs-higher-lows"),
        (descending_channel_path(), "bearish", "lower-highs-lower-lows"),
    ],
)
def test_classify_structure_identifies_direction(closes, trend, sequence) -> None:
    result = structure.analyze_frame(price_frame(closes), metadata())
    assert result["structure"]["trend"] == trend
    assert result["structure"]["swing_sequence"] == sequence


def test_classify_structure_identifies_horizontal_range() -> None:
    closes = [100, 103, 101, 104, 100, 103] * 10
    result = structure.analyze_frame(price_frame(closes), metadata())
    assert result["structure"]["formation"] == "horizontal-range"


def test_developing_double_bottom_has_levels_and_contradictions() -> None:
    closes = (
        [120 - index for index in range(20)]
        + [101, 99, 102, 106, 103, 100, 102, 105, 104, 103] * 4
    )
    result = structure.analyze_frame(price_frame(closes), metadata())
    pattern = pattern_named(result, "double-bottom")
    assert pattern["status"] == "developing"
    assert pattern["confirmation_level"] is not None
    assert pattern["invalidation_level"] is not None
    assert pattern["evidence"]


def test_close_above_neckline_confirms_double_bottom() -> None:
    result = structure.analyze_frame(
        price_frame(double_bottom_path() + [120, 123]), metadata()
    )
    assert pattern_named(result, "double-bottom")["status"] == "confirmed"


@pytest.mark.parametrize(
    ("path_factory", "name"),
    [
        (double_top_path, "double-top"),
        (head_shoulders_path, "head-and-shoulders"),
        (inverse_head_shoulders_path, "inverse-head-and-shoulders"),
    ],
)
def test_reversal_patterns_require_ordered_pivots(path_factory, name) -> None:
    result = structure.analyze_frame(price_frame(path_factory()), metadata())
    assert pattern_named(result, name)["confidence"] >= 0.5


@pytest.mark.parametrize(
    ("path_factory", "name"),
    [
        (ascending_triangle_path, "ascending-triangle"),
        (descending_triangle_path, "descending-triangle"),
        (symmetrical_triangle_path, "symmetrical-triangle"),
        (ascending_channel_path, "ascending-channel"),
        (descending_channel_path, "descending-channel"),
        (range_path, "horizontal-range"),
    ],
)
def test_detects_continuation_and_boundary_patterns(path_factory, name) -> None:
    result = structure.analyze_frame(price_frame(path_factory()), metadata())
    assert pattern_named(result, name)["confidence"] >= 0.5


def test_close_beyond_boundary_reports_breakout() -> None:
    result = structure.analyze_frame(
        price_frame(ascending_triangle_path() + [120, 123]), metadata()
    )
    assert result["structure"]["breakout_state"] == "breakout"


def test_default_analysis_omits_historical_outcomes() -> None:
    result = structure.analyze_frame(price_frame(double_bottom_path()), metadata())
    assert "historical" not in result


def test_historical_analysis_returns_non_overlapping_occurrences() -> None:
    repeated = double_bottom_path() + [120] * 25 + double_bottom_path() + [125] * 25
    result = structure.analyze_frame(price_frame(repeated), metadata(), historical=True)
    historical = result["historical"]
    assert historical["horizons"] == [5, 10, 20]
    assert all(
        left["window_end_index"] < right["window_start_index"]
        for left, right in zip(
            historical["occurrences"], historical["occurrences"][1:], strict=False
        )
    )
