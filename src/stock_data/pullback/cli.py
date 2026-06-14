from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from stock_data.pullback.report import render_json, render_markdown
from stock_data.pullback.screen import analyze_symbol, screen_universe

app = typer.Typer(no_args_is_help=True)


@app.command("analyze")
def analyze(
    prices_root: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    interval: Annotated[str, typer.Option()],
    symbol: Annotated[str, typer.Option()],
    output: Annotated[str, typer.Option()],
) -> None:
    result = analyze_symbol(prices_root, interval, symbol)
    if output != "json":
        raise typer.BadParameter("analyze output must be json")
    typer.echo(render_json(result))


@app.command("screen")
def screen(
    prices_root: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    interval: Annotated[str, typer.Option()],
    output: Annotated[str, typer.Option()],
) -> None:
    result = screen_universe(prices_root, interval)
    if output == "json":
        typer.echo(render_json(result))
    elif output == "markdown":
        typer.echo(render_markdown(result))
    else:
        raise typer.BadParameter("screen output must be json or markdown")
