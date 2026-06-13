# Data Reference — Parquet Market Data

Read-only. Run everything from the repo root with `.venv/bin/python`. Polars 1.41.2.

## Layout

```
market-data/
  prices/<interval>/<SYMBOL>.parquet   # OHLCV per symbol
  metadata/symbols.csv                 # universe list (header: symbol)
```

- Stored intervals: `1d`, `1h`. Symbols Yahoo-style, e.g. `ABSLAMC.NS`.
- One file per symbol per interval. Filename = `<SYMBOL>.parquet`.

## Prices schema

`symbol(str), trade_timestamp(Datetime[us, Asia/Kolkata]), open, high, low, close(f64), volume(i64)`

- `trade_timestamp` is timezone-aware `Asia/Kolkata`. Keep any timestamp literal
  tz-aware so it stays a pushdown-eligible predicate.
- 1d history is short for many names (min 36, median 381, max 1593 bars). Always
  check row count before trusting any statistic.

## Lazy scan idiom (pushdown)

```python
import polars as pl

lf = (
    pl.scan_parquet("market-data/prices/1d/ABSLAMC.NS.parquet")
    .select("trade_timestamp", "open", "high", "low", "close", "volume")
    .sort("trade_timestamp")
)
df = lf.collect()  # one collect per question
print(df.schema, df.height)
```

- Start from `scan_parquet`, never `read_parquet`. `.select(...)` early (projection
  pushdown); `.filter(...)` right after the scan (predicate pushdown).
- Whole-universe scans: pass a glob `market-data/prices/1d/*.parquet` to one
  `scan_parquet` and `group_by` — never loop `read_parquet` per file.
- Use `collect(engine="streaming")` for whole-universe aggregations.

## Deriving a non-stored timeframe

Only `1d` and `1h` are stored. For weekly/monthly, derive from `1d` and disclose it
as on-demand:

```python
wk = (
    df.group_by_dynamic("trade_timestamp", every="1w", closed="left")
      .agg(pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
           pl.col("close").last(), pl.col("volume").sum())
)
```

Note: 381 daily bars → only ~80 weekly bars. Derived long timeframes often have too
few bars to mine pullbacks — say so.
