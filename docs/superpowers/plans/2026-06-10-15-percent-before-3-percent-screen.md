# 15% Before -3% Historical Analog Screen Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank the latest daily stock setups by the historical conditional frequency with which similar setups reached +15% before -3% within 30 trading sessions.

**Architecture:** Run one read-only Polars analysis from standard input, using the existing stock-frame helper to lazily scan and inner-join exact daily prices and indicators. Label historical entries from their next 30 sessions, standardize approved features, compare each latest setup with other-symbol historical setups, and rank by the outcomes of the nearest analogs.

**Tech Stack:** Python 3.12, Polars, local Parquet OHLCV and indicator data

---

## File Map

- Reference: `docs/superpowers/specs/2026-06-10-15-percent-before-3-percent-screen-design.md`
- Reference: `.agents/skills/talk-to-stock-data/scripts/stock_frame.py`
- Create or modify no production, test, or market-data files.
- Run the analysis as a temporary Python program supplied through standard input.

## Task 1: Build And Verify Historical Outcome Labels

**Files:**
- Read: `market-data/prices/1d/*.parquet`
- Read: `market-data/indicators/1d/*.parquet`

- [ ] **Step 1: Load the exact daily joined frame lazily**

Import `load_prices_with_indicators`, request interval `1d`, and select only the keys,
OHLCV fields, and approved features. Confirm the latest timestamp and joined symbol
count in the final analysis output.

- [ ] **Step 2: Create future-window barrier labels with Polars**

For each symbol-sorted historical row, examine offsets 1 through 30. For each offset:

```text
up hit   = future high >= entry close * 1.15
down hit = future low <= entry close * 0.97
```

Set the outcome to `win` when the first up-hit offset is smaller than the first down-hit
offset, `loss` when the first down-hit offset is smaller, `same_candle` when equal, and
`neither` when neither exists. Exclude rows without all 30 future sessions.

- [ ] **Step 3: Verify label semantics**

Print counts for `win`, `loss`, `same_candle`, and `neither`. Assert:

```python
assert complete_window_rows == win_rows + loss_rows + same_candle_rows + neither_rows
assert decisive_rows == win_rows + loss_rows
assert same_candle_rows >= 0
assert neither_rows >= 0
```

Expected: assertions pass and every complete-window row has exactly one label.

## Task 2: Calculate Historical Analog Probabilities

**Files:**
- Read: joined exact-daily frame from Task 1

- [ ] **Step 1: Construct approved scale-comparable features**

Calculate close-relative EMA and MACD features:

```text
ema distance = close / ema - 1
macd relative value = macd value / close
```

Use RSI, ATR percent, ADX, directional indicators, relative volume, band width, ROC, and
distance from the 365-day high directly. Fail if a required feature is missing, nonfinite,
or has zero historical standard deviation.

- [ ] **Step 2: Standardize features**

Calculate each feature's mean and population standard deviation from complete-window
historical setups. Standardize both historical setups and each symbol's latest joined
setup using those historical statistics.

- [ ] **Step 3: Calculate cross-universe distances**

Cross join every latest setup with historical setups, exclude pairs sharing a symbol,
and calculate squared Euclidean distance across all standardized features.

- [ ] **Step 4: Calculate evidence metrics**

For each latest symbol:

```text
conditional win probability = wins among nearest 100 decisive analogs / 100
decisive hit rate = decisive outcomes among nearest 100 unfiltered analogs / 100
```

Fail clearly if any latest setup has fewer than 100 other-symbol decisive analogs.

- [ ] **Step 5: Rank deterministically**

Sort descending by conditional win probability, then descending by decisive hit rate,
then ascending by symbol. Include the top 20 candidates, latest date and close, wins,
losses, decisive hit rate, analog count, and key current indicators.

## Task 3: Validate And Report The Screen

**Files:**
- Modify no files.

- [ ] **Step 1: Run consistency assertions**

Assert for every ranked stock:

```python
assert decisive_analog_count == 100
assert wins + losses == 100
assert conditional_win_probability == wins / 100
```

Expected: all assertions pass.

- [ ] **Step 2: Check data provenance**

Report requested interval `1d`, source interval `1d`, derived `False`, latest included
timestamp, joined symbol count, eligible historical setup count, and outcome counts.

- [ ] **Step 3: Present results**

Present the top-20 ranking and disclose:

- Entry is the daily close.
- The horizon is the next 30 trading sessions.
- Neither and same-candle outcomes are excluded from probability.
- Same-symbol analogs and incomplete future windows are excluded.
- Prices and indicators are raw and unadjusted.
- Results are historical conditional estimates, not guarantees.
