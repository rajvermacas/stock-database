from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from stock_data.config import YahooConfig
from stock_data.normalization import split_batch_frame

LOGGER = logging.getLogger(__name__)


class YahooDownloadError(RuntimeError):
    def __init__(
        self, symbols: list[str], interval: str, start: date, end: date, cause: object
    ) -> None:
        super().__init__(
            f"Yahoo download failed symbols={','.join(symbols)} interval={interval} "
            f"start={start} end={end}: {cause}"
        )


@dataclass(frozen=True)
class DownloadBatch:
    symbols: tuple[str, ...]
    frames: dict[str, pd.DataFrame]
    errors: dict[str, str]


class YahooClient:
    def __init__(self, config: YahooConfig) -> None:
        self.config = config

    def download_batches(
        self, symbols: list[str], start: date, end: date
    ) -> Iterator[DownloadBatch]:
        for chunk in _chunks(symbols, self.config.batch_size):
            yield self._download_chunk(chunk, start, end)

    def _download_chunk(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> DownloadBatch:
        frames: dict[str, pd.DataFrame] = {}
        errors: dict[str, str] = {}
        LOGGER.info(
            "Downloading batch symbols=%d interval=%s start=%s end=%s",
            len(symbols),
            self.config.interval,
            start,
            end,
        )
        try:
            batch = yf.download(tickers=symbols, **self._parameters(start, end))
        except Exception as exc:
            LOGGER.exception("Yahoo batch failed symbols=%s", symbols)
            error = YahooDownloadError(symbols, self.config.interval, start, end, exc)
            errors.update({symbol: str(error) for symbol in symbols})
            return DownloadBatch(tuple(symbols), frames, errors)
        frames.update(split_batch_frame(batch, symbols))
        for symbol in set(symbols).difference(frames):
            self._retry_symbol(symbol, start, end, frames, errors)
        return DownloadBatch(tuple(symbols), frames, errors)

    def _retry_symbol(
        self,
        symbol: str,
        start: date,
        end: date,
        frames: dict[str, pd.DataFrame],
        errors: dict[str, str],
    ) -> None:
        LOGGER.warning("Retrying missing symbol individually: %s", symbol)
        try:
            frame = yf.download(tickers=symbol, **self._parameters(start, end))
            split = split_batch_frame(frame, [symbol])
            if symbol not in split:
                errors[symbol] = str(
                    YahooDownloadError(
                        [symbol],
                        self.config.interval,
                        start,
                        end,
                        "Yahoo returned no data after individual retry",
                    )
                )
            else:
                frames[symbol] = split[symbol]
        except Exception as exc:
            LOGGER.exception("Yahoo individual retry failed symbol=%s", symbol)
            errors[symbol] = str(
                YahooDownloadError([symbol], self.config.interval, start, end, exc)
            )

    def _parameters(self, start: date, end: date) -> dict[str, Any]:
        return {
            "start": start.isoformat(),
            "end": (end + timedelta(days=1)).isoformat(),
            "interval": self.config.interval,
            "auto_adjust": True,
            "actions": False,
            "progress": False,
            "timeout": self.config.timeout_seconds,
            "threads": self.config.threads,
        }


def _chunks(symbols: list[str], size: int) -> list[list[str]]:
    return [symbols[index : index + size] for index in range(0, len(symbols), size)]
