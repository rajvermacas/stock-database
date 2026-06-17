from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from stock_data.config import AppConfig, ConfigError, load_config
from stock_data.indicator_service import IndicatorUpdater
from stock_data.indicator_storage import IndicatorStore
from stock_data.intervals import get_interval
from stock_data.logging_config import LoggingConfigError, configure_logging
from stock_data.service import SymbolStatus, UpdateService, UpdateSummary
from stock_data.storage import PriceStore
from stock_data.symbols import SymbolFileError, load_symbols
from stock_data.yahoo import YahooClient

LOGGER = logging.getLogger(__name__)
app = typer.Typer(no_args_is_help=True)


class State:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Download and maintain local NSE stock price data."""
    ctx.obj = State(config)


@app.command("update-all")
def update_all(
    ctx: typer.Context,
) -> None:
    """Update every symbol in the configured CSV file."""
    _execute(ctx.obj, None)


@app.command("update-symbol")
def update_symbol(
    ctx: typer.Context,
    symbol: str,
) -> None:
    """Update one Yahoo Finance symbol."""
    _execute(ctx.obj, symbol.strip())


def _execute(
    state: State,
    symbol: str | None,
) -> None:
    try:
        config = load_config(state.config_path)
        configure_logging(config.paths.logs_dir)
        config.paths.prices_dir.mkdir(parents=True, exist_ok=True)
        symbols = [symbol] if symbol else load_symbols(config.paths.symbols_file)
        if symbols == [""]:
            raise ValueError("symbol must not be blank")
        typer.echo(f"Interval: {config.yahoo.interval}")
        typer.echo(
            f"Price directory: {config.paths.prices_dir / config.yahoo.interval}"
        )
        if config.indicators.enabled:
            typer.echo(
                "Indicator directory: "
                f"{config.paths.indicators_dir / config.yahoo.interval}"
            )
        started = time.monotonic()
        summary = _run(config, symbols)
        LOGGER.info(
            "Command completed duration_seconds=%.3f", time.monotonic() - started
        )
        _print_summary(summary)
        if summary.has_failures:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except (
        ConfigError,
        LoggingConfigError,
        SymbolFileError,
        OSError,
        ValueError,
    ) as exc:
        LOGGER.exception("Command failed")
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc


def _run(
    config: AppConfig,
    symbols: list[str],
) -> UpdateSummary:
    interval = get_interval(config.yahoo.interval)
    price_store = PriceStore(config.paths.prices_dir, interval)
    indicator_updater = None
    if config.indicators.enabled:
        indicator_store = IndicatorStore(config.paths.indicators_dir, interval)
        indicator_updater = IndicatorUpdater(price_store, indicator_store)
    service = UpdateService(
        price_store,
        YahooClient(config.yahoo),
        indicator_updater,
        interval,
        config.download.initial_start_date,
        config.download.end_date,
    )
    return service.update(symbols, datetime.now(timezone.utc))


def _print_summary(summary: UpdateSummary) -> None:
    typer.echo(f"Successful: {summary.count(SymbolStatus.SUCCESS)}")
    typer.echo(f"Unchanged: {summary.count(SymbolStatus.UNCHANGED)}")
    typer.echo(f"Failed: {summary.count(SymbolStatus.FAILED)}")
    for result in summary.results:
        if result.status == SymbolStatus.FAILED:
            typer.echo(f"  {result.symbol}: {result.error}")
