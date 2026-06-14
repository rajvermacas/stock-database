from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

from stock_data.pullback.errors import InsufficientEvidenceError
from stock_data.pullback.models import ParameterSet


@dataclass(frozen=True)
class CandidateScore:
    parameter_set: ParameterSet
    expected_return: float
    uncertainty_vector: tuple[float, ...]
    historical_errors: tuple[float, ...]


@dataclass(frozen=True)
class SelectionResult:
    parameter_set: ParameterSet | None
    adjusted_return: float
    decision: str


def select_parameter_set(candidates: tuple[CandidateScore, ...]) -> SelectionResult:
    if not candidates:
        raise InsufficientEvidenceError("no candidate parameter sets")
    scored = [(candidate, _adjusted(candidate)) for candidate in candidates]
    scored.sort(key=lambda item: item[1], reverse=True)
    best, value = scored[0]
    if value <= 0:
        return SelectionResult(None, value, "abstain")
    if len(scored) > 1 and np.isclose(value, scored[1][1]):
        return SelectionResult(None, value, "abstain")
    return SelectionResult(best.parameter_set, value, "selected")


def _adjusted(candidate: CandidateScore) -> float:
    uncertainty = np.asarray(candidate.uncertainty_vector, dtype=float)
    errors = np.asarray(candidate.historical_errors, dtype=float)
    if len(errors) != len(uncertainty) or not len(errors):
        raise InsufficientEvidenceError("uncertainty penalty cannot be identified")
    design = np.diag(uncertainty)
    penalty, _ = nnls(design, errors)
    return float(candidate.expected_return - penalty @ uncertainty)
