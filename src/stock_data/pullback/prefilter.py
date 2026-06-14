from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from stock_data.pullback.candidates import transition_boundaries
from stock_data.pullback.errors import InsufficientEvidenceError
from stock_data.pullback.features import causal_features
from stock_data.pullback.models import STOP_LOSS_FRACTION


@dataclass(frozen=True)
class PrefilterRule:
    feature: str | None
    lower: float | None
    upper: float | None
    recall: float
    pass_rate: float
    comparisons: int


@dataclass(frozen=True)
class PrefilterResult:
    rule: PrefilterRule
    passes: bool


def learn_prefilter(prices: pl.DataFrame) -> PrefilterResult:
    features = causal_features(prices)
    labels = _raw_labels(prices)
    rules = [_pass_all()]
    for feature in ("expanding_drawdown", "true_range_fraction", "log_return"):
        rules.extend(_feature_rules(features[feature].to_numpy(), labels, feature))
    selected = select_prefilter(tuple(rules))
    return PrefilterResult(selected, _passes_current(features, selected))


def select_prefilter(rules: tuple[PrefilterRule, ...]) -> PrefilterRule:
    if not rules:
        raise InsufficientEvidenceError("no prefilter rules")
    return min(rules, key=lambda rule: (-rule.recall, rule.pass_rate, rule.comparisons))


def _raw_labels(prices: pl.DataFrame) -> np.ndarray:
    opens = prices["open"].to_numpy()
    highs = prices["high"].to_numpy()
    lows = prices["low"].to_numpy()
    labels = np.zeros(prices.height, dtype=bool)
    for detection in range(prices.height - 1):
        entry_index = detection + 1
        entry = opens[entry_index]
        stop_hits = np.flatnonzero(
            lows[entry_index:] <= entry * (1 - STOP_LOSS_FRACTION)
        )
        end = entry_index + int(stop_hits[0]) + 1 if len(stop_hits) else prices.height
        labels[detection] = bool(np.any(highs[entry_index:end] > entry))
    return labels


def _feature_rules(values: np.ndarray, labels: np.ndarray, feature: str):
    finite = np.isfinite(values)
    values, labels = values[finite], labels[finite]
    if not len(values) or labels.all() or not labels.any():
        return []
    try:
        boundaries = transition_boundaries(values, labels)
    except InsufficientEvidenceError:
        return []
    endpoints = (float(values.min()), *boundaries, float(values.max()))
    rules = [_rule(values, labels, feature, values[labels].min(), values[labels].max())]
    for lower, upper in zip(endpoints, endpoints[1:]):
        rules.append(_rule(values, labels, feature, lower, upper))
    return rules


def _rule(values, labels, feature, lower, upper) -> PrefilterRule:
    passed = (values >= lower) & (values <= upper)
    recall = float(labels[passed].sum() / labels.sum()) if passed.any() else 0.0
    return PrefilterRule(
        feature, float(lower), float(upper), recall, float(passed.mean()), 2
    )


def _passes_current(features: pl.DataFrame, rule: PrefilterRule) -> bool:
    if rule.feature is None:
        return True
    value = features[rule.feature][-1]
    return value is not None and rule.lower <= value <= rule.upper


def _pass_all() -> PrefilterRule:
    return PrefilterRule(None, None, None, 1.0, 1.0, 0)
