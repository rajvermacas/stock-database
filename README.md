# Stock Data Repository

A local repository for raw, daily NSE OHLCV data downloaded from Yahoo Finance.
It stores one validated Parquet file per symbol for later analytics with Polars,
DuckDB, or similar tools.

The initial release is ingestion-only. It does not include a web UI, screening,
indicators, backtesting, automated symbol discovery, or historical gap repair.

## Requirements And Installation

Python 3.12 or newer is required.

```bash
python -m pip install -e '.[dev]'
```

This installs the `stock-data` command. See [COMMANDS.md](COMMANDS.md) for every
supported command with sample input, output, and exit codes.

## Configuration

Every command requires `--config PATH`. Relative paths are resolved from the
configuration file's directory. All settings are required.

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

The symbol CSV must have a `symbol` header and contain no blank or duplicate
symbols:

```csv
symbol
RELIANCE.NS
TCS.NS
INFY.NS
```

## Update Behavior

A normal update downloads from the configured initial date for a new symbol. For
an existing symbol, it downloads strictly after the greatest stored
`trade_date`. It does not detect or repair older gaps.

Supplying both `--start-date` and `--end-date` performs a bounded inclusive
upsert. Newly downloaded rows replace stored rows for matching dates; rows
outside the range remain unchanged.

Raw, unadjusted Yahoo prices are stored. Before 4:00 PM IST, today's candle is
excluded. At or after 4:00 PM IST, today's candle may be stored if Yahoo returns
it.

Symbols are downloaded in configurable batches. A symbol omitted from a
successful batch is retried individually once. Other symbols continue when one
fails, and the command returns exit code `1` after a partial failure.

## Storage

Runtime files are created under the configured `data_dir`:

```text
market-data/
  prices/
    RELIANCE.NS.parquet
  metadata/
    symbols.csv
  logs/
```

Each Parquet file is atomically replaced and sorted by `trade_date`.

| Column | Type |
|---|---|
| `symbol` | string |
| `trade_date` | date |
| `open` | float64 |
| `high` | float64 |
| `low` | float64 |
| `close` | float64 |
| `volume` | int64 |

## Development

Tests mock Yahoo calls and do not require network access.

```bash
pytest -v
ruff check src tests
ruff format --check src tests
```

