# Precalculated Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically calculate and maintain a validated indicator Parquet file for each updated or backfilled symbol in the configured price interval.

**Architecture:** Keep raw `PriceStore` files unchanged. A focused calculator derives indicators from full persisted price history, `IndicatorStore` publishes validated Parquet plus source-fingerprint metadata, and `IndicatorUpdater` decides whether to calculate, skip, or remove insufficient-history output. `UpdateService` invokes that updater for every nonfailed symbol in the selected interval so existing price files are backfilled even when no new candle is downloaded.

**Tech Stack:** Python 3.12, Polars, TA-Lib, Pydantic, Typer, pytest, Ruff

---
## File Map
- Calculation: create `src/stock_data/indicators.py` and `tests/test_indicators.py`.
- Storage: create `src/stock_data/indicator_storage.py` and `tests/test_indicator_storage.py`.
- Refresh: create `src/stock_data/indicator_service.py` and `tests/test_indicator_service.py`.
- Integration: modify `config.py`, `service.py`, `cli.py`, and their matching tests.
- Packaging/docs: modify `pyproject.toml`, `config/stock-data.toml`, `README.md`, and `tests/test_documentation.py`.
## Task 1: Add Required Configuration And Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/stock_data/config.py`
- Modify: `config/stock-data.toml`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Add `[indicators]` to `VALID`, assert the resolved indicator directory, and test
that the required section and required `enabled` field fail fast:

```python
VALID = """
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
[indicators]
enabled = true
"""

def test_load_config_resolves_paths(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    config = load_config(path)
    assert config.paths.indicators_dir == config.paths.data_dir / "indicators"
    assert config.indicators.enabled is True

@pytest.mark.parametrize(
    "text",
    [
        VALID.replace("[indicators]\nenabled = true\n", ""),
        VALID.replace("enabled = true\n", ""),
    ],
)
def test_load_config_requires_indicator_settings(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, text))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`

Expected: FAIL because `indicators_dir` and `IndicatorsConfig` do not exist.

- [ ] **Step 3: Implement configuration and dependency**

Add to `pyproject.toml` dependencies:

```toml
"TA-Lib>=0.6",
```

Add to `src/stock_data/config.py`:

```python
class PathsConfig(StrictModel):
    data_dir: Path
    symbols_file: Path

    @property
    def indicators_dir(self) -> Path:
        return self.data_dir / "indicators"


class IndicatorsConfig(StrictModel):
    enabled: bool


class AppConfig(StrictModel):
    paths: PathsConfig
    download: DownloadConfig
    yahoo: YahooConfig
    indicators: IndicatorsConfig
```

Add to `config/stock-data.toml`:

```toml
[indicators]
enabled = true
```

- [ ] **Step 4: Install project dependencies and run tests**

Run: `python -m pip install -e '.[dev]'`

Expected: installation succeeds and `python -c "import talib"` exits `0`.

Run: `pytest tests/test_config.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add pyproject.toml src/stock_data/config.py config/stock-data.toml tests/test_config.py && git commit -m "feat: configure automatic indicators"`

## Task 2: Implement Core Indicator Calculations

**Files:**
- Create: `src/stock_data/indicators.py`
- Create: `tests/test_indicators.py`

- [ ] **Step 1: Write failing standard-indicator tests**

Create deterministic daily OHLCV history and compare calculator output to direct
TA-Lib calls:

```python
from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest
import talib

from stock_data.indicators import calculate_indicators
from stock_data.intervals import IST
from stock_data.normalization import CANONICAL_SCHEMA


def price_history(days: int = 500) -> pl.DataFrame:
    closes = [100.0 + index * 0.2 + (index % 7) for index in range(days)]
    return pl.DataFrame(
        {
            "symbol": ["TCS.NS"] * days,
            "trade_timestamp": [
                datetime(2024, 1, 1, tzinfo=IST) + timedelta(days=index)
                for index in range(days)
            ],
            "open": [value - 0.5 for value in closes],
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000 + index * 10 for index in range(days)],
        },
        schema=CANONICAL_SCHEMA,
    )


def test_standard_indicators_match_talib() -> None:
    prices = price_history()
    result = calculate_indicators(prices)
    last = result.row(-1, named=True)
    close = np.asarray(prices["close"], dtype=float)
    high = np.asarray(prices["high"], dtype=float)
    low = np.asarray(prices["low"], dtype=float)
    volume = np.asarray(prices["volume"], dtype=float)
    assert last["ema_200"] == pytest.approx(talib.EMA(close, 200)[-1])
    assert last["rsi_14"] == pytest.approx(talib.RSI(close, 14)[-1])
    assert last["atr_14"] == pytest.approx(talib.ATR(high, low, close, 14)[-1])
    assert last["adx_14"] == pytest.approx(talib.ADX(high, low, close, 14)[-1])
    assert last["obv"] == pytest.approx(talib.OBV(close, volume)[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_indicators.py::test_standard_indicators_match_talib -v`

