from __future__ import annotations

from dataclasses import dataclass

from stock_data.pullback.errors import InsufficientEvidenceError
from stock_data.pullback.models import Regime


@dataclass(frozen=True)
class Fold:
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    inner: tuple["Fold", ...]


def nested_folds(regimes: tuple[Regime, ...]) -> tuple[Fold, ...]:
    if len(regimes) < 3:
        raise InsufficientEvidenceError("nested walk-forward requires observed regimes")
    outer = []
    for index in range(2, len(regimes)):
        inner = _inner_folds(regimes[:index])
        outer.append(
            Fold(
                train_start=regimes[0].start_index,
                train_end=regimes[index - 1].end_index - 1,
                validation_start=regimes[index].start_index,
                validation_end=regimes[index].end_index - 1,
                inner=inner,
            )
        )
    return tuple(outer)


def _inner_folds(regimes: tuple[Regime, ...]) -> tuple[Fold, ...]:
    output = []
    for index in range(1, len(regimes)):
        output.append(
            Fold(
                regimes[0].start_index,
                regimes[index - 1].end_index - 1,
                regimes[index].start_index,
                regimes[index].end_index - 1,
                (),
            )
        )
    return tuple(output)
