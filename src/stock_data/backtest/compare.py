from __future__ import annotations

import logging

import polars as pl

from stock_data.backtest.engine import allocate_slots, trading_calendar
from stock_data.backtest.metrics import compute_metrics
from stock_data.backtest.optimize import (
    StrategyResult,
    _candidates_for,
    build_arrays_for_window,
    optimize_strategy,
)
from stock_data.backtest.params import BacktestConfig, WindowSpec
from stock_data.backtest.signals import SIGNALS

LOGGER = logging.getLogger(__name__)


def run_on_window(
    frames: dict,
    strategy: str,
    sl: float,
    tgt: float,
    k: int,
    window: WindowSpec,
    cfg: BacktestConfig,
) -> dict:
    arrays = build_arrays_for_window(frames, strategy, window, cfg)
    calendar = trading_calendar(arrays)
    candidates = _candidates_for(arrays, sl, tgt, cfg.max_hold_days)
    ledger, equity = allocate_slots(candidates, arrays, calendar, k, cfg)
    return compute_metrics(equity, ledger, window.start, window.end, sl)


def bakeoff(
    frames: dict, train: WindowSpec, test: WindowSpec, cfg: BacktestConfig
) -> pl.DataFrame:
    rows = []
    for strategy in SIGNALS:
        LOGGER.info("Optimizing %s on %s ...", strategy, train.name)
        best = optimize_strategy(frames, strategy, train, cfg)
        LOGGER.info("Testing %s on %s ...", strategy, test.name)
        test_metrics = run_on_window(
            frames, strategy, best.sl_pct, best.target_pct, best.k_slots, test, cfg
        )
        rows.append(_row(best, test_metrics))
    return pl.DataFrame(rows).sort("test_calmar", descending=True)


def _row(best: StrategyResult, test_m: dict) -> dict:
    tr = best.metrics
    return {
        "strategy": best.strategy,
        "stoploss_pct": best.sl_pct * 100,
        "target_pct": best.target_pct * 100,
        "k_slots": best.k_slots,
        "train_calmar": tr["calmar"],
        "test_calmar": test_m["calmar"],
        "train_cagr": tr["cagr"],
        "test_cagr": test_m["cagr"],
        "train_max_dd": tr["max_drawdown"],
        "test_max_dd": test_m["max_drawdown"],
        "train_winrate": tr["winrate"],
        "test_winrate": test_m["winrate"],
        "test_expectancy_r": test_m["expectancy_r"],
        "test_avg_win_pct": test_m["avg_win_pct"],
        "test_avg_loss_pct": test_m["avg_loss_pct"],
        "test_num_trades": test_m["num_trades"],
        "overfit_gap": tr["calmar"] - test_m["calmar"],
    }
