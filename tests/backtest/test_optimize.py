from __future__ import annotations

from stock_data.backtest.optimize import StrategyResult, _better


def test_better_prefers_higher_calmar():
    a = StrategyResult("s", 0.05, 0.10, 5, {"calmar": 2.0, "cagr": 0.1})
    b = StrategyResult("s", 0.04, 0.12, 8, {"calmar": 1.0, "cagr": 0.9})
    assert _better(a, b)


def test_better_tiebreak_on_cagr():
    a = StrategyResult("s", 0.05, 0.10, 5, {"calmar": 1.0, "cagr": 0.20})
    b = StrategyResult("s", 0.04, 0.12, 8, {"calmar": 1.0, "cagr": 0.10})
    assert _better(a, b)
