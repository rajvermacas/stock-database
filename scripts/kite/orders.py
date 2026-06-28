from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

logger = logging.getLogger("stock_data.kite.orders")

Exchange = Literal["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "BCD"]
Product = Literal["CNC", "MIS", "NRML"]
Side = Literal["BUY", "SELL"]

# order_type -> (price required?, trigger_price required?)
_PRICE_RULES = {
    "MARKET": (False, False),
    "LIMIT": (True, False),
    "SL": (True, True),
    "SL-M": (False, True),
}


class KiteOrderSpecError(ValueError):
    """Raised when the orders JSON is missing, malformed, or invalid."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegularOrder(StrictModel):
    type: Literal["regular", "amo"]
    exchange: Exchange
    tradingsymbol: str = Field(min_length=1)
    transaction_type: Side
    quantity: int = Field(gt=0)
    product: Product
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M"]
    price: float | None = Field(default=None, gt=0)
    trigger_price: float | None = Field(default=None, gt=0)
    validity: Literal["DAY", "IOC"]
    tag: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _check_price_and_product(self) -> "RegularOrder":
        need_price, need_trigger = _PRICE_RULES[self.order_type]
        if need_price is not (self.price is not None):
            raise ValueError(
                f"{self.order_type} order: price must be "
                f"{'set' if need_price else 'omitted'}"
            )
        if need_trigger is not (self.trigger_price is not None):
            raise ValueError(
                f"{self.order_type} order: trigger_price must be "
                f"{'set' if need_trigger else 'omitted'}"
            )
        if self.product == "CNC" and self.exchange not in ("NSE", "BSE"):
            raise ValueError(f"CNC is only valid on NSE/BSE, not {self.exchange}")
        return self


class GttLeg(StrictModel):
    transaction_type: Side
    quantity: int = Field(gt=0)
    product: Product
    price: float = Field(gt=0)


class GttOrder(StrictModel):
    type: Literal["gtt"]
    trigger_type: Literal["single", "oco"]
    exchange: Exchange
    tradingsymbol: str = Field(min_length=1)
    last_price: float = Field(gt=0)
    trigger_values: list[float]
    legs: list[GttLeg]

    @model_validator(mode="after")
    def _check_cardinality(self) -> "GttOrder":
        expected = 1 if self.trigger_type == "single" else 2
        if len(self.trigger_values) != expected:
            raise ValueError(
                f"{self.trigger_type} GTT needs {expected} trigger_values, "
                f"got {len(self.trigger_values)}"
            )
        if len(self.legs) != expected:
            raise ValueError(
                f"{self.trigger_type} GTT needs {expected} legs, got {len(self.legs)}"
            )
        if any(v <= 0 for v in self.trigger_values):
            raise ValueError("trigger_values must be positive")
        if self.trigger_type == "oco" and not (
            self.trigger_values[0] < self.trigger_values[1]
        ):
            raise ValueError(
                f"OCO trigger_values must be strictly ascending, got {self.trigger_values}"
            )
        return self


Order = Annotated[Union[RegularOrder, GttOrder], Field(discriminator="type")]


class OrdersFile(StrictModel):
    orders: list[Order] = Field(min_length=1)


def load_orders(path: Path) -> list[RegularOrder | GttOrder]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KiteOrderSpecError(f"Unable to read orders file {path}: {exc}") from exc
    try:
        parsed = OrdersFile.model_validate(raw)
    except ValidationError as exc:
        raise KiteOrderSpecError(f"Invalid orders in {path}: {exc}") from exc
    logger.info("Loaded %d orders from %s", len(parsed.orders), path)
    return list(parsed.orders)
