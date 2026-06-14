# Per-Stock Adaptive Pullback Learning Design

## Purpose

Replace the current partly hand-composed pullback screening grammar with a causal,
per-stock learning algorithm. Each stock must learn its own pattern parameters from
its own history on every screening run. No behavioral parameter may be assumed to
work across multiple stocks.

The trader's fixed risk rule is invariant:

- Every evaluated trade uses a stop exactly 3% below its actual causal-detection
  entry price.

The algorithm evaluates raw price movement. Transaction costs, slippage, and
corporate-action-specific detection are out of scope.

## Core Principles

1. Learn each stock independently. Never borrow evidence, parameters, or thresholds
   from another stock.
2. Relearn every parameter on every screening run using the latest valid data.
3. Use only information available at each historical decision point.
4. Give recent behavior the greatest weight, while retaining older regimes when they
   statistically resemble the current regime.
5. Prefer parameter stability before optimizing out-of-sample performance.
6. Select exactly one best learned parameter set per stock, or abstain.
7. Keep the 3% stop fixed in every historical and live evaluation.
8. Use no fixed behavioral confidence standard, minimum event count, or universal
   pattern threshold.

## Scope

The learner must determine, independently for each stock:

- Regime boundaries and current-regime characteristics
- Similarity and weights for older regimes
- Swing sensitivity
- Noise boundary
- Relevant historical lookback
- Dip zone
- Causal setup-detection rule
- Price-action similarity representation
- Holding horizon
- Profit target
- Previous-high recovery probability
- Uncertainty and abstention decision
- High-recall prefilter parameters

The only fixed trade-risk parameter is the 3% stop from actual entry.

## End-to-End Screening Flow

### 1. Data-Quality Gate

Before learning begins, validate every stock independently and exclude invalid
stocks. Disclose every exclusion and its reason.

Reject stocks with:

- Stale data relative to the universe's latest completed bar
- Missing, duplicated, unordered, or inconsistent timestamps
- Invalid OHLC relationships or non-finite prices
- Insufficient continuous history for causal walk-forward evaluation
- Missing or unusable bars that make regime learning unreliable

Structural truths such as `high >= low` may be fixed. Behavioral sufficiency and
continuity requirements must be inferred from the stock's observed cadence,
available history, and resulting uncertainty.

Adjusted OHLCV is trusted as supplied. Corporate-action-specific detection is not
required.

### 2. Causal Feature Construction

At every bar, construct features using only that bar and earlier bars. Features may
describe:

- Returns and return distributions
- Volatility and ATR-normalized movement
- Trend direction and strength
- Volume and liquidity behavior
- Gaps, candle ranges, and candle relationships
- Higher-high, higher-low, lower-high, and lower-low evolution
- Swing depth, duration, velocity, and persistence
- Consolidation, breakout, failed-breakout, and reversal behavior
- Pullback depth, recovery time, and fixed-3%-stop outcomes
- Recurring data-derived price-action sequences

Named chart patterns must not influence learning. Price-action structures are
learned directly from each stock's feature sequences.

### 3. Multivariate Regime Learning

Detect regime changes causally from the stock's multivariate feature history.
Regimes must reflect changes in:

- Volatility
- Trend behavior
- Swing structure
- Volume and liquidity
- Gap and candle behavior
- Data-derived price-action sequences
- Pullback outcomes under the fixed 3% stop

The current regime receives the greatest evidence weight. Older regimes may
contribute only according to their learned statistical similarity to the current
regime.

Regime similarity, weighting decay, and whether a historical regime contributes
must be learned through nested walk-forward validation. Dissimilar historical
regimes are excluded when including them reduces out-of-sample performance.

### 4. Per-Stock Learned Prefilter

Run a lightweight learned prefilter for every valid stock before invoking the full
learner.

The prefilter must:

- Be relearned from the stock's own data every run
- Use the stock's current-regime behavior
- Optimize primarily for historical recall of the full learner's eligible decisions
- Retain uncertain and borderline setups
- Exclude a stock only when its own evidence confidently identifies it as a
  non-candidate
- Use latency only as a secondary tie-breaker between equally high-recall parameter
  sets

