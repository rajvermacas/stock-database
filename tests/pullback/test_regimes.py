import numpy as np

from stock_data.pullback.regimes import fit_regimes


def test_constant_features_yield_one_regime() -> None:
    assert len(fit_regimes(np.ones((40, 3)))) == 1


def test_variance_shift_yields_multiple_regimes() -> None:
    rng = np.random.default_rng(7)
    matrix = np.vstack(
        [rng.normal(0, 0.1, (60, 3)), rng.normal(2, 1.0, (60, 3))]
    )
    regimes = fit_regimes(matrix)
    assert len(regimes) > 1
    assert any(abs(regime.end_index - 60) <= 15 for regime in regimes[:-1])


def test_future_rows_do_not_change_prior_training_regimes() -> None:
    rng = np.random.default_rng(3)
    training = rng.normal(0, 1, (80, 3))
    expected = fit_regimes(training)
    with_future = np.vstack([training, rng.normal(10, 1, (40, 3))])
    assert fit_regimes(with_future[:80]) == expected
