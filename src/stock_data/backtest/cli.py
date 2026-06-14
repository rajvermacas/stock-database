from __future__ import annotations

import logging
from pathlib import Path

from stock_data.backtest.compare import bakeoff
from stock_data.backtest.data import available_symbols, load_symbol_frame
from stock_data.backtest.params import TEST_WINDOW, TRAIN_WINDOW, BacktestConfig
from stock_data.backtest.report import write_report
from stock_data.config import load_config
from stock_data.symbols import load_symbols

LOGGER = logging.getLogger(__name__)


def run_bakeoff(
    config_path: Path, run_date: str, limit: int | None, capital: float
) -> tuple[Path, Path]:
    cfg_app = load_config(config_path)
    symbols = load_symbols(cfg_app.paths.symbols_file)
    usable = available_symbols(
        symbols, cfg_app.paths.indicators_dir, cfg_app.paths.prices_dir
    )
    if limit is not None:
        usable = usable[:limit]
    LOGGER.info("Loading %d symbol frames ...", len(usable))
    frames = {
        s: load_symbol_frame(
            cfg_app.paths.prices_dir, cfg_app.paths.indicators_dir, s
        )
        for s in usable
    }
    cfg = BacktestConfig(capital=capital)
    table = bakeoff(frames, TRAIN_WINDOW, TEST_WINDOW, cfg)
    out_dir = cfg_app.paths.data_dir / "backtest"
    train = f"{TRAIN_WINDOW.start}..{TRAIN_WINDOW.end}"
    test = f"{TEST_WINDOW.start}..{TEST_WINDOW.end}"
    return write_report(table, out_dir, run_date, train, test)
