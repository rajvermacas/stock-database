from __future__ import annotations

import numpy as np
import polars as pl

FRACTION_FEATURES = (
    "log_return",
    "true_range_fraction",
    "gap_fraction",
    "body_fraction",
    "close_location",
    "log_volume_change",
    "expanding_drawdown",
    "expanding_runup",
)
REGIME_FEATURES = (
    "log_return",
    "true_range_fraction",
    "gap_fraction",
    "body_fraction",
    "close_location",
    "log_volume_change",
    "directional_run",
    "expanding_drawdown",
    "expanding_runup",
)


def causal_features(prices: pl.DataFrame) -> pl.DataFrame:
    _validate_input(prices)
    frame = _add_bar_features(prices)
    frame = _add_path_features(frame)
    return frame.with_row_index("bar_index")


def finite_feature_matrix(
    features: pl.DataFrame, columns: tuple[str, ...] = REGIME_FEATURES
) -> tuple[np.ndarray, np.ndarray]:
    values = features.select(columns).to_numpy()
    finite = np.isfinite(values).all(axis=1)
    return values[finite], np.flatnonzero(finite)


def _add_bar_features(prices: pl.DataFrame) -> pl.DataFrame:
    previous = pl.col("close").shift(1)
    bar_range = pl.col("high") - pl.col("low")
    true_range = pl.max_horizontal(
        bar_range,
        (pl.col("high") - previous).abs(),
        (pl.col("low") - previous).abs(),
    )
    return prices.with_columns(
        pl.col("close").log().diff().alias("log_return"),
        (true_range / previous).alias("true_range_fraction"),
        ((pl.col("open") / previous) - 1).alias("gap_fraction"),
        _safe_divide(pl.col("close") - pl.col("open"), bar_range).alias(
            "body_fraction"
        ),
        _safe_divide(pl.col("close") - pl.col("low"), bar_range).alias(
            "close_location"
        ),
        pl.col("volume").cast(pl.Float64).log1p().diff().alias("log_volume_change"),
    )


def _add_path_features(frame: pl.DataFrame) -> pl.DataFrame:
    signs = np.sign(frame["close"].diff().fill_null(0).to_numpy())
    directional_run = _directional_runs(signs)
    return frame.with_columns(
        pl.Series("directional_run", directional_run, dtype=pl.Int64),
        ((pl.col("close") / pl.col("high").cum_max()) - 1).alias(
            "expanding_drawdown"
        ),
        ((pl.col("close") / pl.col("low").cum_min()) - 1).alias("expanding_runup"),
    )


def _safe_divide(numerator: pl.Expr, denominator: pl.Expr) -> pl.Expr:
    return pl.when(denominator != 0).then(numerator / denominator).otherwise(None)


def _directional_runs(signs: np.ndarray) -> list[int]:
    runs: list[int] = []
    previous = 0
    length = 0
    for raw in signs:
        sign = int(raw)
        if sign == 0:
            length = 0
        elif sign == previous:
            length += sign
        else:
            length = sign
        runs.append(length)
        previous = sign
    return runs


def _validate_input(prices: pl.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume", "trade_timestamp"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"price data missing columns: {sorted(missing)}")
    if prices.is_empty():
        raise ValueError("price data is empty")
