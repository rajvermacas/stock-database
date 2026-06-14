from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import polars as pl

from stock_data.pullback.learner import learn_stock
from stock_data.pullback.models import Decision, ScreenResult, StockDecision
from stock_data.pullback.prefilter import learn_prefilter
from stock_data.pullback.quality import validate_universe

LOGGER = logging.getLogger(__name__)


def analyze_symbol(prices_root: Path, interval: str, symbol: str) -> StockDecision:
    path = prices_root / interval / f"{symbol}.parquet"
    if not path.exists():
        raise ValueError(f"missing price file: {path}")
    LOGGER.info(
        "Analyzing pullback symbol=%s interval=%s path=%s", symbol, interval, path
    )
    decision = learn_stock(pl.read_parquet(path))
    LOGGER.info("Analyzed pullback symbol=%s decision=%s", symbol, decision.decision)
    return decision


def screen_universe(prices_root: Path, interval: str) -> ScreenResult:
    LOGGER.info("Starting pullback screen interval=%s root=%s", interval, prices_root)
    quality = validate_universe(prices_root, interval)
    valid = [item for item in quality if item.valid]
    excluded = tuple(issue for item in quality for issue in item.issues)
    rejected = []
    decisions = []
    for item in valid:
        prices = pl.read_parquet(prices_root / interval / f"{item.symbol}.parquet")
        if not learn_prefilter(prices).passes:
            rejected.append(item.symbol)
            LOGGER.info(
                "Prefilter rejected symbol=%s interval=%s", item.symbol, interval
            )
            continue
        decision = learn_stock(prices)
        decisions.append(decision)
        LOGGER.info(
            "Learned symbol=%s interval=%s decision=%s",
            item.symbol,
            interval,
            decision.decision,
        )
    ranked = tuple(
        sorted(
            (
                decision
                for decision in decisions
                if decision.decision != Decision.ABSTAIN
                and decision.adjusted_expected_return is not None
            ),
            key=lambda decision: decision.adjusted_expected_return,
            reverse=True,
        )
    )
    abstained = tuple(
        decision for decision in decisions if decision.decision == Decision.ABSTAIN
    )
    result = ScreenResult(_as_of(valid), ranked, excluded, tuple(rejected), abstained)
    LOGGER.info(
        "Completed pullback screen interval=%s valid=%d ranked=%d rejected=%d abstained=%d",
        interval,
        len(valid),
        len(ranked),
        len(rejected),
        len(abstained),
    )
    return result


def _as_of(valid) -> datetime:
    if not valid:
        raise ValueError("no valid symbols after quality gate")
    return valid[0].last_timestamp
