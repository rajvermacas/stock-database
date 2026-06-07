# Stock Market Data Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI-only repository that downloads raw daily NSE OHLCV data from Yahoo Finance and maintains one validated Parquet file per symbol.

**Architecture:** A `src/stock_data` package separates configuration, symbols, market-time rules, Yahoo access, normalization, storage, orchestration, logging, and CLI concerns. The orchestration layer batches symbols sharing a request range, retries missing batch symbols individually once, and returns explicit per-symbol results so the CLI can report partial failures.

**Tech Stack:** Python 3.12+, Typer, yfinance, Polars, Pydantic, pytest, pytest-mock, standard-library logging and `tomllib`

---

## File Map

- `pyproject.toml`: package metadata, dependencies, CLI entry point, and tool configuration.
- `src/stock_data/config.py`: strict TOML configuration models and loader.
- `src/stock_data/symbols.py`: header-based symbol CSV loader and validator.
- `src/stock_data/market_time.py`: 4:00 PM IST completed-day rule.
- `src/stock_data/normalization.py`: Yahoo frame to canonical Polars conversion.
- `src/stock_data/storage.py`: Parquet reads, upserts, validation, and atomic writes.
- `src/stock_data/yahoo.py`: chunked yfinance calls, result splitting, and individual retry.
- `src/stock_data/service.py`: update planning and per-symbol orchestration.
- `src/stock_data/logging_config.py`: file and console logging setup.
- `src/stock_data/cli.py`: Typer commands, summaries, and exit codes.
- `tests/`: focused unit and integration tests with no live network calls.
- `config/stock-data.toml`: complete example configuration.
- `market-data/metadata/symbols.csv`: initial symbol-list example.
- `README.md`: installation and behavior documentation.
- `COMMANDS.md`: all CLI commands with sample input, output, and exit codes.

All Python files must remain below 800 lines and all functions below 80 lines.

### Task 1: Scaffold The Package And Test Harness

**Files:**
- Create: `pyproject.toml`
- Create: `src/stock_data/__init__.py`
- Create: `tests/test_package.py`
- Create: `config/stock-data.toml`
- Create: `market-data/metadata/symbols.csv`

- [ ] **Step 1: Write the package smoke test**

```python
# tests/test_package.py
import stock_data


def test_package_exposes_version() -> None:
    assert stock_data.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the smoke test and verify it fails**

Run: `pytest tests/test_package.py -v`

Expected: FAIL because `stock_data` is not installed.

- [ ] **Step 3: Create packaging, dependencies, and examples**

Use this dependency and entry-point configuration:

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "stock-data-repository"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "polars>=1.0",
  "pydantic>=2.0",
  "typer>=0.12",
  "yfinance>=0.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.14", "ruff>=0.6"]

[project.scripts]
stock-data = "stock_data.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/stock_data"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 88
target-version = "py312"
```

```python
# src/stock_data/__init__.py
__version__ = "0.1.0"
```

Create `config/stock-data.toml` using the exact approved schema and create
`market-data/metadata/symbols.csv` with `RELIANCE.NS`, `TCS.NS`, and `INFY.NS`.

- [ ] **Step 4: Install and verify the scaffold**

Run: `python -m pip install -e '.[dev]' && pytest tests/test_package.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/stock_data/__init__.py tests/test_package.py config/stock-data.toml market-data/metadata/symbols.csv
git commit -m "build: scaffold stock data package"
```

### Task 2: Add Strict Configuration Loading

**Files:**
- Create: `src/stock_data/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Tests must prove that a complete file loads, relative paths resolve from the
TOML directory, unknown keys fail, missing keys fail, and invalid interval,
batch size, timeout, or initial date fail.

```python
def test_load_config_resolves_paths(config_file: Path) -> None:
    config = load_config(config_file)
    assert config.paths.data_dir == (config_file.parent / "../market-data").resolve()
    assert config.paths.prices_dir == config.paths.data_dir / "prices"
    assert config.paths.logs_dir == config.paths.data_dir / "logs"


def test_load_config_rejects_missing_batch_size(tmp_path: Path) -> None:
    path = write_config(tmp_path, remove="batch_size")
    with pytest.raises(ConfigError, match="batch_size"):
        load_config(path)
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/test_config.py -v`

Expected: FAIL because `stock_data.config` does not exist.

- [ ] **Step 3: Implement strict models and loader**

Define frozen Pydantic models `PathsConfig`, `DownloadConfig`, `YahooConfig`,
and `AppConfig` with `extra="forbid"`. Use `tomllib.loads`, validate
`interval == "1d"`, positive numeric values, and parse `initial_start_date` as
`date`. Add computed `prices_dir` and `logs_dir` properties. Wrap file, TOML,
and Pydantic failures in `ConfigError` with the config path and cause.

```python
class ConfigError(ValueError):
    pass


