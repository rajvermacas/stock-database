# Adjusted Price Full Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist only adjusted Yahoo OHLCV and replace full history for the configured interval on every update.

**Architecture:** Keep Yahoo download, normalization, canonical schema, interval paths, and indicator interfaces. Change Yahoo to return adjusted OHLC, replace `PriceStore` merge/upsert with equality-aware full replacement, and simplify `UpdateService` so every symbol uses `initial_start_date` through today's date. Remove CLI date ranges and update all docs/data contracts that describe raw prices.

**Tech Stack:** Python 3.12+, yfinance, pandas, Polars, Pydantic, Typer, TA-Lib, pytest, Ruff

---

## File Structure

- Modify `src/stock_data/yahoo.py`: request adjusted OHLC from Yahoo.
- Modify `src/stock_data/storage.py`: provide validated, atomic, equality-aware full replacement.
- Modify `src/stock_data/service.py`: always request one configured full-history range.
- Modify `src/stock_data/cli.py`: remove date-range command options and plumbing.
- Modify `tests/test_yahoo.py`: assert adjusted Yahoo parameters.
- Modify `tests/test_storage.py`: verify full replacement, unchanged detection, and failure preservation.
- Modify `tests/test_service.py`: verify full-range requests, replacement, failures, and indicator behavior.
- Modify `tests/test_cli.py`: verify removed date options and simplified service call.
- Modify `README.md`, `COMMANDS.md`, `.agents/skills/talk-to-stock-data/SKILL.md`,
  `.agents/skills/talk-to-stock-data/references/data-contract.md`,
  `.agents/skills/find-similar-stock-setups/SKILL.md`, and
  `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`:
  describe adjusted prices accurately.
- Modify `tests/test_documentation.py` and `tests/test_find_similar_stock_setups.py`:
  enforce updated documentation and warning contracts.

### Task 1: Request Adjusted Yahoo Prices

**Files:**
- Modify: `tests/test_yahoo.py`
- Modify: `src/stock_data/yahoo.py`

- [ ] **Step 1: Change Yahoo parameter test to require adjusted prices**

Rename `test_download_converts_end_and_uses_raw_prices` and strengthen its
parameter assertions:

```python
def test_download_converts_end_and_uses_adjusted_prices(mocker) -> None:
    frame = pd.DataFrame({"Close": [1.0]})
    download = mocker.patch("stock_data.yahoo.yf.download", return_value=frame)
    client = YahooClient(
        YahooConfig(interval="1d", batch_size=2, timeout_seconds=30, threads=True)
    )
    result = client.download(["TCS.NS"], date(2026, 6, 1), date(2026, 6, 5))
    assert "TCS.NS" in result.frames
    assert download.call_args.kwargs["end"] == "2026-06-06"
    assert download.call_args.kwargs["auto_adjust"] is True
    assert download.call_args.kwargs["actions"] is False
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `uv run pytest tests/test_yahoo.py::test_download_converts_end_and_uses_adjusted_prices -v`

Expected: FAIL because `auto_adjust` is currently `False`.

- [ ] **Step 3: Switch the fixed Yahoo parameter**

In `YahooClient._parameters`, change only:

```python
"auto_adjust": True,
```

Keep `actions=False`, configured interval, timeout, threads, and end-date
conversion unchanged.

- [ ] **Step 4: Run Yahoo tests**

Run: `uv run pytest tests/test_yahoo.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Yahoo adjustment behavior**

```bash
git add src/stock_data/yahoo.py tests/test_yahoo.py
git commit -m "feat: download adjusted yahoo prices"
```

### Task 2: Replace Complete Price History Atomically

**Files:**
- Modify: `tests/test_storage.py`
- Modify: `src/stock_data/storage.py`

- [ ] **Step 1: Replace upsert tests with full replacement tests**

Remove `test_upsert_replaces_matching_timestamp` and
`test_latest_timestamp_and_duplicate_validation`. Add:

