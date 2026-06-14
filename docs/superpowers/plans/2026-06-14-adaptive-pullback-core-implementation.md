# Adaptive Per-Stock Pullback Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the causal single-stock learning core that relearns one stock-specific parameter set per run, enters at the next bar open, always applies the fixed 3% stop, and abstains when the stock's own evidence is inconclusive.

**Architecture:** Add the numerical core of a focused `stock_data.pullback` package. It validates one stock, builds causal features, detects BIC-selected regimes, derives candidate values only from that stock's observed distributions, runs nested walk-forward evaluation, learns uncertainty penalties, and either selects one parameter set or abstains.

**Tech Stack:** Python 3.12, Polars, NumPy, SciPy, ruptures, Pydantic, Typer, pytest, Ruff.

**Invariant:** The only fixed trading parameter is `STOP_LOSS_FRACTION = 0.03`, measured from the actual next-bar-open entry. Statistical identities and structural validation rules are allowed; no behavioral threshold, candidate grid, event-count cutoff, holding horizon, profit target, lookback, pivot scale, confidence cutoff, or cross-stock parameter is fixed.

---

## File Structure

Create focused modules under `src/stock_data/pullback/`; keep every file below 800 lines and every function below 80 lines.

| File | Responsibility |
|---|---|
| `errors.py` | Explicit data, evidence, and learning exceptions |
| `models.py` | Immutable public records and the fixed 3% invariant |
| `quality.py` | Shared universe as-of resolution and structural data validation |
| `features.py` | Causal, scale-free per-bar feature construction |
| `sequences.py` | Stock-derived causal price-action sequences and distances |
| `regimes.py` | BIC-selected causal change points and same-stock regime similarity |
| `outcomes.py` | Next-open entries, fixed-stop path outcomes, censoring |
| `candidates.py` | Stock-derived feature bands and parameter candidate generation |
| `walk_forward.py` | Causal nested folds and candidate evaluation |
| `selection.py` | Stock-calibrated uncertainty penalty, single winner, abstention |
| `learner.py` | Full single-stock orchestration |

Test files mirror these responsibilities under `tests/pullback/`.

## Algorithm Contract

- Base features are causal and scale-free: log return, true-range fraction, gap fraction,
  body/range geometry, close location, volume change, directional run length, expanding
  drawdown/run-up, and observed cadence.
- `ruptures.Binseg` generates every mathematically feasible segmentation. BIC chooses the
  segmentation per training fold; there is no fixed change-point penalty.
- Historical regime similarity uses robustly scaled feature distributions from the same
  stock. Candidate similarity boundaries are midpoints between observed regime distances.
- Candidate behavioral values come from observed label-transition boundaries, observed
  swing reversals/durations, observed price-action sequence distances, observed MFE,
  observed times-to-outcome, and observed regime distances. There is no universal
  candidate grid.
- Setup detection uses completed bar data. Entry is the next bar open. Stop is exactly 3%
  below entry.
- Historical labels may use later price movement; features, regimes, setup detection, and
  parameter selection may not.
- Candidate selection learns the penalty for instability and uncertainty from the stock's
  own outer-fold prediction errors. It selects one positive uncertainty-adjusted expected
  return or abstains.

---

### Task 1: Package Skeleton, Dependencies, and Core Models

**Files:**
- Modify: `pyproject.toml`
- Create: `src/stock_data/pullback/__init__.py`
- Create: `src/stock_data/pullback/errors.py`
- Create: `src/stock_data/pullback/models.py`
- Create: `tests/pullback/__init__.py`
- Create: `tests/pullback/conftest.py`
- Create: `tests/pullback/test_models.py`

- [ ] **Step 1: Write model invariant tests**