def load_config(path: Path) -> AppConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        config = AppConfig.model_validate(raw)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ConfigError(f"Invalid configuration {path}: {exc}") from exc
    return config.resolve_relative_paths(path.parent)
```

- [ ] **Step 4: Verify configuration tests**

Run: `pytest tests/test_config.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/config.py tests/test_config.py
git commit -m "feat: add strict TOML configuration"
```

### Task 3: Add Symbol Loading And Completed-Day Rules

**Files:**
- Create: `src/stock_data/symbols.py`
- Create: `src/stock_data/market_time.py`
- Create: `tests/test_symbols.py`
- Create: `tests/test_market_time.py`

- [ ] **Step 1: Write failing focused tests**

```python
def test_load_symbols_strips_and_preserves_order(tmp_path: Path) -> None:
    path = tmp_path / "symbols.csv"
    path.write_text("symbol\n RELIANCE.NS \nTCS.NS\n", encoding="utf-8")
    assert load_symbols(path) == ["RELIANCE.NS", "TCS.NS"]


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(15, date(2026, 6, 6)), (16, date(2026, 6, 7))],
)
def test_latest_completed_date_uses_four_pm_ist(hour: int, expected: date) -> None:
    now = datetime(2026, 6, 7, hour, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert latest_completed_date(now) == expected
```

Also test missing header, blank symbol, duplicate symbol, unreadable file, and
conversion from a non-IST aware datetime.

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/test_symbols.py tests/test_market_time.py -v`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement symbol and market-time modules**

Use `csv.DictReader`; raise `SymbolFileError` on every malformed input. For
market time, require an aware datetime, convert it to `Asia/Kolkata`, and return
today at or after `time(16, 0)`, otherwise yesterday. Do not add weekend or
holiday logic.

- [ ] **Step 4: Verify focused tests**

Run: `pytest tests/test_symbols.py tests/test_market_time.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/symbols.py src/stock_data/market_time.py tests/test_symbols.py tests/test_market_time.py
git commit -m "feat: validate symbols and completed trading dates"
```

### Task 4: Normalize Yahoo Responses

**Files:**
- Create: `src/stock_data/normalization.py`
- Create: `tests/test_normalization.py`

- [ ] **Step 1: Write failing normalization tests**

Build small pandas fixtures matching yfinance single-symbol and multi-index
batch shapes. Assert exact column order and Polars dtypes, raw OHLC values,
volume as `Int64`, current-day cutoff filtering, duplicate removal, and clear
failure for null or missing required values.

```python
EXPECTED_COLUMNS = [
    "symbol", "trade_date", "open", "high", "low", "close", "volume"
]


def test_normalize_symbol_returns_canonical_schema(single_symbol_frame) -> None:
    result = normalize_symbol("RELIANCE.NS", single_symbol_frame, date(2026, 6, 5))
    assert result.columns == EXPECTED_COLUMNS
    assert result["symbol"].to_list() == ["RELIANCE.NS"]
    assert result["trade_date"].to_list() == [date(2026, 6, 5)]
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/test_normalization.py -v`

Expected: FAIL because `normalize_symbol` does not exist.

- [ ] **Step 3: Implement canonical normalization**

Define `CANONICAL_SCHEMA`, `NormalizationError`, `split_batch_frame`, and
`normalize_symbol`. Use yfinance's pandas result only as an adapter input;
convert to Polars immediately. Select required columns, rename them, add symbol,
cast strictly, filter dates after the cutoff, deduplicate by logical key, and
sort ascending. Reject empty output and null required values.

- [ ] **Step 4: Verify normalization tests**

Run: `pytest tests/test_normalization.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/normalization.py tests/test_normalization.py
git commit -m "feat: normalize Yahoo data to canonical schema"
```

### Task 5: Add Safe Parquet Storage

**Files:**
- Create: `src/stock_data/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

Cover missing-file reads, schema validation, latest date, append/upsert with new
row precedence, deterministic sorting, unchanged detection, and preservation of
the old file when temporary-file validation fails.

```python
def test_upsert_replaces_matching_date_with_new_row(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    store.write_atomic("TCS.NS", frame(close=100.0))
    result = store.upsert("TCS.NS", frame(close=105.0))
    assert result.changed is True
    assert store.read("TCS.NS")["close"].to_list() == [105.0]
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/test_storage.py -v`

Expected: FAIL because `PriceStore` does not exist.

- [ ] **Step 3: Implement storage**

Create `StorageError` and frozen `WriteResult(changed, downloaded_rows,
stored_rows)`. `PriceStore.path_for` must reject symbols containing path
separators. `read` validates exact canonical schema and single expected symbol.
`upsert` concatenates old rows before new rows and keeps the last logical key.
`write_atomic` uses `tempfile.NamedTemporaryFile` in the destination directory,
validates the written Parquet, then calls `os.replace`; clean the temporary file
in `finally`.

- [ ] **Step 4: Verify storage tests**

Run: `pytest tests/test_storage.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/storage.py tests/test_storage.py
git commit -m "feat: add atomic Parquet price storage"
```

### Task 6: Add Chunked Yahoo Downloading And Retry

**Files:**
- Create: `src/stock_data/yahoo.py`
- Create: `tests/test_yahoo.py`

- [ ] **Step 1: Write failing adapter tests**

Mock `yfinance.download`. Assert chunks respect `batch_size`, calls contain
`auto_adjust=False`, `actions=False`, `progress=False`, configured timeout and
threads, and Yahoo's end argument is the inclusive end plus one day. Assert a
missing batch symbol is retried individually once and a still-empty symbol is
returned as a failure without stopping successful symbols.

```python
def test_download_converts_inclusive_end_to_exclusive(mocker, yahoo_client) -> None:
    download = mocker.patch("stock_data.yahoo.yf.download", return_value=batch_frame())
    yahoo_client.download(["TCS.NS"], date(2026, 6, 1), date(2026, 6, 5))
    assert download.call_args.kwargs["end"] == "2026-06-06"
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/test_yahoo.py -v`

Expected: FAIL because `YahooClient` does not exist.

- [ ] **Step 3: Implement the Yahoo adapter**

Define frozen `DownloadBatch(frames: dict[str, Any], errors: dict[str, str])`.
`YahooClient.download` chunks symbols, performs batch calls, splits returned
frames, and retries missing symbols individually once. Catch request exceptions
at chunk level, record every affected symbol as failed, and continue. Log batch
start/completion, ranges, row counts, retries, and exceptions through a module
logger.

- [ ] **Step 4: Verify Yahoo tests**

Run: `pytest tests/test_yahoo.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/yahoo.py tests/test_yahoo.py
git commit -m "feat: add chunked Yahoo downloader"
```

### Task 7: Orchestrate Initial, Incremental, And Range Updates

**Files:**
- Create: `src/stock_data/service.py`
- Create: `tests/test_service.py`

- [ ] **Step 1: Write failing orchestration tests**

Use fake storage and Yahoo clients. Cover initial start date, strict latest+1
incremental start, grouping symbols by start date, no call when already current,
explicit range ignoring stored latest date, per-symbol continuation, normalized
upsert, and failed/unchanged/success summaries.

```python
def test_incremental_update_starts_after_latest_date(service, yahoo) -> None:
    service.update(["TCS.NS"], completed_date=date(2026, 6, 5))
    assert yahoo.requests == [
        (["TCS.NS"], date(2026, 6, 5), date(2026, 6, 5))
    ]
```

In this fixture, storage's latest date is `2026-06-04`; the expected request
therefore begins strictly on `2026-06-05`.

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/test_service.py -v`

Expected: FAIL because `UpdateService` does not exist.

- [ ] **Step 3: Implement orchestration**

Define `SymbolStatus` enum, frozen `SymbolResult`, and frozen `UpdateSummary`
with computed counts and `has_failures`. `UpdateService.update` accepts symbols,
completed date, and either both explicit boundaries or neither. Build request
groups, call `YahooClient`, normalize each returned frame, upsert it, collect
results, and log per-symbol outcomes. Keep request planning, group processing,
and result construction in separate functions below 80 lines.

- [ ] **Step 4: Verify service tests**

Run: `pytest tests/test_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/service.py tests/test_service.py
git commit -m "feat: orchestrate stock data updates"
```

### Task 8: Add Logging And CLI Commands

**Files:**
- Create: `src/stock_data/logging_config.py`
- Create: `src/stock_data/cli.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_logging_config.py`

- [ ] **Step 1: Write failing CLI and logging tests**

Use Typer's `CliRunner`. Assert required `--config`, `update-all`,
`update-symbol`, paired date requirements, start-after-end rejection, summary
output, zero on total success, and non-zero on partial failure. Assert logging
creates a timestamped file and does not duplicate handlers across setup calls.

```python
def test_update_all_returns_nonzero_on_partial_failure(runner, mocker, config_path):
    mocker.patch("stock_data.cli.run_update_all", return_value=failed_summary())
    result = runner.invoke(app, ["--config", str(config_path), "update-all"])
    assert result.exit_code == 1
    assert "Failed: 1" in result.stdout
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest tests/test_cli.py tests/test_logging_config.py -v`

Expected: FAIL because CLI and logging modules do not exist.

- [ ] **Step 3: Implement logging and CLI**

`configure_logging(log_dir)` creates directories or raises `LoggingConfigError`,
then installs one detailed file handler and one concise console handler.

The Typer app requires `--config PATH`. Both commands load configuration before
work, initialize logging, determine the current completed date using an aware
UTC datetime, construct dependencies, run the service, print counts and failed
symbols, and raise `typer.Exit(1)` on any failure. Validate paired dates in one
shared callback/helper. Catch whole-command validation errors, log them, print a
clear message, and exit `2`.

- [ ] **Step 4: Verify CLI and logging tests**

Run: `pytest tests/test_cli.py tests/test_logging_config.py -v`

Expected: PASS.

- [ ] **Step 5: Verify installed command help**

Run: `stock-data --help && stock-data update-all --help && stock-data update-symbol --help`

Expected: all commands exit zero and document required arguments.

- [ ] **Step 6: Commit**

```bash
git add src/stock_data/logging_config.py src/stock_data/cli.py tests/test_cli.py tests/test_logging_config.py
git commit -m "feat: add stock data CLI and logging"
```

### Task 9: Document Setup And Every CLI Command

**Files:**
- Create: `README.md`
- Create: `COMMANDS.md`
- Test: `tests/test_documentation.py`

- [ ] **Step 1: Write failing documentation checks**

```python
@pytest.mark.parametrize(
    "command",
    [
        "stock-data --config PATH update-all",
        "stock-data --config PATH update-symbol SYMBOL",
        "--start-date YYYY-MM-DD --end-date YYYY-MM-DD",
    ],
)
def test_commands_document_contains_supported_commands(command: str) -> None:
    assert command in Path("COMMANDS.md").read_text(encoding="utf-8")
```

Also assert `README.md` mentions Python 3.12, installation, configuration,
Parquet schema, strict append behavior, date-range upserts, and links to
`COMMANDS.md`.

- [ ] **Step 2: Verify documentation checks fail**

Run: `pytest tests/test_documentation.py -v`

Expected: FAIL because the documentation files do not exist.

- [ ] **Step 3: Write README**

Document installation with `python -m pip install -e '.[dev]'`, the exact TOML
schema, symbol CSV schema, directories, normal and explicit-range behavior,
4:00 PM IST rule, failure behavior, Parquet schema, tests, and the exclusion of
web UI/backtesting/screening.

- [ ] **Step 4: Write COMMANDS.md**

For every supported invocation, include:

- purpose and prerequisites
- exact sample command with a real config path and symbol/date values
- representative successful console output
- representative partial-failure or validation output where applicable
- exit code (`0`, `1`, or `2`)

Cover `--help`, `update-all`, ranged `update-all`, `update-symbol`, and ranged
`update-symbol`.

- [ ] **Step 5: Verify documentation checks**

Run: `pytest tests/test_documentation.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add README.md COMMANDS.md tests/test_documentation.py
git commit -m "docs: add setup and CLI command examples"
```

### Task 10: Run Full Verification

**Files:**
- Modify only files directly required to fix verification failures.

- [ ] **Step 1: Check file and function size constraints**

Run:

```bash
find src tests -name '*.py' -print0 | xargs -0 wc -l
ruff check src tests
ruff format --check src tests
```

Expected: every file is below 800 lines; Ruff reports no errors. Manually split
any function over 80 lines before proceeding.

- [ ] **Step 2: Run the complete automated suite**

Run: `pytest -v`

Expected: PASS with no live Yahoo requests.

- [ ] **Step 3: Run CLI smoke checks**

Run:

```bash
stock-data --help
stock-data --config config/stock-data.toml update-all --help
stock-data --config config/stock-data.toml update-symbol --help
```

Expected: all help commands exit zero. Do not perform a live data download as
part of automated verification.

- [ ] **Step 4: Inspect repository cleanliness and diff**

Run: `git status --short && git diff --check`

Expected: no unintended generated price files, logs, caches, or whitespace
errors. Preserve unrelated user files and changes.

- [ ] **Step 5: Commit any verification-only fixes**

```bash
git diff --name-only -- src tests README.md COMMANDS.md pyproject.toml | xargs git add --
git commit -m "test: complete stock data repository verification"
```

Skip this commit when verification required no changes.
