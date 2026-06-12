"""Phase-4 backtest: does the setup taxonomy carry edge in this universe?

Vectorized proxies of the live classifier's entry conditions are scored on
every (symbol, day) of price history, then judged under the user's risk model:
enter at close, hard -3% stop against future lows, 15-trading-day time stop,
MFE for survivors. Each setup is split by the extension veto so the veto's
value is itself measured. Results compare against the all-days baseline.

DISCLOSURE: these are proxies, not the live classifier — pivot-cluster levels
are approximated with rolling extremes, and EMAs/ATR are calculated on demand
from prices (first 60 bars trimmed for warm-up). Directionally valid, not
bar-identical to evaluate.py.

Usage: .venv/bin/python .claude/skills/swing-buy-check/scripts/backtest.py
"""

import json
import logging
import sys

import polars as pl

logger = logging.getLogger("backtest")

PRICES_GLOB = "market-data/prices/1d/*.parquet"
STOP_PERCENT = 3.0
HORIZON_BARS = 15
WARMUP_BARS = 60
BREAKOUT_LOOKBACK = 120
BOUNCE_LOOKBACK = 20
MIN_GROUP_ROWS = 100


class BacktestError(Exception):
    """Backtest cannot be computed."""


def _indicator_columns() -> list[pl.Expr]:
    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - pl.col("close").shift(1)).abs(),
        (pl.col("low") - pl.col("close").shift(1)).abs(),
    )
    return [
        pl.col("close").ewm_mean(span=20).over("symbol").alias("ema_20"),
        pl.col("close").ewm_mean(span=50).over("symbol").alias("ema_50"),
        pl.col("close").ewm_mean(span=200).over("symbol").alias("ema_200"),
        tr.ewm_mean(span=14).over("symbol").alias("atr"),
        pl.int_range(pl.len()).over("symbol").alias("bar_index"),
    ]


def _outcome_columns() -> list[pl.Expr]:
    future_min_low = pl.min_horizontal(
        *[pl.col("low").shift(-i).over("symbol") for i in range(1, HORIZON_BARS + 1)]
    )
    future_max_high = pl.max_horizontal(
        *[pl.col("high").shift(-i).over("symbol") for i in range(1, HORIZON_BARS + 1)]
    )
    stop_price = pl.col("close") * (1 - STOP_PERCENT / 100)
    return [
        (future_min_low <= stop_price).alias("stopped"),
        ((future_max_high / pl.col("close") - 1) * 100).alias("mfe_percent"),
        ((pl.col("close").shift(-HORIZON_BARS).over("symbol") / pl.col("close") - 1) * 100)
        .alias("horizon_return"),
    ]


def _setup_columns() -> list[pl.Expr]:
    """Vectorized proxies of the live classifier's three setup types."""
    uptrend = (pl.col("close") > pl.col("ema_200")) & (
        pl.col("ema_50") > pl.col("ema_50").shift(10).over("symbol")
    )
    prior_high = (
        pl.col("close").shift(1).rolling_max(BREAKOUT_LOOKBACK).over("symbol")
    )
    near_rising_ema = (
        (
            ((pl.col("close") - pl.col("ema_20")).abs() / pl.col("atr") <= 0.75)
            & (pl.col("ema_20") > pl.col("ema_20").shift(10).over("symbol"))
        )
        | (
            ((pl.col("close") - pl.col("ema_50")).abs() / pl.col("atr") <= 0.75)
            & (pl.col("ema_50") > pl.col("ema_50").shift(10).over("symbol"))
        )
    )
    prior_low_zone = (
        pl.col("low").shift(1).rolling_min(BOUNCE_LOOKBACK).over("symbol")
        + 0.5 * pl.col("atr")
    )
    return [
        (
            (pl.col("close") > prior_high)
            & (pl.col("close").shift(1) <= prior_high.shift(1)).over("symbol")
            & ((pl.col("close") - prior_high) / pl.col("atr") <= 1.0)
        ).alias("breakout"),
        (uptrend & near_rising_ema).alias("ema_pullback"),
        (
            uptrend
            & (pl.col("low") <= prior_low_zone)
            & (pl.col("close") > pl.col("open"))
        ).alias("support_bounce"),
        ((pl.col("close") - pl.col("ema_20")) / pl.col("atr") > 2.0).alias("extended"),
    ]


def build_scored_frame() -> pl.DataFrame:
    frame = (
        pl.scan_parquet(PRICES_GLOB)
        .filter(~pl.col("symbol").str.starts_with("^"))
        .sort("symbol", "trade_timestamp")
        .with_columns(_indicator_columns())
        .with_columns(_setup_columns())
        .with_columns(_outcome_columns())
        .filter(
            (pl.col("bar_index") >= WARMUP_BARS)
            & pl.col("horizon_return").is_not_null()
            & (pl.col("atr") > 0)
        )
        .select(
            "symbol", "trade_timestamp",
            "breakout", "ema_pullback", "support_bounce", "extended",
            "stopped", "mfe_percent", "horizon_return",
        )
        .collect(engine="streaming")
    )
    if frame.height < 5000:
        raise BacktestError(f"Scored frame too small: {frame.height} rows")
    logger.info("Scored %d (symbol, day) rows", frame.height)
    return frame


def group_stats(group: pl.DataFrame) -> dict | None:
    if group.height < MIN_GROUP_ROWS:
        return None
    survivors = group.filter(~pl.col("stopped"))
    stats = group.select(
        n=pl.len(),
        stop_out_rate=pl.col("stopped").mean() * 100,
        expectancy=pl.when(pl.col("stopped"))
        .then(-STOP_PERCENT)
        .otherwise(pl.col("horizon_return"))
        .mean(),
    ).to_dicts()[0]
    survivor_mfe = (
        None if survivors.is_empty()
        else survivors.select(pl.col("mfe_percent").median()).item()
    )
    return {
        "n": stats["n"],
        "stop_out_rate_percent": round(stats["stop_out_rate"], 1),
        "mechanical_expectancy_percent": round(stats["expectancy"], 2),
        "survivor_median_mfe_percent": (
            None if survivor_mfe is None else round(survivor_mfe, 2)
        ),
    }


def run_backtest() -> dict:
    frame = build_scored_frame()
    report: dict = {
        "params": {
            "stop_percent": STOP_PERCENT,
            "horizon_bars": HORIZON_BARS,
            "universe_rows": frame.height,
            "date_range": [
                str(frame["trade_timestamp"].min()),
                str(frame["trade_timestamp"].max()),
            ],
            "method": "vectorized proxies; EMAs/ATR on demand; 60-bar warm-up trimmed",
        },
        "baseline_all_days": group_stats(frame),
        "setups": {},
    }
    for setup in ("breakout", "ema_pullback", "support_bounce"):
        matched = frame.filter(pl.col(setup))
        report["setups"][setup] = {
            "all": group_stats(matched),
            "veto_passed": group_stats(matched.filter(~pl.col("extended"))),
            "veto_failed": group_stats(matched.filter(pl.col("extended"))),
        }
    report["extension_veto_check"] = {
        "extended_days_all": group_stats(frame.filter(pl.col("extended"))),
        "non_extended_days_all": group_stats(frame.filter(~pl.col("extended"))),
    }
    return report


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    json.dump(run_backtest(), sys.stdout, indent=1, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
