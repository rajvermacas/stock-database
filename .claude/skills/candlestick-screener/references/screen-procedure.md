# Screen Procedure — Universe Scan → Two-Section Report

Inputs from the grammar step: a Polars boolean `mask` (the pattern, addressed by lag
`L(col,k)`) and `WIN_DIR` (+1 bullish, −1 bearish). This file turns those into the report.
Run from the repo root with `.venv/bin/python`. Read-only against `market-data/`.

## Step 0 — Resolve the timeframe (fail fast)

`INTERVAL` is the user-supplied timeframe. Never default it.

- **`1d` or `1h`** → on disk: `market-data/prices/<INTERVAL>/*.parquet`. Use directly.
- **Coarser than daily** (`1wk`/`1mo`/`3mo`, or "weekly"/"monthly") → **derive from `1d`**
  with `group_by_dynamic` (accurate for OHLC, instant, no network). Map the Yahoo code to
  a Polars `every`: `1wk→"1w"`, `1mo→"1mo"`, `3mo→"3mo"`. Disclose "derived from 1d".
  ```python
  EVERY = "1w"   # from the mapping above
  prices = (
      pl.scan_parquet("market-data/prices/1d/*.parquet")
      .select("symbol", "trade_timestamp", "open", "high", "low", "close")
      .sort("symbol", "trade_timestamp")
      .group_by_dynamic("trade_timestamp", every=EVERY, group_by="symbol")
      .agg(open=pl.col("open").first(), high=pl.col("high").max(),
           low=pl.col("low").min(),   close=pl.col("close").last())
      .sort("symbol", "trade_timestamp")
  )   # a LazyFrame; feed into Step 1 in place of the scan
  ```
- **Sub-daily and not `1h`** (`1m,2m,5m,15m,30m,90m`) → cannot be derived. **Fetch** it
  per `../pullback-finder/references/data.md` ("Fetching a missing timeframe"), respecting
  Yahoo history caps, then read the new files. Fail fast on a failed fetch. Disclose
  "fetched".

Disclose the analyzed date range and how many symbols were scanned. Note that per-stock
history varies (1d median ≈ 381 bars); a coarse interval shrinks bar counts sharply.

## Step 1 — One pass: forward outcome + per-stock table

The **sort is mandatory** before any `shift().over()`. The current (latest) bar of each
symbol has a null forward return and is excluded from the *stats* — but is still seen by
the *live* detector in Step 3.

```python
import polars as pl

HORIZON = 1   # next immediate bar; the user may ask for N
GLOB = f"market-data/prices/{INTERVAL}/*.parquet"   # or the derived LazyFrame from Step 0

df = (
    pl.scan_parquet(GLOB)
    .select("symbol", "trade_timestamp", "open", "high", "low", "close")
    .sort("symbol", "trade_timestamp")
    .with_columns(fwd_close=pl.col("close").shift(-HORIZON).over("symbol"))
    .with_columns(ret_fwd=pl.col("close").shift(-HORIZON).over("symbol") / pl.col("close") - 1.0)
    .collect()
)

def L(col, k):
    return pl.col(col).shift(k).over("symbol")

# ---- paste the pattern mask + WIN_DIR built from candle-grammar.md here ----
# mask = ...
# WIN_DIR = 1

r        = pl.col("ret_fwd") * WIN_DIR          # direction-adjusted outcome
win_e    = r > 0                                # a "win" (moved the expected way)
loss_e   = r < 0                                # a "loss" (moved against)
graded   = df.with_columns(pat=mask)
resolved = graded.filter(pl.col("ret_fwd").is_not_null())   # has a forward bar

# Baselines (same direction as the pattern, so lift is comparable)
uni_win  = resolved.select(win_e.mean()).item()             # universe baseline win-rate
own_base = resolved.group_by("symbol").agg(
    base_win=win_e.mean(), base_n=pl.len())

# Per-stock pattern stats (past, resolved occurrences only)
hits = resolved.filter(pl.col("pat"))
per = (
    hits.group_by("symbol").agg(
        n=pl.len(),
        wins=win_e.sum(),
        losses=loss_e.sum(),
        win_pct=win_e.mean(),
        avg_ret=pl.col("ret_fwd").mean(),
        med_ret=pl.col("ret_fwd").median(),
        last_hit=pl.col("trade_timestamp").max(),
    )
    .join(own_base, on="symbol", how="left")
    .with_columns(lift=pl.col("win_pct") - pl.col("base_win"))
)
pooled_win = hits.select(win_e.mean()).item() if hits.height else None
```

