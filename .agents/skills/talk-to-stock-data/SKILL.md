---
name: talk-to-stock-data
description: Query and analyze the project's local OHLCV and precalculated indicator Parquet data conversationally with Polars, acquiring a requested stock through the project's CLI when its required local data is absent. Use for stock rankings, returns, comparisons, technical screens, EMA, RSI, ATR, MACD, ADX, bands, drawdowns, volume analysis, date-range summaries, or any request involving market-data prices or indicators at a stored or derived timeframe.
---

# Talk To Stock Data

Analyze `market-data/prices` and `market-data/indicators` using Polars expressions
and lazy Parquet scans.
Treat analysis as read-only except for the mandatory missing-stock acquisition workflow
or when the user explicitly requests an output artifact.

## Mandatory Rules

- Use Polars for every market-data read, transformation, aggregation, and calculation.
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
- When required data for a requested stock is absent, update `config/stock-data.toml`,
  acquire it with the command documented in `COMMANDS.md`, verify it, then resume the
  user's requested analysis.
- Leave `config/stock-data.toml` changed after acquisition.
- Raise a clear error when acquisition fails or a timeframe cannot be derived reliably.

## Workflow

1. Interpret the requested universe, timeframe, date range, metric, ranking, and output.
2. If any choice materially changes the answer and is not inferable, ask one concise question.
3. Determine the required source interval and price history for each explicitly requested
   stock. Check whether the relevant local Parquet data exists and covers the request.
4. If required stock data is absent, follow [Acquire Missing Stock Data](#acquire-missing-stock-data).
5. Import `scripts/stock_frame.py`. Call `load_prices()` for price-only analysis,
   `load_indicators()` for indicator-only analysis, or
   `load_prices_with_indicators()` for exact-interval combined analysis.
6. Add filters and calculations to the returned `LazyFrame`.
7. Keep the query lazy until one final `collect()`.
8. Verify result dates, symbol count, and row count with Polars expressions.
9. Present a concise table, followed by calculation semantics and data provenance.

Read [references/data-contract.md](references/data-contract.md) when handling timeframe
resolution, resampling, indicator semantics, return semantics, or market-session
boundaries.

## Acquire Missing Stock Data

Use this only for explicitly requested stocks whose required local price data is absent
or does not cover the requested analysis. Do not download an entire ranking or screening
universe merely because some symbols lack data.

1. Read repository-root `COMMANDS.md` before running any acquisition command.
2. Select a Yahoo-supported source interval that can satisfy the requested timeframe.
   Prefer the exact requested interval. For a derived timeframe, use the closest
   compatible native source defined by the data contract. Ask when no source interval
   can be inferred without materially changing the analysis.
3. Edit repository-root `config/stock-data.toml`:
   - set `yahoo.interval` to the selected source interval;
   - set `download.initial_start_date` early enough for the requested date range and
     lookback, including indicator warm-up history when indicators are required;
   - preserve all unrelated fields and leave the resulting values in place.
4. From the repository root, run the single-symbol command documented in `COMMANDS.md`:

```bash
uv run stock-data --config config/stock-data.toml update-symbol <SYMBOL>
```

5. Require exit code `0`. On failure, report the command's symbol-specific error and stop.
6. Verify the expected price Parquet exists at
   `market-data/prices/<source-interval>/<SYMBOL>.parquet` and use one lazy Polars query
   to confirm the required date range or lookback is available. If exact-interval
   precalculated indicators are required, also verify their availability.
7. If verification fails, raise a clear error describing the missing interval, dates,
   lookback, or indicators. Do not answer from a different stock or silently shorten the
   requested analysis.
8. Resume the normal workflow and answer the user's original prompt.

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
