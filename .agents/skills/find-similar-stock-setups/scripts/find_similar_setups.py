from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

WINDOW = 10
MAX_MATCHES = 200
FUTURE_PERIODS = (5, 10, 20, 30)
CORPORATE_ACTION_THRESHOLD = 0.40
SUBGROUPS = (
    "chart_shape",
    "pace",
    "candle_volatility",
    "volume",
    "trend_context",
    "momentum",
)
LOGGER = logging.getLogger("find_similar_stock_setups")


class SimilarityError(ValueError):
    """Raised when a similarity query cannot be completed."""


def validate_symbol(symbol: str) -> None:
    if not symbol or "/" in symbol or "\\" in symbol:
        raise SimilarityError(f"Invalid symbol: {symbol!r}")


def _load_stock_frame():
    path = (
        Path(__file__).resolve().parents[2]
        / "talk-to-stock-data"
        / "scripts"
        / "stock_frame.py"
    )
    spec = importlib.util.spec_from_file_location("similarity_stock_frame", path)
    if spec is None or spec.loader is None:
        raise SimilarityError(f"Unable to import stock-frame helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_symbol_frame(
    symbol: str, prices_root: Path, indicators_root: Path
) -> pl.LazyFrame:
    validate_symbol(symbol)
    helper = _load_stock_frame()
    try:
        return helper.load_prices_with_indicators(
            "1d", prices_root, indicators_root, [symbol], None, None
        )
    except Exception as exc:
        raise SimilarityError(f"Unable to load exact daily data for {symbol}: {exc}") from exc


def _window_list(expression: pl.Expr) -> pl.Expr:
    return pl.concat_list([expression.shift(offset) for offset in range(WINDOW - 1, -1, -1)])


def _base_features(frame: pl.LazyFrame) -> pl.LazyFrame:
    return frame.with_row_index("row_index").with_columns(
        close_return=pl.col("close").pct_change(),
        gap=(pl.col("open") / pl.col("close").shift(1) - 1),
        intraday_range=(pl.col("high") / pl.col("low") - 1),
        candle_body=(pl.col("close") / pl.col("open") - 1),
        volume_change=(
            pl.col("volume").cast(pl.Float64).log1p()
            - pl.col("volume").cast(pl.Float64).shift(1).log1p()
        ),
        volume_mean=pl.col("volume").cast(pl.Float64).rolling_mean(WINDOW),
        position_365=(
            (pl.col("close") - pl.col("trailing_365d_low"))
            / (pl.col("trailing_365d_high") - pl.col("trailing_365d_low"))
        ),
    )


def _path_columns(frame: pl.LazyFrame) -> pl.LazyFrame:
    expressions: list[pl.Expr] = []
    for column in ("open", "high", "low", "close"):
        expressions.append(
            _window_list(pl.col(column) / pl.col("close").shift(WINDOW - 1) - 1)
            .alias(f"path_{column}")
        )
    for column in (
        "close_return",
        "gap",
        "intraday_range",
        "candle_body",
        "volume_change",
        "relative_volume_20",
        "atr_percent_14",
        "rsi_14",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "roc_20",
        "band_width_20_2",
    ):
        expressions.append(_window_list(pl.col(column)).alias(f"path_{column}"))
    expressions.append(
        _window_list(pl.col("volume").cast(pl.Float64) / pl.col("volume_mean"))
        .alias("path_normalized_volume")
    )
    return frame.with_columns(expressions)


def _context_columns(frame: pl.LazyFrame) -> pl.LazyFrame:
    return frame.with_columns(
        return_10=pl.col("close") / pl.col("close").shift(WINDOW - 1) - 1,
        pace_slope=(pl.col("close") / pl.col("close").shift(WINDOW - 1) - 1)
        / (WINDOW - 1),
        pace_acceleration=(
            (pl.col("close") / pl.col("close").shift(4) - 1)
            - (pl.col("close").shift(5) / pl.col("close").shift(9) - 1)
        ),
        up_ratio=(pl.col("close_return") > 0).cast(pl.Float64).rolling_mean(WINDOW),
        max_up=pl.col("close_return").rolling_max(WINDOW),
        max_down=pl.col("close_return").rolling_min(WINDOW),
        realized_vol=pl.col("close_return").rolling_std(WINDOW, ddof=0),
        has_corporate_action_jump=pl.col("close_return")
        .abs()
        .rolling_max(WINDOW)
        .gt(CORPORATE_ACTION_THRESHOLD),
        window_start_index=pl.col("row_index") - WINDOW + 1,
        window_end_index=pl.col("row_index"),
        window_start=pl.col("trade_timestamp").shift(WINDOW - 1),
        window_end=pl.col("trade_timestamp"),
    ).with_columns(
        direction_regime=pl.when(pl.col("return_10").abs() < 0.02)
        .then(pl.lit("sideways"))
        .when(pl.col("return_10") > 0)
        .then(pl.lit("rising"))
        .otherwise(pl.lit("falling")),
        ema_50_side=(pl.col("close") >= pl.col("ema_50")).cast(pl.Int8),
        ema_200_side=(pl.col("close") >= pl.col("ema_200")).cast(pl.Int8),
        yearly_position_regime=pl.when(pl.col("position_365") < 1 / 3)
        .then(pl.lit("near_low"))
        .when(pl.col("position_365") < 2 / 3)
        .then(pl.lit("middle"))
        .otherwise(pl.lit("near_high")),
    )


