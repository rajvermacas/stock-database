from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_data.backtest.errors import ZeroTradesError
from stock_data.backtest.metrics import cagr, compute_metrics, max_drawdown


def test_max_drawdown_simple():
    eq = pl.Series([100.0, 120.0, 90.0, 110.0])  # peak 120 -> trough 90 = 25%
    assert abs(max_drawdown(eq) - 0.25) < 1e-9


def test_cagr_doubling_in_one_year():
    eq = pl.Series([100.0, 200.0])
    val = cagr(eq, date(2020, 1, 1), date(2021, 1, 1))
    assert abs(val - 1.0) < 0.01  # ~100% per year


def test_compute_metrics_raises_on_no_trades():
    eq = pl.Series([100.0, 101.0])
    empty = pl.DataFrame(schema={"return_pct": pl.Float64})
    with pytest.raises(ZeroTradesError):
        compute_metrics(eq, empty, date(2020, 1, 1), date(2021, 1, 1), 0.05)


def test_compute_metrics_winrate_and_calmar():
    eq = pl.Series([100.0, 130.0, 110.0, 150.0])  # mdd from 130->110 = ~15.4%
    ledger = pl.DataFrame({"return_pct": [0.10, -0.05, 0.20]})
    m = compute_metrics(eq, ledger, date(2020, 1, 1), date(2021, 1, 1), 0.05)
    assert abs(m["winrate"] - 2 / 3) < 1e-9
    assert m["num_trades"] == 3
    assert m["calmar"] > 0