```python
def test_trade_stop_is_exactly_three_percent_below_entry() -> None:
    trade = TradePath(entry_index=4, entry_price=100.0, stop_price=97.0)
    assert trade.stop_price == trade.entry_price * (1 - STOP_LOSS_FRACTION)


def test_parameter_set_rejects_non_stock_derived_empty_fields() -> None:
    with pytest.raises(ValueError, match="feature bands"):
        ParameterSet(
            feature_bands=(),
            dip_band=(2.0, 4.0),
            swing_reversal_fraction=0.02,
            regime_distance_limit=1.0,
            sequence_length_bars=5,
            setup_distance_limit=1.0,
            lookback_bars=20,
            horizon_bars=8,
            target=0.05,
        )
```

- [ ] **Step 2: Run tests and verify missing package failure**

Run: `pytest tests/pullback/test_models.py -v`

Expected: FAIL because `stock_data.pullback` does not exist.

- [ ] **Step 3: Add explicit libraries and core immutable records**

Add dependencies:

```toml
"numpy>=2.0",
"scipy>=1.14",
"ruptures>=1.1.9",
```

Implement records including:

```python
STOP_LOSS_FRACTION = 0.03


@dataclass(frozen=True)
class FeatureBand:
    name: str
    lower: float
    upper: float


@dataclass(frozen=True)
class ParameterSet:
    feature_bands: tuple[FeatureBand, ...]
    dip_band: tuple[float, float]
    swing_reversal_fraction: float
    regime_distance_limit: float
    sequence_length_bars: int
    setup_distance_limit: float
    lookback_bars: int
    horizon_bars: int
    target: float

    def __post_init__(self) -> None:
        if not self.feature_bands:
            raise ValueError("parameter set requires feature bands")
        if min(self.horizon_bars, self.lookback_bars, self.sequence_length_bars) < 1:
            raise ValueError("learned bar counts must be positive")
```

Also define `QualityIssue`, `Regime`, `Opportunity`, `TradePath`, `TradeOutcome`,
`FoldScore`, `StockDecision`, and `ScreenResult`. Require every field; do not add
defaults.

Define `PullbackError`, `PullbackDataError`, `InsufficientEvidenceError`, and
`LearningError` in `errors.py`. Numerical modules raise these explicit exceptions with
symbol, interval, and phase context.

- [ ] **Step 4: Add synthetic OHLCV fixture factory**

`tests/pullback/conftest.py` must expose `price_frame(closes, volumes)` and preserve the
canonical schema with Asia/Kolkata timestamps.

- [ ] **Step 5: Run focused tests and lint**

Run: `pytest tests/pullback/test_models.py -v && ruff check src/stock_data/pullback tests/pullback`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/stock_data/pullback tests/pullback
git commit -m "feat(pullback): add adaptive learner model contracts"
```

### Task 2: Shared Data-Quality Gate

**Files:**
- Create: `src/stock_data/pullback/quality.py`
- Create: `tests/pullback/test_quality.py`

- [ ] **Step 1: Write structural quality tests**

Cover:

```python
def test_common_as_of_is_unique_modal_latest_timestamp() -> None:
    assert resolve_common_as_of({"A": t2, "B": t2, "C": t1}) == t2


def test_common_as_of_rejects_tied_modes() -> None:
    with pytest.raises(PullbackDataError, match="common as-of"):
        resolve_common_as_of({"A": t1, "B": t2})


def test_validate_prices_flags_stale_duplicate_and_invalid_ohlc() -> None:
    result = validate_prices(frame, common_as_of)
    assert {issue.code for issue in result.issues} == {
        "stale", "duplicate_timestamp", "invalid_ohlc"
    }
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_quality.py -v`

Expected: FAIL because quality functions do not exist.

- [ ] **Step 3: Implement one shared lazy universe scan**

Use one `scan_parquet()` aggregation to return symbol, row count, first timestamp, last
timestamp, duplicate count, null count, non-finite count, and OHLC violations. Resolve the
common as-of as the unique modal latest timestamp. A stale symbol is any symbol whose last
timestamp differs from that common as-of.

Do not reject sparse or short history using fixed counts. Return observed continuity and
history diagnostics so the learner can abstain from its own uncertainty.

- [ ] **Step 4: Run tests**

Run: `pytest tests/pullback/test_quality.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/pullback/quality.py tests/pullback/test_quality.py
git commit -m "feat(pullback): add shared structural data quality gate"
```

### Task 3: Causal Base Features and Price-Action Sequences

**Files:**
- Create: `src/stock_data/pullback/features.py`
- Create: `src/stock_data/pullback/sequences.py`
- Create: `tests/pullback/test_features.py`
- Create: `tests/pullback/test_sequences.py`

- [ ] **Step 1: Write causality and scale tests**

```python
def test_appending_future_bars_does_not_change_prior_features(price_frame) -> None:
    short = causal_features(price_frame[:40])
    long = causal_features(price_frame)
    assert short.equals(long.head(40))


