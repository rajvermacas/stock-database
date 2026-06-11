# CLI Commands

Install the project first:

```bash
python -m pip install -e '.[dev]'
```

All commands require a valid configuration file. The examples use
`config/stock-data.toml`.

Set the output root and interval in TOML:

```toml
[paths]
data_dir = "../market-data"

[yahoo]
interval = "30m"
```

Supported intervals are `1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk,
1mo, 3mo`. Change `interval` to `30m`, `1h`, or `1d` before running the same
commands. Output is written to `prices/<interval>/<symbol>.parquet`.

Every command downloads adjusted OHLCV full history from configured
`download.initial_start_date` through latest completed candle for only selected
interval. Changed history atomically replaces that interval's symbol file.
Yahoo-provided volume is persisted unchanged.

## Help

```bash
stock-data --help
uv run stock-data --config config/stock-data.toml update-all --help
stock-data --config config/stock-data.toml update-symbol --help
```

Representative output:

```text
Usage: stock-data [OPTIONS] COMMAND [ARGS]...
Commands:
  update-all
  update-symbol
```

Exit code: `0`.

## Update All Symbols

Input symbols come from the configured header-based CSV.

```bash
stock-data --config config/stock-data.toml update-all
```

Representative successful output:

```text
Interval: 30m
Price directory: /path/to/market-data/prices/30m
Successful: 3
Unchanged: 0
Failed: 0
```

Exit code: `0` when every symbol succeeds or is unchanged.

Representative partial-failure output:

```text
Successful: 2
Unchanged: 0
Failed: 1
  INVALID.NS: Yahoo download failed symbols=INVALID.NS interval=30m start=2026-05-01 end=2026-06-11: Yahoo returned no data after individual retry
```

Exit code: `1` after processing all symbols when any symbol fails.

## Update One Symbol

The symbol does not need to appear in `symbols.csv`.

```bash
stock-data --config config/stock-data.toml update-symbol RELIANCE.NS
```

Representative output:

```text
Successful: 1
Unchanged: 0
Failed: 0
```

Exit code: `0` on success or when already current, or `1` when the symbol fails.

## Validation Errors

Invalid configuration, symbols, or arguments fail before downloading.

```bash
stock-data --config missing.toml update-all
```

Output:

```text
Error: Invalid configuration missing.toml: ...
```

Exit code: `2`.

Yahoo availability and unsupported-range failures are processed per symbol and
exit with code `1`; the message includes symbol, interval, start, and end.
