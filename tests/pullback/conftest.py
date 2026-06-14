from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from stock_data.intervals import IST
from stock_data.normalization import CANONICAL_SCHEMA


@pytest.fixture
def price_frame():
    def factory(
        closes: list[float],
        volumes: list[int] | None = None,
        symbol: str = "TEST.NS",
    ) -> pl.DataFrame:
        if volumes is None:
            volumes = [1000 + index for index in range(len(closes))]
        start = datetime(2026, 1, 1, 9, 15, tzinfo=IST)
        timestamps = [start + timedelta(hours=index) for index in range(len(closes))]
        return pl.DataFrame(
            {
                "symbol": [symbol] * len(closes),
                "trade_timestamp": timestamps,
                "open": [value - 0.2 for value in closes],
                "high": [value + 1.0 for value in closes],
                "low": [value - 1.0 for value in closes],
                "close": closes,
                "volume": volumes,
            },
            schema=CANONICAL_SCHEMA,
        )

    return factory
