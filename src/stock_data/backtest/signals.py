from __future__ import annotations

from collections.abc import Callable

import polars as pl

# Fixed strategy-intrinsic thresholds (NOT optimized — spec 5.2).
PULLBACK_LOOKBACK = 5
PULLBACK_RSI_COOL = 45.0
EMA_FRESH_LOOKBACK = 5
BREAKOUT_REL_VOL = 1.5
RSI_DIP_LOOKBACK = 5
RSI_DIP_LOW = 40.0
RSI_DIP_RECLAIM = 50.0
ADX_TREND = 25.0

SignalFn = Callable[[pl.DataFrame], pl.Series]


def _series(frame: pl.DataFrame, expr: pl.Expr) -> pl.Series:
    return frame.select(expr.alias("entry"))["entry"].fill_null(False)


def pullback_buy(frame: pl.DataFrame) -> pl.Series:
    uptrend = (
        pl.col("weekly_uptrend")
        & (pl.col("ema_10") > pl.col("ema_20"))
        & (pl.col("ema_20") > pl.col("ema_50"))
    )
    pulled = pl.col("low").rolling_min(PULLBACK_LOOKBACK) <= pl.col("ema_20")
    cooled = pl.col("rsi_14").rolling_min(PULLBACK_LOOKBACK) < PULLBACK_RSI_COOL
    reclaim = (pl.col("close") > pl.col("ema_10")) & (
        pl.col("close").shift(1) <= pl.col("ema_10").shift(1)
    )
    return _series(frame, uptrend & pulled & cooled & reclaim)


def ema_stack(frame: pl.DataFrame) -> pl.Series:
    aligned = (pl.col("ema_10") > pl.col("ema_20")) & (
        pl.col("ema_20") > pl.col("ema_50")
    )
    prior = aligned.cast(pl.Int8).shift(1).rolling_sum(EMA_FRESH_LOOKBACK)
    fresh = aligned & (prior == 0)
    return _series(frame, pl.col("weekly_uptrend") & fresh)


def breakout_52w(frame: pl.DataFrame) -> pl.Series:
    broke = pl.col("close") > pl.col("trailing_365d_high").shift(1)
    vol = pl.col("relative_volume_20") > BREAKOUT_REL_VOL
    return _series(frame, pl.col("weekly_uptrend") & broke & vol)


def bollinger_revert(frame: pl.DataFrame) -> pl.Series:
    tagged = pl.col("close").shift(1) <= pl.col("band_lower_20_2").shift(1)
    turn_up = pl.col("close") > pl.col("close").shift(1)
    return _series(frame, pl.col("weekly_uptrend") & tagged & turn_up)


def macd_adx(frame: pl.DataFrame) -> pl.Series:
    cross = (pl.col("macd_12_26") > pl.col("macd_signal_9")) & (
        pl.col("macd_12_26").shift(1) <= pl.col("macd_signal_9").shift(1)
    )
    strong = pl.col("adx_14") > ADX_TREND
    return _series(frame, pl.col("weekly_uptrend") & cross & strong)


def rsi_dip(frame: pl.DataFrame) -> pl.Series:
    dipped = pl.col("rsi_14").rolling_min(RSI_DIP_LOOKBACK) < RSI_DIP_LOW
    reclaim = (pl.col("rsi_14") > RSI_DIP_RECLAIM) & (
        pl.col("rsi_14").shift(1) <= RSI_DIP_RECLAIM
    )
    return _series(frame, pl.col("weekly_uptrend") & dipped & reclaim)


SIGNALS: dict[str, SignalFn] = {
    "pullback_buy": pullback_buy,
    "ema_stack": ema_stack,
    "breakout_52w": breakout_52w,
    "bollinger_revert": bollinger_revert,
    "macd_adx": macd_adx,
    "rsi_dip": rsi_dip,
}
