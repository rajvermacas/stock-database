"""Structure engine: pivots, swing grammar, phases, legs, contraction.

Timeframe-agnostic — operates on any OHLC frame with a sorted trade_timestamp.
Detects universal geometry primitives bottom-up; emits measurements with fit
statistics, never bare pattern labels. Naming is the interpreting model's job.
"""

import logging

import polars as pl

logger = logging.getLogger(__name__)

PIVOT_SCALES = (3, 5, 10)
PHASE_SWINGS = 6


class StructureError(Exception):
    """Structure cannot be computed on the given frame."""


def detect_pivots(frame: pl.DataFrame, window: int) -> list[dict]:
    """Centered rolling-extreme pivots with alternation enforced.

    A pivot high is a bar whose high is the max of `window` bars on each side.
    Consecutive same-type pivots collapse to the more extreme one.
    """
    if frame.height < 2 * window + 1:
        raise StructureError(
            f"Frame too short for pivot window {window}: {frame.height} bars"
        )
    size = 2 * window + 1
    marked = frame.select(
        "trade_timestamp", "high", "low",
        is_high=pl.col("high") == pl.col("high").rolling_max(size, center=True),
        is_low=pl.col("low") == pl.col("low").rolling_min(size, center=True),
    ).filter(pl.col("is_high") | pl.col("is_low"))

    pivots: list[dict] = []
    for row in marked.iter_rows(named=True):
        kind = "H" if row["is_high"] else "L"
        price = row["high"] if kind == "H" else row["low"]
        entry = {"timestamp": str(row["trade_timestamp"]), "type": kind, "price": round(price, 2)}
        if pivots and pivots[-1]["type"] == kind:
            more_extreme = (kind == "H" and price > pivots[-1]["price"]) or (
                kind == "L" and price < pivots[-1]["price"]
            )
            if more_extreme:
                pivots[-1] = entry
        else:
            pivots.append(entry)
    return pivots


def label_swings(pivots: list[dict]) -> list[dict]:
    """Attach HH/LH to highs and HL/LL to lows vs the previous same-type pivot."""
    last_high: float | None = None
    last_low: float | None = None
    labelled = []
    for pivot in pivots:
        entry = dict(pivot)
        if pivot["type"] == "H":
            entry["label"] = None if last_high is None else (
                "HH" if pivot["price"] > last_high else "LH"
            )
            last_high = pivot["price"]
        else:
            entry["label"] = None if last_low is None else (
                "HL" if pivot["price"] > last_low else "LL"
            )
            last_low = pivot["price"]
        labelled.append(entry)
    return labelled


def measure_legs(pivots: list[dict]) -> list[dict]:
    """Pivot-to-pivot legs: direction, percent move."""
    legs = []
    for prev, curr in zip(pivots, pivots[1:]):
        if prev["price"] <= 0:
            raise StructureError(f"Non-positive pivot price at {prev['timestamp']}")
        legs.append(
            {
                "start": prev["timestamp"],
                "end": curr["timestamp"],
                "direction": "up" if curr["price"] > prev["price"] else "down",
                "move_percent": round((curr["price"] / prev["price"] - 1) * 100, 2),
            }
        )
    return legs


