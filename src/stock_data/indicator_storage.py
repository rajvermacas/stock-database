from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import polars as pl

from stock_data.indicators import INDICATOR_COLUMNS, INDICATOR_SCHEMA
from stock_data.intervals import IntervalSpec
from stock_data.normalization import CANONICAL_COLUMNS, CANONICAL_SCHEMA


class IndicatorStorageError(ValueError):
    """Raised when indicator storage is invalid or unavailable."""


@dataclass(frozen=True)
class IndicatorMetadata:
    source_fingerprint: str


def source_fingerprint(prices: pl.DataFrame) -> str:
    if prices.schema != CANONICAL_SCHEMA:
        raise IndicatorStorageError(f"Unexpected price schema: {prices.schema}")
    buffer = io.BytesIO()
    prices.select(CANONICAL_COLUMNS).write_ipc(buffer)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


class IndicatorStore:
    def __init__(self, indicators_dir: Path, interval: IntervalSpec) -> None:
        self.indicators_dir = indicators_dir
        self.interval = interval

    @property
    def interval_dir(self) -> Path:
        return self.indicators_dir / self.interval.name

    def path_for(self, symbol: str) -> Path:
        self._validate_symbol(symbol)
        return self.interval_dir / f"{symbol}.parquet"

    def metadata_path_for(self, symbol: str) -> Path:
        self._validate_symbol(symbol)
        return self.interval_dir / f"{symbol}.metadata.json"

    def read(self, symbol: str) -> pl.DataFrame | None:
        path = self.path_for(symbol)
        if not path.exists():
            return None
        try:
            frame = pl.read_parquet(path)
            self._validate_frame(symbol, frame)
            return frame
        except (OSError, pl.exceptions.PolarsError, IndicatorStorageError) as exc:
            raise IndicatorStorageError(f"Unable to read {path}: {exc}") from exc

    def is_current(self, symbol: str, fingerprint: str) -> bool:
        path = self.path_for(symbol)
        metadata_path = self.metadata_path_for(symbol)
        if not path.exists() or not metadata_path.exists():
            return False
        return self._read_metadata(metadata_path).source_fingerprint == fingerprint

    def publish(self, symbol: str, frame: pl.DataFrame, fingerprint: str) -> None:
        self._validate_frame(symbol, frame)
        self.interval_dir.mkdir(parents=True, exist_ok=True)
        destination = self.path_for(symbol)
        metadata_destination = self.metadata_path_for(symbol)
        staged = self._stage_frame(symbol, frame)
        staged_metadata = self._stage_metadata(fingerprint)
        try:
            self._publish_pair(
                staged, destination, staged_metadata, metadata_destination
            )
        finally:
            staged.unlink(missing_ok=True)
            staged_metadata.unlink(missing_ok=True)

    def remove(self, symbol: str) -> bool:
        path = self.path_for(symbol)
        metadata = self.metadata_path_for(symbol)
        existed = path.exists() or metadata.exists()
        try:
            path.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            return existed
        except OSError as exc:
            raise IndicatorStorageError(
                f"Unable to remove indicators for {symbol}"
            ) from exc

    def _stage_frame(self, symbol: str, frame: pl.DataFrame) -> Path:
        path = self._temporary_path(".parquet")
        try:
            frame.write_parquet(path)
            self._validate_frame(symbol, pl.read_parquet(path))
            return path
        except (OSError, pl.exceptions.PolarsError, IndicatorStorageError) as exc:
            path.unlink(missing_ok=True)
            raise IndicatorStorageError(
                f"Unable to stage indicators for {symbol}"
            ) from exc

    def _stage_metadata(self, fingerprint: str) -> Path:
        path = self._temporary_path(".json")
        try:
            metadata = IndicatorMetadata(fingerprint)
            path.write_text(
                json.dumps(asdict(metadata), sort_keys=True), encoding="utf-8"
            )
            self._read_metadata(path)
            return path
        except (OSError, json.JSONDecodeError, IndicatorStorageError) as exc:
            path.unlink(missing_ok=True)
            raise IndicatorStorageError("Unable to stage indicator metadata") from exc

    def _publish_pair(
        self, staged: Path, destination: Path, staged_metadata: Path, metadata: Path
    ) -> None:
        backup = self._backup_path(destination)
        metadata_backup = self._backup_path(metadata)
        try:
            self._move_existing(destination, backup)
            self._move_existing(metadata, metadata_backup)
            os.replace(staged, destination)
            os.replace(staged_metadata, metadata)
        except OSError as exc:
            self._restore(destination, backup)
            self._restore(metadata, metadata_backup)
            raise IndicatorStorageError(f"Unable to publish {destination}") from exc
        finally:
            backup.unlink(missing_ok=True)
            metadata_backup.unlink(missing_ok=True)

    def _read_metadata(self, path: Path) -> IndicatorMetadata:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if set(raw) != {"source_fingerprint"} or not raw["source_fingerprint"]:
                raise IndicatorStorageError(f"Invalid indicator metadata: {raw}")
            return IndicatorMetadata(source_fingerprint=raw["source_fingerprint"])
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise IndicatorStorageError(f"Unable to read {path}: {exc}") from exc

    def _temporary_path(self, suffix: str) -> Path:
        with tempfile.NamedTemporaryFile(
            dir=self.interval_dir, suffix=suffix, delete=False
        ) as file:
            return Path(file.name)

    def _backup_path(self, path: Path) -> Path:
        return path.with_name(f".{path.name}.backup")

    @staticmethod
    def _move_existing(path: Path, backup: Path) -> None:
        if path.exists():
            os.replace(path, backup)

    @staticmethod
    def _restore(path: Path, backup: Path) -> None:
        path.unlink(missing_ok=True)
        if backup.exists():
            os.replace(backup, path)

    @staticmethod
    def _validate_symbol(symbol: str) -> None:
        if not symbol or "/" in symbol or "\\" in symbol:
            raise IndicatorStorageError(f"Invalid symbol for storage: {symbol!r}")

    @staticmethod
    def _validate_frame(symbol: str, frame: pl.DataFrame) -> None:
        if frame.schema != INDICATOR_SCHEMA:
            raise IndicatorStorageError(
                f"Unexpected schema for {symbol}: {frame.schema}"
            )
        if frame.is_empty():
            raise IndicatorStorageError(f"Indicator data for {symbol} is empty")
        finite_or_null = frame.select(
            (pl.col(column).is_finite() | pl.col(column).is_null()).all()
            for column in INDICATOR_COLUMNS
        )
        if not all(finite_or_null.row(0)):
            raise IndicatorStorageError(f"Indicator data for {symbol} is non-finite")
        if frame["symbol"].unique().to_list() != [symbol]:
            raise IndicatorStorageError("Indicator data contains unexpected symbols")
        if frame["trade_timestamp"].n_unique() != frame.height:
            raise IndicatorStorageError(f"Indicator data for {symbol} has duplicates")
        if not frame["trade_timestamp"].is_sorted():
            raise IndicatorStorageError(f"Indicator data for {symbol} is not sorted")
