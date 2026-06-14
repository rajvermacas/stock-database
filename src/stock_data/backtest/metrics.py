from __future__ import annotations

from datetime import date

import polars as pl

from stock_data.backtest.errors import DegenerateMetricError, ZeroTradesError


def max_drawdown(equity: pl.Series) -> float:
    """Worst peak-to-trough drop as a positive fraction (0.20 == -20%)."""
    running_peak = equity.cum_max()
    drawdown = (equity - running_peak) / running_peak
    return float(-drawdown.min())


def cagr(equity: pl.Series, start: date, end: date) -> float:
    years = (end - start).days / 365.25
    if years <= 0:
        raise DegenerateMetricError(f"Non-positive span {start}..{end}")
    final, initial = float(equity[-1]), float(equity[0])
    return (final / initial) ** (1.0 / years) - 1.0


def compute_metrics(
    equity: pl.Series, ledger: pl.DataFrame, start: date, end: date, sl_pct: float
) -> dict:
    if ledger.height == 0:
        raise ZeroTradesError("No trades to compute metrics from")
    mdd = max_drawdown(equity)
    if mdd <= 0:
        raise DegenerateMetricError("Zero drawdown — too few trades or a bug")
    annual = cagr(equity, start, end)
    rets = ledger["return_pct"]
    wins = rets.filter(rets > 0)
    losses = rets.filter(rets <= 0)
    r_multiple = rets / sl_pct  # risk per trade is the fixed stop distance
    return {
        "cagr": annual,
        "max_drawdown": mdd,
        "calmar": annual / mdd,
        "winrate": wins.len() / rets.len(),
        "num_trades": rets.len(),
        "avg_win_pct": float(wins.mean()) if wins.len() else 0.0,
        "avg_loss_pct": float(losses.mean()) if losses.len() else 0.0,
        "expectancy_r": float(r_multiple.mean()),
        "total_return": float(equity[-1] / equity[0] - 1.0),
    }
