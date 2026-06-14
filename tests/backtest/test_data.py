from __future__ import annotations

from datetime import date

import polars as pl

from stock_data.backtest.data import add_weekly_uptrend, slice_window


def _frame(closes: list[float]) -> pl.DataFrame:
    n = len(closes)
    days = pl.datetime_range(
        date(2020, 1, 1), date(2021, 1, 1), interval="1d", eager=True
    )[:n].dt.replace_time_zone("Asia/Kolkata")
    return pl.DataFrame(
        {
            "trade_timestamp": days,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1] * n,
        }
    )


def test_weekly_uptrend_first_week_false_no_lookahead():
    frame = _frame([float(i) for i in range(1, 41)])
    out = add_weekly_uptrend(frame)
    # First completed week has no previous week -> must be False (no look-ahead).
    assert out["weekly_uptrend"][0] == False  # noqa: E712
    assert "weekly_uptrend" in out.columns
    assert out.height == frame.height


def test_weekly_uptrend_eventually_true_for_rising_series():
    frame = _frame([float(i) for i in range(1, 60)])
    out = add_weekly_uptrend(frame)
    # A steadily rising series must register an uptrend at some later bar.
    assert out["weekly_uptrend"].sum() > 0


def test_slice_window_inclusive():
    frame = _frame([float(i) for i in range(1, 11)])
    out = slice_window(frame, date(2020, 1, 3), date(2020, 1, 5))
    assert out["trade_timestamp"].dt.date().min() == date(2020, 1, 3)
    assert out["trade_timestamp"].dt.date().max() == date(2020, 1, 5)
