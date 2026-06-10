# 15% Before -3% Historical Analog Screen

## Objective

Rank the latest available daily setups in the local stock universe by their historical
conditional likelihood of reaching a 15% upside barrier before a 3% downside barrier
within 30 trading sessions.

The result is a historical analog estimate, not a forecast or guaranteed probability.

## Data

- Use local raw, unadjusted daily OHLCV from `market-data/prices/1d`.
- Use exact-interval precalculated daily indicators from `market-data/indicators/1d`.
- Analyze every symbol available in the inner-joined price and indicator dataset.
- Exclude historical entries without a complete next-30-session window.
- Use the latest complete joined row for each symbol as its current setup.

## Historical Outcome Labels

For every eligible historical entry:

- Entry price is that session's close.
- The upside barrier is `entry close * 1.15`.
- The downside barrier is `entry close * 0.97`.
- A win occurs when a later session's high reaches the upside barrier before any later
  session's low reaches the downside barrier.
- A loss occurs when a later session's low reaches the downside barrier before any later
  session's high reaches the upside barrier.
- A neither outcome occurs when neither barrier is reached within the next 30 sessions.
- Exclude entries where both barriers are reached on the same daily candle because daily
  OHLCV cannot establish which barrier occurred first.
- Exclude neither outcomes from the conditional probability denominator.

The 30-session window begins after the entry session.

## Similarity Model

Represent each setup using normalized, scale-comparable features:

- Close relative to EMA 10, 20, 50, 100, and 200
- RSI 14
- ATR percent 14
- MACD, MACD signal, and MACD histogram relative to close
- ADX 14, plus DI 14, and minus DI 14
- Relative volume 20
- Band width 20,2
- ROC 20
- Distance from the trailing 365-day high

Standardize each feature using the eligible historical setup population. For each current
setup, calculate Euclidean distance to historical setups across the full stock universe.
Exclude historical rows belonging to the same symbol as the current setup to reduce
stock-specific leakage. Use the 100 nearest decisive analogs. Fail clearly for a current
setup when fewer than 100 decisive analogs are available.

## Ranking And Output

Calculate:

```text
conditional win probability = wins / (wins + losses)
decisive hit rate = decisive outcomes among the 100 nearest eligible analogs / 100
```

Rank descending by conditional win probability, then by decisive hit rate, then by
symbol. The conditional probability still uses the 100 nearest decisive analogs; the
decisive hit rate separately measures how often the closest unfiltered setups reached
either barrier. Report the highest-ranked candidates with:

- Symbol and latest setup date
- Latest close
- Conditional win probability
- Wins and losses among the 100 decisive analogs
- Decisive hit rate
- Key current indicators for interpretation

Also report the joined universe size, eligible historical setup count, exclusion rules,
data date, and that neither and same-candle outcomes were excluded.

## Implementation Constraints

- Perform reads, transformations, labels, standardization, distance calculations,
  aggregations, and ranking with Polars.
- Use lazy Parquet scans, projection and predicate pushdown where applicable, and one
  final collection for the result.
- Do not calculate per-symbol metrics with Python loops.
- Treat the analysis as read-only unless an output artifact is explicitly requested.
- Raise clear exceptions for absent data, insufficient history, missing required columns,
  zero-variance features, or insufficient decisive analogs.

## Verification

- Confirm source and requested interval are both exact daily data.
- Confirm latest included timestamp, joined symbol count, and eligible row count.
- Verify representative win, loss, neither, and same-candle labels.
- Verify every ranked stock uses exactly 100 decisive analogs from other symbols.
- Verify probabilities equal `wins / 100` and ranking tie-breakers are deterministic.
