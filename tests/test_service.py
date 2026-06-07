from datetime import date

import pandas as pd

from stock_data.service import SymbolStatus, UpdateService
from stock_data.storage import WriteResult
from stock_data.yahoo import DownloadBatch


class FakeStore:
    def __init__(self, latest=None, failed_symbol=None) -> None:
        self.latest = latest
        self.failed_symbol = failed_symbol

    def latest_date(self, symbol):
        if symbol == self.failed_symbol:
            raise ValueError("invalid parquet")
        return self.latest

    def upsert(self, symbol, frame):
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
            index=pd.DatetimeIndex([end], name="Date"),
        )
        frames = {symbol: frame for symbol in symbols if symbol not in self.errors}
        return DownloadBatch(frames, self.errors)


def test_incremental_update_starts_after_latest_date() -> None:
    yahoo = FakeYahoo()
    service = UpdateService(FakeStore(date(2026, 6, 4)), yahoo, date(2000, 1, 1))
    summary = service.update(["TCS.NS"], completed_date=date(2026, 6, 5))
    assert yahoo.requests == [(["TCS.NS"], date(2026, 6, 5), date(2026, 6, 5))]
    assert summary.count(SymbolStatus.SUCCESS) == 1


def test_current_symbol_is_unchanged_without_download() -> None:
    yahoo = FakeYahoo()
    service = UpdateService(FakeStore(date(2026, 6, 5)), yahoo, date(2000, 1, 1))
    summary = service.update(["TCS.NS"], completed_date=date(2026, 6, 5))
    assert yahoo.requests == []
    assert summary.count(SymbolStatus.UNCHANGED) == 1


def test_explicit_range_ignores_latest_date_and_continues_after_failure() -> None:
    yahoo = FakeYahoo({"BAD.NS": "missing"})
    service = UpdateService(FakeStore(date(2026, 6, 5)), yahoo, date(2000, 1, 1))
    summary = service.update(
        ["TCS.NS", "BAD.NS"],
        completed_date=date(2026, 6, 5),
        start=date(2026, 6, 1),
        end=date(2026, 6, 3),
    )
    assert yahoo.requests == [
        (["TCS.NS", "BAD.NS"], date(2026, 6, 1), date(2026, 6, 3))
    ]
    assert summary.count(SymbolStatus.SUCCESS) == 1
    assert summary.count(SymbolStatus.FAILED) == 1


def test_planning_storage_failure_is_isolated_per_symbol() -> None:
    yahoo = FakeYahoo()
    store = FakeStore(date(2026, 6, 4), failed_symbol="BAD.NS")
    service = UpdateService(store, yahoo, date(2000, 1, 1))
    summary = service.update(["BAD.NS", "TCS.NS"], completed_date=date(2026, 6, 5))
    assert yahoo.requests == [(["TCS.NS"], date(2026, 6, 5), date(2026, 6, 5))]
    assert summary.count(SymbolStatus.FAILED) == 1
    assert summary.count(SymbolStatus.SUCCESS) == 1
