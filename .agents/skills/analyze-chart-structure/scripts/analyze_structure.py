from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

MIN_PERIODS = 40
DEFAULT_PERIODS = 120
ATR_PERIOD = 14
SWING_RADIUS = 2
HISTORICAL_HORIZONS = (5, 10, 20)
INTERVAL_PATTERN = re.compile(r"^[1-9][0-9]*(m|h|d|wk|mo)$")


class StructureError(ValueError):
    """Raised when structural chart analysis cannot be completed."""


@dataclass(frozen=True)
class AnalysisRequest:
    symbol: str
    interval: str
    prices_root: Path
    start: datetime | None
    end: datetime | None
    periods: int | None
    historical: bool


def validate_request(
    symbol: str,
    interval: str,
    start: datetime | None,
    end: datetime | None,
    periods: int | None,
    prices_root: Path = Path("market-data/prices"),
    historical: bool = False,
) -> AnalysisRequest:
    if not symbol or "/" in symbol or "\\" in symbol:
        raise StructureError(f"Invalid symbol: {symbol!r}")
    if not INTERVAL_PATTERN.fullmatch(interval):
        raise StructureError(f"Invalid or ambiguous interval: {interval!r}")
    if periods is not None and (start is not None or end is not None):
        raise StructureError("Use either periods or dates, not both")
    if periods is not None and periods < MIN_PERIODS:
        raise StructureError(f"Periods must be at least {MIN_PERIODS}")
    if start is not None and end is not None and start > end:
        raise StructureError("Start date must not follow end date")
    if periods is None and start is None and end is None:
        periods = DEFAULT_PERIODS
    return AnalysisRequest(
        symbol, interval, prices_root, start, end, periods, historical
    )


def _load_stock_frame() -> Any:
    path = (
        Path(__file__).resolve().parents[2]
        / "talk-to-stock-data"
        / "scripts"
        / "stock_frame.py"
    )
    spec = importlib.util.spec_from_file_location("structure_stock_frame", path)
    if spec is None or spec.loader is None:
        raise StructureError(f"Unable to import stock-frame helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_analysis_frame(request: AnalysisRequest) -> tuple[pl.LazyFrame, dict[str, Any]]:
    helper = _load_stock_frame()
    try:
        frame, resolution = helper.load_prices(
            request.interval,
            request.prices_root,
            [request.symbol],
            request.start,
            request.end,
        )
    except Exception as exc:
        raise StructureError(f"Unable to load prices for {request.symbol}: {exc}") from exc
    if request.periods is not None:
        frame = frame.tail(request.periods)
    metadata = {
        "symbol": request.symbol,
        "requested_interval": resolution.requested_interval,
        "source_interval": resolution.source_interval,
        "derived": resolution.derived,
    }
    return frame, metadata


def add_features(frame: pl.LazyFrame) -> pl.LazyFrame:
    previous_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - previous_close).abs(),
        (pl.col("low") - previous_close).abs(),
    )
    return (
        frame.with_row_index("row_index")
        .with_columns(
            true_range=true_range,
            candle_body=(pl.col("close") - pl.col("open")).abs(),
            normalized_volume=(
                pl.col("volume").cast(pl.Float64)
                / pl.col("volume").cast(pl.Float64).rolling_mean(20)
            ),
        )
        .with_columns(atr_14=pl.col("true_range").rolling_mean(ATR_PERIOD))
        .with_columns(
            tolerance=pl.max_horizontal(
                pl.col("atr_14"), pl.col("close") * 0.005
            )
        )
    )


def _collect_usable(frame: pl.LazyFrame) -> pl.DataFrame:
    collected = frame.collect()
    usable = collected.filter(pl.col("tolerance").is_not_null())
    if usable.height < MIN_PERIODS:
        raise StructureError(
            f"Analysis requires at least {MIN_PERIODS} usable rows; got {usable.height}"
        )
    return collected
