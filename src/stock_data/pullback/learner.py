from __future__ import annotations

import logging

import numpy as np
import polars as pl

from stock_data.pullback.candidates import (
    observed_direction_change_fractions,
    outcome_candidates,
    transition_boundaries,
)
from stock_data.pullback.errors import InsufficientEvidenceError, PullbackError
from stock_data.pullback.features import causal_features, finite_feature_matrix
from stock_data.pullback.models import (
    STOP_LOSS_FRACTION,
    Decision,
    FeatureBand,
    OutcomeStatus,
    ParameterSet,
    StockDecision,
)
from stock_data.pullback.outcomes import evaluate_target, trace_path
from stock_data.pullback.regimes import (
    distance_boundaries,
    fit_regimes,
    regime_distances,
)
from stock_data.pullback.selection import CandidateScore, select_parameter_set
from stock_data.pullback.sequences import sequence_length_candidates
from stock_data.pullback.walk_forward import nested_folds

LOGGER = logging.getLogger(__name__)


def learn_stock(prices: pl.DataFrame) -> StockDecision:
    symbol = prices["symbol"][0]
    try:
        features = causal_features(prices)
        matrix, indices = finite_feature_matrix(features)
        regimes = fit_regimes(matrix)
        nested_folds(regimes)
        outcomes = _observed_outcomes(prices, indices, regimes)
        parameter = _derive_parameter_set(features, matrix, regimes, outcomes)
        score, recovery_probability = _score_candidate(prices, parameter, outcomes)
        selected = select_parameter_set((score,))
        if selected.parameter_set is None:
            return _abstain(symbol, "learned setup does not beat abstaining")
        return _current_decision(
            prices,
            features,
            selected.parameter_set,
            score.expected_return,
            selected.adjusted_return,
            recovery_probability,
        )
    except PullbackError as exc:
        LOGGER.info("Pullback learner abstained symbol=%s reason=%s", symbol, exc)
        return _abstain(symbol, str(exc))


def _observed_outcomes(prices, indices, regimes):
    outcomes = []
    for regime in regimes:
        if regime.weight <= 0:
            continue
        regime_start = int(indices[regime.start_index])
        regime_end = int(indices[regime.end_index - 1])
        for detection in range(regime_start, regime_end):
            outcomes.append(trace_path(prices, detection, regime_end))
    usable = tuple(outcome for outcome in outcomes if outcome.path is not None)
    if not usable:
        raise InsufficientEvidenceError("no causal next-open outcomes")
    return usable


def _derive_parameter_set(features, matrix, regimes, outcomes):
    labels = np.asarray([outcome.mfe_fraction > 0 for outcome in outcomes])
    drawdowns = features["expanding_drawdown"].drop_nulls().to_numpy()
    aligned = drawdowns[-len(labels) :]
    boundaries = transition_boundaries(aligned, labels[-len(aligned) :])
    outcome_values = outcome_candidates(outcomes)
    reversals = observed_direction_change_fractions(features["close"].to_numpy())
    durations = [regime.end_index - regime.start_index for regime in regimes]
    regime_limits = distance_boundaries(regime_distances(matrix, regimes))
    limit = regime_limits[-1] if regime_limits else 0.0
    return ParameterSet(
        feature_bands=(FeatureBand("expanding_drawdown", min(aligned), max(aligned)),),
        dip_band=(min(boundaries), max(boundaries)),
        swing_reversal_fraction=float(np.median(reversals)),
        regime_distance_limit=limit,
        sequence_length_bars=int(np.median(sequence_length_candidates(durations))),
        setup_distance_limit=limit,
        lookback_bars=durations[-1],
        horizon_bars=int(np.median(outcome_values.horizons)),
        target=float(np.median(outcome_values.targets)),
    )


def _score_candidate(prices, parameter, outcomes):
    statuses = [
        evaluate_target(prices, outcome, parameter.target, parameter.horizon_bars)
        for outcome in outcomes
    ]
    returns = np.asarray(
        [
            parameter.target if status == OutcomeStatus.SUCCESS else -STOP_LOSS_FRACTION
            for status in statuses
            if status in (OutcomeStatus.SUCCESS, OutcomeStatus.FAILURE)
        ]
    )
    if not len(returns):
        raise InsufficientEvidenceError("no resolved target outcomes")
    expected = float(returns.mean())
    uncertainty = float(returns.std())
    error = float(np.abs(returns - expected).mean())
    recovery = float((returns > 0).mean())
    return CandidateScore(parameter, expected, (uncertainty,), (error,)), recovery


def _current_decision(
    prices,
    features,
    parameter,
    expected_return,
    adjusted_return,
    recovery_probability,
):
    last = features.row(-1, named=True)
    depth = last["expanding_drawdown"]
    in_band = (
        depth is not None and parameter.dip_band[0] <= depth <= parameter.dip_band[1]
    )
    decision = Decision.BUY if in_band and adjusted_return > 0 else Decision.WATCH
    timestamp = prices["trade_timestamp"][-1]
    reason = (
        "current causal setup matches learned dip band"
        if in_band
        else "current setup outside learned dip band"
    )
    return StockDecision(
        symbol=prices["symbol"][0],
        decision=decision,
        reason=reason,
        detection_timestamp=timestamp if in_band else None,
        entry_price=None,
        stop_price=None,
        parameter_set=parameter,
        expected_return=expected_return,
        adjusted_expected_return=adjusted_return,
        recovery_probability=recovery_probability,
    )


def _abstain(symbol: str, reason: str) -> StockDecision:
    return StockDecision(
        symbol,
        Decision.ABSTAIN,
        reason,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