The prefilter must not use universe-wide behavioral thresholds. Its historical
recall is evaluated causally against the full learner's decisions for the same
stock.

### 5. Full Per-Stock Learner

For each prefilter survivor, generate candidate parameter sets entirely from that
stock's observed causal distributions and current-regime evidence.

Candidate parameter sets cover:

- Regime model and historical-regime weights
- Swing sensitivity
- Noise boundary
- Historical lookback
- Dip zone
- Causal setup-detection rule
- Price-action similarity representation
- Learned holding horizon
- Learned profit target

Candidate values must be derived from empirical structures in the stock's data.
There is no shared candidate grid, fixed fractal window, fixed ATR multiplier,
fixed lookback, fixed dip threshold, fixed holding horizon, or universal event-count
requirement.

### 6. Earliest Causal Entry

Historical trades become actionable at the earliest bar where the selected setup
rule recognizes the opportunity using only information available at that time.
Setup detection occurs only after the detection bar is complete. The actual entry
is the next bar's open.

The learner must not:

- Enter at a historical swing low that required future bars to identify
- Use centered-window confirmation before the confirmation bars existed
- Use future regime labels, future extrema, or completed outcomes in live features
- Assume execution at the detection bar's close

For every historical evaluation:

- Entry price is the next bar's open after causal detection
- Stop is exactly 3% below that entry price

If no next bar exists, no historical trade is opened. A live setup detected on the
latest completed bar is reported as pending entry until the next bar opens. Its
entry and 3% stop must not be estimated or fabricated.

### 7. Learned Outcomes

Evaluate two success dimensions separately:

1. Probability of recovering the previous swing high before hitting the fixed 3%
   stop.
2. Expected raw return under the stock's learned profit target and learned holding
   horizon, while respecting the fixed 3% stop.

The holding horizon and profit target are learned independently for each stock and
regime. They must remain causal and pass nested walk-forward validation.

Incomplete trades are censored, not automatically counted as failures. Same-bar
target and stop events are unknown unless the available bar resolution proves their
order.

### 8. Nested Walk-Forward Evaluation

Use nested causal walk-forward evaluation:

- Inner walk-forward periods generate and select candidate parameter sets using only
  prior data.
- Outer walk-forward periods measure honest out-of-sample behavior.
- Recent periods receive greater influence through learned regime-adaptive
  weighting.
- Older similar regimes may add evidence according to their learned weight.
- Dissimilar regimes must not dilute current-regime estimates.

Candidate selection follows a hybrid objective:

1. Require evidence that the candidate's behavior is stable across relevant
   walk-forward periods and similar regimes.
2. Among stable candidates, select the candidate with the highest
   uncertainty-adjusted, probability-weighted expected raw return.

Stability is measured relative to the stock's own candidate and outcome
distributions. It must not use a universal cutoff.

### 9. Single Parameter-Set Selection

Retain exactly one best learned parameter set per stock.

Select it only when:

- It is supported by the stock's own causal walk-forward evidence
- It remains stable relative to alternatives
- Its uncertainty-adjusted expected return exceeds abstaining
- It clearly dominates competing parameter sets within the stock's own uncertainty
  distribution

If competing parameter sets are statistically indistinguishable, abstain rather
than choosing arbitrarily.

### 10. Adaptive Confidence and Abstention

There is no fixed confidence percentage, minimum event count, or universal
stability threshold.

For each stock:

- Estimate uncertainty from regime-weighted walk-forward and bootstrap results
- Learn the penalty for parameter instability, outcome uncertainty, and regime
  mismatch from that stock's out-of-sample history
- Compare BUY against ABSTAIN, where abstaining has zero return
- Issue BUY only when uncertainty-adjusted expected return exceeds abstaining

Abstain when:

- The stock's history cannot support a reliable current-regime estimate
- Learning or validation is inconclusive
- No candidate consistently dominates alternatives
- The selected setup does not beat abstaining

Never borrow evidence from statistically similar stocks and never force a result.

### 11. Universe Ranking

Rank eligible stocks by uncertainty-adjusted, probability-weighted expected raw
return.

Ranking compares the outputs of independently learned stock models. It must not
replace per-stock learning with a universal behavioral rule.

