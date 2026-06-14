from stock_data.pullback.prefilter import PrefilterRule, select_prefilter


def test_prefilter_selects_maximum_recall_before_pass_rate() -> None:
    rules = (
        PrefilterRule(None, None, None, 1.0, 1.0, 0),
        PrefilterRule("x", 0, 1, 1.0, 0.4, 2),
        PrefilterRule("x", 1, 2, 0.9, 0.2, 2),
    )
    selected = select_prefilter(rules)
    assert selected.recall == 1.0
    assert selected.pass_rate == 0.4
