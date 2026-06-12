"""Analog engine: historical setups geometrically similar to today's chart.

Features are price/volume-only (computed on demand from prices, disclosed),
so the full price history is usable instead of the indicator warm-up window.
Outcomes follow the user's risk model exactly: enter at close, hard -3% stop
checked against future lows (gap-throughs measured), 15-trading-day time stop,
max-favorable-excursion for survivors. Search is cosine kNN in numpy.
"""

import logging

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)

PRICES_GLOB = "market-data/prices/1d/*.parquet"
SHAPE_BARS = 40
SHAPE_POINTS = 20
STOP_PERCENT = 3.0
HORIZON_BARS = 15
TOP_K = 30
SAME_SYMBOL_MIN_GAP_BARS = 7
SCALAR_FEATURES = (
    "ret_5", "ret_20", "atr_pct", "dist_60d_high", "dist_120d_high", "vol_ratio",
)
BREAKEVEN_WIN_RATE_PERCENT = 16.7  # at 3% stop / 15% average winner


class AnalogError(Exception):
    """Analog statistics cannot be computed."""


def _shape_columns(per_symbol: bool) -> list[pl.Expr]:
    """Lagged closes sampled every 2 bars over the SHAPE_BARS window."""
    lags = range(SHAPE_BARS - 2, -1, -2)  # 38, 36, ... 0 -> SHAPE_POINTS values
    columns = []
    for i, lag in enumerate(lags):
        expr = pl.col("close").shift(lag)
        if per_symbol:
            expr = expr.over("symbol")
        columns.append(expr.alias(f"shape_{i}"))
    return columns


def _feature_frame() -> pl.LazyFrame:
    """Per (symbol, day) features + forward outcome columns, whole universe."""
    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - pl.col("close").shift(1)).abs(),
        (pl.col("low") - pl.col("close").shift(1)).abs(),
    )
    future_min_low = pl.min_horizontal(
        *[pl.col("low").shift(-i).over("symbol") for i in range(1, HORIZON_BARS + 1)]
    )
    future_max_high = pl.max_horizontal(
        *[pl.col("high").shift(-i).over("symbol") for i in range(1, HORIZON_BARS + 1)]
    )
    return (
        pl.scan_parquet(PRICES_GLOB)
        .filter(~pl.col("symbol").str.starts_with("^"))  # indices are not tradable analogs
        .sort("symbol", "trade_timestamp")
        .with_columns(
            *_shape_columns(per_symbol=True),
            ret_5=(pl.col("close") / pl.col("close").shift(5) - 1).over("symbol") * 100,
            ret_20=(pl.col("close") / pl.col("close").shift(20) - 1).over("symbol") * 100,
            atr_pct=(tr.ewm_mean(span=14).over("symbol") / pl.col("close")) * 100,
            dist_60d_high=(pl.col("close") / pl.col("high").rolling_max(60).over("symbol") - 1) * 100,
            dist_120d_high=(pl.col("close") / pl.col("high").rolling_max(120).over("symbol") - 1) * 100,
            vol_ratio=pl.col("volume").rolling_mean(5).over("symbol")
            / pl.col("volume").rolling_mean(20).over("symbol"),
            bar_index=pl.int_range(pl.len()).over("symbol"),
            future_min_low=future_min_low,
            future_max_high=future_max_high,
            horizon_close=pl.col("close").shift(-HORIZON_BARS).over("symbol"),
        )
    )


def _stop_outcome_columns() -> list[pl.Expr]:
    """Outcome flags relative to entry at this row's close."""
    stop_price = pl.col("close") * (1 - STOP_PERCENT / 100)
    return [
        (pl.col("future_min_low") <= stop_price).alias("stopped"),
        ((pl.col("future_max_high") / pl.col("close") - 1) * 100).alias("mfe_percent"),
        ((pl.col("horizon_close") / pl.col("close") - 1) * 100).alias("horizon_return"),
    ]


