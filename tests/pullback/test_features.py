import numpy as np
import polars as pl

from stock_data.pullback.features import FRACTION_FEATURES, causal_features


def test_appending_future_bars_does_not_change_prior_features(price_frame) -> None:
    frame = price_frame([100 + index + index % 3 for index in range(60)])
    short = causal_features(frame.head(40))
    long = causal_features(frame)
    assert short.equals(long.head(40))


def test_price_scaling_preserves_fractional_features(price_frame) -> None:
    frame = price_frame([100 + index + index % 3 for index in range(60)])
    scaled = frame.with_columns(
        [pl.col(name) * 10 for name in ("open", "high", "low", "close")]
    )
    left = causal_features(frame).select(FRACTION_FEATURES).to_numpy()
    right = causal_features(scaled).select(FRACTION_FEATURES).to_numpy()
    assert np.allclose(
        left,
        right,
        equal_nan=True,
    )


def test_flat_bars_emit_null_geometry(price_frame) -> None:
    frame = price_frame([100.0, 100.0]).with_columns(
        pl.lit(100.0).alias("open"),
        pl.lit(100.0).alias("high"),
        pl.lit(100.0).alias("low"),
        pl.lit(100.0).alias("close"),
    )
    result = causal_features(frame)
    assert result["body_fraction"].null_count() == 2
    assert result["close_location"].null_count() == 2
