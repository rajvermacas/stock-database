"""Data layer: load prices/indicators per timeframe, derive weekly, enforce freshness.

All loads are Polars lazy scans collected once. Fail fast on missing files,
insufficient history, or stale data — never substitute or truncate silently.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Kolkata")
DATA_ROOT = Path("market-data")
MAX_STALE_CALENDAR_DAYS = 7
MIN_DAILY_BARS = 120
MIN_HOURLY_BARS = 200
WEEKLY_EMA_SPANS = (10, 20, 50)


class DataUnavailableError(Exception):
    """Requested symbol/interval/range is not available on disk."""


class StaleDataError(Exception):
    """Last stored bar is too old to evaluate against."""


def _require_file(path: Path) -> Path:
    if not path.exists():
        raise DataUnavailableError(f"Required data file missing: {path}")
    return path


def prices_path(symbol: str, interval: str) -> Path:
    return _require_file(DATA_ROOT / "prices" / interval / f"{symbol}.parquet")


def indicators_path(symbol: str, interval: str) -> Path:
    return _require_file(DATA_ROOT / "indicators" / interval / f"{symbol}.parquet")


def resolve_symbol(raw: str) -> str:
    """Resolve user input (e.g. 'rpel') to a stored Yahoo symbol (RPEL.NS)."""
    candidate = raw.strip().upper()
    if not candidate:
        raise DataUnavailableError("Empty symbol provided")
    daily_dir = DATA_ROOT / "prices" / "1d"
    if (daily_dir / f"{candidate}.parquet").exists():
        return candidate
    suffixed = f"{candidate}.NS"
    if (daily_dir / f"{suffixed}.parquet").exists():
        logger.info("Resolved symbol %s -> %s", raw, suffixed)
        return suffixed
    raise DataUnavailableError(
        f"Symbol '{raw}' not found in {daily_dir} (tried {candidate}, {suffixed})"
    )


def load_joined(symbol: str, interval: str) -> pl.DataFrame:
    """Prices joined with same-interval precalculated indicators (left join).

    Left join keeps the full price history; indicator columns are null during
    the 365-day warm-up window and that is disclosed by the caller.
    """
    frame = (
        pl.scan_parquet(prices_path(symbol, interval))
        .select("symbol", "trade_timestamp", "open", "high", "low", "close", "volume")
        .join(
            pl.scan_parquet(indicators_path(symbol, interval)).drop("symbol"),
            on="trade_timestamp",
            how="left",
        )
        .set_sorted("trade_timestamp")
        .collect()
    )
    if frame.is_empty():
        raise DataUnavailableError(f"No rows in {interval} data for {symbol}")
    logger.info(
        "Loaded %s %s: %d bars, %s -> %s",
        symbol, interval, frame.height,
        frame["trade_timestamp"].min(), frame["trade_timestamp"].max(),
    )
    return frame


def check_freshness(frame: pl.DataFrame, symbol: str, interval: str) -> dict:
    """Raise if the latest bar is older than MAX_STALE_CALENDAR_DAYS."""
    last_ts = frame["trade_timestamp"].max()
    if not isinstance(last_ts, datetime):
        raise DataUnavailableError(f"{symbol} {interval}: no valid trade_timestamp values")
    now = datetime.now(TZ)
    age_days = (now - last_ts).days
    if now - last_ts > timedelta(days=MAX_STALE_CALENDAR_DAYS):
        raise StaleDataError(
            f"{symbol} {interval} data is stale: last bar {last_ts:%Y-%m-%d}, "
            f"{age_days} calendar days old (limit {MAX_STALE_CALENDAR_DAYS})"
        )
    return {
        "last_bar": str(last_ts),
        "age_calendar_days": age_days,
        "bars": frame.height,
        "first_bar": str(frame["trade_timestamp"].min()),
    }


def require_min_bars(frame: pl.DataFrame, minimum: int, label: str) -> None:
    if frame.height < minimum:
        raise DataUnavailableError(
            f"Insufficient history for {label}: {frame.height} bars < required {minimum}"
        )


def load_daily(symbol: str) -> pl.DataFrame:
    frame = load_joined(symbol, "1d")
    require_min_bars(frame, MIN_DAILY_BARS, f"{symbol} 1d")
    return frame


def load_hourly(symbol: str) -> pl.DataFrame:
    frame = load_joined(symbol, "1h")
    require_min_bars(frame, MIN_HOURLY_BARS, f"{symbol} 1h")
    return frame


def derive_weekly(daily: pl.DataFrame) -> pl.DataFrame:
    """Weekly OHLCV from daily, with on-demand weekly EMAs (calculated, not stored).

    ATR(14) on weekly is also calculated on demand for level tolerance work.
    """
    weekly = (
        daily.lazy()
        .set_sorted("trade_timestamp")
        .group_by_dynamic("trade_timestamp", every="1w", group_by="symbol")
        .agg(
            open=pl.col("open").first(),
            high=pl.col("high").max(),
            low=pl.col("low").min(),
            close=pl.col("close").last(),
            volume=pl.col("volume").sum(),
        )
        .with_columns(
            [pl.col("close").ewm_mean(span=s).alias(f"ema_{s}") for s in WEEKLY_EMA_SPANS]
        )
        .with_columns(
            tr=pl.max_horizontal(
                pl.col("high") - pl.col("low"),
                (pl.col("high") - pl.col("close").shift(1)).abs(),
                (pl.col("low") - pl.col("close").shift(1)).abs(),
            )
        )
        .with_columns(atr_14=pl.col("tr").ewm_mean(span=14))
        .drop("tr")
        .collect()
    )
    logger.info("Derived weekly: %d bars (EMAs %s + ATR14 calculated on demand)",
                weekly.height, list(WEEKLY_EMA_SPANS))
    return weekly