def _vector_columns(frame: pl.LazyFrame) -> pl.LazyFrame:
    trend = [
        pl.col("close") / pl.col(f"ema_{period}") - 1
        for period in (10, 20, 50, 100, 200)
    ] + [
        pl.col("distance_from_365d_high_percent"),
        pl.col("position_365"),
        pl.col("adx_14"),
        pl.col("plus_di_14"),
        pl.col("minus_di_14"),
    ]
    momentum = [
        pl.col("rsi_14"),
        pl.col("macd_12_26") / pl.col("close"),
        pl.col("macd_signal_9") / pl.col("close"),
        pl.col("macd_histogram") / pl.col("close"),
        pl.col("roc_20"),
        pl.col("band_width_20_2"),
        pl.col("obv") / pl.col("obv").shift(WINDOW - 1) - 1,
    ]
    return frame.with_columns(
        chart_shape_vector=pl.concat_list(
            ["path_open", "path_high", "path_low", "path_close", "path_close_return"]
        ),
        pace_vector=pl.concat_list(
            ["return_10", "pace_slope", "pace_acceleration", "up_ratio", "max_up", "max_down"]
        ),
        candle_volatility_vector=pl.concat_list(
            ["path_gap", "path_intraday_range", "path_candle_body", "realized_vol", "path_atr_percent_14"]
        ),
        volume_vector=pl.concat_list(
            [
                "path_normalized_volume",
                "path_volume_change",
                "path_relative_volume_20",
            ]
        ),
        trend_context_vector=pl.concat_list(trend),
        momentum_vector=pl.concat_list(momentum),
    )


def _with_volatility_regime(
    frame: pl.LazyFrame, low_threshold: float, high_threshold: float
) -> pl.LazyFrame:
    return frame.with_columns(
        volatility_regime=pl.when(pl.col("atr_percent_14") <= low_threshold)
        .then(pl.lit("low"))
        .when(pl.col("atr_percent_14") <= high_threshold)
        .then(pl.lit("medium"))
        .otherwise(pl.lit("high"))
    )


def _all_window_features(frame: pl.LazyFrame) -> pl.LazyFrame:
    return (
        _vector_columns(_context_columns(_path_columns(_base_features(frame))))
        .filter(pl.col("row_index") >= WINDOW - 1)
    )


def _candidate_windows(frame: pl.LazyFrame) -> pl.LazyFrame:
    return _all_window_features(frame).filter(
        pl.col("row_index") <= pl.col("row_index").max() - max(FUTURE_PERIODS)
    )


def _atr_thresholds(candidates: pl.LazyFrame) -> tuple[float, float]:
    thresholds = candidates.select(
        pl.col("atr_percent_14").quantile(1 / 3).alias("low"),
        pl.col("atr_percent_14").quantile(2 / 3).alias("high"),
    ).collect().row(0, named=True)
    if thresholds["low"] is None or thresholds["high"] is None:
        raise SimilarityError("Insufficient candidate history for volatility regimes")
    return thresholds["low"], thresholds["high"]


def _latest_window(
    frame: pl.LazyFrame, low_threshold: float, high_threshold: float
) -> pl.DataFrame:
    latest = (
        _with_volatility_regime(
            _all_window_features(frame), low_threshold, high_threshold
        )
        .filter(pl.col("row_index") == pl.col("row_index").max())
        .collect()
    )
    if latest.is_empty():
        raise SimilarityError("Latest 10-day setup is unavailable")
    if latest["has_corporate_action_jump"][0]:
        raise SimilarityError("Latest setup contains a likely corporate-action jump")
    return latest


def _same_context(candidates: pl.LazyFrame, latest: dict[str, Any]) -> pl.LazyFrame:
    filters = [
        pl.col("direction_regime") == latest["direction_regime"],
        pl.col("ema_50_side") == latest["ema_50_side"],
        pl.col("ema_200_side") == latest["ema_200_side"],
        pl.col("volatility_regime") == latest["volatility_regime"],
        pl.col("yearly_position_regime") == latest["yearly_position_regime"],
        ~pl.col("has_corporate_action_jump"),
    ]
    return candidates.filter(pl.all_horizontal(filters))


def _standardized_distance(vector: str, latest: list[float]) -> pl.Expr:
    components = []
    for index, value in enumerate(latest):
        candidate = pl.col(vector).list.get(index)
        components.append(((candidate - value) / candidate.std(ddof=0)).pow(2))
    return pl.mean_horizontal(components)


