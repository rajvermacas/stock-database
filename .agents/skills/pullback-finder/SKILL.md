---
name: pullback-finder
description: Analyze whether one named stock is in a learned pullback state using only that stock's history. Requires a user-supplied timeframe.
---

# Adaptive Pullback Finder

Use the repository's `stock-pullback` engine for a single-symbol pullback analysis.
The engine relearns one stock-specific parameter set from current data on every run,
or abstains when its own evidence does not support a unique positive setup.

## Required Input

- Require both symbol and timeframe. Never infer or default either value.
- Read `market-data/prices/<interval>/<symbol>.parquet`.
- If the file is missing, report the missing path. Do not silently swap timeframes
  or fabricate data.

## Run

```bash
stock-pullback analyze \
  --prices-root market-data/prices \
  --interval <user-timeframe> \
  --symbol <symbol> \
  --output json
```

## Interpretation

- `buy`: the latest completed bar matches the stock's learned setup and the selected
  setup beats abstaining.
- `watch`: the learned setup is positive, but the current bar is outside its learned
  dip zone.
- `abstain`: evidence is insufficient, unstable, indistinguishable, or does not beat
  abstaining. Respect the reason; never force a verdict.
- A current match has pending entry until the next bar opens. Do not fabricate entry
  or stop prices.

## Learning Contract

- Relearn all behavioral parameters from this stock on every run.
- Use causal OHLCV price action, not named chart patterns or cross-stock constants.
- Give recent/current-regime behavior the greatest weight.
- Learn duration, horizon, target, dip zone, lookback, and other setup parameters.
- Keep the trader's stop exactly 3% below actual next-bar-open entry in all cases.
  This is the only fixed trading parameter.

Translate the JSON into concise trader-facing language while preserving learned
values and the abstention reason. This is structural evidence, not financial advice.
