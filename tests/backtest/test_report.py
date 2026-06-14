from __future__ import annotations

import polars as pl

from stock_data.backtest.report import render_markdown, write_report


def _table() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "strategy": "pullback_buy",
                "stoploss_pct": 5.0,
                "target_pct": 12.0,
                "k_slots": 8,
                "train_calmar": 2.0,
                "test_calmar": 1.4,
                "train_cagr": 0.25,
                "test_cagr": 0.18,
                "train_max_dd": 0.12,
                "test_max_dd": 0.13,
                "train_winrate": 0.55,
                "test_winrate": 0.5,
                "test_expectancy_r": 0.3,
                "test_avg_win_pct": 0.1,
                "test_avg_loss_pct": -0.04,
                "test_num_trades": 120,
                "overfit_gap": 0.6,
            }
        ]
    )


def test_markdown_names_winner_with_numbers():
    md = render_markdown(_table(), "2016..2022", "2023..2026", "2026-06-14")
    assert "Winner" in md
    assert "pullback_buy" in md
    assert "5%" in md and "12%" in md  # stoploss/target


def test_write_report_creates_both_files(tmp_path):
    md_path, csv_path = write_report(_table(), tmp_path, "2026-06-14", "T", "S")
    assert md_path.exists() and csv_path.exists()
