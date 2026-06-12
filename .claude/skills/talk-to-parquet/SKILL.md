---
name: talk-to-parquet
description: Query the project's Parquet market data (OHLCV prices and precalculated indicators) with Polars lazy scans. Use for any question about stock prices, returns, rankings, comparisons, screens, volume, or indicator values (EMA, RSI, ATR, MACD, ADX, Bollinger bands, ROC, OBV) stored under market-data/.
---

# Talk To Parquet

Answer data questions against this repository's Parquet files using Polars. Treat all
analysis as read-only. Run every query from the repository root with `.venv/bin/python`.

## Data Layout

```
market-data/
  prices/<interval>/<SYMBOL>.parquet       # OHLCV per symbol
  indicators/<interval>/<SYMBOL>.parquet   # precalculated indicators per symbol
  metadata/symbols.csv                     # symbol universe
```

- Stored intervals: `1d` and `1h`.
- Symbols are Yahoo-style (e.g. `CAPLIPOINT.NS`). One file per symbol per interval.
- Timestamps are timezone-aware `Asia/Kolkata` in column `trade_timestamp`.

### Prices schema

`symbol, trade_timestamp, open, high, low, close, volume`

### Indicators schema

`symbol, trade_timestamp, ema_10, ema_20, ema_50, ema_100, ema_200, volume_ema_20,
relative_volume_20, rsi_14, atr_14, atr_percent_14, macd_12_26, macd_signal_9,
macd_histogram, adx_14, plus_di_14, minus_di_14, band_upper_20_2, band_middle_20,
band_lower_20_2, band_width_20_2, roc_20, obv, trailing_365d_high, trailing_365d_low,
distance_from_365d_high_percent`

## Mandatory Rules

- Use Polars for every read, transformation, aggregation, and calculation.
- Use `pl.scan_parquet` lazy scans with predicate and projection pushdown; keep the
  query lazy until one final `collect()`.
- Never inspect rows manually or loop over files in Python to compute per-symbol
  metrics; scan with a glob (`market-data/prices/1d/*.parquet`) and use `group_by`.
- Use precalculated indicator files only at their exact stored interval; never resample
  or join them onto a derived timeframe. For another timeframe, derive OHLCV with
  `group_by_dynamic` first, calculate the indicator with Polars expressions, and state
  that it was calculated on demand.
- Raise a clear error when a symbol, interval, or date range is unavailable. Never
  invent missing data, silently substitute another symbol, or shorten the requested
  range without disclosing it.
- Treat prices as adjusted for corporate actions; volume is Yahoo-provided. Indicator
  files start only after a full 365-calendar-day warm-up and contain no null rows —
  disclose symbols excluded for insufficient lookback.
- Compare symbols over a shared date range when a direct comparison is requested. Sort
  deterministically with `symbol` as the final tie-breaker.

## Performance Rules

Apply all of these in every query — they are the difference between scanning megabytes
and scanning gigabytes.

### Lazy execution and pushdown

- Always start from `pl.scan_parquet`, never `pl.read_parquet`. Lazy scans let the
  optimizer push work into the Parquet reader.
- **Projection pushdown**: name only the columns you need as early as possible
  (`.select(...)` right after the scan). Parquet is columnar — unselected columns are
  never read from disk.
- **Predicate pushdown**: put `.filter(...)` directly after the scan. Filters on
  `trade_timestamp` and `symbol` skip entire row groups before decompression.
- Keep timestamp filter literals timezone-aware (`Asia/Kolkata`) so the comparison
  stays a pushdown-eligible predicate instead of forcing a cast over the column.
- One final `collect()` per question. Intermediate `collect()` calls materialize the
  whole frame in memory and discard the optimized plan.
- Verify pushdown when in doubt: `lf.explain()` must show the filter and projection
  inside the `Parquet SCAN` node, not above it.

### Scanning many files

- Scan a glob (`market-data/prices/1d/*.parquet`) or list of paths in one
  `scan_parquet` call — Polars reads files in parallel and unions lazily. Never loop
  `read_parquet` per file and `concat` eagerly.
- When only some symbols are needed, pass their exact file paths to `scan_parquet`
  instead of glob + `filter(symbol)` — skips opening unrelated files entirely.