def build_universe(symbol_exclude_tail: str) -> pl.DataFrame:
    """Materialize the candidate pool with features and outcomes.

    Rows of `symbol_exclude_tail` overlapping today's query window are dropped
    so the query cannot match itself.
    """
    shape_cols = [f"shape_{i}" for i in range(SHAPE_POINTS)]
    pool = (
        _feature_frame()
        .with_columns(_stop_outcome_columns())
        .with_columns(max_bar=pl.col("bar_index").max().over("symbol"))
        .filter(
            pl.col(shape_cols[0]).is_not_null()
            & pl.col("dist_120d_high").is_not_null()
            & pl.col("horizon_close").is_not_null()
            & ~(
                (pl.col("symbol") == symbol_exclude_tail)
                & (pl.col("bar_index") > pl.col("max_bar") - SHAPE_BARS - HORIZON_BARS)
            )
        )
        .select(
            "symbol", "trade_timestamp", "bar_index", "close",
            *shape_cols, *SCALAR_FEATURES,
            "stopped", "mfe_percent", "horizon_return",
        )
        .collect(engine="streaming")
    )
    if pool.height < 500:
        raise AnalogError(f"Candidate pool too small: {pool.height} rows")
    logger.info("Analog pool: %d candidate rows across universe", pool.height)
    return pool


def _matrix(frame: pl.DataFrame) -> np.ndarray:
    """Feature matrix: z-normalized shape per row + standardized scalars."""
    shape_cols = [f"shape_{i}" for i in range(SHAPE_POINTS)]
    shape = frame.select(shape_cols).to_numpy()
    shape_mean = shape.mean(axis=1, keepdims=True)
    shape_std = shape.std(axis=1, keepdims=True)
    bad = (shape_std == 0).ravel()
    if bad.any():
        raise AnalogError(f"{int(bad.sum())} rows have flat 40-bar windows — corrupt data")
    shape = (shape - shape_mean) / shape_std

    scalars = frame.select(SCALAR_FEATURES).to_numpy()
    col_mean = scalars.mean(axis=0, keepdims=True)
    col_std = scalars.std(axis=0, keepdims=True)
    if (col_std == 0).any():
        raise AnalogError("Degenerate scalar feature (zero variance across pool)")
    scalars = (scalars - col_mean) / col_std
    return np.hstack([shape / np.sqrt(SHAPE_POINTS), scalars / np.sqrt(len(SCALAR_FEATURES))])


def _select_neighbors(pool: pl.DataFrame, similarity: np.ndarray) -> list[int]:
    """Greedy top-K by similarity, skipping same-symbol rows within the overlap gap."""
    order = np.argsort(-similarity)
    chosen: list[int] = []
    seen: dict[str, list[int]] = {}
    symbols = pool["symbol"].to_list()
    bars = pool["bar_index"].to_list()
    for idx in order:
        symbol, bar = symbols[idx], bars[idx]
        if any(abs(bar - b) < SAME_SYMBOL_MIN_GAP_BARS for b in seen.get(symbol, [])):
            continue
        chosen.append(int(idx))
        seen.setdefault(symbol, []).append(bar)
        if len(chosen) == TOP_K:
            break
    if len(chosen) < 10:
        raise AnalogError(f"Only {len(chosen)} usable neighbors after dedup")
    return chosen


