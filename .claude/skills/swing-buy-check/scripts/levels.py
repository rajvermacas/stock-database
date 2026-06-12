"""Support/resistance map: cluster pivot prices into levels with touch evidence.

Tolerance scales with the symbol's own ATR — a volatile small-cap and a quiet
large-cap each get level widths in their own noise units, never a fixed percent.
"""

import logging

from structure import detect_pivots

import polars as pl

logger = logging.getLogger(__name__)

CLUSTER_ATR_FRACTION = 0.5
LEVEL_SCALES = (5, 10)


class LevelError(Exception):
    """S/R levels cannot be computed."""


def _collect_pivots(frame: pl.DataFrame) -> list[dict]:
    pivots: list[dict] = []
    for window in LEVEL_SCALES:
        if frame.height >= 2 * window + 1:
            pivots.extend(detect_pivots(frame, window))
    if not pivots:
        raise LevelError(f"No pivots detectable on {frame.height}-bar frame")
    return pivots


def _cluster(pivots: list[dict], tolerance: float) -> list[dict]:
    """Greedy 1-D clustering of pivot prices within `tolerance` rupees."""
    ordered = sorted(pivots, key=lambda p: p["price"])
    clusters: list[list[dict]] = [[ordered[0]]]
    for pivot in ordered[1:]:
        anchor = sum(p["price"] for p in clusters[-1]) / len(clusters[-1])
        if pivot["price"] - anchor <= tolerance:
            clusters[-1].append(pivot)
        else:
            clusters.append([pivot])
    levels = []
    for members in clusters:
        prices = [m["price"] for m in members]
        levels.append(
            {
                "price": round(sum(prices) / len(prices), 2),
                "touches": len(members),
                "high_touches": sum(1 for m in members if m["type"] == "H"),
                "low_touches": sum(1 for m in members if m["type"] == "L"),
                "first_touch": min(m["timestamp"] for m in members),
                "last_touch": max(m["timestamp"] for m in members),
            }
        )
    return levels


def build_level_map(frame: pl.DataFrame, atr: float) -> dict:
    """Full S/R map plus nearest support below / resistance above last close."""
    if atr <= 0:
        raise LevelError(f"Non-positive ATR ({atr}) — cannot scale level tolerance")
    close = frame["close"][-1]
    tolerance = atr * CLUSTER_ATR_FRACTION
    levels = _cluster(_collect_pivots(frame), tolerance)

    supports = [lv for lv in levels if lv["price"] < close]
    resistances = [lv for lv in levels if lv["price"] >= close]
    nearest_support = max(supports, key=lambda lv: lv["price"]) if supports else None
    nearest_resistance = (
        min(resistances, key=lambda lv: lv["price"]) if resistances else None
    )

    def with_distance(level: dict | None) -> dict | None:
        if level is None:
            return None
        return {**level, "distance_percent": round((level["price"] / close - 1) * 100, 2)}

    multi_touch = sorted(
        (lv for lv in levels if lv["touches"] >= 2),
        key=lambda lv: (-lv["touches"], lv["price"]),
    )
    logger.info(
        "Level map: %d clusters (%d multi-touch), tolerance %.2f (%.2f ATR)",
        len(levels), len(multi_touch), tolerance, CLUSTER_ATR_FRACTION,
    )
    resistance_d = with_distance(nearest_resistance)
    return {
        "tolerance_rupees": round(tolerance, 2),
        "close": close,
        "nearest_support": with_distance(nearest_support),
        "nearest_resistance": resistance_d,
        "strong_levels": [with_distance(lv) for lv in multi_touch[:8]],
        "headroom_to_resistance_percent": (
            resistance_d["distance_percent"] if resistance_d else None
        ),
    }
