---
name: talk-to-stock-data
description: Query and analyze the project's local OHLCV Parquet data conversationally with Polars. Use for stock rankings, returns, comparisons, screens, indicators, drawdowns, volume analysis, date-range summaries, or any request involving market-data/prices at a stored or derived timeframe.
---

# Talk To Stock Data

Analyze `market-data/prices` using Polars expressions and lazy Parquet scans.
Treat all operations as read-only unless the user explicitly requests an output artifact.

## Mandatory Rules

- Use Polars for every data read, transformation, aggregation, and calculation.
- Use `pl.scan_parquet`, lazy expressions, predicate pushdown, projection pushdown,
  streaming-capable operations, and one final `collect()`.
- Never manually inspect rows or read files one by one to answer a data question.
- Never use Python loops to calculate per-symbol metrics.
- Prefer an exact stored interval. Otherwise derive it from the closest compatible
  stored interval with the bundled helper.
- State the source interval and whether the requested timeframe was derived.
- Do not silently invent missing dates, prices, symbols, or calculation semantics.
- Raise a clear error when data is absent or a timeframe cannot be derived reliably.

## Workflow

1. Interpret the requested universe, timeframe, date range, metric, ranking, and output.
2. If any choice materially changes the answer and is not inferable, ask one concise question.
3. Import `scripts/stock_frame.py` and call `load_prices()` with all known symbol and
   date filters so Polars pushes them into the scan.
4. Add filters and calculations to the returned `LazyFrame`.
5. Keep the query lazy until one final `collect()`.
6. Verify result dates, symbol count, and row count with Polars expressions.
7. Present a concise table, followed by calculation semantics and data provenance.

Read [references/data-contract.md](references/data-contract.md) when handling timeframe
resolution, resampling, return semantics, or market-session boundaries.

## Query Pattern

Run analysis from the repository root:

```python
import sys

import polars as pl

sys.path.insert(0, ".agents/skills/talk-to-stock-data/scripts")
from stock_frame import load_prices

prices, resolution = load_prices(
    requested_interval="1d",
    prices_root="market-data/prices",
    symbols=["TCS.NS", "INFY.NS"],
    start=None,
    end=None,
)
result = (
    prices
    .group_by("symbol")
    .agg(pl.col("close").last())
    .collect()
)
```

Use `resolution` to report the requested interval, source interval, and derivation status.

## Calculation Rules

- Interpret "last N trading periods" as the latest N available observations per symbol.
- For return across N observations, calculate `last_close / first_close - 1`.
- Distinguish observations from transitions when wording makes the difference material.
- Use adjusted-return language only if adjusted-price columns exist. Current data is raw OHLCV.
- Compare symbols over a shared date range when the user asks for a direct comparison.
- Exclude symbols lacking the required lookback and disclose the exclusion rule.
- Sort deterministically, adding `symbol` as a final tie-breaker.
- Select only required columns after loading when using an exact stored interval.
- Avoid `collect_schema()`, repeated `collect()`, and full-frame sorts unless required.

## Output

Include:

- requested and source timeframe;
- latest included timestamp or analyzed date range;
- calculation formula and lookback interpretation;
- exclusions caused by insufficient data;
- requested result table.

Do not dump full datasets or implementation details unless requested.
