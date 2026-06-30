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

## Multi-timeframe — any interval is allowed

The skill works on ANY Yahoo interval the user asks for, not just the two stored
on disk. Supported: `1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo`.
Resolve the data for the requested interval like this:

1. If `market-data/prices/<interval>/<SYMBOL>.parquet` exists and is current → use it.
2. Else **fetch it** with the project pipeline (see below), then read the new file.

`market-data/prices/` is gitignored — fetching is the intended way to grow the data
lake and never dirties git. (This is data, not the scratch files the skill is
forbidden to write.)

## Fetching a missing timeframe (see COMMANDS.md)

Interval is set in a config TOML; there is no CLI interval flag. Reuse the repo
config when the interval matches one it already targets, otherwise write a throwaway
config to `/tmp` (absolute paths, indicators off since the skill computes its own):

- `1h` → `.venv/bin/stock-data --config config/stock-data-1h.toml update-symbol SYMBOL`
- `1d` → `.venv/bin/stock-data --config config/stock-data-1d.toml update-symbol SYMBOL`
- any other interval → write `/tmp/pf-<interval>.toml` (keep `[indicators] enabled =
  false`, see note below):

```toml
[paths]
data_dir = "/workspaces/stock-database/market-data"
symbols_file = "/workspaces/stock-database/market-data/metadata/symbols.csv"

[download]
initial_start_date = "<within the interval's Yahoo cap — see table>"

[yahoo]
interval = "<interval>"
batch_size = 50
timeout_seconds = 30
threads = true

[indicators]
enabled = false
```

then `.venv/bin/stock-data --config /tmp/pf-<interval>.toml update-symbol SYMBOL`.

**Why `indicators = false` (not an oversight).** This skill computes its own EMA/ATR
in Polars, so precalc indicator files are never read. More importantly, the pipeline's
indicator step needs a **365-calendar-day warm-up**; an intraday fetch (sub-hour,
capped at ~60 days) can't meet it, so with indicators enabled the run logs
`Insufficient indicator history`, writes **no** indicator file, AND exits non-zero
(`Failed`/`Successful: 0`) even though the price download was fine — which would
falsely trip the fail-fast above. Keeping indicators off makes the price fetch exit 0
cleanly. (The repo's own 1h/1d configs enable indicators because they hold enough
history; only these short on-the-fly fetches must disable it.)

**Yahoo history caps (start date MUST respect these or the download returns nothing):**

| Interval(s)                  | Max lookback |
|------------------------------|--------------|
| `1m`                         | ~7 days      |
| `2m,5m,15m,30m,90m`          | ~60 days     |
| `60m`/`1h`                   | ~730 days    |
| `1d,5d,1wk,1mo,3mo`          | full history |

For sub-hour intervals set `initial_start_date` to a recent date, e.g.
`date -d '55 days ago' +%Y-%m-%d`. Verify success: the run prints `Successful: 1`
and exit code 0. On `Failed`/non-zero, quote the Yahoo error and stop — the usual
cause is a start date older than the cap (fix it and rerun).

**Consequence to disclose:** fine intraday intervals have short history → few
pullback events → the `n_events < 5` low-confidence rule will often apply. Say so.

## Deriving a coarse timeframe (offline fallback only)

Prefer a native fetch. Only when offline (or when you already hold a finer stored
interval and explicitly want a coarse roll-up) derive it — never upsample a coarse
file into a finer one:

```python
wk = (
    df.group_by_dynamic("trade_timestamp", every="1w", closed="left")
      .agg(pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
           pl.col("close").last(), pl.col("volume").sum())
)
```

Note: 381 daily bars → only ~80 weekly bars; derived long timeframes often have too
few bars to mine pullbacks — say so.
