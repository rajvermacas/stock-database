# CLI Commands

Install the project first:

```bash
python -m pip install -e '.[dev]'
```

All commands require a valid configuration file. The examples use
`config/stock-data.toml`.

## Help

```bash
stock-data --help
stock-data --config config/stock-data.toml update-all --help
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
  INVALID.NS: Yahoo returned no data after individual retry
```

Exit code: `1` after processing all symbols when any symbol fails.

## Update All Symbols For A Date Range

Both boundaries are required and inclusive.

```bash
stock-data --config config/stock-data.toml update-all \
  --start-date 2026-05-01 --end-date 2026-05-31
```

Representative output:

```text
Successful: 3
Unchanged: 0
Failed: 0
```

Exit code: `0` on total success, or `1` after a partial failure.

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

## Update One Symbol For A Date Range

```bash
stock-data --config config/stock-data.toml update-symbol RELIANCE.NS \
  --start-date 2026-05-01 --end-date 2026-05-31
```

Representative output:

```text
Successful: 1
Unchanged: 0
Failed: 0
```

Exit code: `0` on success or `1` on a symbol failure.

## Validation Errors

Invalid configuration, symbols, or arguments fail before downloading.

```bash
stock-data --config config/stock-data.toml update-all --start-date 2026-05-01
```

Output:

```text
Error: --start-date and --end-date must be supplied together
```

Exit code: `2`.

