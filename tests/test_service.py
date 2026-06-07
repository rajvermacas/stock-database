from datetime import date

import pandas as pd

from stock_data.service import SymbolStatus, UpdateService
from stock_data.storage import WriteResult
from stock_data.yahoo import DownloadBatch


class FakeStore:
    def __init__(self, latest=None) -> None:
        self.latest = latest

    def latest_date(self, symbol):
        return self.latest

    def upsert(self, symbol, frame):
        return WriteResult(True, frame.height, frame.height)


class FakeYahoo:
    def __init__(self) -> None:
        self.requests = []

    def download(self, symbols, start, end):
        self.requests.append((symbols, start, end))
        frame = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10]},
            index=pd.DatetimeIndex([end], name="Date"),
        )
        return DownloadBatch({symbol: frame for symbol in symbols}, {})


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
