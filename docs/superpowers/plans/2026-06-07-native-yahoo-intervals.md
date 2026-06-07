# Native Yahoo Intervals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support every native Yahoo interval using a unified timezone-aware timestamp schema and interval-separated Parquet storage.

**Architecture:** Add a centralized interval registry that drives validation, completed-candle filtering, incremental request boundaries, and output paths. Replace the daily-only `trade_date` contract with timezone-aware `trade_timestamp` in `Asia/Kolkata`, while retaining the existing configuration-driven CLI and per-symbol failure isolation.

**Tech Stack:** Python 3.12+, yfinance, Polars, pandas, Pydantic, Typer, pytest, Ruff

---

## File Map

- Create `src/stock_data/intervals.py`: native interval registry and completed-candle rules.
- Modify `src/stock_data/config.py`: validate configured interval through the registry.
- Modify `src/stock_data/normalization.py`: emit timezone-aware `trade_timestamp`.
- Modify `src/stock_data/storage.py`: write to `prices/<interval>/` and key by timestamp.
- Modify `src/stock_data/yahoo.py`: add interval-aware download exceptions and logs.
- Modify `src/stock_data/service.py`: interval-aware incremental requests and normalization.
- Modify `src/stock_data/cli.py`: construct interval-aware storage/service dependencies.
- Modify tests corresponding to each changed module.
- Modify `README.md`, `COMMANDS.md`, and `config/stock-data.toml`: document native intervals and output directories.

All Python files must remain below 800 lines and all functions below 80 lines.
Preserve the user's untracked `queries.sql`. The user has already changed
`config/stock-data.toml` to `interval = "1h"`; retain that value unless they
change it again.

### Task 1: Add The Native Interval Registry

**Files:**
- Create: `src/stock_data/intervals.py`
- Create: `tests/test_intervals.py`

- [ ] **Step 1: Write failing registry tests**

Test every native interval, invalid lookup behavior, fixed durations, and each
completed-candle strategy:

```python
ALL_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m",
    "1h", "1d", "5d", "1wk", "1mo", "3mo",
}


def test_registry_supports_all_native_intervals() -> None:
    assert set(INTERVALS) == ALL_INTERVALS


def test_intraday_completed_cutoff_excludes_active_candle() -> None:
    now = datetime(2026, 6, 8, 10, 47, tzinfo=IST)
    assert get_interval("30m").completed_cutoff(now) == datetime(
        2026, 6, 8, 10, 0, tzinfo=IST
    )
```

Also test `1h`/`60m` durations, daily cutoff before and after 4:00 PM IST, and
that `5d`, `1wk`, `1mo`, and `3mo` reject a timestamp in the current period.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_intervals.py -v`

Expected: FAIL because `stock_data.intervals` does not exist.

- [ ] **Step 3: Implement the registry**

Define:

```python
class IntervalCategory(StrEnum):
    INTRADAY = "intraday"
    DAILY = "daily"
    MULTI_DAY = "multi_day"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


@dataclass(frozen=True)
class IntervalSpec:
    name: str
    category: IntervalCategory
    duration: timedelta | None

    def is_complete(self, candle_start: datetime, now: datetime) -> bool:
        ...

    def next_request_start(self, latest: datetime) -> datetime:
        ...
```

Use explicit registry entries for all native intervals. Intraday completeness
uses `candle_start + duration <= now`; daily uses 4:00 PM IST; longer periods
compare the candle's calendar period with the current period. Raise
`UnsupportedIntervalError` from `get_interval(name)`.

- [ ] **Step 4: Run interval tests**

Run: `pytest tests/test_intervals.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/intervals.py tests/test_intervals.py
git commit -m "feat: add native Yahoo interval registry"
```

### Task 2: Validate Configuration Through The Registry

**Files:**
- Modify: `src/stock_data/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add failing configuration tests**

Parameterize every registry name and prove it loads. Prove an unsupported value
such as `2h` fails with an interval-specific message.

```python
@pytest.mark.parametrize("interval", sorted(INTERVALS))
def test_load_config_accepts_registered_interval(tmp_path: Path, interval: str) -> None:
    config = load_config(write_config(tmp_path, VALID.replace('interval = "1d"', f'interval = "{interval}"')))
    assert config.yahoo.interval == interval
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_config.py -v`

