# Stock Data Contract

## Storage

- Root: `market-data/prices`
- Layout: `market-data/prices/<interval>/<symbol>.parquet`
- Time zone: `Asia/Kolkata`
- Data is raw, unadjusted OHLCV.

| Column | Polars type | Meaning |
|---|---|---|
| `symbol` | `String` | Yahoo-style ticker |
| `trade_timestamp` | `Datetime(..., Asia/Kolkata)` | Candle start |
| `open` | `Float64` | First price |
| `high` | `Float64` | Maximum price |
| `low` | `Float64` | Minimum price |
| `close` | `Float64` | Last price |
| `volume` | `Int64` | Traded volume |

## Timeframe Resolution

Use an exact stored interval when available. Otherwise use the closest stored compatible
source that is finer than the request. This minimizes fetched rows without losing
information needed for aggregation:

- Fixed intraday requests are positive minute/hour durations and require an intraday
  source whose duration divides the requested duration exactly.
- Daily requests require daily or finer data.
- Weekly, monthly, quarterly, and yearly requests require daily or finer data.
- Never derive a finer timeframe from a coarser source.
- Reject ambiguous timeframes such as an unspecified "quarter" or "session".

Examples:

- derive `2h` from `1h`, not `30m`;
- derive `1wk` or `1mo` from `1d`, not an intraday interval;
- derive `90m` from `30m` when `1h` cannot divide evenly into `90m`.

Use `scripts/stock_frame.py` to enforce these rules.

## Performance

- Pass known symbols and date boundaries into `load_prices()` for predicate pushdown.
- Use lazy expressions and collect only the final result.
- Project only required columns after loading exact stored intervals.
- Avoid Python row iteration, per-symbol file reads, repeated collection, and eager joins.
- Use Polars window, group, rolling, and dynamic-group expressions for all calculations.

## OHLCV Resampling

Within each symbol and output period:

- timestamp: period boundary or first source candle, as defined by the helper;
- open: first `open`;
- high: maximum `high`;
- low: minimum `low`;
- close: last `close`;
- volume: sum of `volume`.

Sort by `symbol, trade_timestamp` before using first/last expressions.

Fixed intraday periods align to the first available candle for each symbol so Indian
market sessions remain anchored to their actual opening candle. Calendar periods use
calendar boundaries. Derived periods may be incomplete at the beginning or end of the
available range; disclose this when it affects the question.

## Return Semantics

For N observations:

```text
return = latest close / earliest close among the N observations - 1
```

This uses N prices and spans N-1 price transitions. If the user explicitly requests N
period-to-period returns, use N+1 closing prices.

## Fail-Fast Conditions

Raise a clear exception when:

- `market-data/prices` is absent;
- no stored interval can derive the requested timeframe;
- a requested symbol or date range has no data;
- required lookback observations are unavailable;
- the requested calculation is materially ambiguous.
