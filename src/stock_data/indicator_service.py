from __future__ import annotations

import logging
from dataclasses import dataclass

from stock_data.indicator_storage import IndicatorStore, source_fingerprint
from stock_data.indicators import calculate_indicators
from stock_data.storage import PriceStore

LOGGER = logging.getLogger(__name__)


class IndicatorUpdateError(ValueError):
    """Raised when one symbol's indicators cannot be refreshed."""


@dataclass(frozen=True)
class IndicatorUpdateResult:
    changed: bool
    stored_rows: int


class IndicatorUpdater:
    def __init__(
        self, price_store: PriceStore, indicator_store: IndicatorStore
    ) -> None:
        self.price_store = price_store
        self.indicator_store = indicator_store

    def refresh(self, symbol: str, prices_changed: bool) -> IndicatorUpdateResult:
        try:
            prices = self.price_store.read(symbol)
            if prices is None:
                raise IndicatorUpdateError(f"Price data does not exist for {symbol}")
            fingerprint = source_fingerprint(prices)
            if not prices_changed and self.indicator_store.is_current(
                symbol, fingerprint
            ):
                current = self.indicator_store.read(symbol)
                if current is None:
                    raise IndicatorUpdateError(
                        f"Current indicator data does not exist for {symbol}"
                    )
                return IndicatorUpdateResult(False, current.height)
            indicators = calculate_indicators(prices)
            if indicators is None:
                return self._remove_insufficient(symbol, prices.height)
            self.indicator_store.publish(symbol, indicators, fingerprint)
            LOGGER.info(
                "Indicator refresh complete symbol=%s interval=%s source_rows=%d indicator_rows=%d",
                symbol,
                self.price_store.interval.name,
                prices.height,
                indicators.height,
            )
            return IndicatorUpdateResult(True, indicators.height)
        except IndicatorUpdateError:
            raise
        except Exception as exc:
            raise IndicatorUpdateError(
                f"Indicator refresh failed symbol={symbol} "
                f"interval={self.price_store.interval.name}: {exc}"
            ) from exc

    def _remove_insufficient(
        self, symbol: str, source_rows: int
    ) -> IndicatorUpdateResult:
        removed = self.indicator_store.remove(symbol)
        LOGGER.warning(
            "Insufficient indicator history symbol=%s interval=%s source_rows=%d",
            symbol,
            self.price_store.interval.name,
            source_rows,
        )
        return IndicatorUpdateResult(removed, 0)
