"""Setup candidate detection + hard vetoes.

Emits CANDIDATES with measurements, never a final verdict. A chart can match
zero, one, or several candidates; the interpreting model adjudicates using
structure, levels, and EMA facts. Vetoes are facts the verdict layer must obey.
"""

import logging

import polars as pl

logger = logging.getLogger(__name__)

BREAKOUT_LOOKBACK_BARS = 5
BREAKOUT_MAX_PAST_PIVOT_ATR = 1.0
PULLBACK_MAX_DISTANCE_ATR = 0.75
BOUNCE_MAX_DISTANCE_ATR = 0.75
EXTENSION_VETO_ATR = 2.0
MIN_RESPECT_HOLD_RATE = 0.6


class ClassifierError(Exception):
    """Setup candidates cannot be evaluated."""


def _last(frame: pl.DataFrame) -> dict:
    return frame.tail(1).to_dicts()[0]


def detect_breakout(frame: pl.DataFrame, level_map: dict, atr: float) -> dict | None:
    """Close crossed above a multi-touch resistance within the lookback window."""
    recent = frame.tail(BREAKOUT_LOOKBACK_BARS + 1)
    closes = recent["close"].to_list()
    rel_volumes = recent["relative_volume_20"].to_list()
    timestamps = recent["trade_timestamp"].to_list()
    close = closes[-1]

    for level in level_map["strong_levels"]:
        price = level["price"]
        if not closes[0] <= price < close:
            continue
        cross_index = next(
            (i for i in range(1, len(closes)) if closes[i - 1] <= price < closes[i]),
            None,
        )
        if cross_index is None:
            continue
        distance_atr = (close - price) / atr
        return {
            "setup": "breakout",
            "level": level,
            "breakout_bar": str(timestamps[cross_index]),
            "relative_volume_on_break": (
                None if rel_volumes[cross_index] is None
                else round(rel_volumes[cross_index], 2)
            ),
            "distance_past_level_atr": round(distance_atr, 2),
            "still_enterable": distance_atr <= BREAKOUT_MAX_PAST_PIVOT_ATR,
        }
    return None


def detect_ema_pullback(frame: pl.DataFrame, ema_facts: dict) -> dict | None:
    """Price within reach of a respected, rising EMA — pullback entry zone."""
    last = _last(frame)
    atr = last["atr_14"]
    candidates = []
    for name in ema_facts["respect"]["respected"]:
        slope = ema_facts["slopes_percent_per_10_bars"][name]
        if slope is None or slope <= 0:
            continue
        distance_atr = (last["close"] - last[name]) / atr
        if -0.25 <= distance_atr <= PULLBACK_MAX_DISTANCE_ATR:
            candidates.append(
                {
                    "ema": name,
                    "hold_rate": ema_facts["respect"]["per_ema"][name]["hold_rate"],
                    "distance_atr": round(distance_atr, 2),
                    "ema_slope_percent_per_10_bars": slope,
                }
            )
    if not candidates:
        return None
    best = min(candidates, key=lambda c: abs(c["distance_atr"]))
    return {"setup": "ema_pullback", **best, "all_candidates": candidates}


def detect_support_bounce(frame: pl.DataFrame, level_map: dict, atr: float) -> dict | None:
    """Price sitting just above a multi-touch support with a reactive last bar."""
    support = level_map["nearest_support"]
    if support is None or support["touches"] < 2:
        return None
    last = _last(frame)
    distance_atr = (last["close"] - support["price"]) / atr
    if not 0 <= distance_atr <= BOUNCE_MAX_DISTANCE_ATR:
        return None
    bar_range = last["high"] - last["low"]
    close_location = (
        None if bar_range == 0 else round((last["close"] - last["low"]) / bar_range, 2)
    )
    return {
        "setup": "support_bounce",
        "level": support,
        "distance_atr": round(distance_atr, 2),
        "last_bar_close_location": close_location,
        "last_bar_closed_up": last["close"] > last["open"],
    }


def evaluate_vetoes(frame: pl.DataFrame, entry_facts: dict) -> dict:
    """Hard vetoes: extension past EMA20, and stop-survival from hourly facts."""
    last = _last(frame)
    extension_atr = (last["close"] - last["ema_20"]) / last["atr_14"]
    extension_veto = extension_atr > EXTENSION_VETO_ATR
    stop_survival_veto = not entry_facts["stop_survival"]
    logger.info(
        "Vetoes: extension=%s (%.2f ATR above ema_20), stop_survival_failed=%s",
        extension_veto, extension_atr, stop_survival_veto,
    )
    return {
        "extension_atr_above_ema20": round(extension_atr, 2),
        "extension_veto": extension_veto,
        "stop_survival_veto": stop_survival_veto,
        "any_veto": extension_veto or stop_survival_veto,
    }


def classify(frame: pl.DataFrame, level_map: dict, ema_facts: dict, entry_facts: dict) -> dict:
    """All setup candidates + vetoes on the daily frame."""
    last = _last(frame)
    atr = last["atr_14"]
    if atr is None or atr <= 0:
        raise ClassifierError(f"Invalid atr_14 on latest bar: {atr}")
    candidates = [
        c for c in (
            detect_breakout(frame, level_map, atr),
            detect_ema_pullback(frame, ema_facts),
            detect_support_bounce(frame, level_map, atr),
        ) if c is not None
    ]
    logger.info("Setup candidates: %s", [c["setup"] for c in candidates] or "none")
    return {
        "candidates": candidates,
        "vetoes": evaluate_vetoes(frame, entry_facts),
    }
