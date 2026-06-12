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


def detect_swings(frame: pl.LazyFrame) -> pl.LazyFrame:
    window = SWING_RADIUS * 2 + 1
    rolling_high = pl.col("high").rolling_max(window, center=True)
    rolling_low = pl.col("low").rolling_min(window, center=True)
    return frame.with_columns(
        is_swing_high=(
            (pl.col("high") == rolling_high)
            & ((pl.col("high") - rolling_low) >= pl.col("tolerance"))
        ),
        is_swing_low=(
            (pl.col("low") == rolling_low)
            & ((rolling_high - pl.col("low")) >= pl.col("tolerance"))
        ),
    )


def _ordered_pivots(frame: pl.DataFrame) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in frame.iter_rows(named=True):
        if row["is_swing_high"]:
            candidates.append(
                {"kind": "high", "index": row["row_index"], "value": row["high"]}
            )
        if row["is_swing_low"]:
            candidates.append(
                {"kind": "low", "index": row["row_index"], "value": row["low"]}
            )
    candidates.sort(key=lambda pivot: (pivot["index"], pivot["kind"]))
    pivots: list[dict[str, Any]] = []
    for pivot in candidates:
        if pivots and pivots[-1]["kind"] == pivot["kind"]:
            more_extreme = (
                pivot["value"] > pivots[-1]["value"]
                if pivot["kind"] == "high"
                else pivot["value"] < pivots[-1]["value"]
            )
            if more_extreme:
                pivots[-1] = pivot
        else:
            pivots.append(pivot)
    return pivots


def _slope(pivots: list[dict[str, Any]]) -> float | None:
    if len(pivots) < 2:
        return None
    xs = [float(pivot["index"]) for pivot in pivots]
    ys = [float(pivot["value"]) for pivot in pivots]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    variance = sum((value - x_mean) ** 2 for value in xs)
    if variance == 0:
        return None
    return sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(xs, ys, strict=True)
    ) / variance


def _trend_and_sequence(
    highs: list[dict[str, Any]], lows: list[dict[str, Any]], tolerance: float
) -> tuple[str, str]:
    if len(highs) < 2 or len(lows) < 2:
        return "insufficient", "insufficient"
    high_change = highs[-1]["value"] - highs[-2]["value"]
    low_change = lows[-1]["value"] - lows[-2]["value"]
    if high_change > tolerance and low_change > tolerance:
        return "bullish", "higher-highs-higher-lows"
    if high_change < -tolerance and low_change < -tolerance:
        return "bearish", "lower-highs-lower-lows"
    return "sideways", "mixed"


def _formation(
    high_slope: float | None, low_slope: float | None, tolerance: float
) -> str:
    if high_slope is None or low_slope is None:
        return "insufficient"
    flat = tolerance * 0.25
    if abs(high_slope) <= flat and abs(low_slope) <= flat:
        return "horizontal-range"
    if high_slope > flat and low_slope > flat:
        return "ascending-channel"
    if high_slope < -flat and low_slope < -flat:
        return "descending-channel"
    return "mixed"


def _breakout_state(
    close: float, support: float | None, resistance: float | None, tolerance: float
) -> str:
    if resistance is not None and close > resistance + tolerance:
        return "breakout"
    if support is not None and close < support - tolerance:
        return "breakdown"
    return "inside"


def classify_structure(frame: pl.DataFrame, pivots: list[dict[str, Any]]) -> dict[str, Any]:
    highs = [pivot for pivot in pivots if pivot["kind"] == "high"]
    lows = [pivot for pivot in pivots if pivot["kind"] == "low"]
    tolerance = float(frame["tolerance"].drop_nulls()[-1])
    close = float(frame["close"][-1])
    high_slope = _slope(highs[-4:])
    low_slope = _slope(lows[-4:])
    trend, sequence = _trend_and_sequence(highs, lows, tolerance)
    support = float(lows[-1]["value"]) if lows else None
    resistance = float(highs[-1]["value"]) if highs else None
    return {
        "trend": trend,
        "swing_sequence": sequence,
        "formation": _formation(high_slope, low_slope, tolerance),
        "support": support,
        "resistance": resistance,
        "high_boundary_slope": high_slope,
        "low_boundary_slope": low_slope,
        "breakout_state": _breakout_state(close, support, resistance, tolerance),
    }


def analyze_frame(
    frame: pl.LazyFrame, metadata: dict[str, Any], historical: bool = False
) -> dict[str, Any]:
    collected = _collect_usable(detect_swings(add_features(frame)))
    pivots = _ordered_pivots(collected)
    return {
        "data": {
            **metadata,
            "period_count": collected.height,
            "start": collected["trade_timestamp"][0],
            "end": collected["trade_timestamp"][-1],
        },
        "structure": classify_structure(collected, pivots),
        "patterns": [],
    }
