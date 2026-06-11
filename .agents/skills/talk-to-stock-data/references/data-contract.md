# Stock Data Contract

## Storage

- Price root: `market-data/prices`
- Price layout: `market-data/prices/<interval>/<symbol>.parquet`
- Indicator root: `market-data/indicators`
- Indicator layout: `market-data/indicators/<interval>/<symbol>.parquet`
- Indicator metadata: `market-data/indicators/<interval>/<symbol>.metadata.json`
- Time zone: `Asia/Kolkata`
- Price columns are adjusted for corporate actions; volume is Yahoo-provided.

| Column | Polars type | Meaning |
|---|---|---|
| `symbol` | `String` | Yahoo-style ticker |
| `trade_timestamp` | `Datetime(..., Asia/Kolkata)` | Candle start |
| `open` | `Float64` | First price |
| `high` | `Float64` | Maximum price |
| `low` | `Float64` | Minimum price |
| `close` | `Float64` | Last price |
| `volume` | `Int64` | Traded volume |

## Precalculated Indicators

Indicators derive from adjusted prices. Use them only for the exact interval
directory containing them. Never resample precalculated indicators or join them to a
derived timeframe.

Indicator files contain only rows after full 365-calendar-day history and after every
indicator is valid. Files contain no null, NaN, or infinite values. Missing indicator
files usually mean insufficient history or that the symbol was not part of the selected
interval update. Inner joins therefore exclude unavailable symbols and early history;
disclose these exclusions.

| Columns | Meaning |
|---|---|
| `ema_10`, `ema_20`, `ema_50`, `ema_100`, `ema_200` | Close EMAs |
| `volume_ema_20`, `relative_volume_20` | Volume EMA and `volume / volume_ema_20` |
| `rsi_14` | Standard Wilder RSI |
| `atr_14`, `atr_percent_14` | Standard Wilder ATR and `atr_14 / close * 100` |
| `macd_12_26`, `macd_signal_9`, `macd_histogram` | Standard MACD |
| `adx_14`, `plus_di_14`, `minus_di_14` | Standard Wilder trend strength/direction |
| `band_upper_20_2`, `band_middle_20`, `band_lower_20_2`, `band_width_20_2` | EMA-20-centered bands using 20-period standard deviation |
| `roc_20`, `obv` | Rate of change and on-balance volume |
| `trailing_365d_high`, `trailing_365d_low`, `distance_from_365d_high_percent` | True trailing 365-calendar-day context |

No simple moving averages are stored. Metadata contains a source-price fingerprint used
by ingestion to detect stale output; query code normally reads Parquet, not metadata.

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

For derived timeframe indicator requests, derive OHLCV with `load_prices()` and calculate
the requested indicator on demand. State formula and that the result was not
precalculated.

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
- exact-interval precalculated indicators are requested but unavailable;
- no stored interval can derive the requested timeframe;
- a requested symbol or date range has no data;
- required lookback observations are unavailable;
- the requested calculation is materially ambiguous.
