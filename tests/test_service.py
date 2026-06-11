from datetime import date, datetime

import pandas as pd

from stock_data.intervals import IST, get_interval
from stock_data.indicator_service import IndicatorUpdateResult
from stock_data.service import SymbolStatus, UpdateService
from stock_data.storage import WriteResult
from stock_data.yahoo import DownloadBatch


class FakeStore:
    def __init__(self, changed=True, failed_symbol=None) -> None:
        self.changed = changed
        self.failed_symbol = failed_symbol
        self.replaced_symbols = []

    def replace(self, symbol, frame):
        if symbol == self.failed_symbol:
            raise ValueError("invalid parquet")
        self.replaced_symbols.append(symbol)
        return WriteResult(self.changed, frame.height, frame.height)


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
    changed=True,
    errors=None,
    failed_symbol=None,
    indicator_failed_symbol=None,
):
    service = UpdateService(
        FakeStore(changed, failed_symbol),
        FakeYahoo(errors),
        FakeIndicators(indicator_failed_symbol),
        get_interval(interval),
        date(2000, 1, 1),
    )
    return service


def test_update_requests_full_configured_history_for_all_symbols() -> None:
    service = build_service(interval="30m")
    service.update(["TCS.NS", "INFY.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.yahoo.requests == [
        (["TCS.NS", "INFY.NS"], date(2000, 1, 1), date(2026, 6, 8))
    ]


def test_yahoo_failure_is_isolated() -> None:
    service = build_service(errors={"BAD.NS": "missing"})
    summary = service.update(
        ["TCS.NS", "BAD.NS"],
        datetime(2026, 6, 8, 16, 30, tzinfo=IST),
    )
    assert summary.count(SymbolStatus.SUCCESS) == 1
    assert summary.count(SymbolStatus.FAILED) == 1


def test_storage_failure_is_isolated() -> None:
    service = build_service(failed_symbol="BAD.NS")
    summary = service.update(
        ["BAD.NS", "TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST)
    )
    assert summary.count(SymbolStatus.FAILED) == 1
    assert summary.count(SymbolStatus.SUCCESS) == 1


def test_unchanged_full_history_does_not_force_indicator_recalculation() -> None:
    service = build_service(changed=False)
    service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == [("TCS.NS", False)]


def test_changed_price_triggers_indicator_refresh() -> None:
    service = build_service()
    service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == [("TCS.NS", True)]


def test_indicator_failure_marks_symbol_failed_after_price_write() -> None:
    service = build_service(indicator_failed_symbol="TCS.NS")
    summary = service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert summary.count(SymbolStatus.FAILED) == 1
    assert service.store.replaced_symbols == ["TCS.NS"]


def test_price_failure_does_not_refresh_indicators() -> None:
    service = build_service(errors={"BAD.NS": "missing"})
    service.update(["BAD.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == []


def test_normalization_failure_does_not_replace_prices(mocker) -> None:
    service = build_service()
    malformed = pd.DataFrame(
        {"Close": [1.0]},
        index=pd.DatetimeIndex(["2026-06-08 09:15"], name="Datetime"),
    )
    mocker.patch.object(
        service.yahoo,
        "download",
        return_value=DownloadBatch({"TCS.NS": malformed}, {}),
    )
    summary = service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert summary.count(SymbolStatus.FAILED) == 1
    assert service.store.replaced_symbols == []
