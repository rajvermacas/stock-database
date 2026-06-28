from __future__ import annotations

import logging
from dataclasses import dataclass

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from .orders import GttOrder, RegularOrder

logger = logging.getLogger("stock_data.kite.placement")

# our trigger_type label -> SDK trigger_type value
_GTT_TYPE = {"single": "single", "oco": "two-leg"}


@dataclass(frozen=True)
class OrderResult:
    index: int
    kind: str
    tradingsymbol: str
    side: str
    quantity: int
    ok: bool
    reference: str  # order_id / trigger_id on success, else error message


def _place_regular(kite: KiteConnect, order: RegularOrder) -> str:
    order_id = kite.place_order(
        variety=order.type,
        exchange=order.exchange,
        tradingsymbol=order.tradingsymbol,
        transaction_type=order.transaction_type,
        quantity=order.quantity,
        product=order.product,
        order_type=order.order_type,
        price=order.price,
        trigger_price=order.trigger_price,
        validity=order.validity,
        tag=order.tag,
    )
    return str(order_id)


def _place_gtt(kite: KiteConnect, order: GttOrder) -> str:
    legs = [
        {
            "transaction_type": leg.transaction_type,
            "quantity": leg.quantity,
            "order_type": "LIMIT",
            "product": leg.product,
            "price": leg.price,
        }
        for leg in order.legs
    ]
    result = kite.place_gtt(
        trigger_type=_GTT_TYPE[order.trigger_type],
        tradingsymbol=order.tradingsymbol,
        exchange=order.exchange,
        trigger_values=order.trigger_values,
        last_price=order.last_price,
        orders=legs,
    )
    trigger_id = result["trigger_id"] if isinstance(result, dict) else result
    return str(trigger_id)


def place_one(kite: KiteConnect, order: RegularOrder | GttOrder) -> str:
    if isinstance(order, RegularOrder):
        return _place_regular(kite, order)
    if isinstance(order, GttOrder):
        return _place_gtt(kite, order)
    raise TypeError(f"Unknown order type: {type(order)!r}")


def _describe_side(order: RegularOrder | GttOrder) -> tuple[str, int]:
    if isinstance(order, RegularOrder):
        return order.transaction_type, order.quantity
    first = order.legs[0]
    return first.transaction_type, first.quantity


def run_batch(
    kite: KiteConnect, orders: list[RegularOrder | GttOrder]
) -> list[OrderResult]:
    results: list[OrderResult] = []
    total = len(orders)
    for index, order in enumerate(orders, start=1):
        side, qty = _describe_side(order)
        logger.info(
            "Placing %d/%d: %s %s %s x%d",
            index,
            total,
            order.type,
            side,
            order.tradingsymbol,
            qty,
        )
        try:
            reference = place_one(kite, order)
            logger.info("Order %d OK: %s -> %s", index, order.tradingsymbol, reference)
            ok, ref = True, reference
        except (KiteException, KeyError, ValueError, TypeError) as exc:
            logger.error("Order %d FAILED: %s -> %s", index, order.tradingsymbol, exc)
            ok, ref = False, str(exc)
        results.append(
            OrderResult(index, order.type, order.tradingsymbol, side, qty, ok, ref)
        )
    return results


def format_summary(results: list[OrderResult]) -> str:
    lines = ["", "Order placement summary:", "-" * 72]
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        lines.append(
            f"  [{r.index}] {status} {r.kind:7} {r.side:4} "
            f"{r.tradingsymbol:14} x{r.quantity}  -> {r.reference}"
        )
    ok = sum(1 for r in results if r.ok)
    lines.append("-" * 72)
    lines.append(f"  {ok}/{len(results)} placed successfully")
    return "\n".join(lines)