def up_leg_stats(legs: list[dict]) -> dict:
    """Distribution of historical up-leg sizes — evidence for target headroom."""
    moves = sorted(leg["move_percent"] for leg in legs if leg["direction"] == "up")
    if not moves:
        return {"count": 0, "median_percent": None, "max_percent": None}
    return {
        "count": len(moves),
        "median_percent": round(moves[len(moves) // 2], 2),
        "max_percent": round(moves[-1], 2),
    }


def classify_phase(swings: list[dict], close: float, ema_mid: float | None) -> dict:
    """Phase from recent swing labels + mid-EMA position. Reported with evidence."""
    recent = [s["label"] for s in swings[-PHASE_SWINGS:] if s["label"]]
    if not recent:
        return {"phase": "undetermined", "evidence": "no labelled swings yet"}
    bullish = sum(1 for lab in recent if lab in ("HH", "HL"))
    bearish = len(recent) - bullish
    above_mid = ema_mid is not None and close > ema_mid
    if bullish >= bearish + 2 and above_mid:
        phase = "markup"
    elif bearish >= bullish + 2 and not above_mid:
        phase = "markdown"
    elif bearish >= bullish + 2:
        phase = "correction"
    else:
        phase = "range_or_base"
    return {
        "phase": phase,
        "recent_labels": recent,
        "bullish_swings": bullish,
        "bearish_swings": bearish,
        "close_above_mid_ema": above_mid,
    }


def measure_unconfirmed_leg(frame: pl.DataFrame, pivots: list[dict]) -> dict:
    """Move from the last confirmed pivot to the current close.

    Centered-window pivots lag by `window` bars, so a strong ongoing leg is
    invisible in swing labels. This measurement makes it visible: phase labels
    describe the chart UP TO the last pivot; this describes what came after.
    """
    if not pivots:
        raise StructureError("No pivots — cannot measure unconfirmed leg")
    last_pivot = pivots[-1]
    after = frame.filter(
        pl.col("trade_timestamp").cast(pl.String) > last_pivot["timestamp"]
    )
    close = frame["close"][-1]
    return {
        "from_pivot": last_pivot,
        "bars_since_pivot": after.height,
        "move_percent": round((close / last_pivot["price"] - 1) * 100, 2),
    }


def measure_contraction(pivots: list[dict]) -> dict:
    """Swing-range contraction: recent 3 swing ranges vs the prior 3.

    Ratio < 1 means ranges are tightening (coiling); > 1 means expanding.
    """
    ranges = [
        abs(curr["price"] - prev["price"])
        for prev, curr in zip(pivots, pivots[1:])
    ]
    if len(ranges) < 6:
        return {"ratio": None, "evidence": f"only {len(ranges)} swings, need 6"}
    recent, prior = ranges[-3:], ranges[-6:-3]
    prior_mean = sum(prior) / 3
    if prior_mean == 0:
        raise StructureError("Zero prior swing range — corrupt price data")
    return {
        "ratio": round((sum(recent) / 3) / prior_mean, 3),
        "recent_ranges": [round(r, 2) for r in recent],
        "prior_ranges": [round(r, 2) for r in prior],
    }


def fit_pivot_lines(pivots: list[dict], n: int = 4) -> dict:
    """Least-squares lines through last n pivot highs and last n pivot lows.

    Slopes are %-per-pivot-step; r2 quantifies fit. Channel/triangle evidence,
    not a verdict: parallel slopes = channel, converging = triangle.
    """
    def fit(points: list[float]) -> dict | None:
        if len(points) < 3:
            return None
        k = len(points)
        xs = list(range(k))
        mean_x, mean_y = sum(xs) / k, sum(points) / k
        var_x = sum((x - mean_x) ** 2 for x in xs)
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, points))
        slope = cov / var_x
        ss_tot = sum((y - mean_y) ** 2 for y in points)
        ss_res = sum(
            (y - (mean_y + slope * (x - mean_x))) ** 2 for x, y in zip(xs, points)
        )
        r2 = 1.0 if ss_tot == 0 else 1 - ss_res / ss_tot
        return {
            "slope_percent_per_step": round(slope / mean_y * 100, 3),
            "r2": round(r2, 3),
            "points": k,
        }

    highs = [p["price"] for p in pivots if p["type"] == "H"][-n:]
    lows = [p["price"] for p in pivots if p["type"] == "L"][-n:]
    return {"highs_line": fit(highs), "lows_line": fit(lows)}


def analyze_structure(frame: pl.DataFrame, ema_mid_col: str | None) -> dict:
    """Full structural read of one timeframe at multiple pivot scales."""
    close = frame["close"][-1]
    ema_mid = None
    if ema_mid_col is not None:
        if ema_mid_col not in frame.columns:
            raise StructureError(f"Column {ema_mid_col} absent from frame")
        ema_mid = frame[ema_mid_col][-1]

    scales = {}
    for window in PIVOT_SCALES:
        if frame.height < 2 * window + 1:
            logger.info("Skipping pivot scale %d: only %d bars", window, frame.height)
            scales[f"scale_{window}"] = {"skipped": f"{frame.height} bars too short"}
            continue
        pivots = label_swings(detect_pivots(frame, window))
        legs = measure_legs(pivots)
        scales[f"scale_{window}"] = {
            "pivots": pivots[-12:],
            "phase": classify_phase(pivots, close, ema_mid),
            "unconfirmed_leg": measure_unconfirmed_leg(frame, pivots),
            "contraction": measure_contraction(pivots),
            "pivot_lines": fit_pivot_lines(pivots),
            "up_leg_stats": up_leg_stats(legs),
        }
    return {"close": close, "scales": scales}