```python
def test_replace_removes_rows_absent_from_full_download(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("1d"))
    old = pl.concat(
        [
            frame(100.0, datetime(2026, 6, 4, tzinfo=IST)),
            frame(101.0, datetime(2026, 6, 5, tzinfo=IST)),
        ]
    )
    replacement = frame(105.0, datetime(2026, 6, 5, tzinfo=IST))
    store.write_atomic("TCS.NS", old)
    result = store.replace("TCS.NS", replacement)
    assert result.changed is True
    assert result.downloaded_rows == 1
    assert result.stored_rows == 1
    assert store.read("TCS.NS").equals(replacement)  # type: ignore[union-attr]


def test_replace_equal_history_is_unchanged(tmp_path: Path) -> None:
    store = PriceStore(tmp_path, get_interval("1d"))
    prices = frame(100.0)
    store.write_atomic("TCS.NS", prices)
    original = store.path_for("TCS.NS").read_bytes()
    result = store.replace("TCS.NS", prices)
    assert result == WriteResult(False, 1, 1)
    assert store.path_for("TCS.NS").read_bytes() == original


def test_replace_write_failure_preserves_existing_file(
    mocker, tmp_path: Path
) -> None:
    store = PriceStore(tmp_path, get_interval("1d"))
    store.write_atomic("TCS.NS", frame(100.0))
    original = store.path_for("TCS.NS").read_bytes()
    real_replace = os.replace

    def fail_destination_publish(source, destination):
        if Path(destination) == store.path_for("TCS.NS"):
            raise OSError("disk full")
        real_replace(source, destination)

    mocker.patch("stock_data.storage.os.replace", side_effect=fail_destination_publish)
    with pytest.raises(StorageError, match="disk full"):
        store.replace("TCS.NS", frame(105.0))
    assert store.path_for("TCS.NS").read_bytes() == original


def test_replace_changes_only_configured_interval(tmp_path: Path) -> None:
    daily = PriceStore(tmp_path, get_interval("1d"))
    hourly = PriceStore(tmp_path, get_interval("1h"))
    hourly.write_atomic("TCS.NS", frame(100.0))
    hourly_original = hourly.path_for("TCS.NS").read_bytes()
    daily.replace("TCS.NS", frame(105.0))
    assert daily.path_for("TCS.NS").exists()
    assert hourly.path_for("TCS.NS").read_bytes() == hourly_original
```

Retain duplicate validation coverage by writing duplicated rows directly and
asserting `store.read` raises `StorageError`. Add `import os` for the failure
test.

- [ ] **Step 2: Run storage tests and verify failure**

Run: `uv run pytest tests/test_storage.py -v`

Expected: FAIL because `PriceStore.replace` does not exist and current atomic
write does not restore the destination after `os.replace` failure.

- [ ] **Step 3: Implement equality-aware full replacement**

Remove `latest_timestamp` and `upsert`. Add:

```python
def replace(self, symbol: str, frame: pl.DataFrame) -> WriteResult:
    self._validate(symbol, frame)
    existing = self.read(symbol)
    if existing is not None and existing.equals(frame):
        return WriteResult(False, frame.height, existing.height)
    self.write_atomic(symbol, frame)
    return WriteResult(True, frame.height, frame.height)
```

Update `write_atomic` to stage and validate first, then preserve the old file
if publishing fails:

```python
def write_atomic(self, symbol: str, frame: pl.DataFrame) -> None:
    self._validate(symbol, frame)
    self.interval_dir.mkdir(parents=True, exist_ok=True)
    destination = self.path_for(symbol)
    temporary = self._stage(symbol, frame)
    backup = destination.with_name(f".{destination.name}.backup")
    try:
        if destination.exists():
            os.replace(destination, backup)
        os.replace(temporary, destination)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        if backup.exists():
            os.replace(backup, destination)
        raise StorageError(f"Unable to write {destination}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
```

Add a focused `_stage(symbol, frame) -> Path` helper that creates the temporary
file, writes it, reads it back, validates it, and deletes it before raising
`StorageError` on staging failure. Keep each function below 80 lines.

- [ ] **Step 4: Run storage tests**

Run: `uv run pytest tests/test_storage.py -v`

Expected: PASS.

- [ ] **Step 5: Commit replacement storage**

```bash
git add src/stock_data/storage.py tests/test_storage.py
git commit -m "feat: replace complete adjusted price history"
```

### Task 3: Always Refresh Configured Interval Full History

**Files:**
- Modify: `tests/test_service.py`
- Modify: `src/stock_data/service.py`

- [ ] **Step 1: Rewrite service fakes around replacement**

Replace `FakeStore.latest_timestamp` and `FakeStore.upsert` with:

```python
class FakeStore:
    def __init__(self, changed=True, failed_symbol=None) -> None:
        self.changed = changed
        self.failed_symbol = failed_symbol
        self.replaced_symbols = []

    def replace(self, symbol, frame):
        if symbol == self.failed_symbol:
            raise ValueError("invalid parquet")
        self.replaced_symbols.append(symbol)
        return WriteResult(self.changed, frame.height, frame.height)
```

Update `build_service` to accept `changed=True` instead of `latest`.

- [ ] **Step 2: Replace incremental/range tests with full-refresh tests**

Add:

