from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

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
        self, store: PriceStore, yahoo: YahooClient, initial_start: date
    ) -> None:
        self.store = store
        self.yahoo = yahoo
        self.initial_start = initial_start

    def update(
        self,
        symbols: list[str],
        completed_date: date,
        start: date | None = None,
        end: date | None = None,
    ) -> UpdateSummary:
        if (start is None) != (end is None):
            raise ValueError("start and end must be supplied together")
        groups, results = self._plan(symbols, completed_date, start, end)
        for (request_start, request_end), group in groups.items():
            results.extend(
                self._process_group(group, request_start, request_end, completed_date)
            )
        ordered = sorted(results, key=lambda result: symbols.index(result.symbol))
        return UpdateSummary(tuple(ordered))

    def _plan(
        self,
        symbols: list[str],
        completed_date: date,
        start: date | None,
        end: date | None,
    ) -> tuple[dict[tuple[date, date], list[str]], list[SymbolResult]]:
        groups: dict[tuple[date, date], list[str]] = defaultdict(list)
        results: list[SymbolResult] = []
        for symbol in symbols:
            try:
                request_start = start or self._incremental_start(symbol)
            except Exception as exc:
                LOGGER.exception("Update planning failed symbol=%s", symbol)
                results.append(
                    SymbolResult(symbol, SymbolStatus.FAILED, 0, 0, str(exc))
                )
                continue
            request_end = min(end or completed_date, completed_date)
            if request_start > request_end:
                results.append(SymbolResult(symbol, SymbolStatus.UNCHANGED, 0, 0, None))
            else:
                groups[(request_start, request_end)].append(symbol)
        return groups, results

    def _incremental_start(self, symbol: str) -> date:
        latest = self.store.latest_date(symbol)
        return self.initial_start if latest is None else latest + timedelta(days=1)

    def _process_group(
        self, symbols: list[str], start: date, end: date, cutoff: date
    ) -> list[SymbolResult]:
        batch = self.yahoo.download(symbols, start, end)
        results: list[SymbolResult] = []
        for symbol in symbols:
            if symbol in batch.errors:
                results.append(
                    SymbolResult(
                        symbol, SymbolStatus.FAILED, 0, 0, batch.errors[symbol]
                    )
                )
                continue
            try:
                normalized = normalize_symbol(symbol, batch.frames[symbol], cutoff)
                write = self.store.upsert(symbol, normalized)
                status = (
                    SymbolStatus.SUCCESS if write.changed else SymbolStatus.UNCHANGED
                )
                result = SymbolResult(
                    symbol, status, write.downloaded_rows, write.stored_rows, None
                )
                LOGGER.info(
                    "Update complete symbol=%s status=%s downloaded_rows=%d stored_rows=%d",
                    symbol,
                    status,
                    write.downloaded_rows,
                    write.stored_rows,
                )
                results.append(result)
            except Exception as exc:
                LOGGER.exception("Update failed symbol=%s", symbol)
                results.append(
                    SymbolResult(symbol, SymbolStatus.FAILED, 0, 0, str(exc))
                )
        return results
