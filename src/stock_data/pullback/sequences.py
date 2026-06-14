from __future__ import annotations

import numpy as np
import polars as pl

from stock_data.pullback.errors import InsufficientEvidenceError
from stock_data.pullback.features import REGIME_FEATURES


def sequence_vector(
    features: pl.DataFrame,
    end_index: int,
    length: int,
    columns: tuple[str, ...] = REGIME_FEATURES,
) -> np.ndarray:
    if length < 1:
        raise ValueError("sequence length must be positive")
    start = end_index - length + 1
    if start < 0 or end_index >= features.height:
        raise InsufficientEvidenceError("sequence extends beyond observed history")
    values = features.slice(start, length).select(columns).to_numpy()
    if not np.isfinite(values).all():
        raise InsufficientEvidenceError("sequence contains unavailable causal features")
    center = np.median(values, axis=0)
    scale = np.median(np.abs(values - center), axis=0)
    usable = scale > 0
    if not usable.any():
        raise InsufficientEvidenceError("sequence has no varying causal features")
    return ((values[:, usable] - center[usable]) / scale[usable]).ravel()


def sequence_length_candidates(
    durations: list[int] | tuple[int, ...],
) -> tuple[int, ...]:
    candidates = sorted({int(value) for value in durations if value > 0})
    if not candidates:
        raise InsufficientEvidenceError("no observed sequence durations")
    return tuple(candidates)


def euclidean_sequence_distance(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise ValueError("sequence vectors must have equal shape")
    return float(np.linalg.norm(left - right) / np.sqrt(left.size))
