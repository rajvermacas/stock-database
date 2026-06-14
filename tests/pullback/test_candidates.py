import numpy as np

from stock_data.pullback.candidates import outcome_candidates, transition_boundaries
from stock_data.pullback.models import OutcomeStatus, TradeOutcome, TradePath


def test_boundaries_come_only_from_observed_label_transitions() -> None:
    values = np.array([1.0, 2.0, 5.0, 9.0])
    labels = np.array([False, False, True, True])
    assert transition_boundaries(values, labels) == (3.5,)


def test_horizon_and_target_candidates_are_observed_outcomes() -> None:
    paths = (
        TradeOutcome(OutcomeStatus.CENSORED, TradePath(1, 100, 97), 0.04, -0.01, None, None, 2),
        TradeOutcome(OutcomeStatus.CENSORED, TradePath(1, 100, 97), 0.08, -0.02, None, None, 5),
    )
    candidates = outcome_candidates(paths)
    assert candidates.horizons == (3, 6)
    assert candidates.targets == (0.04, 0.08)
