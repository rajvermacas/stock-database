from __future__ import annotations

import json

import pytest

from scripts.kite.orders import KiteOrderSpecError, load_orders


def _write(tmp_path, payload):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_valid_orders_parse(tmp_path):
    payload = {
        "orders": [
            {
                "type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
                "transaction_type": "BUY", "quantity": 1, "product": "CNC",
                "order_type": "MARKET", "validity": "DAY",
            },
            {
                "type": "gtt", "trigger_type": "oco", "exchange": "NSE",
                "tradingsymbol": "HDFCBANK", "last_price": 1600.0,
                "trigger_values": [1450.0, 1750.0],
                "legs": [
                    {"transaction_type": "SELL", "quantity": 5,
                     "product": "CNC", "price": 1450.0},
                    {"transaction_type": "SELL", "quantity": 5,
                     "product": "CNC", "price": 1750.0},
                ],
            },
        ]
    }
    orders = load_orders(_write(tmp_path, payload))
    assert len(orders) == 2
    assert orders[0].type == "regular"
    assert orders[1].trigger_type == "oco"


@pytest.mark.parametrize(
    "order",
    [
        {"type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
         "transaction_type": "BUY", "quantity": 1, "product": "CNC",
         "order_type": "MARKET", "price": 100.0, "validity": "DAY"},
        {"type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
         "transaction_type": "BUY", "quantity": 1, "product": "CNC",
         "order_type": "LIMIT", "validity": "DAY"},
        {"type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
         "transaction_type": "BUY", "quantity": 0, "product": "CNC",
         "order_type": "MARKET", "validity": "DAY"},
        {"type": "regular", "exchange": "NFO", "tradingsymbol": "X",
         "transaction_type": "BUY", "quantity": 1, "product": "CNC",
         "order_type": "MARKET", "validity": "DAY"},
        {"type": "gtt", "trigger_type": "oco", "exchange": "NSE",
         "tradingsymbol": "X", "last_price": 100.0, "trigger_values": [90.0],
         "legs": [{"transaction_type": "BUY", "quantity": 1,
                   "product": "CNC", "price": 90.0}]},
        {"type": "gtt", "trigger_type": "oco", "exchange": "NSE",
         "tradingsymbol": "X", "last_price": 100.0,
         "trigger_values": [110.0, 90.0],
         "legs": [{"transaction_type": "SELL", "quantity": 1,
                   "product": "CNC", "price": 110.0},
                  {"transaction_type": "SELL", "quantity": 1,
                   "product": "CNC", "price": 90.0}]},
    ],
)
def test_invalid_orders_raise(tmp_path, order):
    with pytest.raises(KiteOrderSpecError):
        load_orders(_write(tmp_path, {"orders": [order]}))


def test_unknown_key_rejected(tmp_path):
    order = {
        "type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
        "transaction_type": "BUY", "quantity": 1, "product": "CNC",
        "order_type": "MARKET", "validity": "DAY", "bogus": 1,
    }
    with pytest.raises(KiteOrderSpecError):
        load_orders(_write(tmp_path, {"orders": [order]}))


def test_empty_orders_rejected(tmp_path):
    with pytest.raises(KiteOrderSpecError):
        load_orders(_write(tmp_path, {"orders": []}))
