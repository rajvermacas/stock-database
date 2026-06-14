from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import polars as pl

from stock_data.backtest.data import slice_window
from stock_data.backtest.engine import (
    SymbolArrays,
    allocate_slots,
    build_symbol_arrays,
    simulate_exits,
    trading_calendar,
)
from stock_data.backtest.errors import BacktestError, ZeroTradesError
from stock_data.backtest.metrics import compute_metrics
from stock_data.backtest.params import (
    K_GRID,
    SL_GRID,
    TARGET_GRID,
    BacktestConfig,
    WindowSpec,
)
from stock_data.backtest.signals import SIGNALS

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    sl_pct: float
    target_pct: float
    k_slots: int
    metrics: dict


def build_arrays_for_window(
    frames: dict[str, pl.DataFrame],
    strategy: str,
    window: WindowSpec,
    cfg: BacktestConfig,
) -> dict[str, SymbolArrays]:
    """Compute signals on full history, then slice arrays to the window."""
    fn = SIGNALS[strategy]
    arrays: dict[str, SymbolArrays] = {}
    for sym, full in frames.items():
        entry_full = fn(full)
        sliced = slice_window(
            full.with_columns(entry_full.alias("__entry")), window.start, window.end
        )
        if sliced.height == 0:
            continue
        arrays[sym] = build_symbol_arrays(
            sliced.drop("__entry"), sliced["__entry"], cfg.rel_volume_tiebreak_col
        )
    if not arrays:
        raise BacktestError(f"No data for {strategy} in {window.name}")
    return arrays


def _candidates_for(arrays, sl, tgt, max_hold):
    candidates = []
    for a in arrays.values():
        candidates.extend(simulate_exits(a, sl, tgt, max_hold))
    return candidates


def score_combo(
    candidates,
    arrays: dict[str, SymbolArrays],
    calendar: list[date],
    sl: float,
    k: int,
    window: WindowSpec,
    cfg: BacktestConfig,
) -> dict | None:
    if not candidates:
        return None
    ledger, equity = allocate_slots(candidates, arrays, calendar, k, cfg)
    try:
        return compute_metrics(equity, ledger, window.start, window.end, sl)
    except (ZeroTradesError, BacktestError):
        return None


def optimize_strategy(
    frames: dict[str, pl.DataFrame],
    strategy: str,
    window: WindowSpec,
    cfg: BacktestConfig,
) -> StrategyResult:
    arrays = build_arrays_for_window(frames, strategy, window, cfg)
    calendar = trading_calendar(arrays)
    best: StrategyResult | None = None
    for sl in SL_GRID:
        for tgt in TARGET_GRID:
            # Stage A shared across K: compute candidates once per (sl, tgt).
            candidates = _candidates_for(arrays, sl, tgt, cfg.max_hold_days)
            for k in K_GRID:
                metrics = score_combo(candidates, arrays, calendar, sl, k, window, cfg)
                if metrics is None:
                    continue
                cand = StrategyResult(strategy, sl, tgt, k, metrics)
                if best is None or _better(cand, best):
                    best = cand
    if best is None:
        raise ZeroTradesError(f"{strategy}: no profitable combo produced trades")
    LOGGER.info(
        "%s best: SL=%.0f%% TGT=%.0f%% K=%d Calmar=%.2f",
        strategy,
        best.sl_pct * 100,
        best.target_pct * 100,
        best.k_slots,
        best.metrics["calmar"],
    )
    return best


def _better(a: StrategyResult, b: StrategyResult) -> bool:
    if a.metrics["calmar"] != b.metrics["calmar"]:
        return a.metrics["calmar"] > b.metrics["calmar"]
    return a.metrics["cagr"] > b.metrics["cagr"]   # tie-break (spec 5.3)
