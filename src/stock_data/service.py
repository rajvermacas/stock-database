from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from stock_data.indicator_service import IndicatorUpdater
from stock_data.intervals import IntervalSpec
from stock_data.normalization import normalize_symbol
from stock_data.storage import PriceStore
from stock_data.yahoo import YahooClient

LOGGER = logging.getLogger(__name__)


class SymbolStatus(StrEnum):
    SUCCESS = "success"
    UNCHANGED = "unchanged"
    FAILED = "failed"


@dataclass(frozen=True)
class SymbolResult:
    symbol: str
    status: SymbolStatus
    downloaded_rows: int
    stored_rows: int
    error: str | None


@dataclass(frozen=True)
class UpdateSummary:
    results: tuple[SymbolResult, ...]

    def count(self, status: SymbolStatus) -> int:
        return sum(result.status == status for result in self.results)

    @property
    def has_failures(self) -> bool:
        return self.count(SymbolStatus.FAILED) > 0


class UpdateService:
    def __init__(
        self,
        store: PriceStore,
        yahoo: YahooClient,
        indicators: IndicatorUpdater | None,
        interval: IntervalSpec,
        initial_start: date,
    ) -> None:
        self.store = store
        self.yahoo = yahoo
        self.indicators = indicators
        self.interval = interval
        self.initial_start = initial_start

    def update(
        self,
        symbols: list[str],
        now: datetime,
    ) -> UpdateSummary:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        results = self._process_group(
            symbols, self.initial_start, now.date(), now
        )
        results = self._refresh_indicators(results)
        ordered = sorted(results, key=lambda result: symbols.index(result.symbol))
        return UpdateSummary(tuple(ordered))

    def _refresh_indicators(self, results: list[SymbolResult]) -> list[SymbolResult]:
        if self.indicators is None:
            return results
        return [self._refresh_symbol_indicators(result) for result in results]

    def _refresh_symbol_indicators(self, result: SymbolResult) -> SymbolResult:
        if result.status == SymbolStatus.FAILED:
            return result
        try:
            refreshed = self.indicators.refresh(
                result.symbol, result.status == SymbolStatus.SUCCESS
            )
            status = SymbolStatus.SUCCESS if refreshed.changed else result.status
            return SymbolResult(
                result.symbol,
                status,
                result.downloaded_rows,
                result.stored_rows,
                None,
            )
        except Exception as exc:
            LOGGER.exception(
                "Indicator update failed symbol=%s interval=%s",
                result.symbol,
                self.interval.name,
            )
            return SymbolResult(
                result.symbol,
                SymbolStatus.FAILED,
                result.downloaded_rows,
                result.stored_rows,
                str(exc),
            )

    def _process_group(
        self, symbols: list[str], start: date, end: date, now: datetime
    ) -> list[SymbolResult]:
        batch = self.yahoo.download(symbols, start, end)
        return [
            self._process_symbol(symbol, batch.frames, batch.errors, now)
            for symbol in symbols
        ]

    def _process_symbol(
        self, symbol: str, frames: dict, errors: dict, now: datetime
    ) -> SymbolResult:
        if symbol in errors:
            return SymbolResult(symbol, SymbolStatus.FAILED, 0, 0, errors[symbol])
        try:
            normalized = normalize_symbol(symbol, frames[symbol], self.interval, now)
            write = self.store.replace(symbol, normalized)
            status = SymbolStatus.SUCCESS if write.changed else SymbolStatus.UNCHANGED
            LOGGER.info(
                "Update complete symbol=%s interval=%s status=%s downloaded_rows=%d stored_rows=%d",
                symbol,
                self.interval.name,
                status,
                write.downloaded_rows,
                write.stored_rows,
            )
            return SymbolResult(
                symbol, status, write.downloaded_rows, write.stored_rows, None
            )
        except Exception as exc:
            LOGGER.exception(
                "Update failed symbol=%s interval=%s", symbol, self.interval.name
            )
            return SymbolResult(symbol, SymbolStatus.FAILED, 0, 0, str(exc))