def test_price_scaling_preserves_fractional_features(price_frame) -> None:
    scaled = price_frame.with_columns(
        [pl.col(name) * 10 for name in ("open", "high", "low", "close")]
    )
    assert causal_features(price_frame).select(FRACTION_FEATURES).equals(
        causal_features(scaled).select(FRACTION_FEATURES)
    )
```

- [ ] **Step 2: Write causal sequence tests**

```python
def test_sequence_vector_uses_only_rows_through_detection(features) -> None:
    vector = sequence_vector(features, end_index=20, length=6)
    changed = features.with_columns(
        pl.when(pl.int_range(pl.len()) > 20)
        .then(999.0)
        .otherwise(pl.col("log_return"))
        .alias("log_return")
    )
    assert np.array_equal(vector, sequence_vector(changed, 20, 6))


def test_sequence_lengths_come_from_observed_durations(observed_durations) -> None:
    assert set(sequence_length_candidates(observed_durations)).issubset(
        set(observed_durations)
    )
```

- [ ] **Step 3: Run tests and verify failure**

Run: `pytest tests/pullback/test_features.py tests/pullback/test_sequences.py -v`

Expected: FAIL because feature and sequence construction do not exist.

- [ ] **Step 4: Implement causal scale-free features**

Build features only from current/prior bars:

```python
return prices.with_columns(
    pl.col("close").log().diff().alias("log_return"),
    (true_range / pl.col("close").shift(1)).alias("true_range_fraction"),
    ((pl.col("open") / pl.col("close").shift(1)) - 1).alias("gap_fraction"),
    ((pl.col("close") - pl.col("open")) / bar_range).alias("body_fraction"),
    ((pl.col("close") - pl.col("low")) / bar_range).alias("close_location"),
    pl.col("volume").cast(pl.Float64).log1p().diff().alias("log_volume_change"),
)
```

Add causal expanding high/low distance, directional run length, and bar-position index.
For flat bars, emit null candle-geometry features rather than dividing by zero. Preserve
null warm-up rows; do not fill missing values with defaults.

- [ ] **Step 5: Implement data-derived price-action sequences**

Build normalized ordered vectors from causal base features ending at the completed
detection bar. Candidate sequence lengths come only from observed directional-run,
swing, and regime-subsequence durations. Compute distances only to earlier same-stock
sequences. Candidate setup-similarity limits are midpoints between observed
profitable/non-profitable distance transitions.

- [ ] **Step 6: Run tests**

Run: `pytest tests/pullback/test_features.py tests/pullback/test_sequences.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_data/pullback/features.py src/stock_data/pullback/sequences.py tests/pullback/test_features.py tests/pullback/test_sequences.py
git commit -m "feat(pullback): add causal features and price action sequences"
```

### Task 4: Causal Regimes and Similarity

**Files:**
- Create: `src/stock_data/pullback/regimes.py`
- Create: `tests/pullback/test_regimes.py`

- [ ] **Step 1: Write regime-selection tests**

Test that:

- A constant feature frame yields one regime.
- A synthetic variance/trend shift yields a boundary near the observed shift.
- Appending future bars does not change regimes fitted to an earlier training slice.
- Similarity uses only regimes from the same symbol.

```python
def test_constant_features_yield_one_regime(constant_features) -> None:
    assert len(fit_regimes(constant_features)) == 1


