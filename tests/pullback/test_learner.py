from stock_data.pullback.learner import learn_stock
from stock_data.pullback.models import Decision


def test_short_stock_abstains(price_frame) -> None:
    result = learn_stock(price_frame([100.0, 101.0, 100.5]))
    assert result.decision == Decision.ABSTAIN


def test_distinct_stocks_do_not_share_parameter_objects(price_frame) -> None:
    shallow = [100 + index * 0.2 + (index % 8) * 0.1 for index in range(160)]
    deep = [100 + index * 0.2 + (index % 8) * 1.0 for index in range(160)]
    left = learn_stock(price_frame(shallow, symbol="SHALLOW.NS"))
    right = learn_stock(price_frame(deep, symbol="DEEP.NS"))
    if left.parameter_set is not None and right.parameter_set is not None:
        assert left.parameter_set != right.parameter_set
