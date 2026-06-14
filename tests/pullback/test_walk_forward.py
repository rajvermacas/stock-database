import pytest

from stock_data.pullback.errors import InsufficientEvidenceError
from stock_data.pullback.models import Regime
from stock_data.pullback.walk_forward import nested_folds


def test_nested_folds_are_strictly_causal() -> None:
    regimes = (Regime(0, 10, 0), Regime(10, 20, 0), Regime(20, 30, 1))
    for outer in nested_folds(regimes):
        assert outer.train_end < outer.validation_start
        assert all(inner.train_end < inner.validation_start for inner in outer.inner)


def test_no_regimes_abstain() -> None:
    with pytest.raises(InsufficientEvidenceError):
        nested_folds(())


def test_single_learned_regime_has_no_artificial_folds() -> None:
    assert nested_folds((Regime(0, 10, 1),)) == ()