def test_future_rows_do_not_change_prior_training_regimes(features) -> None:
    expected = fit_regimes(features.head(80))
    assert fit_regimes(features.head(80)) == expected
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_regimes.py -v`

Expected: FAIL because regime learning does not exist.

- [ ] **Step 3: Implement BIC-selected segmentation**

Use `ruptures.Binseg(model="l2", min_size=feature_count + 1)` to generate every
mathematically feasible break count for the training slice. Select the segmentation with
minimum BIC:

```python
def bic(residual_sum_squares: float, observations: int, parameters: int) -> float:
    if residual_sum_squares <= 0:
        return float("-inf")
    return observations * math.log(residual_sum_squares / observations) + (
        parameters * math.log(observations)
    )
```

`feature_count + 1` is a structural identifiability requirement, not a behavioral
threshold. Return one regime directly when every selected feature is constant. Fit
separately inside every walk-forward training slice.

- [ ] **Step 4: Implement same-stock regime similarity candidates**

Robustly scale regime feature distributions using training-slice median and MAD. Compute
regime distances with SciPy's energy distance per selected feature. Return observed
distance-transition midpoints as candidate inclusion boundaries; do not impose a fixed
distance limit. Normalize the current regime's evidence weight to `1.0`; learn every
older regime's weight from its observed distance and out-of-sample contribution, under
the design constraint that no older regime may outweigh the current regime.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pullback/test_regimes.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_data/pullback/regimes.py tests/pullback/test_regimes.py
git commit -m "feat(pullback): learn causal stock regimes with BIC"
```

### Task 5: Next-Open Outcomes and Fixed 3% Stop

**Files:**
- Create: `src/stock_data/pullback/outcomes.py`
- Create: `tests/pullback/test_outcomes.py`

- [ ] **Step 1: Write execution-path tests**

```python
def test_detection_enters_at_next_bar_open() -> None:
    outcome = trace_path(prices, detection_index=3, regime_end_index=8)
    assert outcome.entry_index == 4
    assert outcome.entry_price == prices["open"][4]
    assert outcome.stop_price == prices["open"][4] * 0.97


def test_latest_detection_is_pending_not_fabricated() -> None:
    assert trace_path(prices, detection_index=prices.height - 1, regime_end_index=None).pending


def test_same_bar_stop_and_target_is_unknown() -> None:
    assert evaluate_target(path, target=0.04, horizon_bars=3).status == "unknown"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_outcomes.py -v`

Expected: FAIL because outcome tracing does not exist.

- [ ] **Step 3: Implement vector-indexed path tracing**

Trace from next-bar open until the fixed 3% stop, causal regime end, or data end. Record
MFE, MAE, bars to prior high, bars to stop, bars to MFE, and censoring. Use bar indices and
NumPy arrays; never repeatedly filter the full Polars frame.

Raw prefilter label:

```python
raw_profitable = path.mfe_fraction is not None and path.mfe_fraction > 0
```

Future movement is a training label only. Same-bar stop/target order remains unknown.

- [ ] **Step 4: Run tests**

Run: `pytest tests/pullback/test_outcomes.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/pullback/outcomes.py tests/pullback/test_outcomes.py
git commit -m "feat(pullback): add causal next-open fixed-stop outcomes"
```

### Task 6: Stock-Derived Candidate Generation

**Files:**
- Create: `src/stock_data/pullback/candidates.py`
- Create: `tests/pullback/test_candidates.py`

- [ ] **Step 1: Write no-grid candidate tests**

```python
def test_boundaries_come_only_from_observed_label_transitions() -> None:
    values = np.array([1.0, 2.0, 5.0, 9.0])
    labels = np.array([False, False, True, True])
    assert transition_boundaries(values, labels) == (3.5,)


def test_horizon_and_target_candidates_are_observed_outcomes() -> None:
    candidates = outcome_candidates(paths)
    assert set(candidates.horizons).issubset({path.bars_to_mfe for path in paths})
    assert set(candidates.targets).issubset({path.mfe_fraction for path in paths})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_candidates.py -v`

