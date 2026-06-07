from datetime import date, datetime

import pandas as pd

from stock_data.intervals import IST, get_interval
from stock_data.indicator_service import IndicatorUpdateResult
from stock_data.service import SymbolStatus, UpdateService
from stock_data.storage import WriteResult
from stock_data.yahoo import DownloadBatch


class FakeStore:
    def __init__(self, latest=None, failed_symbol=None) -> None:
        self.latest = latest
        self.failed_symbol = failed_symbol
        self.upserted_symbols = []

    def latest_timestamp(self, symbol):
        if symbol == self.failed_symbol:
            raise ValueError("invalid parquet")
        return self.latest

    def upsert(self, symbol, frame):
        self.upserted_symbols.append(symbol)
        return WriteResult(True, frame.height, frame.height)


class FakeYahoo:
    def __init__(self, errors=None) -> None:
        self.requests = []
        self.errors = errors or {}

    def download(self, symbols, start, end):
        self.requests.append((symbols, start, end))
        frame = pd.DataFrame(
            {
                "Open": [1.0],
                "High": [2.0],
                "Low": [0.5],
                "Close": [1.5],
                "Volume": [10],
            },
            index=pd.DatetimeIndex([f"{end} 09:15"], name="Datetime"),
        )
        frames = {symbol: frame for symbol in symbols if symbol not in self.errors}
        return DownloadBatch(frames, self.errors)


class FakeIndicators:
    def __init__(self, failed_symbol=None) -> None:
        self.failed_symbol = failed_symbol
        self.requests = []

    def refresh(self, symbol, prices_changed):
        self.requests.append((symbol, prices_changed))
        if symbol == self.failed_symbol:
            raise ValueError("indicator failed")
        return IndicatorUpdateResult(True, 1)


def build_service(
    interval="30m",
    latest=None,
    errors=None,
    failed_symbol=None,
    indicator_failed_symbol=None,
):
    service = UpdateService(
        FakeStore(latest, failed_symbol),
        FakeYahoo(errors),
        FakeIndicators(indicator_failed_symbol),
        get_interval(interval),
        date(2000, 1, 1),
    )
    return service


def test_intraday_incremental_request_includes_next_candle_date() -> None:
    latest = datetime(2026, 6, 8, 14, 30, tzinfo=IST)
    service = build_service(latest=latest)
    service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.yahoo.requests == [(["TCS.NS"], date(2026, 6, 8), date(2026, 6, 8))]


def test_explicit_range_continues_after_failure() -> None:
    service = build_service(errors={"BAD.NS": "missing"})
    summary = service.update(
        ["TCS.NS", "BAD.NS"],
        datetime(2026, 6, 8, 16, 30, tzinfo=IST),
        date(2026, 6, 8),
        date(2026, 6, 8),
    )
    assert summary.count(SymbolStatus.SUCCESS) == 1
    assert summary.count(SymbolStatus.FAILED) == 1


def test_planning_storage_failure_is_isolated() -> None:
    latest = datetime(2026, 6, 8, 14, 30, tzinfo=IST)
    service = build_service(latest=latest, failed_symbol="BAD.NS")
    summary = service.update(
        ["BAD.NS", "TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST)
    )
    assert summary.count(SymbolStatus.FAILED) == 1
    assert summary.count(SymbolStatus.SUCCESS) == 1


def test_indicator_backfill_runs_for_planned_unchanged_symbol() -> None:
    latest = datetime(2026, 6, 9, 14, 30, tzinfo=IST)
    service = build_service(latest=latest)
    summary = service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == [("TCS.NS", False)]
    assert summary.count(SymbolStatus.SUCCESS) == 1


def test_changed_price_triggers_indicator_refresh() -> None:
    service = build_service()
    service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == [("TCS.NS", True)]


def test_indicator_failure_marks_symbol_failed_after_price_write() -> None:
    service = build_service(indicator_failed_symbol="TCS.NS")
    summary = service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert summary.count(SymbolStatus.FAILED) == 1
    assert service.store.upserted_symbols == ["TCS.NS"]


def test_price_failure_does_not_refresh_indicators() -> None:
    service = build_service(errors={"BAD.NS": "missing"})
    service.update(["BAD.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == []
