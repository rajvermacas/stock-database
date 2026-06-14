from __future__ import annotations

from datetime import date

import numpy as np

from stock_data.backtest.engine import (
    CandidateTrade,
    SymbolArrays,
    allocate_slots,
    simulate_exits,
)
from stock_data.backtest.params import BacktestConfig


def _arrays(symbol, dates, o, h, l, c, entry, rel=None):
    return SymbolArrays(
        symbol=symbol,
        dates=np.array(dates, dtype=object),
        open=np.array(o, float),
        high=np.array(h, float),
        low=np.array(l, float),
        close=np.array(c, float),
        rel_vol=np.array(rel or [1.0] * len(o), float),
        entry=np.array(entry, bool),
    )


def test_target_hit_exit_price_and_reason():
    # signal bar 0, enter bar 1 at open=100, target +10% = 110 hit on bar 2.
    a = _arrays(
        "X",
        [date(2020, 1, i) for i in range(1, 5)],
        o=[99, 100, 105, 108],
        h=[100, 104, 111, 109],
        l=[98, 99, 104, 107],
        c=[100, 103, 110, 108],
        entry=[True, False, False, False],
    )
    trades = simulate_exits(a, sl_pct=0.05, tgt_pct=0.10, max_hold=40)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "target"
    assert abs(t.exit_price - 110.0) < 1e-9
    assert t.entry_price == 100.0


def test_stoploss_precedence_when_both_touched():
    # bar 2 touches both stop (95) and target (110): stoploss must win.
    a = _arrays(
        "X",
        [date(2020, 1, i) for i in range(1, 4)],
        o=[99, 100, 102],
        h=[100, 101, 111],
        l=[98, 99, 94],
        c=[100, 100, 96],
        entry=[True, False, False],
    )
    trades = simulate_exits(a, sl_pct=0.05, tgt_pct=0.10, max_hold=40)
    assert trades[0].exit_reason == "stoploss"
    assert abs(trades[0].exit_price - 95.0) < 1e-9


def test_slot_cap_limits_concurrent_positions():
    cfg = BacktestConfig(capital=100.0, cost_bps_round_trip=0.0, max_hold_days=40)
    days = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    # Two candidate trades entering same day, only 1 slot -> higher rel_vol taken.
    c_lo = CandidateTrade("A", 1, days[1], days[2], 10.0, 11.0, 0.1, 1.0, "target")
    c_hi = CandidateTrade("B", 1, days[1], days[2], 10.0, 12.0, 0.2, 5.0, "target")
    arrays = {
        "A": _arrays("A", days, [10] * 3, [10] * 3, [10] * 3, [10, 10, 11], [0, 1, 0]),
        "B": _arrays("B", days, [10] * 3, [10] * 3, [10] * 3, [10, 10, 12], [0, 1, 0]),
    }
    ledger, equity = allocate_slots([c_lo, c_hi], arrays, days, 1, cfg)
    assert ledger.height == 1
    assert ledger["symbol"][0] == "B"   # higher rel_vol won the single slot
    assert equity.len() == 3


def test_same_day_round_trip_frees_slot():
    # Trade enters and exits on the same day; slot must free so a later trade fits.
    cfg = BacktestConfig(capital=100.0, cost_bps_round_trip=0.0, max_hold_days=40)
    days = [date(2020, 1, 1), date(2020, 1, 2)]
    same_day = CandidateTrade("A", 0, days[0], days[0], 10.0, 9.5, -0.05, 1.0, "stoploss")
    later = CandidateTrade("B", 1, days[1], days[1], 10.0, 11.0, 0.10, 1.0, "target")
    arrays = {
        "A": _arrays("A", days, [10, 10], [10, 10], [10, 10], [10, 10], [1, 0]),
        "B": _arrays("B", days, [10, 10], [10, 10], [10, 10], [10, 11], [0, 1]),
    }
    ledger, _ = allocate_slots([same_day, later], arrays, days, 1, cfg)
    assert ledger.height == 2  # both taken; same-day trade did not block the slot
    assert set(ledger["symbol"].to_list()) == {"A", "B"}


def test_dynamic_sizing_keeps_equity_positive_through_losses():
    # A long run of -8% losing trades must shrink equity geometrically, never go
    # negative (regression: fixed initial-capital sizing produced leverage/blowup).
    cfg = BacktestConfig(capital=100.0, cost_bps_round_trip=0.0, max_hold_days=40)
    n = 12
    days = [date(2020, 1, d + 1) for d in range(n)]
    candidates = []
    for i in range(0, n - 1, 2):  # enter even day, exit next day at -8%
        candidates.append(
            CandidateTrade("A", i, days[i], days[i + 1], 100.0, 92.0, -0.08, 1.0, "stoploss")
        )
    closes = [100.0] * n
    arrays = {
        "A": _arrays(
            "A", days, [100.0] * n, [100.0] * n, [92.0] * n, closes, [0] * n
        )
    }
    _, equity = allocate_slots(candidates, arrays, days, 1, cfg)
    assert equity.min() > 0  # never negative
    assert equity[-1] < 100.0  # losses compounded down
