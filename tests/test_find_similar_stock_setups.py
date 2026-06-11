import importlib.util
import sys
from pathlib import Path

import polars as pl
import pytest

SCRIPT = Path(
    ".agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py"
)
SPEC = importlib.util.spec_from_file_location("find_similar_stock_setups", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
similarity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = similarity
SPEC.loader.exec_module(similarity)


def test_constants_define_fixed_version_one_semantics() -> None:
    assert similarity.WINDOW == 10
    assert similarity.MAX_MATCHES == 200
    assert similarity.FUTURE_PERIODS == (5, 10, 20, 30)
    assert similarity.CORPORATE_ACTION_THRESHOLD == 0.40
    assert len(similarity.SUBGROUPS) == 6


def test_invalid_symbol_fails_fast() -> None:
    with pytest.raises(similarity.SimilarityError, match="symbol"):
        similarity.validate_symbol("")


def test_select_non_overlapping_prefers_best_ranked_windows() -> None:
    ranked = pl.DataFrame(
        {
            "window_start_index": [0, 5, 10, 20],
            "window_end_index": [9, 14, 19, 29],
            "combined_distance": [0.1, 0.2, 0.3, 0.4],
        }
    )
    selected = similarity.select_non_overlapping(ranked, 200)
    assert selected["window_start_index"].to_list() == [0, 10, 20]


def test_window_list_preserves_ordered_ten_day_path() -> None:
    result = (
        pl.DataFrame({"value": list(range(12))})
        .lazy()
        .select(similarity._window_list(pl.col("value")).alias("path"))
        .collect()
    )
    assert result["path"][-1].to_list() == list(range(2, 12))


def test_context_gates_reject_mismatched_regimes() -> None:
    candidates = pl.DataFrame(
        {
            "candidate": ["matching", "wrong_direction"],
            "direction_regime": ["rising", "falling"],
            "ema_50_side": [1, 1],
            "ema_200_side": [1, 1],
            "volatility_regime": ["medium", "medium"],
            "yearly_position_regime": ["near_high", "near_high"],
            "has_corporate_action_jump": [False, False],
        }
    ).lazy()
    latest = {
        "direction_regime": "rising",
        "ema_50_side": 1,
        "ema_200_side": 1,
        "volatility_regime": "medium",
        "yearly_position_regime": "near_high",
    }
    result = similarity._same_context(candidates, latest).collect()
    assert result["candidate"].to_list() == ["matching"]


def test_real_window_vectors_preserve_full_paths() -> None:
    frame = similarity.load_symbol_frame(
        "CHENNPETRO.NS", Path("market-data/prices"), Path("market-data/indicators")
    )
    thresholds = similarity._atr_thresholds(similarity._candidate_windows(frame))
    latest = similarity._latest_window(frame, *thresholds)
    assert len(latest["chart_shape_vector"][0]) == 50
    assert len(latest["volume_vector"][0]) == 30
    assert len(latest["candle_volatility_vector"][0]) == 41


def test_real_query_returns_auditable_non_overlapping_matches() -> None:
    result = similarity.find_similar_setups(
        "CHENNPETRO.NS", Path("market-data/prices"), Path("market-data/indicators")
    )
    assert result["metadata"]["source_interval"] == "1d"
    assert result["metadata"]["warning"] == (
        "Prices are adjusted for corporate actions; volume is Yahoo-provided."
    )
    assert 0 < result["metadata"]["match_count"] <= 200
    matches = result["matches"]
    assert all("combined_distance" in row for row in matches)
    assert all("chart_shape_distance" in row for row in matches)
    ranges = [
        (pl.Series([row["window_start"]]).str.to_datetime()[0],
         pl.Series([row["window_end"]]).str.to_datetime()[0])
        for row in matches
    ]
    assert all(
        end_a < start_b or end_b < start_a
        for index, (start_a, end_a) in enumerate(ranges)
        for start_b, end_b in ranges[index + 1 :]
    )
