# Same-Stock Similarity Skill Design

## Objective

Create a repository skill that finds historical setups resembling a stock's latest
10-day daily setup. Search only that stock's own history and preserve chart direction,
movement pace, candle behavior, volume behavior, indicators, and broader trend context
during matching.

The skill returns up to 200 non-overlapping historical matches plus their subsequent
5, 10, 20, and 30 trading-day outcomes. It measures similarity, not predictive quality
or trade profitability.

## Skill Structure

Create:

```text
.agents/skills/find-similar-stock-setups/
├── SKILL.md
├── agents/openai.yaml
└── scripts/find_similar_setups.py
```

The skill depends on `talk-to-stock-data` conventions and imports its
`scripts/stock_frame.py` helper. Its bundled script provides deterministic similarity
calculation rather than asking the agent to rewrite the query for every request.

## Inputs

Required:

- One Yahoo-style stock symbol

Fixed version-one semantics:

- Exact daily price and indicator data
- Latest 10 available trading sessions define the query setup
- Same-symbol historical candidates only
- Up to 200 matches
- No recency weighting
- Raw, unadjusted local data

Fail clearly when the symbol, exact daily data, indicators, or required latest 10 rows
are unavailable.

## Candidate Windows

Each candidate is a historical 10-session rolling window ending before the latest setup
begins. Exclude:

- Windows overlapping the latest setup
- Windows containing an absolute close-to-close move above 40%
- Windows lacking complete OHLCV or indicator values
- Windows lacking enough future data for all requested outcome periods

If the latest setup itself contains an absolute close-to-close move above 40%, fail
clearly because raw corporate-action distortion may be present.

## Features

Preserve signed values wherever direction matters. Calculate features with Polars from
each 10-day window.

### Chart Shape

- Each day's open, high, low, and close relative to the window's first close
- Daily close returns
- Three-day rolling returns

These retain direction, path, pullbacks, breakouts, gaps, and daily movement pace.

### Pace

- Linear close-path slope
- Change in slope between the first and second halves as acceleration
- Up-day and down-day proportions
- Largest positive and negative daily returns

### Candle And Volatility

- Open gap relative to previous close
- Intraday high-low range relative to previous close
- Candle body relative to open
- Ten-day realized volatility of daily returns
- ATR percent path

### Volume

- Daily volume divided by the window's mean volume
- Relative-volume-20 path
- Daily volume percentage changes

### Trend Context

- Close relative to EMA 10, 20, 50, 100, and 200
- Distance from trailing 365-day high
- Close position within trailing 365-day high-low range
- ADX and directional-indicator paths

### Momentum Indicators

- RSI path
- MACD, signal, and histogram relative to close
- ROC path
- Band-width path
- OBV change path, normalized within the window

## Hierarchical Distance

### Hard Context Gates

Reject candidates that do not share the latest setup's:

- Direction regime: rising, falling, or sideways, based on 10-day close return
- Major trend regime: close above or below EMA 50 and EMA 200
- Volatility regime: low, medium, or high ATR percent tercile within the stock's history
- Yearly-position regime: near high, middle, or near low, using thirds of the trailing
  365-day range

Define sideways as an absolute 10-day close return below 2%. Derive ATR terciles only
from the stock's candidate history.

### Subgroup Distances

Calculate mean squared difference separately for:

- Chart shape
- Pace
- Candle and volatility
- Volume
- Trend context
- Momentum indicators

Before distance calculation, standardize scalar and path components using means and
population standard deviations from the stock's candidate history. Fail clearly on
required zero-variance components rather than silently defaulting.

Scale each subgroup distance by its median distance among surviving candidates. Reject a
zero subgroup median because it cannot produce meaningful scaling.

```text
combined distance = mean(scaled subgroup distances)
```

Lower distance means more similar. Return combined distance and every scaled subgroup
distance so the result remains auditable.

## Match Selection

Sort surviving candidates by combined distance, then candidate end date ascending.
Greedily select up to 200 candidates. Each selected candidate's 10-session window must
not overlap another selected candidate's window.

Return all available matches when fewer than 200 survive. Do not relax hard gates or
allow overlaps to reach 200. Fail only when no candidate survives.

## Future Outcomes

For every selected match, calculate from the candidate end close:

- Close return after 5, 10, 20, and 30 trading sessions
- Maximum favorable excursion over the next 30 sessions
- Maximum adverse excursion over the next 30 sessions
- Maximum close drawdown over the next 30 sessions

Because all requested outcomes require future data, candidates must have 30 later
sessions. State that prices are raw and unadjusted.

## Output

Present:

- Symbol, latest setup start/end dates, and latest close
- Candidate and rejection counts by reason
- Available match count
- Table of matches with dates, combined distance, six subgroup distances, and outcomes
- Aggregate outcome summary across selected matches
- Exact daily source interval and latest included timestamp
- Raw-price corporate-action warning

Do not describe similarity score as probability.

## Implementation Rules

- Use Polars for all data reads, transformations, feature calculations, distances,
  filtering, outcome calculations, and aggregation.
- Use lazy Parquet scans, projection pushdown, predicate pushdown, and one final
  collection where feasible.
- Do not calculate per-window metrics with Python loops.
- A small deterministic loop may select non-overlapping rows after the final ranked
  candidate table is collected because greedy interval selection is stateful.
- Keep every created file below 800 lines and every function below 80 lines.
- Use clear exceptions and detailed logger output. Do not use fallback/default values.

## Validation

- Unit-test feature direction and pace using rising, falling, sideways, steady-rise,
  late-breakout, and early-spike fixtures.
- Verify hard gates reject mismatched direction, trend, volatility, and yearly position.
- Verify subgroup distances cannot cancel signed directional differences.
- Verify lower subgroup mismatch produces lower subgroup distance.
- Verify selected 10-day windows never overlap and output order is deterministic.
- Verify corporate-action threshold, insufficient history, missing indicators,
  zero-variance components, and no-survivor conditions fail clearly.
- Verify future returns, excursions, and drawdown against small hand-calculated fixtures.
- Run skill validation and forward-test realistic requests for multiple symbols.