### Memory footprint

- Use `collect(engine="streaming")` for whole-universe scans and large aggregations —
  processes in batches instead of materializing all rows at once.
- Pass `low_memory=True` to `scan_parquet` when memory pressure matters more than speed.
- Cast `symbol` to `pl.Categorical` before joins/group_bys on large multi-symbol frames
  to shrink string memory and speed up comparisons.
- Take `head`/`tail`/`slice` on the LazyFrame, not after collect — slice pushdown
  limits what is materialized.
- Drop columns from the result before `collect()`, never after.

### Expressions over Python

- Never use `map_elements` / `map_rows` or Python loops over rows — single-threaded
  Python UDFs destroy parallelism. Express logic with native expressions
  (`pl.when/then`, `rolling_*`, `over`, `cum_*`, `diff`, `shift`, `pct_change`).
- Put independent expressions in one `with_columns`/`agg` context — Polars runs
  expressions within a context in parallel.
- Use window functions (`expr.over("symbol")`) for per-symbol calculations on a
  multi-symbol frame instead of group-loop-concat.
- Duplicate subexpressions are fine — common-subexpression elimination computes them
  once; do not pre-collect to "reuse" a result.

### Sorting and joins

- Avoid full-frame sorts unless the answer requires global order. For "top N by X" use
  `top_k(n, by=...)` / `bottom_k` — O(n) instead of O(n log n) and no full
  materialization.
- Per-symbol files are already in timestamp order: mark with
  `.set_sorted("trade_timestamp")` after a single-file scan to unlock fast
  `group_by_dynamic`, `rolling`, and `join_asof` without a re-sort. Do not claim
  sortedness on a multi-file glob scan — the union is not globally sorted.
- Prefer `join(how="semi")` / `"anti"` to filter one frame by membership in another —
  cheaper than an inner join that drags in columns you discard.
- Filter both sides before a join, not after.

### Diagnostics

- `lf.explain()` — confirm pushdowns and plan shape before running anything heavy.
- `lf.profile()` — per-node timings when a query is unexpectedly slow.
- Avoid repeated `collect_schema()` calls; capture it once if needed.

## Query Patterns

Single symbol, prices joined with exact-interval indicators:

```python
import polars as pl

frame = (
    pl.scan_parquet("market-data/prices/1d/CAPLIPOINT.NS.parquet")
    .select("symbol", "trade_timestamp", "close")
    .join(
        pl.scan_parquet("market-data/indicators/1d/CAPLIPOINT.NS.parquet")
        .select("symbol", "trade_timestamp", "ema_200"),
        on=["symbol", "trade_timestamp"],
        how="inner",
    )
    .set_sorted("trade_timestamp")
)
result = frame.filter(pl.col("close") > pl.col("ema_200")).collect()
```

Universe scan across all symbols:

```python
result = (
    pl.scan_parquet("market-data/prices/1d/*.parquet")
    .select("symbol", "trade_timestamp", "close")
    .group_by("symbol")
    .agg(
        ret=pl.col("close").sort_by("trade_timestamp").last()
        / pl.col("close").sort_by("trade_timestamp").first()
        - 1,
        last_ts=pl.col("trade_timestamp").max(),
    )
    .top_k(20, by="ret")
    .sort(["ret", "symbol"], descending=[True, False])
    .collect(engine="streaming")
)
```

Derived timeframe (e.g. weekly from daily):

```python
weekly = (
    pl.scan_parquet("market-data/prices/1d/CAPLIPOINT.NS.parquet")
    .set_sorted("trade_timestamp")
    .group_by_dynamic("trade_timestamp", every="1w", group_by="symbol")
    .agg(
        open=pl.col("open").first(),
        high=pl.col("high").max(),
        low=pl.col("low").min(),
        close=pl.col("close").last(),
        volume=pl.col("volume").sum(),
    )
    .collect()
)
```

## Output

Report with every answer:

- requested timeframe, source interval, and whether it was derived;
- latest included timestamp or the analyzed date range;
- the calculation formula and lookback interpretation;
- exclusions caused by insufficient data;
- whether indicators came precalculated or were calculated on demand;
- a concise result table — never a full data dump.
