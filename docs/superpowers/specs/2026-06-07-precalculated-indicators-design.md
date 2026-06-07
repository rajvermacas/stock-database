# Precalculated Indicators Design

## Goal

Extend the repository with automatically calculated technical indicators for every
supported price interval. Indicator data is derived from persisted raw OHLCV data
and stored separately so price files remain unchanged.

The configured Yahoo interval is the selected interval for each update run.
Existing price files in that interval are backfilled when their indicator file is
missing or stale. Other interval directories are not scanned during that run.

## Storage Layout

Raw price storage remains unchanged:

```text
market-data/prices/<interval>/<symbol>.parquet
```

Derived indicators use matching interval and symbol paths:

```text
market-data/indicators/<interval>/<symbol>.parquet
market-data/indicators/<interval>/<symbol>.metadata.json
```

Indicator files are atomically replaced only after calculation and validation
succeed. The metadata sidecar records a deterministic fingerprint of the source
price data used for the calculation. Raw price files are never modified by
indicator processing.

## Indicator Schema

Each indicator file contains:

| Column | Formula |
|---|---|
| `symbol` | Source symbol |
| `trade_timestamp` | Source candle timestamp |
| `ema_10` | 10-period EMA of close |
| `ema_20` | 20-period EMA of close |
| `ema_50` | 50-period EMA of close |
| `ema_100` | 100-period EMA of close |
| `ema_200` | 200-period EMA of close |
| `volume_ema_20` | 20-period EMA of volume |
| `relative_volume_20` | Volume divided by `volume_ema_20` |
| `rsi_14` | 14-period RSI using standard Wilder smoothing |
| `atr_14` | 14-period ATR using standard Wilder smoothing |
| `atr_percent_14` | `atr_14 / close * 100` |
| `macd_12_26` | 12/26 EMA MACD line |
| `macd_signal_9` | 9-period EMA signal line |
| `macd_histogram` | MACD line minus signal line |
| `adx_14` | 14-period ADX using standard Wilder smoothing |
| `plus_di_14` | 14-period positive directional indicator |
| `minus_di_14` | 14-period negative directional indicator |
| `band_upper_20_2` | `ema_20 + 2 * rolling standard deviation` |
| `band_middle_20` | `ema_20` |
| `band_lower_20_2` | `ema_20 - 2 * rolling standard deviation` |
| `band_width_20_2` | `(upper - lower) / middle * 100` |
| `roc_20` | 20-period close rate of change |
| `obv` | On-balance volume |
| `trailing_365d_high` | Highest high in trailing 365 calendar days |
| `trailing_365d_low` | Lowest low in trailing 365 calendar days |
| `distance_from_365d_high_percent` | `(close / trailing high - 1) * 100` |

All numeric indicator columns use `Float64`. Files contain no null, NaN, or
infinite values.

No simple moving averages are calculated. RSI, ATR, ADX, and directional
indicators retain their standard Wilder formulas rather than replacing their
smoothing with EMA.

## Calculation

TA-Lib calculates standard technical indicators. Polars handles the EMA-centered
bands, trailing calendar window, final filtering, schema construction, and
validation.

Calculation always reads the full persisted price file for one symbol and
interval. This ensures bounded price upserts and revised historical candles
produce a consistent complete indicator file.

Rows are retained only after every indicator is valid and the symbol has a full
365-calendar-day history. A row qualifies when its timestamp is at least 365
calendar days after the earliest persisted timestamp. This rule applies to every
interval, including intraday intervals.

If no row qualifies, no indicator file is written. Any existing indicator file
for that symbol and interval is removed after the calculation confirms
insufficient history, and a warning is logged.

## Update Integration

After each symbol's price upsert succeeds, the update service checks whether
indicators require calculation. Calculation runs when:

- the price upsert changed persisted prices;
- the indicator file does not exist; or
- its metadata sidecar is missing or its source fingerprint differs from the
  current full price file.

This backfills existing price files for the configured interval during a normal
update without scanning other interval directories. A current indicator file for
an unchanged price file is skipped. The fingerprint covers all canonical price
columns, so historical revisions are detected even when the final timestamp is
unchanged.

Successful indicator calculation is part of a successful symbol update. When
indicator calculation or storage fails:

- the newly persisted price data remains;
- any previous valid indicator file remains;
- the symbol result is marked failed;
- the detailed exception is logged; and
- the next update retries because the indicator file is missing or stale.

## Components

### `stock_data.indicators`

Owns indicator calculation, formulas, output schema, validation, and the
insufficient-history result. Functions remain focused and under 80 lines.

### `stock_data.indicator_storage`

Owns indicator paths, reads, strict validation, atomic replacement, freshness
inspection through source fingerprints, metadata sidecars, and removal after
confirmed insufficient history. The indicator file and matching metadata are
published only after both temporary files validate.

### `stock_data.service`

Triggers indicator processing after successful price upserts and combines price
and indicator outcomes into the existing per-symbol update result.

### Configuration

Add a required section:

```toml
[indicators]
enabled = true
```

When enabled, automatic calculation and selected-interval backfill occur.
Indicator periods are fixed in this release so all files share one schema.
Missing or invalid configuration fails fast with a clear validation error.

## Logging

Detailed logs identify symbol, interval, trigger reason, source row count,
indicator row count, outcome, and failure cause. Insufficient history is a
warning rather than a symbol failure.

## Testing

Tests verify:

- TA-Lib output against known expected values;
- Wilder RSI, ATR, ADX, and directional indicator behavior;
- EMA-centered band and derived percentage formulas;
- true trailing 365-calendar-day high and low values;
- exact full-history warm-up boundary;
- strict null-, NaN-, and infinity-free schema;
- atomic indicator writes and validation;
- deterministic source fingerprint and metadata validation;
- selected-interval backfill for missing and stale files;
- changed prices trigger recalculation;
- unchanged prices with current indicators skip recalculation;
- insufficient history removes stale indicators and logs a warning;
- indicator failures preserve prices and previous valid indicators while marking
  the symbol failed; and
- raw price schema and files remain unchanged.

Production files must remain under 800 lines, and functions must remain under 80
lines with a single responsibility.

## Dependencies

Add TA-Lib as the battle-tested indicator calculation dependency. Polars remains
the storage, windowing, and validation engine.

## Out Of Scope

- Adjusted-price ingestion
- Simple moving averages
- User-configurable indicator periods
- Backfilling every interval in one update run
- A separate manual indicator rebuild command
- Screening, backtesting, or trading signals
