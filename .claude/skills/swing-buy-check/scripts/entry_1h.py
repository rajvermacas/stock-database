"""Hourly entry analysis: 1h structure, noise measurement, 3% stop anchors.

The user's stop is a hard 3% — an entry is only valid when a structural anchor
(1h swing low) sits inside that 3% band AND the band clears hourly noise.
This module reports the facts; the verdict layer applies the veto.
"""

import logging

from structure import detect_pivots, label_swings

import polars as pl

logger = logging.getLogger(__name__)

STOP_PERCENT = 3.0
HOURLY_PIVOT_WINDOW = 5
RECENT_HOURLY_BARS = 250
NOISE_LOOKBACK_DAYS = 10
MIN_STOP_TO_NOISE = 1.5


class EntryAnalysisError(Exception):
    """Hourly entry facts cannot be computed."""


def hourly_noise(frame: pl.DataFrame) -> dict:
    """Recent intraday adverse-excursion noise, in percent of close.

    Measures per-day drawdown from that day's running high — how far price
    habitually dips below intraday highs purely as noise.
    """
    daily_dips = (
        frame.lazy()
        .with_columns(day=pl.col("trade_timestamp").dt.date())
        .with_columns(running_high=pl.col("high").cum_max().over("day"))
        .with_columns(
            dip_percent=(1 - pl.col("low") / pl.col("running_high")) * 100
        )
        .group_by("day")
        .agg(max_dip_percent=pl.col("dip_percent").max())
        .sort("day")
        .tail(NOISE_LOOKBACK_DAYS)
        .collect()
    )
    if daily_dips.is_empty():
        raise EntryAnalysisError("No hourly bars available for noise measurement")
    dips = daily_dips["max_dip_percent"]
    median_dip, max_dip = dips.median(), dips.max()
    if not isinstance(median_dip, (int, float)) or not isinstance(max_dip, (int, float)):
        raise EntryAnalysisError("Noise aggregation returned non-numeric values")
    return {
        "lookback_days": daily_dips.height,
        "median_daily_dip_percent": round(float(median_dip), 2),
        "max_daily_dip_percent": round(float(max_dip), 2),
        "stop_covers_noise": float(median_dip) * MIN_STOP_TO_NOISE <= STOP_PERCENT,
        "required_multiple": MIN_STOP_TO_NOISE,
    }


def hourly_structure(frame: pl.DataFrame) -> dict:
    """Swing read on recent hourly bars: labels + last pivots."""
    recent = frame.tail(RECENT_HOURLY_BARS)
    pivots = label_swings(detect_pivots(recent, HOURLY_PIVOT_WINDOW))
    labels = [p["label"] for p in pivots[-6:] if p["label"]]
    return {
        "bars_analyzed": recent.height,
        "recent_labels": labels,
        "last_pivots": pivots[-6:],
    }


def stop_anchors(frame: pl.DataFrame, close: float) -> dict:
    """Structural anchors (1h swing lows) inside the 3% stop band below close."""
    recent = frame.tail(RECENT_HOURLY_BARS)
    pivots = detect_pivots(recent, HOURLY_PIVOT_WINDOW)
    stop_floor = close * (1 - STOP_PERCENT / 100)
    candidates = [
        {
            "price": round(p["price"], 2),
            "timestamp": p["timestamp"],
            "distance_percent": round((1 - p["price"] / close) * 100, 2),
        }
        for p in pivots
        if p["type"] == "L" and stop_floor <= p["price"] < close
    ]
    candidates.sort(key=lambda c: c["price"], reverse=True)
    return {
        "stop_percent": STOP_PERCENT,
        "stop_floor_price": round(stop_floor, 2),
        "anchors_within_band": candidates[:4],
        "anchor_exists": bool(candidates),
    }


def analyze_entry(hourly: pl.DataFrame) -> dict:
    """Full hourly entry read: noise, structure, stop anchors, survival verdict facts."""
    close = hourly["close"][-1]
    noise = hourly_noise(hourly)
    anchors = stop_anchors(hourly, close)
    survival = noise["stop_covers_noise"] and anchors["anchor_exists"]
    logger.info(
        "Stop survival: noise_ok=%s anchor_exists=%s -> %s",
        noise["stop_covers_noise"], anchors["anchor_exists"], survival,
    )
    return {
        "close": close,
        "noise": noise,
        "structure": hourly_structure(hourly),
        "stop_anchors": anchors,
        "stop_survival": survival,
    }
