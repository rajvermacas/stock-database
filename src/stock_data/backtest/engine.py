from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from stock_data.backtest.params import BacktestConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SymbolArrays:
    """Window-sliced numpy view of one symbol for fast scanning."""

    symbol: str
    dates: np.ndarray          # dtype=object of datetime.date
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    rel_vol: np.ndarray
    entry: np.ndarray          # bool, signal fired on this bar


@dataclass(frozen=True)
class CandidateTrade:
    symbol: str
    entry_idx: int             # index into that symbol's arrays
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    gross_return: float
    rel_vol_at_signal: float
    exit_reason: str


def build_symbol_arrays(frame: pl.DataFrame, entry: pl.Series, col: str) -> SymbolArrays:
    f = frame.sort("trade_timestamp")
    aligned_entry = entry  # entry was computed on the same sliced+sorted rows
    return SymbolArrays(
        symbol=f["symbol"][0],
        dates=np.array(f["trade_timestamp"].dt.date().to_list(), dtype=object),
        open=f["open"].to_numpy(),
        high=f["high"].to_numpy(),
        low=f["low"].to_numpy(),
        close=f["close"].to_numpy(),
        rel_vol=f[col].to_numpy(),
        entry=aligned_entry.to_numpy(),
    )


def simulate_exits(
    arrays: SymbolArrays, sl_pct: float, tgt_pct: float, max_hold: int
) -> list[CandidateTrade]:
    """Stage A: resolve each signal into a candidate trade (entry next open)."""
    trades: list[CandidateTrade] = []
    n = len(arrays.close)
    signal_idx = np.flatnonzero(arrays.entry)
    for s in signal_idx:
        e = int(s) + 1                  # enter at next bar's open
        if e >= n:
            continue
        entry_price = float(arrays.open[e])
        stop = entry_price * (1.0 - sl_pct)
        target = entry_price * (1.0 + tgt_pct)
        trades.append(_scan_forward(arrays, int(s), e, stop, target, max_hold, n))
    return trades


def _scan_forward(arrays, s, e, stop, target, max_hold, n) -> CandidateTrade:
    last = min(e + max_hold, n - 1)
    for j in range(e, last + 1):
        low, high, op = arrays.low[j], arrays.high[j], arrays.open[j]
        if low <= stop:                 # stoploss precedence
            price = float(op) if op <= stop else float(stop)
            return _mk(arrays, s, e, j, price, "stoploss")
        if high >= target:
            price = float(op) if op >= target else float(target)
            return _mk(arrays, s, e, j, price, "target")
    reason = "time_stop" if last == e + max_hold else "window_end"
    return _mk(arrays, s, e, last, float(arrays.close[last]), reason)


def _mk(arrays, s, e, j, exit_price, reason) -> CandidateTrade:
    entry_price = float(arrays.open[e])
    return CandidateTrade(
        symbol=arrays.symbol,
        entry_idx=e,
        entry_date=arrays.dates[e],
        exit_date=arrays.dates[j],
        entry_price=entry_price,
        exit_price=exit_price,
        gross_return=exit_price / entry_price - 1.0,
        rel_vol_at_signal=float(arrays.rel_vol[s]),
        exit_reason=reason,
    )


def _free_exited(open_positions, day, cash, cost_per_leg):
    """Close positions whose exit_date is today; return (still_open, cash)."""
    still = []
    for pos in open_positions:
        if pos["trade"].exit_date == day:
            cash += pos["shares"] * pos["trade"].exit_price * (1.0 - cost_per_leg)
        else:
            still.append(pos)
    return still, cash


def allocate_slots(
    candidates: list[CandidateTrade],
    arrays_by_symbol: dict[str, SymbolArrays],
    trading_days: list[date],
    k_slots: int,
    cfg: BacktestConfig,
) -> tuple[pl.DataFrame, pl.Series]:
    """Stage B: K equal-weight slots; build ledger + daily equity curve."""
    by_entry: dict[date, list[CandidateTrade]] = {}
    for c in candidates:
        by_entry.setdefault(c.entry_date, []).append(c)

    cash = cfg.capital
    prev_equity = cfg.capital      # size today's entries on yesterday's equity
    open_positions: list[dict] = []
    taken: list[CandidateTrade] = []
    equity_points: list[float] = []
    close_lookup = _close_lookup(arrays_by_symbol)

    for day in trading_days:
        # 1) free positions opened earlier that exit today (recycle slot)
        open_positions, cash = _free_exited(
            open_positions, day, cash, cfg.cost_per_leg
        )
        # 2) entries: fill free slots from today's candidates (tie-break rel_vol).
        #    Equal-weight, compounding: each slot = previous equity / K (no leverage,
        #    no look-ahead since prev_equity is yesterday's close value).
        free = k_slots - len(open_positions)
        if free > 0 and day in by_entry and prev_equity > 0:
            slot_capital = prev_equity / k_slots
            ranked = sorted(by_entry[day], key=lambda c: -c.rel_vol_at_signal)
            for c in ranked[:free]:
                cash -= slot_capital * (1.0 + cfg.cost_per_leg)
                shares = slot_capital / c.entry_price
                open_positions.append({"trade": c, "shares": shares})
                taken.append(c)
        # 3) same-day round trips (entry_date == exit_date == today)
        open_positions, cash = _free_exited(
            open_positions, day, cash, cfg.cost_per_leg
        )
        # 4) mark-to-market remaining open positions at today's close
        held_value = sum(
            p["shares"]
            * close_lookup[p["trade"].symbol].get(day, p["trade"].entry_price)
            for p in open_positions
        )
        prev_equity = cash + held_value
        equity_points.append(prev_equity)

    return _ledger(taken, cfg.cost_per_leg), pl.Series("equity", equity_points)


def _close_lookup(arrays_by_symbol):
    return {
        sym: dict(zip(a.dates.tolist(), a.close.tolist()))
        for sym, a in arrays_by_symbol.items()
    }


def _ledger(taken: list[CandidateTrade], cost_per_leg: float) -> pl.DataFrame:
    rows = [
        {
            "symbol": c.symbol,
            "entry_date": c.entry_date,
            "exit_date": c.exit_date,
            "entry_price": c.entry_price,
            "exit_price": c.exit_price,
            "return_pct": (1.0 + c.gross_return) * (1.0 - cost_per_leg) ** 2 - 1.0,
            "exit_reason": c.exit_reason,
        }
        for c in taken
    ]
    schema = {
        "symbol": pl.String,
        "entry_date": pl.Date,
        "exit_date": pl.Date,
        "entry_price": pl.Float64,
        "exit_price": pl.Float64,
        "return_pct": pl.Float64,
        "exit_reason": pl.String,
    }
    return pl.DataFrame(rows, schema=schema)


def trading_calendar(arrays_by_symbol: dict[str, SymbolArrays]) -> list[date]:
    days: set[date] = set()
    for a in arrays_by_symbol.values():
        days.update(a.dates.tolist())
    return sorted(days)
