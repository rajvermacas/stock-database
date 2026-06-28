from __future__ import annotations

from kiteconnect.exceptions import InputException

from scripts.kite.orders import GttOrder, RegularOrder
from scripts.kite.placement import format_summary, place_one, run_batch


def _regular(**kw):
    base = dict(
        type="regular", exchange="NSE", tradingsymbol="INFY",
        transaction_type="BUY", quantity=1, product="CNC",
        order_type="MARKET", validity="DAY",
    )
    base.update(kw)
    return RegularOrder(**base)


def _gtt_single():
    return GttOrder(
        type="gtt", trigger_type="single", exchange="NSE",
        tradingsymbol="RELIANCE", last_price=2900.0, trigger_values=[2700.0],
        legs=[{"transaction_type": "BUY", "quantity": 1,
               "product": "CNC", "price": 2700.0}],
    )


def _gtt_oco():
    return GttOrder(
        type="gtt", trigger_type="oco", exchange="NSE",
        tradingsymbol="HDFCBANK", last_price=1600.0,
        trigger_values=[1450.0, 1750.0],
        legs=[{"transaction_type": "SELL", "quantity": 5,
               "product": "CNC", "price": 1450.0},
              {"transaction_type": "SELL", "quantity": 5,
               "product": "CNC", "price": 1750.0}],
    )


def test_place_regular_amo_calls_place_order(mocker):
    kite = mocker.Mock()
    kite.place_order.return_value = "OID1"
    assert place_one(kite, _regular(type="amo")) == "OID1"
    kwargs = kite.place_order.call_args.kwargs
    assert kwargs["variety"] == "amo"
    assert kwargs["order_type"] == "MARKET"
    assert kwargs["product"] == "CNC"


def test_place_gtt_single_legs_are_limit(mocker):
    kite = mocker.Mock()
    kite.place_gtt.return_value = {"trigger_id": 555}
    assert place_one(kite, _gtt_single()) == "555"
    kwargs = kite.place_gtt.call_args.kwargs
    assert kwargs["trigger_type"] == "single"
    assert kwargs["orders"][0]["order_type"] == "LIMIT"


def test_place_gtt_oco_maps_two_leg_and_scalar_return(mocker):
    kite = mocker.Mock()
    kite.place_gtt.return_value = 777
    assert place_one(kite, _gtt_oco()) == "777"
    assert kite.place_gtt.call_args.kwargs["trigger_type"] == "two-leg"


def test_run_batch_continue_on_error(mocker):
    kite = mocker.Mock()
    kite.place_order.side_effect = ["OID1", InputException("bad")]
    results = run_batch(kite, [_regular(), _regular()])
    assert results[0].ok is True
    assert results[1].ok is False
    assert "1/2 placed successfully" in format_summary(results)