def calculate_distances(candidates: pl.LazyFrame, latest: dict[str, Any]) -> pl.LazyFrame:
    raw_names = []
    expressions = []
    for group in SUBGROUPS:
        raw = f"{group}_raw_distance"
        raw_names.append(raw)
        expressions.append(
            _standardized_distance(
                f"{group}_vector", list(latest[f"{group}_vector"])
            ).alias(raw)
        )
    with_raw = candidates.with_columns(expressions)
    medians = with_raw.select(
        *[pl.col(name).median().alias(f"{name}_median") for name in raw_names]
    )
    scaled = with_raw.join(medians, how="cross").with_columns(
        *[
            (pl.col(raw) / pl.col(f"{raw}_median")).alias(f"{group}_distance")
            for group, raw in zip(SUBGROUPS, raw_names, strict=True)
        ]
    )
    return scaled.with_columns(
        combined_distance=pl.mean_horizontal(
            [pl.col(f"{group}_distance") for group in SUBGROUPS]
        )
    )


def attach_future_outcomes(frame: pl.LazyFrame) -> pl.LazyFrame:
    outcomes = [
        (pl.col("close").shift(-period) / pl.col("close") - 1).alias(
            f"return_{period}"
        )
        for period in FUTURE_PERIODS
    ]
    future_highs = [pl.col("high").shift(-i) / pl.col("close") - 1 for i in range(1, 31)]
    future_lows = [pl.col("low").shift(-i) / pl.col("close") - 1 for i in range(1, 31)]
    future_closes = [pl.col("close").shift(-i) for i in range(0, 31)]
    drawdowns = [
        future_closes[j] / future_closes[i] - 1
        for i in range(30)
        for j in range(i + 1, 31)
    ]
    return frame.with_columns(
        *outcomes,
        mfe_30=pl.max_horizontal(future_highs),
        mae_30=pl.min_horizontal(future_lows),
        max_close_drawdown_30=pl.min_horizontal(drawdowns),
    )


def select_non_overlapping(ranked: pl.DataFrame, limit: int) -> pl.DataFrame:
    selected: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for row in ranked.iter_rows(named=True):
        interval = (row["window_start_index"], row["window_end_index"])
        if any(interval[0] <= end and start <= interval[1] for start, end in occupied):
            continue
        selected.append(row)
        occupied.append(interval)
        if len(selected) == limit:
            break
    if not selected:
        raise SimilarityError("No non-overlapping historical matches survived")
    return pl.DataFrame(selected, schema=ranked.schema)


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise SimilarityError("Result contains non-finite values")
    return value


def _summary(matches: pl.DataFrame) -> dict[str, Any]:
    return matches.select(
        *[pl.col(f"return_{period}").mean().alias(f"mean_return_{period}") for period in FUTURE_PERIODS],
        pl.col("mfe_30").mean().alias("mean_mfe_30"),
        pl.col("mae_30").mean().alias("mean_mae_30"),
        pl.col("max_close_drawdown_30").mean().alias("mean_max_close_drawdown_30"),
    ).row(0, named=True)


def find_similar_setups(
    symbol: str, prices_root: Path, indicators_root: Path
) -> dict[str, Any]:
    frame = attach_future_outcomes(load_symbol_frame(symbol, prices_root, indicators_root))
    candidate_windows = _candidate_windows(frame)
    low_threshold, high_threshold = _atr_thresholds(candidate_windows)
    latest_frame = _latest_window(frame, low_threshold, high_threshold)
    latest = latest_frame.row(0, named=True)
    candidates = _with_volatility_regime(
        candidate_windows, low_threshold, high_threshold
    )
    counts = candidates.select(
        pl.len().alias("eligible_candidate_count"),
        pl.col("has_corporate_action_jump").sum().alias("jump_excluded_count"),
    ).collect().row(0, named=True)
    gated = _same_context(candidates, latest)
    ranked = (
        calculate_distances(gated, latest)
        .sort(["combined_distance", "window_end"])
        .collect()
    )
    if ranked.is_empty():
        raise SimilarityError("No historical candidates survived context gates")
    matches = select_non_overlapping(ranked, MAX_MATCHES)
    output_columns = [
        "window_start",
        "window_end",
        "combined_distance",
        *[f"{group}_distance" for group in SUBGROUPS],
        *[f"return_{period}" for period in FUTURE_PERIODS],
        "mfe_30",
        "mae_30",
        "max_close_drawdown_30",
    ]
    records = [
        {key: _serialize(value) for key, value in row.items()}
        for row in matches.select(output_columns).iter_rows(named=True)
    ]
    LOGGER.info("symbol=%s candidates=%d matches=%d", symbol, ranked.height, matches.height)
    return {
        "metadata": {
            "symbol": symbol,
            "source_interval": "1d",
            "derived": False,
            "latest_setup_start": _serialize(latest["window_start"]),
            "latest_setup_end": _serialize(latest["window_end"]),
            "latest_close": latest["close"],
            **counts,
            "context_rejected_count": counts["eligible_candidate_count"] - ranked.height,
            "surviving_candidate_count": ranked.height,
            "match_count": matches.height,
            "warning": "Prices are adjusted for corporate actions; volume is Yahoo-provided.",
        },
        "summary": _summary(matches),
        "matches": records,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--prices-root", required=True, type=Path)
    parser.add_argument("--indicators-root", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = _arguments()
    print(json.dumps(find_similar_setups(args.symbol, args.prices_root, args.indicators_root)))


if __name__ == "__main__":
    main()