Expected: FAIL because `stock_data.indicators` does not exist.

- [ ] **Step 3: Implement standard indicator expressions**

Create `src/stock_data/indicators.py` with:

```python
from __future__ import annotations

from datetime import timedelta

import numpy as np
import polars as pl
import talib

INDICATOR_COLUMNS = [
    "ema_10", "ema_20", "ema_50", "ema_100", "ema_200",
    "volume_ema_20", "relative_volume_20", "rsi_14", "atr_14",
    "atr_percent_14", "macd_12_26", "macd_signal_9", "macd_histogram",
    "adx_14", "plus_di_14", "minus_di_14", "band_upper_20_2",
    "band_middle_20", "band_lower_20_2", "band_width_20_2", "roc_20",
    "obv", "trailing_365d_high", "trailing_365d_low",
    "distance_from_365d_high_percent",
]
INDICATOR_SCHEMA = {
    "symbol": pl.String,
    "trade_timestamp": pl.Datetime(time_unit="us", time_zone="Asia/Kolkata"),
    **{column: pl.Float64 for column in INDICATOR_COLUMNS},
}


class IndicatorError(ValueError):
    """Raised when indicators cannot be calculated or validated."""


def _talib_columns(prices: pl.DataFrame) -> dict[str, np.ndarray]:
    close = prices["close"].to_numpy().astype(float)
    high = prices["high"].to_numpy().astype(float)
    low = prices["low"].to_numpy().astype(float)
    volume = prices["volume"].to_numpy().astype(float)
    macd, signal, histogram = talib.MACD(close, 12, 26, 9)
    return {
        "ema_10": talib.EMA(close, 10),
        "ema_20": talib.EMA(close, 20),
        "ema_50": talib.EMA(close, 50),
        "ema_100": talib.EMA(close, 100),
        "ema_200": talib.EMA(close, 200),
        "volume_ema_20": talib.EMA(volume, 20),
        "rsi_14": talib.RSI(close, 14),
        "atr_14": talib.ATR(high, low, close, 14),
        "macd_12_26": macd,
        "macd_signal_9": signal,
        "macd_histogram": histogram,
        "adx_14": talib.ADX(high, low, close, 14),
        "plus_di_14": talib.PLUS_DI(high, low, close, 14),
        "minus_di_14": talib.MINUS_DI(high, low, close, 14),
        "roc_20": talib.ROC(close, 20),
        "obv": talib.OBV(close, volume),
    }
```

Implement `calculate_indicators()` as small helpers that attach these arrays,
then return rows at least 365 calendar days after the first source timestamp:

```python
def calculate_indicators(prices: pl.DataFrame) -> pl.DataFrame | None:
    threshold = prices["trade_timestamp"].min() + timedelta(days=365)
    if prices["trade_timestamp"].max() < threshold:
        return None
    columns = [
        pl.Series(name, values, dtype=pl.Float64)
        for name, values in _talib_columns(prices).items()
    ]
    return prices.with_columns(columns).filter(pl.col("trade_timestamp") >= threshold)
```

- [ ] **Step 4: Run focused test and inspect current failure**

Run: `pytest tests/test_indicators.py::test_standard_indicators_match_talib -v`

Expected: PASS.

- [ ] **Step 5: Commit standard calculations**

Run: `git add src/stock_data/indicators.py tests/test_indicators.py && git commit -m "feat: calculate standard technical indicators"`

## Task 3: Complete Derived Columns, Calendar Window, And Validation