Expected: FAIL because candidate generation does not exist.

- [ ] **Step 3: Implement empirical transition boundaries**

Generate boundaries only where sorted observed labels change. Build contiguous feature
bands from those boundaries. Derive:

- swing reversal candidates from every observed causal direction-change fraction;
- lookbacks from observed current/similar-regime lengths;
- dip bands from observed profitable-opportunity drawdowns;
- regime limits from observed same-stock regime distances;
- sequence lengths from observed same-stock structure durations;
- setup-similarity limits from observed same-stock price-action sequence distances;
- horizons from observed resolved time-to-outcome values;
- targets from observed MFE values;
- setup feature bands from observed positive/negative label transitions.

Raise `InsufficientEvidenceError` when a candidate family cannot be derived; do not provide
a fallback.

- [ ] **Step 4: Implement Pareto candidate pruning**

Remove a candidate only when another candidate is at least as good on every completed
training fold and better on at least one. Do not use a fixed beam width or score cutoff.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pullback/test_candidates.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_data/pullback/candidates.py tests/pullback/test_candidates.py
git commit -m "feat(pullback): derive behavioral candidates per stock"
```

### Task 7: Nested Causal Walk-Forward Evaluation

**Files:**
- Create: `src/stock_data/pullback/walk_forward.py`
- Create: `tests/pullback/test_walk_forward.py`

- [ ] **Step 1: Write fold-causality tests**

Assert that:

- Outer validation rows always occur after outer training rows.
- Inner validation rows always occur after inner training rows.
- Regimes and candidates are refit inside each training slice.
- No incomplete path is counted as a resolved failure.

```python
def test_nested_folds_are_strictly_causal(regimes) -> None:
    for outer in nested_folds(regimes):
        assert outer.train_end < outer.validation_start
        assert all(inner.train_end < inner.validation_start for inner in outer.inner)


