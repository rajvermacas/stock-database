from datetime import date

import pandas as pd

from stock_data.config import YahooConfig
from stock_data.yahoo import YahooClient


def test_download_converts_end_and_uses_raw_prices(mocker) -> None:
    frame = pd.DataFrame({"Close": [1.0]})
    download = mocker.patch("stock_data.yahoo.yf.download", return_value=frame)
    client = YahooClient(YahooConfig(interval="1d", batch_size=2, timeout_seconds=30, threads=True))
    result = client.download(["TCS.NS"], date(2026, 6, 1), date(2026, 6, 5))
    assert "TCS.NS" in result.frames
    assert download.call_args.kwargs["end"] == "2026-06-06"
    assert download.call_args.kwargs["auto_adjust"] is False


def test_missing_batch_symbol_is_retried_once(mocker) -> None:
    columns = pd.MultiIndex.from_product([["Close"], ["TCS.NS"]])
    batch = pd.DataFrame([[1.0]], columns=columns)
    individual = pd.DataFrame({"Close": [2.0]})
    download = mocker.patch("stock_data.yahoo.yf.download", side_effect=[batch, individual])
    client = YahooClient(YahooConfig(interval="1d", batch_size=5, timeout_seconds=30, threads=False))
    result = client.download(["TCS.NS", "INFY.NS"], date(2026, 6, 1), date(2026, 6, 5))
    assert set(result.frames) == {"TCS.NS", "INFY.NS"}
    assert download.call_count == 2

