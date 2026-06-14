from stock_data.pullback.models import OutcomeStatus
from stock_data.pullback.outcomes import evaluate_target, trace_path


def test_detection_enters_at_next_bar_open(price_frame) -> None:
    prices = price_frame([100, 101, 102, 103, 104, 105])
    outcome = trace_path(prices, detection_index=2, regime_end_index=5)
    assert outcome.path is not None
    assert outcome.path.entry_index == 3
    assert outcome.path.entry_price == prices["open"][3]
    assert outcome.path.stop_price == prices["open"][3] * 0.97


def test_latest_detection_is_pending_not_fabricated(price_frame) -> None:
    prices = price_frame([100, 101, 102])
    assert trace_path(prices, prices.height - 1, None).status == OutcomeStatus.PENDING


def test_same_bar_stop_and_target_is_unknown(price_frame) -> None:
    prices = price_frame([100, 100, 100]).with_columns(
        prices_column("high", [101.0, 106.0, 101.0]),
        prices_column("low", [99.0, 95.0, 99.0]),
    )
    outcome = trace_path(prices, 0, 2)
    assert evaluate_target(prices, outcome, 0.04, 2) == OutcomeStatus.UNKNOWN


def prices_column(name: str, values: list[float]):
    import polars as pl

    return pl.Series(name, values)
