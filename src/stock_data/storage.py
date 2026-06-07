from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from stock_data.intervals import IntervalSpec
from stock_data.normalization import CANONICAL_SCHEMA


class StorageError(ValueError):
    """Raised when price storage is invalid or unavailable."""


@dataclass(frozen=True)
class WriteResult:
    changed: bool
    downloaded_rows: int
    stored_rows: int


class PriceStore:
    def __init__(self, prices_dir: Path, interval: IntervalSpec) -> None:
        self.prices_dir = prices_dir
        self.interval = interval

    @property
    def interval_dir(self) -> Path:
        return self.prices_dir / self.interval.name

    def path_for(self, symbol: str) -> Path:
        if not symbol or "/" in symbol or "\\" in symbol:
            raise StorageError(f"Invalid symbol for storage: {symbol!r}")
        return self.interval_dir / f"{symbol}.parquet"

    def read(self, symbol: str) -> pl.DataFrame | None:
        path = self.path_for(symbol)
        if not path.exists():
            return None
        try:
            frame = pl.read_parquet(path)
            self._validate(symbol, frame)
            return frame
        except (OSError, pl.exceptions.PolarsError, StorageError) as exc:
            raise StorageError(f"Unable to read {path}: {exc}") from exc

    def latest_timestamp(self, symbol: str) -> datetime | None:
        frame = self.read(symbol)
        return None if frame is None else frame["trade_timestamp"].max()

    def upsert(self, symbol: str, new_rows: pl.DataFrame) -> WriteResult:
        self._validate(symbol, new_rows)
        existing = self.read(symbol)
        merged = new_rows if existing is None else pl.concat([existing, new_rows])
        merged = merged.unique(["symbol", "trade_timestamp"], keep="last").sort(
            "trade_timestamp"
        )
        if existing is not None and existing.equals(merged):
            return WriteResult(False, new_rows.height, existing.height)
        self.write_atomic(symbol, merged)
        return WriteResult(True, new_rows.height, merged.height)

    def write_atomic(self, symbol: str, frame: pl.DataFrame) -> None:
        self._validate(symbol, frame)
        self.interval_dir.mkdir(parents=True, exist_ok=True)
        destination = self.path_for(symbol)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.interval_dir, delete=False
            ) as file:
                temporary = Path(file.name)
            frame.write_parquet(temporary)
            self._validate(symbol, pl.read_parquet(temporary))
            os.replace(temporary, destination)
        except (OSError, pl.exceptions.PolarsError, StorageError) as exc:
            raise StorageError(f"Unable to write {destination}: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate(symbol: str, frame: pl.DataFrame) -> None:
        if frame.schema != CANONICAL_SCHEMA:
            raise StorageError(f"Unexpected schema for {symbol}: {frame.schema}")
        if frame.is_empty():
            raise StorageError(f"Price data for {symbol} is empty")
        if frame.null_count().select(pl.sum_horizontal(pl.all())).item() > 0:
            raise StorageError(f"Price data for {symbol} contains nulls")
        if frame.unique(["symbol", "trade_timestamp"]).height != frame.height:
            raise StorageError(f"Price data for {symbol} contains duplicate timestamps")
        if frame["symbol"].unique().to_list() != [symbol]:
            raise StorageError(f"Price data contains unexpected symbols for {symbol}")
