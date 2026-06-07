# Stock Market Data Repository Design

## Purpose

Build a lightweight local repository of daily OHLCV data for NSE-listed stocks.
The initial release provides reliable ingestion and Parquet storage through a
command-line interface. It intentionally excludes screening, indicators,
backtesting, databases, scheduling systems, and web interfaces.

## Success Criteria

- Download raw, unadjusted daily OHLCV data from Yahoo Finance using `yfinance`.
- Maintain one analytics-friendly Parquet file per symbol.
- Append only dates after the latest stored date during normal updates.
- Support explicit bounded date-range upserts.
- Process 500 or more symbols while continuing after per-symbol failures.
- Produce idempotent output with no duplicate symbol/date records.
- Return a non-zero command exit code when any selected symbol fails.
- Log download activity, row counts, failures, retries, and durations.

## Technology

- Python 3.12 or newer
- `yfinance` for Yahoo Finance access
- Polars for transformations and Parquet I/O
- TOML configuration parsed with Python's `tomllib`
- `pytest` for automated tests
- Standard-library `logging`

## Repository Layout

```text
src/
  stock_data/
    __init__.py
    cli.py
    config.py
    symbols.py
    yahoo.py
    normalization.py
    storage.py
    service.py
tests/
config/
  stock-data.toml
market-data/
  prices/
  metadata/
    symbols.csv
  logs/
pyproject.toml
README.md
COMMANDS.md
```

Runtime price files and logs are ignored by Git. Configuration and the symbol
list are intended to be version-controlled examples or user-maintained inputs.

## Architecture

The system is a layered CLI application with focused modules:

- `cli.py` parses commands and arguments, reports a summary, and maps results to
  process exit codes.
- `config.py` loads and validates required TOML settings.
- `symbols.py` loads and validates the CSV symbol list.
- `yahoo.py` performs chunked batch downloads and individual retries.
- `normalization.py` converts Yahoo results into the canonical Polars schema.
- `storage.py` reads and atomically rewrites per-symbol Parquet files.
- `service.py` orchestrates update selection, downloads, persistence, logging,
  and failure collection.

Module interfaces use explicit inputs and outputs. Missing required values are
errors; the application does not silently substitute fallback values.

## CLI

The installed command is `stock-data`.

```text
stock-data --config PATH update-all
stock-data --config PATH update-all --start-date YYYY-MM-DD --end-date YYYY-MM-DD
stock-data --config PATH update-symbol SYMBOL
stock-data --config PATH update-symbol SYMBOL --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

`update-all` reads symbols from the configured CSV. `update-symbol` operates on
the supplied symbol without requiring it to appear in that CSV.

`--config` is required for every command. Date-range arguments are optional, but
they must be supplied together. The
requested range is inclusive at both boundaries from the user's perspective.
The Yahoo adapter converts the inclusive end date to Yahoo's exclusive end-date
argument.

Invalid commands, unpaired or invalid dates, and a start date after the end date
fail before any download begins.

## Configuration

The CLI requires the TOML file supplied through `--config`. It does not search
other locations. Every setting below is required:

```toml
[paths]
data_dir = "../market-data"
symbols_file = "../market-data/metadata/symbols.csv"

[download]
initial_start_date = "2000-01-01"

