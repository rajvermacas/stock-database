# Stock Data Repository

A local repository for adjusted OHLCV data downloaded from Yahoo Finance.
It stores one validated Parquet file per symbol for later analytics with Polars,
DuckDB, or similar tools.

It also maintains precalculated technical indicators from persisted adjusted prices.
It does not include a web UI, screening, backtesting, automated symbol discovery,
or historical gap repair.

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
interval = "1h"
batch_size = 50
timeout_seconds = 30
threads = true

[indicators]
enabled = true
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

Every update downloads full history from `download.initial_start_date` through
the latest completed candle for only the configured interval. A changed result
atomically replaces that interval's complete symbol file; an equal result is
left unchanged. Other interval directories are not read or modified.

Yahoo adjusts Open, High, Low, and Close for corporate actions. Volume is
persisted unchanged as Yahoo-provided volume. No raw prices, adjusted-close
helper column, dividends, or split records are stored. Only completed candles
are retained.
Intraday candles are complete after their duration, daily candles after 4:00 PM
IST, and the current weekly/monthly/quarterly period is excluded.

Supported native intervals:

```text
1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
```

Select one through `[yahoo].interval`. The application sends requested ranges
to Yahoo without enforcing retention limits; unavailable ranges fail with an
interval-and-range-specific error.

Symbols are downloaded in configurable batches. A symbol omitted from a
successful batch is retried individually once. Other symbols continue when one
fails, and the command returns exit code `1` after a partial failure.

When indicators are enabled, every nonfailed symbol in the selected configured
interval is checked after its price update. Changed prices force recalculation.
Missing or stale indicator files are backfilled, including when full downloaded
price history is unchanged. Other intervals are not scanned.

## Storage

Runtime files are created under the configured `data_dir`:

```text
market-data/
  indicators/
    1h/
      RELIANCE.NS.parquet
      RELIANCE.NS.metadata.json
  prices/
    1h/
      RELIANCE.NS.parquet
  metadata/
    symbols.csv
  logs/
```

The output root is `[paths].data_dir`; relative paths resolve from the TOML
file's directory. Files use `prices/<interval>/<symbol>.parquet`, are atomically
replaced, and are sorted by `trade_timestamp`.

| Column | Type |
|---|---|
| `symbol` | string |
| `trade_timestamp` | timezone-aware timestamp in `Asia/Kolkata` |
| `open` | float64 |
| `high` | float64 |
| `low` | float64 |
| `close` | float64 |
| `volume` | int64 |

Adjusted price files remain unchanged by indicator processing.

## Indicators

TA-Lib calculates standard indicators from full persisted adjusted OHLCV
history. Indicator files use `indicators/<interval>/<symbol>.parquet`; matching
metadata files contain a source-price fingerprint used to detect stale output.

Every output row requires full 365-calendar-day history and valid values for all
indicators. When history is insufficient, no indicator file is written and a
warning is logged. A calculation or storage failure preserves prices and any
previous valid indicator file, but marks that symbol update failed.

| Columns | Formula |
|---|---|
| `ema_10`, `ema_20`, `ema_50`, `ema_100`, `ema_200` | EMA of close |
| `volume_ema_20`, `relative_volume_20` | Volume EMA and volume divided by EMA |
| `rsi_14` | Wilder RSI |
| `atr_14`, `atr_percent_14` | Wilder ATR and ATR divided by close |
| `macd_12_26`, `macd_signal_9`, `macd_histogram` | Standard MACD |
| `adx_14`, `plus_di_14`, `minus_di_14` | Wilder directional indicators |
| `band_upper_20_2`, `band_middle_20`, `band_lower_20_2`, `band_width_20_2` | EMA-20-centered bands using 20-period standard deviation |
| `roc_20`, `obv` | Rate of change and on-balance volume |
| `trailing_365d_high`, `trailing_365d_low`, `distance_from_365d_high_percent` | Trailing calendar-year context |

No simple moving averages are calculated.

## Development

Tests mock Yahoo calls and do not require network access.

```bash
pytest -v
ruff check src tests
ruff format --check src tests
```
