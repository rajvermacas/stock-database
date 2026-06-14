from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import ruptures as rpt
from ruptures.exceptions import BadSegmentationParameters
from scipy.stats import energy_distance

from stock_data.pullback.errors import InsufficientEvidenceError
from stock_data.pullback.models import Regime


@dataclass(frozen=True)
class RegimeDistance:
    regime_index: int
    distance: float


def fit_regimes(matrix: np.ndarray) -> tuple[Regime, ...]:
    _validate_matrix(matrix)
    if np.allclose(matrix, matrix[0], equal_nan=False):
        return (Regime(0, len(matrix), 1.0),)
    scaled = robust_scale(matrix)
    endpoints = _select_endpoints(scaled)
    return _regimes_from_endpoints(endpoints)


def robust_scale(matrix: np.ndarray) -> np.ndarray:
    center = np.median(matrix, axis=0)
    scale = np.median(np.abs(matrix - center), axis=0)
    usable = scale > 0
    if not usable.any():
        raise InsufficientEvidenceError("regime features have no variation")
    return (matrix[:, usable] - center[usable]) / scale[usable]


def regime_distances(
    matrix: np.ndarray, regimes: tuple[Regime, ...]
) -> tuple[RegimeDistance, ...]:
    if not regimes:
        raise InsufficientEvidenceError("no regimes available")
    current = matrix[regimes[-1].start_index : regimes[-1].end_index]
    output = []
    for index, regime in enumerate(regimes[:-1]):
        historical = matrix[regime.start_index : regime.end_index]
        distances = [
            energy_distance(historical[:, column], current[:, column])
            for column in range(matrix.shape[1])
        ]
        output.append(RegimeDistance(index, float(np.mean(distances))))
    return tuple(output)


def distance_boundaries(distances: tuple[RegimeDistance, ...]) -> tuple[float, ...]:
    values = sorted({item.distance for item in distances})
    return tuple((left + right) / 2 for left, right in zip(values, values[1:]))


def _select_endpoints(matrix: np.ndarray) -> tuple[int, ...]:
    observations, features = matrix.shape
    min_size = features + 1
    penalty = features * math.log(observations)
    try:
        detected = tuple(
            rpt.Pelt(model="l2", min_size=min_size).fit(matrix).predict(pen=penalty)
        )
    except BadSegmentationParameters:
        detected = (observations,)
    candidates = {(observations,), detected}
    return min(candidates, key=lambda endpoints: _segmentation_bic(matrix, endpoints))


def _segmentation_bic(matrix: np.ndarray, endpoints: tuple[int, ...]) -> float:
    start = 0
    residual = 0.0
    for end in endpoints:
        segment = matrix[start:end]
        residual += float(np.square(segment - segment.mean(axis=0)).sum())
        start = end
    observations, features = matrix.shape
    parameters = len(endpoints) * features
    if residual <= 0:
        return float("-inf")
    return observations * math.log(residual / observations) + parameters * math.log(
        observations
    )


def _regimes_from_endpoints(endpoints: tuple[int, ...]) -> tuple[Regime, ...]:
    start = 0
    regimes = []
    for end in endpoints:
        regimes.append(Regime(start, end, 1.0 if end == endpoints[-1] else 0.0))
        start = end
    return tuple(regimes)


def _validate_matrix(matrix: np.ndarray) -> None:
    if matrix.ndim != 2 or len(matrix) < 2:
        raise InsufficientEvidenceError("regime learning requires a feature matrix")
    if not np.isfinite(matrix).all():
        raise InsufficientEvidenceError(
            "regime feature matrix contains non-finite values"
        )
