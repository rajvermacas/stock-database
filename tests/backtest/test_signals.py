from __future__ import annotations

from datetime import date

import polars as pl

from stock_data.backtest.signals import SIGNALS, macd_adx


def _base(n: int) -> dict:
    ts = (
        pl.datetime_range(
            date(2020, 1, 1), date(2030, 1, 1), interval="1d", eager=True
        )[:n]
        .dt.replace_time_zone("Asia/Kolkata")
        .alias("trade_timestamp")
    )
    return {
        "trade_timestamp": ts,
        "weekly_uptrend": [True] * n,
        "ema_10": [10.0] * n,
        "ema_20": [9.0] * n,
        "ema_50": [8.0] * n,
        "rsi_14": [50.0] * n,
        "low": [9.5] * n,
        "close": [11.0] * n,
        "trailing_365d_high": [100.0] * n,
        "relative_volume_20": [1.0] * n,
        "band_lower_20_2": [5.0] * n,
        "macd_12_26": [0.0] * n,
        "macd_signal_9": [1.0] * n,
        "adx_14": [30.0] * n,
    }


def test_all_signals_return_bool_series_of_right_length():
    frame = pl.DataFrame(_base(60))
    for name, fn in SIGNALS.items():
        out = fn(frame)
        assert out.dtype == pl.Boolean, name
        assert out.len() == 60, name


def test_macd_adx_fires_on_cross_with_strong_adx():
    cols = _base(5)
    # Build a clean MACD cross-up on the last bar with ADX>25.
    cols["macd_12_26"] = [0.0, 0.0, 0.0, 0.0, 2.0]
    cols["macd_signal_9"] = [1.0, 1.0, 1.0, 1.0, 1.0]
    out = macd_adx(pl.DataFrame(cols))
    assert out[-1]  # cross up + adx 30 > 25
    assert not out[0]
