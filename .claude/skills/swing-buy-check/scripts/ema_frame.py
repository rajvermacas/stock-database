"""EMA framework: stack state, slopes, distances, per-symbol respected-EMA stats.

The respected-EMA statistic measures which EMA THIS stock actually rides:
touch = bar's low crosses the EMA while in an uptrend context; hold = bar
closes back above it. High hold-rate EMAs anchor pullback entries and stops.
"""

import logging

import polars as pl

logger = logging.getLogger(__name__)

EMA_SPANS = (10, 20, 50, 100, 200)
SLOPE_LOOKBACK_BARS = 10
RESPECT_LOOKBACK_BARS = 126


class EmaFrameError(Exception):
    """EMA framework cannot be computed."""


def _require_columns(frame: pl.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise EmaFrameError(f"Missing EMA/ATR columns: {missing}")


def stack_state(frame: pl.DataFrame) -> dict:
    """Ordering of close vs each EMA, plus full-stack flags."""
    last = frame.tail(1).to_dicts()[0]
    close = last["close"]
    relations = {
        f"ema_{span}": {
            "value": round(last[f"ema_{span}"], 2),
            "close_above": close > last[f"ema_{span}"],
        }
        for span in EMA_SPANS
    }
    values = [last[f"ema_{span}"] for span in EMA_SPANS]
    return {
        "close": close,
        "emas": relations,
        "bullish_stack": all(a > b for a, b in zip(values, values[1:])),
        "close_above_all": all(close > v for v in values),
    }


def slopes(frame: pl.DataFrame) -> dict:
    """Percent change of each EMA over SLOPE_LOOKBACK_BARS bars."""
    if frame.height <= SLOPE_LOOKBACK_BARS:
        raise EmaFrameError(
            f"Need > {SLOPE_LOOKBACK_BARS} bars for EMA slopes, have {frame.height}"
        )
    result = frame.select(
        [
            ((pl.col(f"ema_{span}").last() / pl.col(f"ema_{span}").slice(-1 - SLOPE_LOOKBACK_BARS, 1).first() - 1) * 100)
            .alias(f"ema_{span}")
            for span in EMA_SPANS
        ]
    ).to_dicts()[0]
    return {
        name: None if value is None else round(value, 2)
        for name, value in result.items()
    }


def distances(frame: pl.DataFrame) -> dict:
    """Distance from close to each EMA, in percent and in ATR multiples."""
    last = frame.tail(1).to_dicts()[0]
    close, atr = last["close"], last["atr_14"]
    if atr is None or atr <= 0:
        raise EmaFrameError(f"Invalid atr_14 on latest bar: {atr}")
    out = {}
    for span in EMA_SPANS:
        ema = last[f"ema_{span}"]
        out[f"ema_{span}"] = {
            "percent": round((close / ema - 1) * 100, 2),
            "atr_multiples": round((close - ema) / atr, 2),
        }
    return out


def respected_ema_stats(frame: pl.DataFrame) -> dict:
    """Touch-and-hold rate per EMA over the respect lookback window.

    touch: low <= ema <= high (price interacted with the EMA that bar)
    hold:  touch bar closes at/above the EMA
    """
    window = frame.tail(RESPECT_LOOKBACK_BARS)
    stats = {}
    for span in EMA_SPANS:
        ema = pl.col(f"ema_{span}")
        agg = window.select(
            touches=((pl.col("low") <= ema) & (ema <= pl.col("high"))).sum(),
            holds=(
                (pl.col("low") <= ema) & (ema <= pl.col("high"))
                & (pl.col("close") >= ema)
            ).sum(),
        ).to_dicts()[0]
        touches, holds = agg["touches"], agg["holds"]
        stats[f"ema_{span}"] = {
            "touches": touches,
            "holds": holds,
            "hold_rate": round(holds / touches, 2) if touches else None,
        }
    respected = [
        name for name, s in stats.items()
        if s["touches"] >= 3 and s["hold_rate"] is not None and s["hold_rate"] >= 0.6
    ]
    logger.info("Respected EMAs over last %d bars: %s", RESPECT_LOOKBACK_BARS, respected)
    return {
        "lookback_bars": min(RESPECT_LOOKBACK_BARS, frame.height),
        "per_ema": stats,
        "respected": respected,
    }


def analyze_ema_frame(frame: pl.DataFrame) -> dict:
    """Full EMA framework on a daily frame with precalculated indicators."""
    required = [f"ema_{span}" for span in EMA_SPANS] + ["atr_14", "close", "low", "high"]
    _require_columns(frame, required)
    with_indicators = frame.filter(pl.col("ema_200").is_not_null())
    if with_indicators.is_empty():
        raise EmaFrameError("No bars with indicator values (warm-up not complete)")
    return {
        "indicator_bars": with_indicators.height,
        "stack": stack_state(with_indicators),
        "slopes_percent_per_10_bars": slopes(with_indicators),
        "distances": distances(with_indicators),
        "respect": respected_ema_stats(with_indicators),
    }