```python
def test_update_requests_full_configured_history_for_all_symbols() -> None:
    service = build_service(interval="30m")
    service.update(
        ["TCS.NS", "INFY.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST)
    )
    assert service.yahoo.requests == [
        (["TCS.NS", "INFY.NS"], date(2000, 1, 1), date(2026, 6, 8))
    ]


def test_storage_failure_is_isolated() -> None:
    service = build_service(failed_symbol="BAD.NS")
    summary = service.update(
        ["BAD.NS", "TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST)
    )
    assert summary.count(SymbolStatus.FAILED) == 1
    assert summary.count(SymbolStatus.SUCCESS) == 1


def test_unchanged_full_history_does_not_force_indicator_recalculation() -> None:
    service = build_service(changed=False)
    service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == [("TCS.NS", False)]


def test_normalization_failure_does_not_replace_prices(mocker) -> None:
    service = build_service()
    malformed = pd.DataFrame(
        {"Close": [1.0]},
        index=pd.DatetimeIndex(["2026-06-08 09:15"], name="Datetime"),
    )
    mocker.patch.object(
        service.yahoo,
        "download",
        return_value=DownloadBatch({"TCS.NS": malformed}, {}),
    )
    summary = service.update(
        ["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST)
    )
    assert summary.count(SymbolStatus.FAILED) == 1
    assert service.store.replaced_symbols == []
```

Retain and adapt tests for Yahoo failure isolation, changed-price indicator
refresh, indicator failure, and no indicator refresh after price failure.
Assert `service.store.replaced_symbols` instead of `upserted_symbols`.

- [ ] **Step 3: Run service tests and verify failure**

Run: `uv run pytest tests/test_service.py -v`

Expected: FAIL because `UpdateService.update` still accepts ranges, plans
incrementally, and calls `upsert`.

- [ ] **Step 4: Simplify service to one full-range batch**

Change public update signature and flow:

```python
def update(self, symbols: list[str], now: datetime) -> UpdateSummary:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    results = self._process_group(
        symbols, self.initial_start, now.date(), now
    )
    results = self._refresh_indicators(results)
    ordered = sorted(results, key=lambda result: symbols.index(result.symbol))
    return UpdateSummary(tuple(ordered))
```

Delete `_plan` and `_incremental_start`. In `_process_symbol`, replace:

```python
write = self.store.replace(symbol, normalized)
```

Keep result ordering, per-symbol errors, logging, completed-candle filtering,
and indicator refresh behavior unchanged.

- [ ] **Step 5: Run service and indicator-service tests**

Run: `uv run pytest tests/test_service.py tests/test_indicator_service.py -v`

Expected: PASS.

- [ ] **Step 6: Commit full-refresh orchestration**

```bash
git add src/stock_data/service.py tests/test_service.py
git commit -m "feat: refresh configured interval full history"
```

### Task 4: Remove CLI Date Ranges

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/stock_data/cli.py`

- [ ] **Step 1: Replace range validation test with rejected-option tests**

Remove `test_unpaired_range_returns_validation_exit`. Add:

```python
@pytest.mark.parametrize("option", ["--start-date", "--end-date"])
def test_update_all_rejects_removed_date_options(tmp_path: Path, option: str) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    result = runner.invoke(
        app, ["--config", str(config), "update-all", option, "2026-06-01"]
    )
    assert result.exit_code == 2
    assert "No such option" in result.output
```

Import `pytest`. Update `test_run_uses_configured_interval` to call:

```python
_run(config, ["TCS.NS"])
update.assert_called_once()
assert update.call_args.args[0] == ["TCS.NS"]
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `uv run pytest tests/test_cli.py -v`

Expected: FAIL because date options and `_run` date parameters still exist.

- [ ] **Step 3: Remove date options and parsing**

Remove date parameters from `update_all`, `update_symbol`, `_execute`, and
`_run`. Delete `_parse_dates` and the unused `date` import. Call:

```python
summary = _run(config, symbols)
```

and:

```python
return service.update(symbols, datetime.now(timezone.utc))
```

- [ ] **Step 4: Run CLI tests**

Run: `uv run pytest tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 5: Commit CLI simplification**

```bash
git add src/stock_data/cli.py tests/test_cli.py
git commit -m "feat: remove partial price update options"
```

### Task 5: Update Documentation And Skill Data Contracts

**Files:**
- Modify: `README.md`
- Modify: `COMMANDS.md`
- Modify: `.agents/skills/talk-to-stock-data/SKILL.md`
- Modify: `.agents/skills/talk-to-stock-data/references/data-contract.md`
- Modify: `.agents/skills/find-similar-stock-setups/SKILL.md`
- Modify: `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`
- Modify: `tests/test_documentation.py`
- Modify: `tests/test_find_similar_stock_setups.py`

- [ ] **Step 1: Change documentation contract tests**

In `tests/test_documentation.py`, remove date-range command expectations and
replace raw/incremental expectations with:

```python
@pytest.mark.parametrize(
    "required",
    [
        "adjusted OHLCV",
        "initial_start_date",
        "full history",
        "Yahoo-provided volume",
        "prices/<interval>/<symbol>.parquet",
        "indicators/<interval>/<symbol>.parquet",
    ],
)
def test_readme_documents_required_behavior(required: str) -> None:
    assert required in Path("README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "forbidden",
    ["raw, unadjusted", "--start-date", "--end-date", "strictly after"],
)
def test_user_docs_do_not_describe_removed_behavior(forbidden: str) -> None:
    text = Path("README.md").read_text() + Path("COMMANDS.md").read_text()
    assert forbidden not in text