def _round_stat(value: object, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise AnalogError(f"Aggregate {label} is non-numeric: {value!r}")
    return round(float(value), 2)


def _neighbor_stats(neighbors: pl.DataFrame) -> dict:
    """Outcome statistics under the user's risk model."""
    survivors = neighbors.filter(~pl.col("stopped"))
    realized = neighbors.select(
        realized=pl.when(pl.col("stopped"))
        .then(-STOP_PERCENT)
        .otherwise(pl.col("horizon_return"))
    )["realized"]
    survivor_stats = (
        None
        if survivors.is_empty()
        else survivors.select(
            median_mfe=pl.col("mfe_percent").median(),
            p75_mfe=pl.col("mfe_percent").quantile(0.75),
            median_horizon=pl.col("horizon_return").median(),
        ).to_dicts()[0]
    )
    return {
        "n": neighbors.height,
        "stop_out_rate_percent": round(
            100 * neighbors["stopped"].sum() / neighbors.height, 1
        ),
        "survivors": {
            "count": survivors.height,
            "median_mfe_percent": (
                None if survivor_stats is None
                else _round_stat(survivor_stats["median_mfe"], "median_mfe")
            ),
            "p75_mfe_percent": (
                None if survivor_stats is None
                else _round_stat(survivor_stats["p75_mfe"], "p75_mfe")
            ),
            "median_horizon_return_percent": (
                None if survivor_stats is None
                else _round_stat(survivor_stats["median_horizon"], "median_horizon")
            ),
        },
        "mechanical_expectancy_percent": _round_stat(realized.mean(), "expectancy"),
        "breakeven_win_rate_percent": BREAKEVEN_WIN_RATE_PERCENT,
    }


def find_analogs(daily: pl.DataFrame, symbol: str) -> dict:
    """Top-K historical analogs of `symbol`'s latest bar + outcome statistics."""
    if daily.height < SHAPE_BARS + 21:
        raise AnalogError(f"{symbol}: {daily.height} bars < {SHAPE_BARS + 21} needed for query features")
    pool = build_universe(symbol_exclude_tail=symbol)
    query_pool = pl.concat([pool, _query_row(daily)], how="vertical_relaxed")
    matrix = _matrix(query_pool)
    query_vec = matrix[-1]
    similarity = matrix[:-1] @ query_vec / (
        np.linalg.norm(matrix[:-1], axis=1) * np.linalg.norm(query_vec)
    )
    chosen = _select_neighbors(pool, similarity)
    neighbors = pool[chosen].with_columns(
        similarity=pl.Series([round(float(similarity[i]), 3) for i in chosen])
    )
    stats = _neighbor_stats(neighbors)
    examples = (
        neighbors.head(8)
        .select("symbol", "trade_timestamp", "similarity", "stopped", "mfe_percent", "horizon_return")
        .with_columns(pl.col("trade_timestamp").cast(pl.String))
        .to_dicts()
    )
    return {
        "params": {
            "shape_bars": SHAPE_BARS,
            "stop_percent": STOP_PERCENT,
            "horizon_bars": HORIZON_BARS,
            "top_k": TOP_K,
            "features": "price/volume only, calculated on demand (not precalc indicators)",
        },
        "stats": stats,
        "nearest_examples": examples,
    }


def _query_row(daily: pl.DataFrame) -> pl.DataFrame:
    """Build the query feature row from the symbol's full daily frame."""
    shape_cols = [f"shape_{i}" for i in range(SHAPE_POINTS)]
    return (
        _frame_features_for(daily)
        .tail(1)
        .select(
            "symbol", "trade_timestamp", "bar_index", "close",
            *shape_cols, *SCALAR_FEATURES,
            pl.lit(False).alias("stopped"),
            pl.lit(0.0).alias("mfe_percent"),
            pl.lit(0.0).alias("horizon_return"),
        )
    )


def _frame_features_for(daily: pl.DataFrame) -> pl.DataFrame:
    """Same feature expressions as the universe scan, on one in-memory frame."""
    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - pl.col("close").shift(1)).abs(),
        (pl.col("low") - pl.col("close").shift(1)).abs(),
    )
    out = daily.select("symbol", "trade_timestamp", "open", "high", "low", "close", "volume").with_columns(
        *_shape_columns(per_symbol=False),
        ret_5=(pl.col("close") / pl.col("close").shift(5) - 1) * 100,
        ret_20=(pl.col("close") / pl.col("close").shift(20) - 1) * 100,
        atr_pct=(tr.ewm_mean(span=14) / pl.col("close")) * 100,
        dist_60d_high=(pl.col("close") / pl.col("high").rolling_max(60) - 1) * 100,
        dist_120d_high=(pl.col("close") / pl.col("high").rolling_max(120) - 1) * 100,
        vol_ratio=pl.col("volume").rolling_mean(5) / pl.col("volume").rolling_mean(20),
        bar_index=pl.int_range(pl.len()),
    )
    last = out.tail(1)
    nulls = [c for c in ["shape_0", *SCALAR_FEATURES] if last[c][0] is None]
    if nulls:
        raise AnalogError(f"Query features incomplete (insufficient lookback): {nulls}")
    return out
