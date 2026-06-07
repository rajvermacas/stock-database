from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from stock_data.config import AppConfig, ConfigError, load_config
from stock_data.logging_config import LoggingConfigError, configure_logging
from stock_data.market_time import latest_completed_date
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
    start_date: Annotated[str | None, typer.Option()] = None,
    end_date: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Update every symbol in the configured CSV file."""
    _execute(ctx.obj, None, start_date, end_date)


@app.command("update-symbol")
def update_symbol(
    ctx: typer.Context,
    symbol: str,
    start_date: Annotated[str | None, typer.Option()] = None,
    end_date: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Update one Yahoo Finance symbol."""
    _execute(ctx.obj, symbol.strip(), start_date, end_date)


def _execute(
    state: State,
    symbol: str | None,
    start_date: str | None,
    end_date: str | None,
) -> None:
    try:
        start, end = _parse_dates(start_date, end_date)
        config = load_config(state.config_path)
        configure_logging(config.paths.logs_dir)
        config.paths.prices_dir.mkdir(parents=True, exist_ok=True)
        symbols = [symbol] if symbol else load_symbols(config.paths.symbols_file)
        if symbols == [""]:
            raise ValueError("symbol must not be blank")
        summary = _run(config, symbols, start, end)
        _print_summary(summary)
        if summary.has_failures:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except (ConfigError, LoggingConfigError, SymbolFileError, OSError, ValueError) as exc:
        LOGGER.exception("Command failed")
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc


def _run(
    config: AppConfig,
    symbols: list[str],
    start_date: date | None,
    end_date: date | None,
) -> UpdateSummary:
    service = UpdateService(
        PriceStore(config.paths.prices_dir),
        YahooClient(config.yahoo),
        config.download.initial_start_date,
    )
    completed = latest_completed_date(datetime.now(timezone.utc))
    return service.update(symbols, completed, start_date, end_date)


def _parse_dates(start_date: str | None, end_date: str | None) -> tuple[date | None, date | None]:
    if (start_date is None) != (end_date is None):
        raise ValueError("--start-date and --end-date must be supplied together")
    if start_date is None or end_date is None:
        return None, None
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("dates must use YYYY-MM-DD format") from exc
    if start > end:
        raise ValueError("--start-date must not be after --end-date")
    return start, end


def _print_summary(summary: UpdateSummary) -> None:
    typer.echo(f"Successful: {summary.count(SymbolStatus.SUCCESS)}")
    typer.echo(f"Unchanged: {summary.count(SymbolStatus.UNCHANGED)}")
    typer.echo(f"Failed: {summary.count(SymbolStatus.FAILED)}")
    for result in summary.results:
        if result.status == SymbolStatus.FAILED:
            typer.echo(f"  {result.symbol}: {result.error}")
