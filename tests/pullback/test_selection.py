from stock_data.pullback.models import FeatureBand, ParameterSet
from stock_data.pullback.selection import CandidateScore, select_parameter_set


def parameter(target: float) -> ParameterSet:
    return ParameterSet(
        (FeatureBand("drawdown", -0.1, -0.02),),
        (-0.1, -0.02),
        0.02,
        1.0,
        5,
        1.0,
        30,
        8,
        target,
    )


def test_indistinguishable_candidates_abstain() -> None:
    candidates = (
        CandidateScore(parameter(0.05), 0.1, (0.01,), (0.01,)),
        CandidateScore(parameter(0.06), 0.1, (0.01,), (0.01,)),
    )
    assert select_parameter_set(candidates).decision == "abstain"


def test_positive_calibrated_candidate_is_selected() -> None:
    candidate = CandidateScore(parameter(0.05), 0.1, (0.01,), (0.001,))
    assert select_parameter_set((candidate,)).parameter_set == candidate.parameter_set
