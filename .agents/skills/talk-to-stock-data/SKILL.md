---
name: talk-to-stock-data
description: Query and analyze the project's local OHLCV and precalculated indicator Parquet data conversationally with Polars. Use for stock rankings, returns, comparisons, technical screens, EMA, RSI, ATR, MACD, ADX, bands, drawdowns, volume analysis, date-range summaries, or any request involving market-data prices or indicators at a stored or derived timeframe.
---

# Talk To Stock Data

Analyze `market-data/prices` and `market-data/indicators` using Polars expressions
and lazy Parquet scans.
Treat all operations as read-only unless the user explicitly requests an output artifact.

## Mandatory Rules

- Use Polars for every data read, transformation, aggregation, and calculation.
- Use `pl.scan_parquet`, lazy expressions, predicate pushdown, projection pushdown,
  streaming-capable operations, and one final `collect()`.
- Never manually inspect rows or read files one by one to answer a data question.
- Never use Python loops to calculate per-symbol metrics.
- Prefer an exact stored interval. Otherwise derive it from the closest compatible
  stored interval with the bundled helper.
- Use precalculated indicators only for their exact stored interval. Never resample
  or join them to a derived timeframe.
- For a derived timeframe indicator request, derive OHLCV first, then calculate the
  requested indicator with Polars and clearly state that it was calculated on demand.
- State the source interval and whether the requested timeframe was derived.
- Do not silently invent missing dates, prices, symbols, or calculation semantics.
- Raise a clear error when data is absent or a timeframe cannot be derived reliably.

## Workflow

1. Interpret the requested universe, timeframe, date range, metric, ranking, and output.
2. If any choice materially changes the answer and is not inferable, ask one concise question.
3. Import `scripts/stock_frame.py`. Call `load_prices()` for price-only analysis,
   `load_indicators()` for indicator-only analysis, or
   `load_prices_with_indicators()` for exact-interval combined analysis.
4. Add filters and calculations to the returned `LazyFrame`.
5. Keep the query lazy until one final `collect()`.
6. Verify result dates, symbol count, and row count with Polars expressions.
7. Present a concise table, followed by calculation semantics and data provenance.

Read [references/data-contract.md](references/data-contract.md) when handling timeframe
resolution, resampling, indicator semantics, return semantics, or market-session
boundaries.

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

For exact-interval price and indicator analysis:

```python
from stock_frame import load_prices_with_indicators

frame = load_prices_with_indicators(
    interval="1d",
    prices_root="market-data/prices",
    indicators_root="market-data/indicators",
    symbols=["TCS.NS", "INFY.NS"],
    start=None,
    end=None,
)
result = frame.filter(pl.col("close") > pl.col("ema_200")).collect()
```

## Calculation Rules

- Interpret "last N trading periods" as the latest N available observations per symbol.
- For return across N observations, calculate `last_close / first_close - 1`.
- Distinguish observations from transitions when wording makes the difference material.
- Treat stored prices as adjusted for corporate actions.
- Treat volume as Yahoo-provided and not independently adjusted by the application.
- Treat precalculated indicators as adjusted-price indicators.
- Precalculated indicator files start only after full 365-calendar-day history and
  contain no partial/null rows. Disclose symbols excluded because indicator files or
  requested lookback rows are absent.
- Prefer precalculated columns over recalculation when exact-interval files exist.
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
- whether indicators were precalculated or calculated on demand;
- requested result table.

Do not dump full datasets or implementation details unless requested.
