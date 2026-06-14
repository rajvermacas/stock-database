import pytest

from stock_data.pullback.models import (
    STOP_LOSS_FRACTION,
    ParameterSet,
    TradePath,
)


def test_trade_stop_is_exactly_three_percent_below_entry() -> None:
    trade = TradePath(entry_index=4, entry_price=100.0, stop_price=97.0)
    assert trade.stop_price == trade.entry_price * (1 - STOP_LOSS_FRACTION)


def test_trade_rejects_non_three_percent_stop() -> None:
    with pytest.raises(ValueError, match="exactly 3%"):
        TradePath(entry_index=4, entry_price=100.0, stop_price=96.0)


def test_parameter_set_rejects_non_stock_derived_empty_fields() -> None:
    with pytest.raises(ValueError, match="feature bands"):
        ParameterSet(
            feature_bands=(),
            dip_band=(0.02, 0.04),
            swing_reversal_fraction=0.02,
            regime_distance_limit=1.0,
            sequence_length_bars=5,
            setup_distance_limit=1.0,
            lookback_bars=20,
            horizon_bars=8,
            target=0.05,
        )