[yahoo]
interval = "1d"
batch_size = 50
timeout_seconds = 30
threads = true
```

Relative paths are resolved from the directory containing the TOML file.
`prices/` and `logs/` are fixed subdirectories of `data_dir`; they are created
when absent. Yahoo calls always use raw prices with `auto_adjust=false`,
`actions=false`, and `progress=false`. These behavior-defining values are not
configurable in the initial release.

Configuration loading validates types, dates, positive batch size, and writable
output directories. The only valid interval is `1d`. Unknown sections and
settings are rejected to expose mistakes early.

## Symbol Management

The symbol file is a header-based CSV with a required `symbol` column.

```csv
symbol
RELIANCE.NS
TCS.NS
INFY.NS
```

Blank symbols, duplicate symbols, and a missing `symbol` column cause
`update-all` to fail before downloading. Symbols are preserved as supplied after
surrounding whitespace is removed. Yahoo validity is determined by download
results rather than a locally maintained exchange-symbol rule.

## Canonical Parquet Schema

Each symbol has one file named `<symbol>.parquet` with this stable schema:

| Column | Type | Constraint |
|---|---|---|
| `symbol` | UTF-8 string | non-null |
| `trade_date` | date | non-null |
| `open` | float64 | non-null |
| `high` | float64 | non-null |
| `low` | float64 | non-null |
| `close` | float64 | non-null |
| `volume` | int64 | non-null |

The primary logical key is (`symbol`, `trade_date`). Files are sorted by
`trade_date` ascending. Prices are raw, unadjusted Yahoo OHLC values. Adjusted
close, dividends, and splits are not stored.

## Completed Trading-Day Rule

The service evaluates the current time in `Asia/Kolkata`.

- Before 4:00 PM IST, today's row is excluded.
- At or after 4:00 PM IST, today's row may be stored if Yahoo returns it.

The implementation does not add an NSE trading-calendar dependency. On
weekends and holidays, Yahoo simply returns no row for the current date. This
cutoff is applied after normalization so no incomplete current-day candle is
persisted.

## Normal Update Flow

For each selected symbol:

1. If no Parquet file exists, request data from the configured initial start
   date through the latest completed trading day.
2. If a Parquet file exists, read its greatest `trade_date` and request data
   strictly after that date through the latest completed trading day.
3. Do not inspect or repair gaps at or before the greatest stored date.
4. Normalize and validate returned data.
5. Combine new and existing rows, deduplicate by the logical key, sort, and
   atomically replace the Parquet file.

If the file is already current, the symbol succeeds without rewriting it.

## Explicit Date-Range Upsert Flow

When both date arguments are supplied, the same inclusive range applies to
every selected symbol. Existing file state does not change the requested range.

Returned rows are normalized and upserted into the existing file. For matching
logical keys, newly downloaded rows replace stored rows. Rows outside the
requested range remain unchanged. The completed trading-day rule still applies,
so a future date or an incomplete current-day candle is never stored.

An empty valid Yahoo result for a range is treated as a symbol failure after the
configured retry behavior, because it cannot be distinguished reliably from an
invalid symbol or upstream response problem without a trading calendar.

## Batch Download Strategy

The service groups symbols by required request start date during normal updates,
because their latest stored dates can differ. Explicit date-range updates
naturally share one range.

Each group is divided into configured chunks and sent through `yfinance` batch
downloads. Batch results are split into per-symbol frames. Any requested symbol
missing from a successful batch response is retried individually once using the
same date range and parameters. A symbol that still has no usable data is marked
failed; the remaining symbols continue.

The design does not retry an entire batch or introduce general retry/backoff
policy in the initial release.

## Normalization And Validation

The normalization layer handles Yahoo's single-symbol and multi-symbol result
shapes and emits one canonical Polars DataFrame per symbol. It:

- maps Yahoo columns to lowercase canonical names
- converts the index to `trade_date`
- adds the requested symbol
- selects only required columns
- applies canonical types
- rejects null or malformed required values
- removes rows after the completed trading-day cutoff
- deduplicates returned rows by the logical key

A malformed response fails only the affected symbol when it can be isolated.

## Storage Safety

The storage layer validates existing Parquet schema before merging. An invalid
or unreadable existing file causes that symbol to fail without overwriting it.

Writes go to a temporary file in the destination directory. After the temporary
file is successfully written and validated, it atomically replaces the
destination file. Temporary files are cleaned up after failures. This preserves
the previous valid file if writing fails.

## Error Handling And Exit Behavior

Errors that invalidate the whole command fail immediately:

- invalid or missing configuration
- invalid CLI arguments
- invalid `symbols.csv` for `update-all`
- inability to initialize required output or log directories

Download, normalization, or storage failures are isolated per symbol. Processing
continues for all remaining symbols. At completion, the CLI prints and logs
success, unchanged, and failure counts. It exits non-zero if one or more selected
symbols failed and zero only when all selected symbols succeeded or were already
current.

## Logging

Logging uses the standard library and writes detailed logs to the configured log
directory. Logs include:

- command start, parameters, and completion duration
- batch start, completion, symbol count, and requested range
- per-symbol downloaded, stored, and unchanged row counts
- individual retry attempts
- errors with symbol and relevant exception details
- final success, unchanged, and failure summary

Secrets are not expected in configuration, but request parameters and exception
logging must not expose sensitive environment values.

## Testing Strategy

Tests use temporary directories and mocked Yahoo calls. No live-network test is
required for the initial release.

Unit and focused integration tests cover:

- required configuration and validation failures
- symbol CSV validation
- CLI command and paired date-range validation
- 4:00 PM IST completed-day cutoff
- single-symbol and batch Yahoo response normalization
- missing-symbol individual retry
- initial load and normal strict-append behavior
- explicit bounded range upserts
- new-row precedence during deduplication
- schema validation and atomic replacement
- no rewrite when already current
- per-symbol failure isolation
- non-zero exit after partial failure

## Documentation Deliverables

- `README.md` documents installation, configuration, repository layout, and the
  ingestion behavior.
- `COMMANDS.md` documents every supported CLI command with sample input,
  representative console output, and exit-code behavior.

## Future Compatibility

Per-symbol Parquet files with a stable canonical schema can be queried directly
by DuckDB in a later phase. Future indicators, factors, fundamentals, screening,
and backtesting should consume this storage contract without changing it.

The initial release deliberately does not include DuckDB integration, automated
symbol discovery, historical gap repair, a trading calendar, adjusted prices,
web interfaces, scheduling, or distributed processing.
