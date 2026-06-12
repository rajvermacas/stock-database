"""Market context: benchmark index regime + universe breadth.

Index data lives in market-data/prices/1d/^*.parquet, managed by the main
stock-data pipeline (indices are listed in metadata/symbols.csv). If an index
file is missing or stale, the fix is:

    .venv/bin/stock-data --config config/stock-data-1d.toml update-symbol '^NSEI'

Breadth is computed over the stock universe only — index symbols (^*) excluded.
"""

import logging

import polars as pl

import tf_data

logger = logging.getLogger(__name__)

REGIME_INDICES = ("^NSEI", "^CRSLDX", "^NSEMDCP50")
PRICES_GLOB = "market-data/prices/1d/*.parquet"
INDICATORS_GLOB = "market-data/indicators/1d/*.parquet"
NEAR_HIGH_PERCENT = 5.0


class MarketContextError(Exception):
    """Regime or breadth facts cannot be computed."""


def index_regime(symbol: str) -> dict:
    """Trend state of one benchmark index from its precalculated indicators."""
    frame = tf_data.load_joined(symbol, "1d")
    tf_data.check_freshness(frame, symbol, "1d")
    with_indicators = frame.filter(pl.col("ema_200").is_not_null())
    if with_indicators.is_empty():
        raise MarketContextError(f"{symbol}: no indicator bars (warm-up incomplete)")
    last = with_indicators.tail(1).to_dicts()[0]
    return {
        "last_bar": str(last["trade_timestamp"]),
        "close": round(last["close"], 2),
        "close_above_ema_200": last["close"] > last["ema_200"],
        "close_above_ema_50": last["close"] > last["ema_50"],
        "ema_50_above_ema_200": last["ema_50"] > last["ema_200"],
        "distance_from_365d_high_percent": round(
            last["distance_from_365d_high_percent"], 2
        ),
        "roc_20_percent": round(last["roc_20"], 2),
    }


def universe_breadth() -> dict:
    """Breadth internals across the stock universe (latest bar per symbol)."""
    prices_last = (
        pl.scan_parquet(PRICES_GLOB)
        .filter(~pl.col("symbol").str.starts_with("^"))
        .group_by("symbol")
        .agg(
            price_ts=pl.col("trade_timestamp").max(),
            close=pl.col("close").sort_by("trade_timestamp").last(),
        )
    )
    indicators_last = (
        pl.scan_parquet(INDICATORS_GLOB)
        .filter(~pl.col("symbol").str.starts_with("^"))
        .group_by("symbol")
        .agg(
            indicator_ts=pl.col("trade_timestamp").max(),
            ema_50=pl.col("ema_50").sort_by("trade_timestamp").last(),
            ema_200=pl.col("ema_200").sort_by("trade_timestamp").last(),
            trailing_365d_high=pl.col("trailing_365d_high")
            .sort_by("trade_timestamp").last(),
        )
    )
    joined = prices_last.join(indicators_last, on="symbol", how="inner").filter(
        pl.col("price_ts") == pl.col("indicator_ts")
    )
    stats = joined.select(
        n=pl.len(),
        pct_above_ema_200=(pl.col("close") > pl.col("ema_200")).mean() * 100,
        pct_above_ema_50=(pl.col("close") > pl.col("ema_50")).mean() * 100,
        pct_near_365d_high=(
            pl.col("close") >= pl.col("trailing_365d_high") * (1 - NEAR_HIGH_PERCENT / 100)
        ).mean() * 100,
        last_bar=pl.col("price_ts").max(),
    ).collect(engine="streaming").to_dicts()[0]
    total_symbols = (
        pl.scan_parquet(PRICES_GLOB)
        .filter(~pl.col("symbol").str.starts_with("^"))
        .select(pl.col("symbol").n_unique())
        .collect(engine="streaming")
        .item()
    )
    if stats["n"] == 0:
        raise MarketContextError("Breadth join produced zero symbols — data misaligned")
    logger.info(
        "Breadth: %d/%d symbols included (excluded: missing indicators or misaligned last bar)",
        stats["n"], total_symbols,
    )
    return {
        "symbols_included": stats["n"],
        "symbols_total": total_symbols,
        "pct_above_ema_200": round(stats["pct_above_ema_200"], 1),
        "pct_above_ema_50": round(stats["pct_above_ema_50"], 1),
        "pct_within_5pct_of_365d_high": round(stats["pct_near_365d_high"], 1),
        "as_of": str(stats["last_bar"]),
    }


def market_context() -> dict:
    """Full regime + breadth block for the fact document."""
    return {
        "indices": {symbol: index_regime(symbol) for symbol in REGIME_INDICES},
        "breadth": universe_breadth(),
        "note": (
            "context, not a gate: weak regime caps grade, never auto-rejects; "
            "no NSE smallcap index available on Yahoo"
        ),
    }