Expected: FAIL for intervals other than `1d`.

- [ ] **Step 3: Replace the literal type with registry validation**

Change `YahooConfig.interval` to `str` and add a Pydantic field validator that
calls `get_interval`. Do not add retention-range validation or fallback values.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_config.py tests/test_intervals.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/config.py tests/test_config.py
git commit -m "feat: validate all native Yahoo intervals"
```

### Task 3: Replace The Canonical Schema With Trade Timestamps

**Files:**
- Modify: `src/stock_data/normalization.py`
- Modify: `tests/test_normalization.py`

- [ ] **Step 1: Add failing timestamp normalization tests**

Cover timezone-aware intraday input, timezone-naive daily input, timezone
conversion to `Asia/Kolkata`, incomplete-candle filtering, timestamp
deduplication, and weekly/monthly current-period exclusion.

```python
def test_normalize_intraday_converts_timestamp_to_ist() -> None:
    result = normalize_symbol(
        "TCS.NS",
        intraday_frame("2026-06-08 04:15:00+00:00"),
        get_interval("30m"),
        datetime(2026, 6, 8, 10, 30, tzinfo=IST),
    )
    assert result["trade_timestamp"].to_list() == [
        datetime(2026, 6, 8, 9, 45, tzinfo=IST)
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_normalization.py -v`

Expected: FAIL because the schema still contains `trade_date`.

- [ ] **Step 3: Implement timestamp normalization**

Replace `trade_date` with:

```python
"trade_timestamp": pl.Datetime(time_unit="us", time_zone="Asia/Kolkata")
```

Convert timezone-aware Yahoo indexes to IST. Localize timezone-naive daily and
higher-period indexes to IST. Pass `IntervalSpec` and an aware `now` into
`normalize_symbol`, then filter rows with `interval.is_complete(timestamp, now)`.
Keep raw OHLCV, strict types, last-row deduplication, and ascending sorting.

- [ ] **Step 4: Run normalization tests**

Run: `pytest tests/test_normalization.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/normalization.py tests/test_normalization.py
git commit -m "feat: normalize all intervals to IST timestamps"
```

### Task 4: Separate Parquet Storage By Interval

**Files:**
- Modify: `src/stock_data/storage.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Add failing interval-storage tests**

Test path layout, timestamp-based latest/upsert/deduplication, exact timezone
schema validation, and invalid interval/symbol paths:

```python
def test_path_for_includes_interval_directory(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("30m"))
    assert store.path_for("TCS.NS") == tmp_path / "30m" / "TCS.NS.parquet"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_storage.py -v`

Expected: FAIL because `PriceStore` does not accept an interval.

- [ ] **Step 3: Implement interval-aware timestamp storage**

Require `IntervalSpec` in `PriceStore.__init__`. Make `path_for` use
`prices_dir / interval.name / f"{symbol}.parquet"`. Replace every logical key,
sort, latest-value, duplicate, and validation reference from `trade_date` to
`trade_timestamp`. Keep atomic temporary writes in the interval directory.

- [ ] **Step 4: Run storage tests**

Run: `pytest tests/test_storage.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/storage.py tests/test_storage.py
git commit -m "feat: store prices by native interval"
```

### Task 5: Add Interval-Aware Yahoo Errors

**Files:**
- Modify: `src/stock_data/yahoo.py`
- Modify: `tests/test_yahoo.py`

- [ ] **Step 1: Add failing Yahoo error tests**

Prove requests pass the configured interval unchanged and errors contain the
interval and inclusive requested range:

```python
def test_batch_error_contains_interval_and_range(mocker, yahoo_client) -> None:
    mocker.patch("stock_data.yahoo.yf.download", side_effect=RuntimeError("range unavailable"))
    result = yahoo_client.download(["TCS.NS"], date(2025, 1, 1), date(2026, 6, 1))
    assert "interval=1h" in result.errors["TCS.NS"]
    assert "start=2025-01-01" in result.errors["TCS.NS"]
    assert "end=2026-06-01" in result.errors["TCS.NS"]
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_yahoo.py -v`

Expected: FAIL because errors currently contain only the original message.

- [ ] **Step 3: Implement structured download errors**

Define `YahooDownloadError` carrying symbols, interval, start, end, and cause.
Use its message for per-symbol batch and retry errors. Include the interval and
range in download/retry logs. Continue sending `auto_adjust=False`,
`actions=False`, `progress=False`, and the configured native interval unchanged.
Do not add retention limits.

- [ ] **Step 4: Run Yahoo tests**

Run: `pytest tests/test_yahoo.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/yahoo.py tests/test_yahoo.py
git commit -m "feat: report interval-aware Yahoo download errors"
```

### Task 6: Make Update Orchestration Interval-Aware

**Files:**
- Modify: `src/stock_data/service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Add failing service tests**

Test:

- initial updates begin at configured date
- intraday incremental updates request the date containing the next timestamp
- daily and longer-period updates use registry boundaries
- explicit date ranges ignore latest timestamps
- completed-candle filtering receives an aware `now`
- planning/storage failures remain isolated

```python
def test_intraday_incremental_request_includes_next_candle_date() -> None:
    latest = datetime(2026, 6, 8, 14, 30, tzinfo=IST)
    service = build_service("30m", latest=latest)
    service.update(["TCS.NS"], now=datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert yahoo.requests[0].start == date(2026, 6, 8)
```

- [ ] **Step 2: Run service tests and verify failure**

Run: `pytest tests/test_service.py -v`

Expected: FAIL because orchestration is date/cutoff based.

- [ ] **Step 3: Implement interval-aware orchestration**

Require `IntervalSpec` in `UpdateService`. Replace `completed_date` with aware
`now`. Use the registry to determine whether stored data is current and to
calculate the next timestamp. Because yfinance's public range inputs are dates,
request the date containing the next required timestamp, then rely on
timestamp-key upserts to remove duplicates. Pass interval and `now` to
normalization. Keep explicit user date ranges inclusive and failure isolation.

- [ ] **Step 4: Run service tests**

Run: `pytest tests/test_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/service.py tests/test_service.py
git commit -m "feat: orchestrate interval-aware updates"
```

### Task 7: Wire Interval Support Into The CLI

**Files:**
- Modify: `src/stock_data/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_logging_config.py`

- [ ] **Step 1: Add failing CLI dependency-construction tests**

Prove the CLI uses configured interval storage and passes aware current time:

```python
def test_run_uses_configured_interval_directory(mocker, config_30m) -> None:
    store = mocker.patch("stock_data.cli.PriceStore")
    mocker.patch("stock_data.cli.UpdateService").return_value.update.return_value = empty_summary()
    run_update(config_30m, ["TCS.NS"], None, None)
    assert store.call_args.args[1].name == "30m"
```

Also prove validation errors still exit `2`, partial Yahoo failures exit `1`,
and output-root behavior remains controlled by `data_dir`.

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `pytest tests/test_cli.py tests/test_logging_config.py -v`

Expected: FAIL because CLI does not construct interval-aware dependencies.

- [ ] **Step 3: Implement CLI wiring**

Resolve `IntervalSpec` from `config.yahoo.interval`, construct
`PriceStore(config.paths.prices_dir, interval)`, construct the interval-aware
service, and pass `datetime.now(timezone.utc)` as the aware current time. Print
the configured interval and resolved price directory at command start. Preserve
existing exit codes and paired date behavior.

- [ ] **Step 4: Run CLI tests and help smoke checks**

Run:

```bash
pytest tests/test_cli.py tests/test_logging_config.py -v
stock-data --help
stock-data --config config/stock-data.toml update-all --help
stock-data --config config/stock-data.toml update-symbol --help
```

Expected: tests and help commands PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/cli.py tests/test_cli.py tests/test_logging_config.py
git commit -m "feat: wire native intervals into CLI"
```

### Task 8: Update Documentation And Examples

**Files:**
- Modify: `README.md`
- Modify: `COMMANDS.md`
- Modify: `config/stock-data.toml`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Add failing documentation tests**

Assert documentation includes:

```python
REQUIRED_TEXT = [
    "[paths]",
    'data_dir = "../market-data"',
    "prices/<interval>/<symbol>.parquet",
    "trade_timestamp",
    "Asia/Kolkata",
    "1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo",
]
```

Also assert `COMMANDS.md` includes configuration examples for `30m`, `1h`, and
`1d`, plus representative unavailable-range failure output.

- [ ] **Step 2: Run documentation tests and verify failure**

Run: `pytest tests/test_documentation.py -v`

Expected: FAIL until documentation is updated.

- [ ] **Step 3: Update README and COMMANDS**

Document output root resolution, interval selection through TOML, all native
intervals, interval directories, timestamp schema, completed-candle rules, raw
prices, no application retention limits, Yahoo runtime errors, and commands for
`30m`, `1h`, and `1d`.

Retain the user's current `interval = "1h"` example in
`config/stock-data.toml`. Do not modify or stage `queries.sql`.

- [ ] **Step 4: Run documentation tests**

Run: `pytest tests/test_documentation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit tracked documentation changes only**

```bash
git add README.md COMMANDS.md config/stock-data.toml tests/test_documentation.py
git commit -m "docs: document native interval downloads"
```

### Task 9: Run Automated Verification

**Files:**
- Modify only files directly required to fix verification failures.

- [ ] **Step 1: Run all automated tests**

Run: `pytest -v`

Expected: PASS with no live Yahoo requests.

- [ ] **Step 2: Run lint and formatting checks**

Run:

```bash
ruff check src tests
ruff format --check src tests
git diff --check
```

Expected: PASS.

- [ ] **Step 3: Verify size constraints**

Run:

```bash
find src tests -name '*.py' -print0 | xargs -0 wc -l
python - <<'PY'
import ast
from pathlib import Path

violations = []
for path in [*Path("src").rglob("*.py"), *Path("tests").rglob("*.py")]:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > 80:
                violations.append(f"{path}:{node.lineno} {node.name} {length}")
print("\n".join(violations))
raise SystemExit(bool(violations))
PY
```

Expected: every file is below 800 lines and the script prints no violations.

- [ ] **Step 4: Commit verification fixes when needed**

```bash
git diff --name-only -- src tests README.md COMMANDS.md config/stock-data.toml | xargs -r git add --
git commit -m "test: complete native interval verification"
```

Skip the commit if verification required no changes. Never stage `queries.sql`.

### Task 10: Perform Mandatory Bounded Live Verification

**Files:**
- Do not modify tracked files.
- Create temporary configuration and runtime data only under `/tmp`.

- [ ] **Step 1: Create temporary configs and symbol CSV**

Create a temporary root with one TOML file per representative interval and a
CSV containing `RELIANCE.NS`, `TCS.NS`, and `INFY.NS`. Each TOML must set an
absolute temporary `data_dir`; do not edit repository configuration.

- [ ] **Step 2: Live-test intraday, 30m, 1h, daily, and weekly**

Run bounded `update-symbol RELIANCE.NS` requests for:

```text
5m: recent 2-day range
30m: recent 5-day range
1h: recent 10-day range
1d: recent 10-day range
1wk: recent 3-month range
```

Choose ranges relative to the live-test date so intraday ranges remain recent.
Record each command's exit code and summary.

- [ ] **Step 3: Verify generated Parquet data**

Use Polars to assert for every successful file:

```python
assert frame.schema["trade_timestamp"] == pl.Datetime(
    time_unit="us", time_zone="Asia/Kolkata"
)
assert frame["symbol"].n_unique() == 1
assert frame["trade_timestamp"].is_sorted()
assert frame.unique(["symbol", "trade_timestamp"]).height == frame.height
```

Also assert files exist below `prices/<interval>/` and the latest intraday
candle is complete at inspection time.

- [ ] **Step 4: Verify batch splitting and idempotency**

Run a bounded `update-all` for `30m` across the three symbols. Repeat the exact
request and verify the second command reports every symbol unchanged.

- [ ] **Step 5: Verify Yahoo availability error behavior**

Run a deliberately old bounded `1m` request likely to exceed Yahoo availability.
If Yahoo returns an error or empty result, verify output contains symbol,
`interval=1m`, start, and end and exits non-zero. If Yahoo unexpectedly returns
data, report that observed behavior rather than claiming an error test passed.

- [ ] **Step 6: Verify repository cleanliness**

Run: `git status --short`

Expected: only the user's pre-existing untracked `queries.sql` may remain; no
temporary live-test files are created in the repository.

- [ ] **Step 7: Report live and automated results separately**

Report each live interval, rows written, timestamps, batch/idempotency result,
error-test observation, temporary data path, automated test count, and any
Yahoo-dependent limitations observed.