## Reporting Contract

For each analyzed stock, report:

- Decision: BUY, WATCH, AVOID, or ABSTAIN
- Detection timestamp
- Entry status: executed at next-bar open or pending next-bar open
- Actual next-bar-open entry price when available
- Fixed 3% stop price when entry is available
- Selected single parameter set
- Learned current regime and supporting evidence
- Contribution from older similar regimes
- Learned dip zone
- Learned holding horizon
- Learned profit target
- Previous-high recovery probability
- Probability-weighted expected raw return
- Uncertainty-adjusted expected raw return
- Walk-forward performance and stability evidence
- Abstention reason when applicable

For every screening run, also report:

- Universe size
- Data-quality exclusions and reasons
- Prefilter survivor count
- Prefilter recall evidence
- Full-learner eligible count
- Stocks where the learner abstained
- Screening as-of timestamp

## Performance Design

Accuracy and causal correctness take precedence over latency. The chosen two-stage
flow limits cost without using a universal prefilter.

Performance requirements:

- Scan and validate the universe in shared lazy Polars passes where possible.
- Construct reusable causal base features once per stock per run.
- Avoid repeated full-DataFrame filtering inside candidate and event loops.
- Use indexed bar positions and precomputed feature arrays for walk-forward
  evaluation.
- Evaluate independent stocks in parallel after the shared data-quality gate.
- Relearn every stock on every run; do not trust cached parameter outputs after data
  changes.
- Permit reuse of immutable intermediate features within the same run.

## Failure Handling

- Invalid stock data: exclude, disclose, and continue screening other stocks.
- Failed per-stock learning: abstain for that stock and disclose the error.
- Inconclusive candidate selection: abstain.
- Insufficient evidence: abstain.
- Incomplete historical outcome: censor it.
- Same-bar stop and target ambiguity: mark unknown.
- Stale universe data: fail fast when a reliable common as-of timestamp cannot be
  established.

The algorithm must never silently substitute a universal parameter or forced
fallback.

## Validation Strategy

Validation must prove that the learner generalizes causally and independently for
each stock.

### Causal Correctness

- Confirm every feature uses only current and prior bars.
- Confirm regime labels are available at the historical decision time.
- Confirm entries occur at the next bar's open after earliest causal detection.
- Confirm the 3% stop is always measured from actual entry.
- Confirm future swing confirmation does not leak into historical entries.

### Learning Quality

- Compare learned parameter sets against simpler stock-specific baselines.
- Confirm added complexity improves out-of-sample results.
- Measure parameter stability across relevant walk-forward periods and similar
  regimes.
- Confirm dissimilar regimes receive no beneficial weight unless proven
  out-of-sample.
- Confirm the selected parameter set clearly dominates alternatives or abstains.

### Prefilter Quality

- Measure causal prefilter recall against historical full-learner decisions.
- Confirm uncertain and borderline cases remain eligible for the full learner.
- Confirm latency optimization never overrides the primary recall objective.

### Adversarial Cases

Test:

- Flat prices and tied extrema
- Gaps
- Sparse or zero volume
- Missing and duplicated bars
- Short histories
- Stale data
- Regime transitions
- Incomplete outcomes
- Same-bar stop and target events
- Parameter ties
- No profitable or stable parameter set

## Acceptance Criteria

The design is successfully implemented when:

1. No behavioral parameter is shared or fixed across stocks.
2. Every stock relearns its parameters on every screening run.
3. Every historical decision is causal.
4. Every evaluated trade enters at the next bar's open after detection and uses a
   stop exactly 3% below that actual entry.
5. Holding horizon and profit target are learned per stock.
6. Recent behavior receives regime-adaptive greater weight.
7. Older regimes contribute only when learned similarity supports them.
8. The learned prefilter prioritizes recall and uses only per-stock evidence.
9. Exactly one parameter set is selected per stock, or the learner abstains.
10. Confidence and abstention use the stock's own uncertainty distribution.
11. Invalid, stale, or inconclusive cases are disclosed without forced fallbacks.
12. Universe ranking uses uncertainty-adjusted, probability-weighted expected raw
    return.
