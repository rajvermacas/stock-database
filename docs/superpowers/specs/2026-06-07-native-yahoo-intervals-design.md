# Native Yahoo Intervals Design

## Purpose

Extend the stock data repository from daily-only storage to every native
interval accepted by `yfinance`, while retaining one configuration-driven CLI
and one canonical Parquet schema.

## Supported Intervals

The application supports these native Yahoo interval names:

```text
1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
```

It does not derive or resample custom intervals such as `2h`. Supported
intervals and their completed-candle behavior are defined in one centralized
registry so interval-dependent logic is not distributed throughout the code.

`[yahoo].interval` remains required in TOML and selects the interval for a
command. No CLI interval override is added.

## Output Directory

`[paths].data_dir` controls the output root. Relative paths resolve from the
configuration file directory. With:

```toml
[paths]
data_dir = "../market-data"
```

in `config/stock-data.toml`, the resolved root is
`/workspaces/stock-database/market-data`.

Price files are isolated by configured interval:

```text
market-data/prices/1d/RELIANCE.NS.parquet
market-data/prices/30m/RELIANCE.NS.parquet
market-data/prices/1h/RELIANCE.NS.parquet
```

Logs remain under `market-data/logs/`. No legacy daily-file migration is
required because no existing daily files need preservation.

## Canonical Schema

Every interval uses the same schema:

| Column | Type | Constraint |
|---|---|---|
| `symbol` | UTF-8 string | non-null |
| `trade_timestamp` | timezone-aware timestamp in `Asia/Kolkata` | non-null |
| `open` | float64 | non-null |
| `high` | float64 | non-null |
| `low` | float64 | non-null |
| `close` | float64 | non-null |
| `volume` | int64 | non-null |

The logical key is (`symbol`, `trade_timestamp`). Files are sorted ascending by
`trade_timestamp`. Daily and longer-period timestamps are normalized to the
start of their Yahoo period in `Asia/Kolkata`.

## Interval Registry

One interval registry describes each supported native interval. Each entry
contains:

- Yahoo interval name
- interval category: intraday, daily, multi-day, weekly, monthly, or quarterly
- fixed duration when the interval has one
- completed-candle filtering strategy

The registry drives configuration validation, request planning, incremental
boundaries, and completed-candle filtering. It does not encode Yahoo retention
limits.

## Completed-Candle Rules

Only completed candles are stored.

- Intraday intervals exclude the currently forming candle. A candle is complete
  when its start timestamp plus its interval duration is not later than the
  current `Asia/Kolkata` time.
- `1d` excludes today's candle before 4:00 PM IST and allows it at or after
  4:00 PM IST.
- `5d`, `1wk`, `1mo`, and `3mo` conservatively exclude the current Yahoo period.
  They become eligible only after Yahoo returns them as a prior period.

The system does not add an NSE trading-calendar dependency.

## Request And Update Flow

Normal updates read the latest stored timestamp from the configured interval's
directory. The next request begins strictly after that timestamp according to
the interval registry. New symbols begin from the configured
`initial_start_date`.

Explicit `--start-date` and `--end-date` ranges remain paired and inclusive from
the user's perspective. Returned timestamps within the requested date range are
upserted into the configured interval file.

Yahoo requests receive the configured interval unchanged. The application does
not reject or clamp requests based on assumed Yahoo retention limits. This
allows Yahoo's current behavior to decide whether a range is available.

## Error Handling

Yahoo, network, invalid interval/range, and unavailable-history failures are
wrapped in a clear download exception containing:

- affected symbol or batch
- configured interval
- requested start
- requested end
- original error

Batch failures remain isolated per symbol and processing continues. Missing
symbols from successful batches are retried individually once. A command exits
non-zero after processing when any symbol fails.

Malformed timestamps, timezone conversion failures, incomplete candles, invalid
existing schemas, and storage failures are handled per symbol without
overwriting a valid existing file.

## Component Changes

- Add an interval registry module for supported names and completion rules.
- Update configuration validation to accept every registered interval.
- Update normalization to emit timezone-aware `trade_timestamp`.
- Update storage to use interval directories and timestamp logical keys.
- Update orchestration to plan interval-aware incremental requests.
- Update Yahoo errors and logs to include interval and requested range.
- Keep the existing CLI commands and TOML-selected interval behavior.

## Testing

Automated tests remain network-free and cover:

- every supported interval in configuration validation
- interval registry lookups and invalid intervals
- Yahoo timestamps converted to `Asia/Kolkata`
- completed-candle filtering for intraday, daily, 5-day, weekly, monthly, and
  quarterly intervals
- interval-separated storage paths
- timestamp-based deduplication and incremental planning
- explicit range upserts
- interval-and-range-specific Yahoo exceptions
- per-symbol failure isolation
- CLI and documentation behavior

## Mandatory Live Verification

After automated tests pass, perform bounded live Yahoo downloads using temporary
configuration and storage. Live verification must not modify repository example
configuration or tracked runtime data.

At minimum, verify:

- one intraday interval, including completed-candle filtering
- `30m`
- `1h`
- `1d`
- one higher-period interval such as `1wk`
- multi-symbol batch splitting
- canonical Parquet schema and `Asia/Kolkata` timezone
- interval-separated output directories
- idempotency on a repeated bounded request
- useful failure output for an unavailable or invalid range when Yahoo returns
  an error

Report live results separately from automated-test results because live Yahoo
availability can vary over time.

## Documentation

Update `README.md` and `COMMANDS.md` to document:

- setting the output root through `[paths].data_dir`
- selecting an interval through `[yahoo].interval`
- every supported native interval
- interval-separated output layout
- the canonical timestamp schema
- completed-candle rules
- examples for `30m`, `1h`, and `1d`
- Yahoo availability errors and command exit behavior

## Out Of Scope

- custom or derived timeframes
- local resampling
- CLI interval overrides
- application-enforced Yahoo retention limits
- NSE trading-calendar integration
- legacy daily-file migration

