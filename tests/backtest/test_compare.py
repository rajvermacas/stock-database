from __future__ import annotations

from stock_data.backtest.compare import _row
from stock_data.backtest.optimize import StrategyResult


def test_row_shapes_train_and_test_columns():
    best = StrategyResult(
        "pullback_buy",
        0.05,
        0.12,
        8,
        {"calmar": 2.0, "cagr": 0.25, "max_drawdown": 0.12, "winrate": 0.55},
    )
    test_m = {
        "calmar": 1.4,
        "cagr": 0.18,
        "max_drawdown": 0.13,
        "winrate": 0.5,
        "expectancy_r": 0.3,
        "avg_win_pct": 0.1,
        "avg_loss_pct": -0.04,
        "num_trades": 120,
    }
    row = _row(best, test_m)
    assert row["strategy"] == "pullback_buy"
    assert row["stoploss_pct"] == 5.0
    assert row["target_pct"] == 12.0
    assert abs(row["overfit_gap"] - 0.6) < 1e-9
