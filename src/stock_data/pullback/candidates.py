from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from stock_data.pullback.errors import InsufficientEvidenceError
from stock_data.pullback.models import TradeOutcome


@dataclass(frozen=True)
class OutcomeCandidates:
    horizons: tuple[int, ...]
    targets: tuple[float, ...]


def transition_boundaries(values: np.ndarray, labels: np.ndarray) -> tuple[float, ...]:
    if len(values) != len(labels) or not len(values):
        raise InsufficientEvidenceError("values and labels must be non-empty and aligned")
    order = np.argsort(values, kind="stable")
    ordered_values = values[order]
    ordered_labels = labels[order]
    boundaries = []
    for index in range(1, len(ordered_values)):
        if ordered_labels[index] != ordered_labels[index - 1]:
            boundaries.append((ordered_values[index] + ordered_values[index - 1]) / 2)
    if not boundaries:
        raise InsufficientEvidenceError("no observed label transition boundaries")
    return tuple(sorted(set(float(value) for value in boundaries)))


def outcome_candidates(outcomes: tuple[TradeOutcome, ...]) -> OutcomeCandidates:
    horizons = sorted(
        {outcome.bars_to_mfe + 1 for outcome in outcomes if outcome.bars_to_mfe is not None}
    )
    targets = sorted(
        {
            outcome.mfe_fraction
            for outcome in outcomes
            if outcome.mfe_fraction is not None and outcome.mfe_fraction > 0
        }
    )
    if not horizons or not targets:
        raise InsufficientEvidenceError("no observed resolved outcome candidates")
    return OutcomeCandidates(tuple(horizons), tuple(targets))


def observed_direction_change_fractions(closes: np.ndarray) -> tuple[float, ...]:
    if len(closes) < 3:
        raise InsufficientEvidenceError("no observed direction changes")
    changes = np.diff(closes)
    points = np.flatnonzero(np.sign(changes[1:]) != np.sign(changes[:-1])) + 1
    values = {
        abs(closes[index] / closes[index - 1] - 1)
        for index in points
        if closes[index - 1] != 0
    }
    if not values:
        raise InsufficientEvidenceError("no observed direction changes")
    return tuple(sorted(float(value) for value in values))