def test_censored_paths_are_not_failures(evaluation) -> None:
    assert evaluation.resolved_failures == sum(
        outcome.status == "failure" for outcome in evaluation.outcomes
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_walk_forward.py -v`

Expected: FAIL because walk-forward evaluation does not exist.

- [ ] **Step 3: Derive folds from causal regime boundaries**

Build folds from observed regime endpoints rather than fixed bar counts. Each fold trains
on all earlier eligible regimes and validates on the next observed regime. If the stock
cannot form an inner and outer evaluation, raise `InsufficientEvidenceError`.

- [ ] **Step 4: Evaluate parameter sets**

For each fold:

1. Fit causal features and regimes on training data.
2. Generate candidates from training outcomes only.
3. Detect setups on completed validation bars.
4. Enter at next-bar open.
5. Apply the exact 3% stop.
6. Record previous-high recovery, learned-target return, censoring, and instability.

Use stock/regime similarity weights learned from prior folds; no future fold may influence
an earlier fold.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pullback/test_walk_forward.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_data/pullback/walk_forward.py tests/pullback/test_walk_forward.py
git commit -m "feat(pullback): add nested causal walk-forward evaluation"
```

### Task 8: Stock-Calibrated Selection and Abstention

**Files:**
- Create: `src/stock_data/pullback/selection.py`
- Create: `tests/pullback/test_selection.py`

- [ ] **Step 1: Write adaptive-selection tests**

Test that:

- A stable positive candidate is selected.
- A candidate with positive mean but historically miscalibrated uncertainty abstains.
- Indistinguishable winners abstain.
- No event-count or confidence constant exists in the module.

```python
def test_indistinguishable_candidates_abstain(equal_candidates) -> None:
    assert select_parameter_set(equal_candidates).decision == "abstain"


def test_positive_calibrated_candidate_is_selected(stable_candidate) -> None:
    result = select_parameter_set((stable_candidate,))
    assert result.parameter_set == stable_candidate.parameter_set
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_selection.py -v`

Expected: FAIL because selection does not exist.

- [ ] **Step 3: Learn uncertainty penalty from outer folds**

Fit the stock's penalty coefficient from prior outer-fold prediction errors:

```python
penalty = fit_non_negative_least_squares(
    instability_and_uncertainty,
    absolute_out_of_sample_error,
)
adjusted_return = expected_return - penalty @ current_uncertainty_vector
```

Use SciPy NNLS. If the penalty cannot be identified from the stock's history, abstain.
Compare the best candidate with zero-return abstention and competing candidates using
their stock-calibrated adjusted returns. Select one unique positive winner or abstain.

Build the uncertainty vector from outer-fold dispersion and regime-block bootstrap
resamples. Use one deterministic resample per observed regime, seeded from the stock and
as-of fingerprint; the resample count therefore comes from that stock's learned regime
history, not a global constant.

Evaluate simpler stock-specific baselines through the same folds: current-regime-only
evidence and abstain/pass-all behavior. Added complexity must improve the stock's own
adjusted out-of-sample result; otherwise select the simpler winner or abstain.

- [ ] **Step 4: Run tests**

Run: `pytest tests/pullback/test_selection.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/pullback/selection.py tests/pullback/test_selection.py
git commit -m "feat(pullback): select one stock-calibrated setup or abstain"
```

### Task 9: Full Single-Stock Learner

**Files:**
- Create: `src/stock_data/pullback/learner.py`
- Create: `tests/pullback/test_learner.py`

- [ ] **Step 1: Write end-to-end learner tests**

Use synthetic stocks with distinct behavior:

- shallow frequent dips;
- deep slow dips;
- unstable regime transitions;
- flat/ambiguous history.

Assert the first two learn different parameter sets, the unstable/flat stocks abstain, and
all executed trades use next-open entries with exact 3% stops.

```python
def test_distinct_stocks_learn_distinct_parameters(shallow_stock, deep_stock) -> None:
    shallow = learn_stock(shallow_stock)
    deep = learn_stock(deep_stock)
    assert shallow.parameter_set != deep.parameter_set


def test_unstable_stock_abstains(unstable_stock) -> None:
    assert learn_stock(unstable_stock).decision == "abstain"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_learner.py -v`

Expected: FAIL because orchestration does not exist.

- [ ] **Step 3: Implement `learn_stock` orchestration**

Compose quality diagnostics, features, regimes, outcomes, candidate generation,
walk-forward evaluation, selection, and current-state evaluation. Log symbol, phase,
candidate counts, fold counts, learned parameter values, and abstention reasons.

Classify the live result as BUY, WATCH, AVOID, or ABSTAIN from the selected stock-specific
rule and current causal state. A setup detected on the final completed bar is pending
next-open entry and has no fabricated entry or stop price.

Do not catch `InsufficientEvidenceError` inside the numerical modules. Convert it to an
explicit ABSTAIN decision only at the learner boundary.

- [ ] **Step 4: Run tests**

Run: `pytest tests/pullback/test_learner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/pullback/learner.py tests/pullback/test_learner.py
git commit -m "feat(pullback): orchestrate adaptive single-stock learning"
```

---

## Spec Coverage Audit

| Approved requirement | Implemented by |
|---|---|
| Fixed 3% stop from actual next-open entry | Tasks 1, 5, 7 |
| Every behavioral parameter learned per stock every run | Tasks 4, 6, 7, 9 |
| Multivariate causal regimes and similar historical regimes | Task 4 |
| Recent/current regime receives greatest evidence | Tasks 4, 7 |
| Data-derived price action, no named patterns | Tasks 3, 6 |
| Earliest causal detection, next-bar-open execution | Tasks 3, 5, 7 |
| Learned target and horizon | Tasks 5–7 |
| Previous-high recovery and expected return | Tasks 5, 7 |
| Single best parameter set or abstain | Task 8 |
| No fixed confidence or event-count standard | Tasks 6, 8 |
| Structural data-quality gate | Task 2 |
| Causal core orchestration | Task 9 |

After this plan passes, execute
`docs/superpowers/plans/2026-06-14-adaptive-pullback-screening-implementation.md`.
