# Strategy Bake-Off & Optimizer — Design Spec

**Date:** 2026-06-14
**Status:** Approved design, pending plan
**Author:** brainstormed with user (rajverma)

## 1. Purpose

Find, by backtest, **the strategy with the best profit-per-drawdown** over the
project's NSE daily stock data. Test multiple strategy families, optimize each
independently, compare all out-of-sample, and report a ranked table with the
concrete numbers the user asked for: **max drawdown, winrate, stoploss, target,
yearly profit (CAGR)**.

The single end goal: hand the user the strategy that delivers the best
**profit + drawdown** balance, with honest (non-overfit) numbers.

## 2. Objective Function

Primary ranking metric: **Calmar ratio = CAGR ÷ MaxDrawdown** (return per unit
of worst peak-to-trough equity drop). This rewards profit and low drawdown
together, matching the user's "min drawdown, still profitable" intent.

Reported alongside (never as the sole ranker): winrate, expectancy, avg win/loss,
trade count, exposure.

## 3. Data

- **Universe:** the 175-symbol watchlist in `market-data/metadata/symbols.csv`
  (the user's actual watchlist).
- **Backtest timeframe:** **daily** (`market-data/prices/1d/*.parquet`) +
  **weekly trend filter** resampled from daily. Full multi-year history
  (114 symbols reach back to ≤2016).
- **Indicators:** read precalculated from `market-data/indicators/1d/*.parquet`
  (EMA 10/20/50/100/200, RSI14, ATR14, ATR%, MACD, ADX, ±DI, Bollinger 20/2,
  ROC20, OBV, trailing_365d_high/low, distance_from_365d_high_percent,
  relative_volume_20). **Do not recompute** — reuse what exists.
- **Hourly (`1h`):** EXCLUDED from the backtest. Universe-wide it starts only
  2024-12-02 (~18 months, single market regime) — too short for a valid
  train/test optimization. Reserved for a future live entry-timing layer, not
  this deliverable.

Joining: prices (OHLCV) joined to indicators on `(symbol, trade_timestamp)`.
Weekly frame built by Polars `group_by_dynamic` on a 1-week window per symbol.

## 4. Validation (anti-overfit — non-negotiable)

- **Train (in-sample):** 2016-01-01 → 2022-12-31. Grid-search params here only.
- **Test (out-of-sample):** 2023-01-01 → 2026-06-12. Chosen params run here;
  **these are the headline numbers.**
- Report train AND test side by side. A large train→test degradation is flagged
  as an overfit warning in the output.
- Params are selected per strategy by best **train** Calmar, then frozen for test.

## 5. Architecture

One shared engine, pluggable entry rules (DRY). Only the entry signal differs
between strategies; sizing, exits, costs, and metrics are identical for all.

```
src/stock_data/backtest/
  __init__.py
  data.py        # load+join prices/indicators, build weekly frame, slice dates
  signals.py     # entry-rule functions (one per strategy), return entry-bar bool
  engine.py      # portfolio simulation loop, exits, costs, equity curve
  metrics.py     # CAGR, MaxDD, Calmar, winrate, expectancy, avg W/L, etc.
  optimize.py    # per-strategy grid search over (SL%, target%, K) on train
  compare.py     # run best params on test, rank by Calmar, build table
  report.py      # render comparison table + per-strategy detail (markdown/CSV)
  cli.py         # typer entrypoint: run bake-off end to end
```

Each file stays <800 lines; each function <80 lines, single responsibility.

### 5.1 Engine (shared)

- **Portfolio:** equal-weight **K slots**. Capital ÷ K per slot, one stock per
  slot, max K concurrent positions. Long-only, no leverage.
- **Entry execution:** on a bar where a strategy's signal fires AND a slot is
  free, enter next bar at open (avoid look-ahead). If more signals than free
  slots, rank candidates by a fixed, declared tie-break (e.g. higher
  relative_volume_20) and fill until slots full.
- **Exits (per position), checked each bar:**
  1. **Stoploss:** intrabar low ≤ entry × (1 − SL%) → exit at stop price.
  2. **Target:** intrabar high ≥ entry × (1 + target%) → exit at target price.
  3. **Time-stop:** held ≥ 40 trading days → exit next open.
  - If both SL and target gap through on the same bar, assume **stoploss first**
    (conservative).
- **Costs:** 0.30% round-trip (brokerage + STT + slippage, India delivery),
  charged on entry+exit notional.
- **Output:** trade ledger + daily equity curve.

### 5.2 Entry signals (the bake-off roster)

All long-only, evaluated on daily bars, all gated by the weekly uptrend filter
unless noted. Chosen for orthogonal edges.

1. **Pullback-buy** — weekly uptrend (weekly close > weekly EMA30 and rising);
   daily EMA10>EMA20>EMA50; price dipped to the EMA20–EMA50 zone with RSI14
   cooling; entry when close reclaims above EMA10 (bounce). *Trend continuation.*
2. **EMA-stack trend-follow** — fresh bullish alignment EMA10>EMA20>EMA50 that
   was not aligned in the prior N bars; entry on the alignment/reclaim bar.
   *Trend entry.*
3. **52-week-high breakout** — close breaks above trailing_365d_high with
   relative_volume_20 > threshold (volume expansion). *Momentum/volume.*
4. **Bollinger lower-band mean-reversion** — weekly uptrend; daily close tags/closes
   below band_lower_20_2, then turns up; target the band middle. *Counter-trend.*
5. **MACD + ADX momentum** — MACD line crosses above signal while ADX14 > 25
   (trend strength present). *Momentum + strength.*
6. **RSI dip-reclaim** — weekly uptrend; RSI14 dips below 40 then crosses back
   above 50. *Oscillator dip-buy.*

Signal functions take the joined per-symbol frame and return a boolean entry
column. Thresholds that are intrinsic to a strategy (e.g. RSI 40/50, ADX 25)
are fixed constants declared in `signals.py`, **not** tuned — only SL%, target%,
K are tuned, to keep the grid small and overfitting low.

### 5.3 Optimizer

Per strategy, grid-search:
- **SL%** ∈ {3, 4, 5, 6, 8}
- **target%** ∈ {6, 9, 12, 15, 20}
- **K (slots)** ∈ {5, 8, 10, 15}

= 100 combinations per strategy, 6 strategies = 600 train backtests. Pick the
combo with best **train Calmar** per strategy (tie-break: higher CAGR).

### 5.4 Comparator + report

- Run each strategy's frozen best params on the **test** window.
- Rank strategies by **test Calmar**.
- Emit a comparison table (markdown + CSV) with, per strategy, **train and test**
  columns: max drawdown, winrate, stoploss%, target%, K, CAGR (yearly profit),
  Calmar, expectancy (avg R), avg win%, avg loss%, #trades, % time in market.
- Name the **winner** (best test profit+drawdown) explicitly, with its exact
  SL%, target%, K.

## 6. Deliverables

1. Working bake-off CLI: `stock-data backtest-bakeoff` that runs end to end and
   writes the report.
2. A report file written to `market-data/backtest/bakeoff-<run-date>.md` (and a
   sibling `.csv`) with the ranked comparison and the recommended strategy + its
   numbers. The run date is passed in explicitly (no implicit clock default).
3. Tests for engine correctness (a hand-checked trade, metric math, exit
   precedence) and signal sanity.

## 7. Success Criteria

- Each strategy produces a complete metric set on both train and test.
- Numbers are out-of-sample (test window never seen by the optimizer).
- The report ranks all 6 and states the winner with concrete SL%, target%, K,
  max drawdown, winrate, CAGR.
- No look-ahead: entries fill on the bar AFTER the signal; exits use that bar's
  own high/low.
- Costs and the survivorship caveat are applied/stated, not omitted.

## 8. Honest Caveats (stated in the report)

- **Survivorship bias:** universe = today's 175-symbol watchlist (already
  survivors). Real-world results will be worse. Stated, not hidden.
- **Long-only, no hedge:** drawdown will spike in broad declines (e.g. 2022).
- **Single train/test split** (not walk-forward): one out-of-sample estimate,
  not a distribution. Adequate first cut; walk-forward is a future upgrade.
- **No position-level risk normalization:** equal-weight slots mean a volatile
  stock risks more rupees than a calm one per slot (user's chosen model).

## 9. Out of Scope

- Hourly/intraday backtest (data too short).
- Shorting, options, leverage, pyramiding.
- Walk-forward optimization (future upgrade).
- Live/broker execution and the 1h entry-timing layer (future, separate work).
- Tuning strategy-intrinsic thresholds (kept fixed to limit overfit).

## 10. Tech & Conventions

- Python 3.12, Polars, Typer, pydantic; reuse `src/stock_data` conventions
  (`from __future__ import annotations`, logging via `logging_config`).
- Files <800 lines, functions <80 lines, single responsibility.
- Fail-fast: missing data, empty windows, or zero-trade strategies raise clear
  exceptions — no silent defaults or fallback values.
- Detailed logging through the existing logger.
