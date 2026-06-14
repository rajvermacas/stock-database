import numpy as np

from stock_data.pullback.features import causal_features
from stock_data.pullback.sequences import sequence_length_candidates, sequence_vector


def test_sequence_vector_uses_only_rows_through_detection(price_frame) -> None:
    features = causal_features(price_frame([100 + index % 7 for index in range(40)]))
    vector = sequence_vector(features, end_index=20, length=6)
    changed = features.with_columns(
        features["log_return"].scatter([30], [999.0]).alias("log_return")
    )
    assert np.array_equal(vector, sequence_vector(changed, 20, 6))


def test_sequence_lengths_come_from_observed_durations() -> None:
    observed = [3, 5, 5, 8]
    assert sequence_length_candidates(observed) == (3, 5, 8)
