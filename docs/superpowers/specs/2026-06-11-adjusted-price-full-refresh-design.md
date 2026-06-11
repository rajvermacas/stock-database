# Adjusted Price Full Refresh Design

## Purpose

Change price ingestion from raw, incrementally updated OHLCV to adjusted-only
OHLCV that nullifies corporate-action price discontinuities. Each command
refreshes full history only for the configured Yahoo interval.

## Success Criteria

- Persist only Yahoo-adjusted OHLCV.
- Download from required `download.initial_start_date` through the current date
  on every update.
- Refresh only the interval selected by required `[yahoo].interval`.
- Atomically replace a symbol's interval file after a successful full download.
- Preserve the existing valid file when download, normalization, or write fails.
- Remove CLI start-date and end-date options.
- Recalculate indicators only when persisted adjusted prices change.
- Keep per-symbol failure isolation and batch download behavior.

## Adjustment Semantics

Yahoo calls use `auto_adjust=true`, `actions=false`, and `progress=false`.
`yfinance` returns adjusted values under the standard `Open`, `High`, `Low`,
and `Close` columns. It derives adjusted OHLC using Yahoo's adjusted-close
factor, which incorporates splits and dividends.

The application persists Yahoo's returned `Volume` unchanged. This means
"adjusted OHLCV" describes an adjusted price series plus Yahoo-provided volume;
the application does not independently split-adjust volume.

No raw prices, adjusted-close helper column, dividends, or split records are
persisted.

## Command And Range Semantics

The CLI retains:

```text
stock-data --config PATH update-all
stock-data --config PATH update-symbol SYMBOL
```

It removes `--start-date` and `--end-date`. The required
`download.initial_start_date` config value is the only history-start control.
The request end is the current date, converted by the Yahoo adapter to its
exclusive end-date argument. Existing completed-candle filtering remains in
place.

Each command operates only on `[yahoo].interval`. For example, a command
configured with `interval = "1d"` replaces `prices/1d/<symbol>.parquet` and
does not read or change files for `30m`, `1h`, or any other interval.

The application does not clamp requests according to assumed Yahoo retention
limits. If Yahoo rejects a full-history range for an interval, that symbol
fails with the existing interval-and-range-specific error behavior.

## Full Refresh Flow

Every selected symbol uses the same request range:

1. Request adjusted data from `download.initial_start_date` through the current
   date for the configured interval.
2. Retain existing chunked batch downloads and one individual retry for symbols
   missing from a successful batch.
3. Normalize returned adjusted OHLCV and remove incomplete candles.
4. Compare the complete normalized result with the existing interval file.
5. If equal, report the symbol unchanged and do not rewrite prices or
   recalculate indicators.
6. If different, atomically replace the complete symbol file and refresh its
   indicators.

The service no longer reads the latest stored timestamp to plan incremental
requests. It never merges newly downloaded rows with existing rows.

Full replacement is required because a new dividend or split can retroactively
change adjusted prices for all earlier candles. Incremental append would leave
old rows stale and create an internally inconsistent adjusted series.

## Storage Safety

The canonical Parquet schema and interval-based paths remain unchanged.
Normalized data must still be non-empty, sorted, unique by symbol and
`trade_timestamp`, and free of null required values.

The price store exposes full replacement behavior with change detection. It
writes a validated temporary Parquet file in the destination directory and
atomically replaces the destination only after validation succeeds.

Download, normalization, validation, and temporary-write failures do not modify
an existing valid symbol file. Existing raw files are replaced with adjusted
history on the first successful update for their interval; no raw-price
compatibility mode or metadata marker is retained.

## Components

- `cli.py`: remove date-range options, parsing, and arguments passed to the
  service.
- `yahoo.py`: switch the fixed Yahoo parameter from `auto_adjust=false` to
  `auto_adjust=true`.
- `service.py`: replace incremental and explicit-range planning with one
  configured full-history range for all selected symbols.
- `storage.py`: replace merge/upsert behavior with validated full replacement
  and equality-based unchanged detection.
- Indicator modules: retain existing interfaces; changed price files trigger
  recalculation while unchanged files do not.
- `README.md` and `COMMANDS.md`: document adjusted-only full-refresh behavior,
  configured start date, interval isolation, and unchanged Yahoo volume.

## Error Handling

Existing per-symbol failure isolation remains. A failed symbol records a clear
error and does not prevent other symbols from completing.

Missing or empty Yahoo data after individual retry, malformed adjusted data,
invalid existing storage, and write failures mark the affected symbol failed.
They preserve any existing destination file. Required configuration remains
fail-fast, and no fallback start date or interval is introduced.

## Testing

Automated tests remain network-free and cover:

- Yahoo calls use `auto_adjust=true`, `actions=false`, and the configured
  interval.
- Every normal update requests `download.initial_start_date` through the
  current date regardless of existing stored timestamps.
- An update changes only the configured interval directory.
- Successful full refresh removes old rows absent from the downloaded result.
- Equal full-history results are unchanged and avoid indicator recalculation.
- Changed full-history results replace prices and refresh indicators.
- Download, normalization, and storage failures preserve existing files.
- CLI date-range options are absent and rejected.
- Documentation no longer describes raw prices or incremental updates.

Run the full test suite, Ruff checks, and file/function line-limit checks.
Perform bounded live verification for representative configured intervals
without modifying tracked configuration or existing runtime data.

## Out Of Scope

- Raw-price persistence or compatibility mode
- Corporate-action persistence
- Local adjustment-factor calculation
- Independent volume adjustment
- Partial or incremental price refresh
- Updating multiple intervals in one command
- Application-enforced Yahoo retention limits