```

Update similarity-skill contract expectation from `"raw, unadjusted"` to
`"adjusted"`. In `tests/test_find_similar_stock_setups.py`, update the expected
report warning to match the new adjusted-price wording.

- [ ] **Step 2: Run documentation and skill tests and verify failure**

Run: `uv run pytest tests/test_documentation.py tests/test_find_similar_stock_setups.py -v`

Expected: FAIL because docs and skill contracts still describe raw data.

- [ ] **Step 3: Rewrite user docs for adjusted full refresh**

Document these exact behaviors in `README.md` and `COMMANDS.md`:

```text
Prices are adjusted OHLCV returned by Yahoo. Yahoo adjusts Open, High, Low,
and Close for corporate actions; volume is persisted exactly as Yahoo provides
it. Every command downloads full history from download.initial_start_date
through the latest completed candle for only the configured interval, then
atomically replaces that interval's symbol file when data changed.
```

Remove all date-range command sections and validation examples. Update indicator
language to say indicators derive from adjusted prices. Keep examples for
`update-all`, `update-symbol`, interval selection, paths, and exit codes.

- [ ] **Step 4: Update internal stock-analysis skill contracts**

Replace claims that current data and indicators are raw/unadjusted in both
stock-data skills and `data-contract.md`. In
`find_similar_setups.py`, change report warning to:

```python
"warning": "Prices are adjusted for corporate actions; volume is Yahoo-provided.",
```

Do not change similarity calculations or command interfaces.

- [ ] **Step 5: Run documentation and skill tests**

Run: `uv run pytest tests/test_documentation.py tests/test_find_similar_stock_setups.py -v`

Expected: PASS.

- [ ] **Step 6: Commit documentation and data contracts**

```bash
git add README.md COMMANDS.md tests/test_documentation.py \
  tests/test_find_similar_stock_setups.py \
  .agents/skills/talk-to-stock-data/SKILL.md \
  .agents/skills/talk-to-stock-data/references/data-contract.md \
  .agents/skills/find-similar-stock-setups/SKILL.md \
  .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py
git commit -m "docs: describe adjusted full-refresh price data"
```

### Task 6: Full Verification

**Files:**
- Verify all changed files

- [ ] **Step 1: Run complete automated suite**

Run: `uv run pytest -v`

Expected: PASS.

- [ ] **Step 2: Run lint and formatting checks**

Run: `uv run ruff check src tests .agents/skills/find-similar-stock-setups/scripts`

Expected: PASS.

Run: `uv run ruff format --check src tests .agents/skills/find-similar-stock-setups/scripts`

Expected: PASS.

- [ ] **Step 3: Verify removed behavior and adjusted contract**

Run:

```bash
rg -n "auto_adjust|start-date|end-date|latest_timestamp|\\.upsert\\(|raw, unadjusted|Current data is raw" src tests README.md COMMANDS.md .agents
```

Expected: `auto_adjust` appears with `True`; no active source, tests, user docs,
or skill contracts describe removed CLI ranges, incremental storage methods, or
raw/unadjusted current data. Historical design/plan documents are intentionally
excluded from this check.

- [ ] **Step 4: Verify line limits**

Run:

```bash
find src tests .agents/skills/find-similar-stock-setups/scripts \
  -type f -name '*.py' -print0 | xargs -0 wc -l
```

Expected: every file remains below 800 lines. Manually inspect changed
functions; every function remains at or below 80 lines.

- [ ] **Step 5: Perform isolated live verification**

Create temporary config and data directories outside tracked runtime paths.
Run one bounded symbol set for representative configured intervals such as
`1d` and `30m`, each using a recent `initial_start_date` to limit traffic:

```bash
uv run stock-data --config /tmp/stock-data-adjusted-1d.toml update-symbol TCS.NS
uv run stock-data --config /tmp/stock-data-adjusted-30m.toml update-symbol TCS.NS
```

Inspect each temporary Parquet file with Polars. Verify only its configured
interval path exists, schema is canonical, rows are sorted and unique, and a
second identical command reports unchanged. Yahoo availability failures are
acceptable only when clearly reported per symbol and must be recorded in final
verification notes.

- [ ] **Step 6: Commit any verification-only corrections**

If verification required corrections, rerun affected checks and commit only
those corrections:

```bash
git add <corrected-files>
git commit -m "fix: address adjusted refresh verification"
```
