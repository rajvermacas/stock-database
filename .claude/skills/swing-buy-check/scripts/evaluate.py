"""Orchestrator: full multi-timeframe fact run for one symbol.

Usage: .venv/bin/python .claude/skills/swing-buy-check/scripts/evaluate.py SYMBOL

Emits a single JSON document on stdout (facts only — no verdict, no advice);
detailed logs go to stderr. Any data problem raises and exits non-zero.
"""

import json
import logging
import sys

import polars as pl

import tf_data
from analog import find_analogs
from classifier import classify
from ema_frame import analyze_ema_frame
from entry_1h import analyze_entry
from levels import build_level_map
from market_context import market_context
from structure import analyze_structure

logger = logging.getLogger("swing_buy_check")


def latest_atr(frame: pl.DataFrame, column: str) -> float:
    value = frame[column][-1]
    if value is None or value <= 0:
        raise tf_data.DataUnavailableError(f"Invalid {column} on latest bar: {value}")
    return float(value)


def daily_facts(daily: pl.DataFrame) -> dict:
    atr = latest_atr(daily.filter(pl.col("atr_14").is_not_null()), "atr_14")
    with_indicators = daily.filter(pl.col("ema_200").is_not_null())
    ema_facts = analyze_ema_frame(daily)
    level_map = build_level_map(daily, atr)
    last = daily.tail(1).to_dicts()[0]
    context = {
        "atr_14": round(atr, 2),
        "atr_percent_14": round(last["atr_percent_14"], 2),
        "rsi_14": round(last["rsi_14"], 2),
        "adx_14": round(last["adx_14"], 2),
        "relative_volume_20": round(last["relative_volume_20"], 2),
        "distance_from_365d_high_percent": round(
            last["distance_from_365d_high_percent"], 2
        ),
        "indicator_bars": with_indicators.height,
    }
    return {
        "structure": analyze_structure(daily, "ema_50"),
        "levels": level_map,
        "ema_framework": ema_facts,
        "secondary_context": context,
    }


def weekly_facts(daily: pl.DataFrame) -> dict:
    weekly = tf_data.derive_weekly(daily)
    atr = latest_atr(weekly.filter(pl.col("atr_14").is_not_null()), "atr_14")
    return {
        "derived_from": "1d via group_by_dynamic 1w; EMAs 10/20/50 + ATR14 calculated on demand",
        "bars": weekly.height,
        "structure": analyze_structure(weekly, "ema_20"),
        "levels": build_level_map(weekly, atr),
    }


def evaluate(symbol_raw: str) -> dict:
    symbol = tf_data.resolve_symbol(symbol_raw)
    daily = tf_data.load_daily(symbol)
    hourly = tf_data.load_hourly(symbol)
    freshness = {
        "daily": tf_data.check_freshness(daily, symbol, "1d"),
        "hourly": tf_data.check_freshness(hourly, symbol, "1h"),
    }
    daily_section = daily_facts(daily)
    entry_section = analyze_entry(hourly)
    setups = classify(
        daily, daily_section["levels"], daily_section["ema_framework"], entry_section
    )
    return {
        "symbol": symbol,
        "freshness": freshness,
        "weekly": weekly_facts(daily),
        "daily": daily_section,
        "hourly_entry": entry_section,
        "setups": setups,
        "analogs": find_analogs(daily, symbol),
        "market_context": market_context(),
        "disclosures": {
            "weekly_indicators": "calculated on demand from daily closes, not precalculated",
            "daily_hourly_indicators": "precalculated at stored interval",
            "analog_features": "price/volume only, calculated on demand across the whole universe",
            "facts_only": "this document contains measurements; verdict authored by the interpreting model",
        },
    }


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if len(sys.argv) != 2:
        raise SystemExit("Usage: evaluate.py SYMBOL")
    result = evaluate(sys.argv[1])
    json.dump(result, sys.stdout, indent=1, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
