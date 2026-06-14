---
name: stock-screening
description: Screen the Parquet stock universe for pullback candidates using a fresh, independent parameter-learning run for every stock. Requires a user-supplied timeframe.
---

# Adaptive Stock Screening

Use the repository's `stock-pullback` engine to screen the full local Parquet
universe. The engine learns each stock independently on every run and returns one
best parameter set or abstains.

## Required Input

- Require the timeframe from the user. Never infer or default it.
- Use the complete local universe under `market-data/prices/<interval>/`.
- If the interval directory is missing, report that clearly. Do not silently swap
  timeframes or fabricate data.

## Run

```bash
stock-pullback screen \
  --prices-root market-data/prices \
  --interval <user-timeframe> \
  --output markdown
```

Use `--output json` when exact learned parameters or machine-readable evidence are
needed.

## Learning Contract

- Relearn every behavioral parameter separately for each stock on every run.
- Give the current regime the greatest weight; include older behavior only when the
  stock's own evidence supports its similarity.
- Learn price-action behavior directly from causal OHLCV features. Do not impose
  named chart patterns.
- Learn lookback, dip zone, swing sensitivity, sequence duration, target, holding
  horizon, regime similarity, prefilter, and abstention evidence from that stock.
- Keep the trader's stop exactly 3% below actual next-bar-open entry in every
  historical evaluation. This is the only fixed trading parameter.
- Treat a latest-bar match as pending entry. Never estimate its next open or stop.
- Never replace abstention with a closest match or forced pick.

## Report

Lead with ranked `BUY` and `WATCH` results, then disclose:

- excluded symbols and quality reasons;
- learned-prefilter rejection count;
- abstentions and their reasons;
- that parameters were relearned per stock;
- that entry is next-bar open and the fixed risk stop is 3% from actual entry.

Do not claim that a learned horizon, target, dip depth, or other parameter is a
universal standard. This is structural evidence, not financial advice.
