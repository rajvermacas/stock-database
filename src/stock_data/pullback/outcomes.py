from __future__ import annotations

import numpy as np
import polars as pl

from stock_data.pullback.models import (
    STOP_LOSS_FRACTION,
    OutcomeStatus,
    TradeOutcome,
    TradePath,
)


def trace_path(
    prices: pl.DataFrame, detection_index: int, regime_end_index: int | None
) -> TradeOutcome:
    entry_index = detection_index + 1
    if entry_index >= prices.height:
        return _pending()
    entry = float(prices["open"][entry_index])
    path = TradePath(entry_index, entry, entry * (1 - STOP_LOSS_FRACTION))
    end = (
        prices.height
        if regime_end_index is None
        else min(regime_end_index + 1, prices.height)
    )
    future = prices.slice(entry_index, end - entry_index)
    return _summarize_path(future, path)


def evaluate_target(
    prices: pl.DataFrame, outcome: TradeOutcome, target: float, horizon_bars: int
) -> OutcomeStatus:
    if outcome.path is None:
        return OutcomeStatus.PENDING
    future = prices.slice(outcome.path.entry_index, horizon_bars)
    if future.is_empty():
        return OutcomeStatus.CENSORED
    target_price = outcome.path.entry_price * (1 + target)
    for high, low in zip(future["high"], future["low"], strict=True):
        hit_target = high >= target_price
        hit_stop = low <= outcome.path.stop_price
        if hit_target and hit_stop:
            return OutcomeStatus.UNKNOWN
        if hit_target:
            return OutcomeStatus.SUCCESS
        if hit_stop:
            return OutcomeStatus.FAILURE
    return OutcomeStatus.CENSORED


def _summarize_path(future: pl.DataFrame, path: TradePath) -> TradeOutcome:
    highs = future["high"].to_numpy()
    lows = future["low"].to_numpy()
    stop_hits = np.flatnonzero(lows <= path.stop_price)
    if len(stop_hits):
        end = int(stop_hits[0]) + 1
        highs = highs[:end]
        lows = lows[:end]
    mfe_values = highs / path.entry_price - 1
    mae_values = lows / path.entry_price - 1
    status = OutcomeStatus.FAILURE if len(stop_hits) else OutcomeStatus.CENSORED
    return TradeOutcome(
        status=status,
        path=path,
        mfe_fraction=float(mfe_values.max()),
        mae_fraction=float(mae_values.min()),
        bars_to_prior_high=None,
        bars_to_stop=int(stop_hits[0]) if len(stop_hits) else None,
        bars_to_mfe=int(mfe_values.argmax()),
    )


def _pending() -> TradeOutcome:
    return TradeOutcome(
        OutcomeStatus.PENDING,
        None,
        None,
        None,
        None,
        None,
        None,
    )