`win_pct` is direction-adjusted (fraction moving the pattern's expected way). `avg_ret`
and `med_ret` are the **raw** next-bar returns (negative = price fell), so they read
naturally for both bullish and bearish patterns. Say this in the report.

## Step 2 — Section A: edge ranking (with the occurrence gate)

A high win-rate on a tiny sample is noise. Gate, then rank.

```python
MIN_N, TOP_N = 10, 20

def rank_at(min_n):
    return (per.filter(pl.col("n") >= min_n)
               .sort(["win_pct", "n", "avg_ret", "symbol"],
                     descending=[True, True, True, False]))

ranking = rank_at(MIN_N)
note = None
if ranking.height < TOP_N:                       # adaptive: too few qualified
    for lower in (8, 5, 3):
        if rank_at(lower).height >= TOP_N or lower == 3:
            ranking, note = rank_at(lower), f"threshold lowered to n>={lower} (only "\
                f"{rank_at(MIN_N).height} stocks reached n>={MIN_N})"
            MIN_N = lower
            break
top = ranking.head(TOP_N)
```

**Adaptive-gate judgment** (state whatever you choose):
- Enough stocks at `n>=10` → use it; this is the credible default.
- Too few → lower the gate to 8/5/3 and **disclose** that the win-rates are now noisier.
- The pattern is so rare nothing reaches `n>=3` (typical of a Strict definition) → there
  is **no rankable Section A**. Report **pooled-only**: total signals, `pooled_win`,
  `uni_win`, average move — and say the pattern is too rare per stock to rank. Offer to
  rerun at the Standard strictness rung (`candle-grammar.md`).

Always print, above the table: pattern + exact definition, `INTERVAL` + source, universe
size, date range, `uni_win` (baseline), `pooled_win`, the gate used. Table columns:
rank, symbol, n, wins, losses, win %, avg next-bar, median, **lift vs own baseline**.

## Step 3 — Section B: live signals (printing on the latest bar)

A signal is live when `mask` is true on a symbol's most recent bar. That bar has no
forward outcome yet, so it is absent from `per`; join `per` to attach the stock's *past*
reliability.

```python
last_ts = graded.group_by("symbol").agg(last_ts=pl.col("trade_timestamp").max())
live = (
    graded.filter(pl.col("pat"))
          .join(last_ts, on="symbol")
          .filter(pl.col("trade_timestamp") == pl.col("last_ts"))      # mask true on the last bar
          .select("symbol", pl.col("trade_timestamp").alias("signal_bar"))
          .join(per.select("symbol", "n", "win_pct", "avg_ret", "med_ret", "lift"),
                on="symbol", how="left")
          .with_columns(
              confidence=pl.when(pl.col("n").is_null()).then(pl.lit("none — first ever"))
                          .when(pl.col("n") < MIN_N).then(pl.lit("low"))
                          .otherwise(pl.lit("ok")))
          .sort(["win_pct", "n"], descending=[True, True], nulls_last=True)
)
```

Report the live table: symbol, signal_bar date, historical n, win %, avg, lift,
confidence. If `live` is empty, say so plainly — "no stock prints this pattern on its
latest bar" is a valid, common result (especially for strict/rare patterns), not a
failure. Flag any live signal whose history is thin (`confidence != "ok"`): the pattern
is firing, but this stock has too little past evidence to trust the rate.

## Step 4 — Report shape

Two clearly separated sections under one header:

```
## <Pattern> — <INTERVAL> screen
<definition in words> · win = next bar <up|down> · horizon <H> bar(s)
Universe: <N> symbols · range <start>–<end> · source <on-disk|derived from 1d|fetched>
Baseline next-bar <up|down> rate: <uni_win> · Pooled after pattern: <pooled_win> (<total hits>)
Occurrence gate: n>=<MIN_N> (<note if lowered>)

### A. Edge ranking (top <TOP_N>)
<table: rank, symbol, n, wins, losses, win%, avg, median, lift>

### B. Printing on the latest bar
<table: symbol, signal_bar, n, win%, avg, lift, confidence>   — or "none"

<disclosures: on-demand calc; exclusions; any strictness/threshold caveats>
```

Keep tables concise (top-N only). Follow the SKILL.md output contract for disclosures.

## Failure & edge cases

- **No timeframe** → ask; do not proceed.
- **Unresolvable interval** (fetch fails / not a real Yahoo interval) → clear error, stop.
- **Zero occurrences universe-wide** → report it; do not fabricate or widen silently.
- **Pattern too rare to rank** → pooled-only Section A (Step 2), still emit Section B.
- **Thin per-stock history** → keep it, but flag confidence in both sections.
- Never write scratch files into the repo; the report is the deliverable.