**Files:**
- Modify: `src/stock_data/indicators.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Write failing warm-up, calendar-window, and schema tests**

Add:

```python
def test_requires_full_365_calendar_days() -> None:
    prices = price_history(367)
    result = calculate_indicators(prices)
    assert result["trade_timestamp"].min() == prices["trade_timestamp"][365]


def test_trailing_high_uses_calendar_days_not_candle_count() -> None:
    prices = price_history(500).with_columns(
        pl.when(pl.int_range(pl.len()) == 100)
        .then(1000.0)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    result = calculate_indicators(prices)
    assert result.row(-1, named=True)["trailing_365d_high"] < 1000.0


def test_output_has_strict_finite_schema() -> None:
    result = calculate_indicators(price_history())
    assert result.schema == INDICATOR_SCHEMA
    assert result.null_count().select(pl.sum_horizontal(pl.all())).item() == 0
    assert np.isfinite(result.select(INDICATOR_COLUMNS).to_numpy()).all()


def test_insufficient_history_returns_none() -> None:
    assert calculate_indicators(price_history(365)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_indicators.py -v`

Expected: FAIL on missing derived columns, window logic, or return contract.

- [ ] **Step 3: Implement derived columns and strict result validation**

Use a dynamic Polars calendar window rather than a candle-count window:

```python
def _add_calendar_window(frame: pl.DataFrame) -> pl.DataFrame:
    return (
        frame.sort("trade_timestamp")
        .rolling(index_column="trade_timestamp", period="365d", closed="both")
        .agg(
            pl.col("symbol").last(),
            pl.all().exclude("symbol", "trade_timestamp").last(),
            pl.col("high").max().alias("trailing_365d_high"),
            pl.col("low").min().alias("trailing_365d_low"),
        )
    )


def _add_derived_columns(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        (pl.col("volume") / pl.col("volume_ema_20")).alias("relative_volume_20"),
        (pl.col("atr_14") / pl.col("close") * 100).alias("atr_percent_14"),
        pl.col("close").rolling_std(20).alias("close_std_20"),
    ).with_columns(
        pl.col("ema_20").alias("band_middle_20"),
        (pl.col("ema_20") + 2 * pl.col("close_std_20")).alias("band_upper_20_2"),
        (pl.col("ema_20") - 2 * pl.col("close_std_20")).alias("band_lower_20_2"),
        ((pl.col("close") / pl.col("trailing_365d_high") - 1) * 100).alias(
            "distance_from_365d_high_percent"
        ),
    ).with_columns(
        (
            (pl.col("band_upper_20_2") - pl.col("band_lower_20_2"))
            / pl.col("band_middle_20")
            * 100
        ).alias("band_width_20_2")
    )
```

`calculate_indicators(prices)` must:

1. Fail with `IndicatorError` for empty data, wrong canonical schema, mixed
   symbols, duplicate timestamps, or unsorted/invalid source values.
2. Return `None` when no timestamp is at least `timedelta(days=365)` after the
   earliest timestamp.
3. Attach TA-Lib columns and derived columns.
4. Filter to timestamps meeting full-history threshold.
5. Select `INDICATOR_SCHEMA` order and cast with `strict=True`.
6. Fail with `IndicatorError` if any null, NaN, or infinite value remains.

Keep each helper under 80 lines and `indicators.py` under 800 lines.

- [ ] **Step 4: Run calculation tests**

Run: `pytest tests/test_indicators.py -v`

Expected: PASS.

- [ ] **Step 5: Commit calculator**

Run: `git add src/stock_data/indicators.py tests/test_indicators.py && git commit -m "feat: calculate full indicator bundle"`

## Task 4: Implement Indicator Storage And Source Fingerprints

**Files:**
- Create: `src/stock_data/indicator_storage.py`
- Create: `tests/test_indicator_storage.py`

- [ ] **Step 1: Write failing path, fingerprint, and freshness tests**

Create tests using `price_history()` and calculated indicators:

```python
def test_paths_include_selected_interval(tmp_path: Path) -> None:
    store = IndicatorStore(tmp_path, get_interval("30m"))
    assert store.path_for("TCS.NS") == tmp_path / "30m" / "TCS.NS.parquet"
    assert store.metadata_path_for("TCS.NS") == (
        tmp_path / "30m" / "TCS.NS.metadata.json"
    )


def test_source_fingerprint_changes_for_historical_revision() -> None:
    prices = price_history()
    revised = prices.with_columns(
        pl.when(pl.int_range(pl.len()) == 10)
        .then(pl.col("close") + 1)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    assert source_fingerprint(prices) != source_fingerprint(revised)


def test_publish_and_read_metadata(tmp_path: Path) -> None:
    prices = price_history()
    indicators = calculate_indicators(prices)
    assert indicators is not None
    store = IndicatorStore(tmp_path, get_interval("1d"))
    store.publish("TCS.NS", indicators, source_fingerprint(prices))
    assert store.read("TCS.NS").equals(indicators)
    assert store.is_current("TCS.NS", source_fingerprint(prices))
```

Also test invalid symbol, invalid schema, corrupt metadata, removal of both
files, and rollback preserving prior valid files when a publication replacement
raises `OSError`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_indicator_storage.py -v`

Expected: FAIL because `stock_data.indicator_storage` does not exist.

- [ ] **Step 3: Implement fingerprint and store**

Implement these public contracts:

```python
class IndicatorStorageError(ValueError):
    """Raised when indicator storage is invalid or unavailable."""


@dataclass(frozen=True)
class IndicatorMetadata:
    source_fingerprint: str


def source_fingerprint(prices: pl.DataFrame) -> str:
    buffer = io.BytesIO()
    prices.select(CANONICAL_COLUMNS).write_ipc(buffer)
    return hashlib.sha256(buffer.getvalue()).hexdigest()
```

`IndicatorStore` must expose `path_for(symbol)`, `metadata_path_for(symbol)`,
`read(symbol)`, `is_current(symbol, fingerprint)`,
`publish(symbol, frame, fingerprint)`, and `remove(symbol)`. Constructor requires
`indicators_dir` and `interval`; none of these methods have default arguments.

Use `hashlib.sha256`, Polars/Arrow IPC serialization, and `json` structured
metadata. Do not use ad hoc delimited strings. Validate exact
`INDICATOR_SCHEMA`, one expected symbol, unique sorted timestamps, at least one
row, and finite/non-null indicator values.

`publish()` must stage and validate both temporary files before replacement.
Use backup paths and rollback on caught replacement errors so a normal storage
failure preserves the prior valid pair. Replace indicator first and metadata
last so an unexpected process crash leaves freshness false rather than falsely
current.

- [ ] **Step 4: Run storage tests**

Run: `pytest tests/test_indicator_storage.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/stock_data/indicator_storage.py tests/test_indicator_storage.py && git commit -m "feat: store indicators with source fingerprints"`

## Task 5: Implement One-Symbol Indicator Refresh

**Files:**
- Create: `src/stock_data/indicator_service.py`
- Create: `tests/test_indicator_service.py`

- [ ] **Step 1: Write failing refresh behavior tests**

Use fake price and indicator stores to cover:

```python
def test_missing_indicator_is_backfilled_when_price_unchanged() -> None:
    updater, indicator_store = build_updater(current=False)
    result = updater.refresh("TCS.NS", prices_changed=False)
    assert result.changed is True
    assert indicator_store.published_symbols == ["TCS.NS"]


def test_current_indicator_is_skipped_when_price_unchanged() -> None:
    updater, indicator_store = build_updater(current=True)
    result = updater.refresh("TCS.NS", prices_changed=False)
    assert result.changed is False
    assert indicator_store.published_symbols == []


def test_changed_price_forces_recalculation() -> None:
    updater, indicator_store = build_updater(current=True)
    updater.refresh("TCS.NS", prices_changed=True)
    assert indicator_store.published_symbols == ["TCS.NS"]


def test_insufficient_history_removes_stale_indicator(caplog) -> None:
    updater, indicator_store = build_updater(current=False, sufficient=False)
    result = updater.refresh("TCS.NS", prices_changed=False)
    assert result.changed is True
    assert indicator_store.removed_symbols == ["TCS.NS"]
    assert "Insufficient indicator history" in caplog.text
```

Also verify a missing price file raises a clear `IndicatorUpdateError`, and
calculator/storage exceptions preserve their cause.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_indicator_service.py -v`

Expected: FAIL because `stock_data.indicator_service` does not exist.

- [ ] **Step 3: Implement refresh service**

Create:

```python
@dataclass(frozen=True)
class IndicatorUpdateResult:
    changed: bool
    stored_rows: int


class IndicatorUpdateError(ValueError):
    """Raised when one symbol's indicators cannot be refreshed."""


class IndicatorUpdater:
    def __init__(self, price_store: PriceStore, indicator_store: IndicatorStore) -> None:
        self.price_store = price_store
        self.indicator_store = indicator_store

    def refresh(self, symbol: str, prices_changed: bool) -> IndicatorUpdateResult:
        prices = self.price_store.read(symbol)
        if prices is None:
            raise IndicatorUpdateError(f"Price data does not exist for {symbol}")
        fingerprint = source_fingerprint(prices)
        if not prices_changed and self.indicator_store.is_current(symbol, fingerprint):
            current = self.indicator_store.read(symbol)
            assert current is not None
            return IndicatorUpdateResult(False, current.height)
        indicators = calculate_indicators(prices)
        if indicators is None:
            removed = self.indicator_store.remove(symbol)
            LOGGER.warning(
                "Insufficient indicator history symbol=%s interval=%s source_rows=%d",
                symbol,
                self.price_store.interval.name,
                prices.height,
            )
            return IndicatorUpdateResult(removed, 0)
        self.indicator_store.publish(symbol, indicators, fingerprint)
        LOGGER.info(
            "Indicator refresh complete symbol=%s interval=%s source_rows=%d indicator_rows=%d",
            symbol,
            self.price_store.interval.name,
            prices.height,
            indicators.height,
        )
        return IndicatorUpdateResult(True, indicators.height)
```

Wrap calculator/storage errors in `IndicatorUpdateError` with symbol and interval
context. Keep `refresh()` under 80 lines.

- [ ] **Step 4: Run refresh tests**

Run: `pytest tests/test_indicator_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/stock_data/indicator_service.py tests/test_indicator_service.py && git commit -m "feat: refresh stale indicator files"`

## Task 6: Integrate Indicator Refresh Into Update Service

**Files:**
- Modify: `src/stock_data/service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Extend service fakes and write failing integration tests**

Add a fake updater that records `(symbol, prices_changed)` and can fail selected
symbols. Update `build_service()` to pass it explicitly.

Add tests:

```python
def test_indicator_backfill_runs_for_planned_unchanged_symbol() -> None:
    latest = datetime(2026, 6, 9, 14, 30, tzinfo=IST)
    service = build_service(latest=latest)
    summary = service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == [("TCS.NS", False)]
    assert summary.count(SymbolStatus.SUCCESS) == 1


def test_changed_price_triggers_indicator_refresh() -> None:
    service = build_service()
    service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert service.indicators.requests == [("TCS.NS", True)]


def test_indicator_failure_marks_symbol_failed_after_price_write() -> None:
    service = build_service(indicator_failed_symbol="TCS.NS")
    summary = service.update(["TCS.NS"], datetime(2026, 6, 8, 16, 30, tzinfo=IST))
    assert summary.count(SymbolStatus.FAILED) == 1
    assert service.store.upserted_symbols == ["TCS.NS"]
```

Also test Yahoo/price failures do not invoke indicator refresh and one indicator
failure does not stop other symbols.

- [ ] **Step 2: Run service tests to verify they fail**

Run: `pytest tests/test_service.py -v`

Expected: FAIL because `UpdateService` does not accept or invoke an updater.

- [ ] **Step 3: Integrate updater without growing long functions**

Change constructor to require an explicit updater state:

```python
def __init__(
    self,
    store: PriceStore,
    yahoo: YahooClient,
    indicators: IndicatorUpdater | None,
    interval: IntervalSpec,
    initial_start: date,
) -> None:
```

Track whether each nonfailed symbol's price changed. After price processing,
refresh indicators for every successful or unchanged symbol when `indicators` is
not `None`. A created/removed/recalculated indicator changes an otherwise
unchanged symbol status to `SUCCESS`. An indicator exception changes that symbol
to `FAILED` while retaining existing downloaded/stored row counts.

Extract focused helpers such as `_refresh_indicators()` and
`_replace_result()` so every function remains under 80 lines.

- [ ] **Step 4: Run service tests**

Run: `pytest tests/test_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/stock_data/service.py tests/test_service.py && git commit -m "feat: update indicators after price refresh"`

## Task 7: Wire CLI And Document Behavior

**Files:**
- Modify: `src/stock_data/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Write failing CLI and documentation tests**

Update the test `AppConfig` fixture with:

```python
"indicators": {"enabled": True},
```

Assert `_run()` constructs matching interval stores and passes an
`IndicatorUpdater`:

```python
def test_run_uses_matching_interval_for_prices_and_indicators(mocker, tmp_path: Path) -> None:
    config = enabled_config(tmp_path, "30m")
    price_store = mocker.patch("stock_data.cli.PriceStore")
    indicator_store = mocker.patch("stock_data.cli.IndicatorStore")
    indicator_updater = mocker.patch("stock_data.cli.IndicatorUpdater")
    update_service = mocker.patch("stock_data.cli.UpdateService")
    update_service.return_value.update.return_value = UpdateSummary(())
    _run(config, ["TCS.NS"], None, None)
    assert price_store.call_args.args[1].name == "30m"
    assert indicator_store.call_args.args[1].name == "30m"
    assert update_service.call_args.args[2] is indicator_updater.return_value
```

Add README required strings:

```python
"indicators/<interval>/<symbol>.parquet",
"full 365-calendar-day history",
"TA-Lib",
"Raw price files remain unchanged",
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py tests/test_documentation.py -v`

Expected: FAIL because CLI and README do not mention or construct indicators.

- [ ] **Step 3: Wire CLI dependencies**

Import and construct `IndicatorStore` and `IndicatorUpdater` in `_run()`:

```python
price_store = PriceStore(config.paths.prices_dir, interval)
indicator_updater = None
if config.indicators.enabled:
    indicator_store = IndicatorStore(config.paths.indicators_dir, interval)
    indicator_updater = IndicatorUpdater(price_store, indicator_store)
service = UpdateService(
    price_store,
    YahooClient(config.yahoo),
    indicator_updater,
    interval,
    config.download.initial_start_date,
)
```

Print selected indicator directory when enabled. Explicitly pass `None` when
disabled; do not introduce constructor defaults.

- [ ] **Step 4: Update README**

Document:

- automatic processing of updated, missing, or stale selected-interval files;
- separate price, indicator, and metadata paths;
- complete indicator column table and formulas;
- raw/unadjusted source implications;
- 365-calendar-day warm-up and insufficient-history warning behavior;
- TA-Lib installation dependency; and
- indicator failure preserving price data and causing symbol failure.

Remove the old statement that indicators are excluded.

- [ ] **Step 5: Run CLI and documentation tests**

Run: `pytest tests/test_cli.py tests/test_documentation.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run: `git add src/stock_data/cli.py tests/test_cli.py README.md tests/test_documentation.py && git commit -m "docs: wire automatic indicator updates"`

## Task 8: Full Verification And Constraint Audit

**Files:**
- Inspect all modified production and test files.

- [ ] **Step 1: Run full automated verification**

Run: `pytest -v`

Expected: all tests PASS.

Run: `ruff check src tests`

Expected: PASS.

Run: `ruff format --check src tests`

Expected: PASS.

- [ ] **Step 2: Audit size constraints**

Run: `wc -l src/stock_data/*.py tests/*.py README.md`

Expected: every file is at most 800 lines.

Run: `ruff check src tests --select C901`

Expected: PASS. Manually inspect every changed function and split any function
over 80 lines, even if Ruff does not flag it.

- [ ] **Step 3: Verify raw files and inspect final diff**

Add an integration test comparing price Parquet bytes before and after
`IndicatorUpdater.refresh()`; expect identical bytes plus indicator and metadata
files. Then run: `git status --short && git diff --check && git log --oneline -8`.

Expected: no whitespace errors, no unrelated changes, and only intended
uncommitted formatting fixes if any.

- [ ] **Step 4: Commit any verification fixes**

Run: `git add src tests README.md && git commit -m "test: verify automatic indicator pipeline"`

Skip this commit when verification required no changes.
