# Stream Batched Stock Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce peak update RAM by fully processing one configured Yahoo batch before downloading the next.

**Architecture:** Convert `YahooClient.download` from an all-symbol accumulator into a lazy `download_batches` iterator that yields one ordered `DownloadBatch` per configured chunk. Make `UpdateService` consume, write, and refresh indicators for each yielded batch before advancing the iterator, while retaining only lightweight results.

**Tech Stack:** Python 3.12, pandas, Polars, yfinance, pytest, pytest-mock, Ruff

---

## File Structure

- Modify `src/stock_data/yahoo.py`: expose lazy per-chunk downloads and keep retry/error ownership inside Yahoo client.
- Modify `tests/test_yahoo.py`: verify existing Yahoo behavior through batch iteration and prove downloads are lazy.
- Modify `src/stock_data/service.py`: process prices and indicators before requesting the next Yahoo batch.
- Modify `tests/test_service.py`: adapt fake Yahoo client and verify batch processing order, failures, and result order.
- Modify `README.md`: document bounded batch processing and `batch_size` RAM/runtime tradeoff.

### Task 1: Yield Yahoo Downloads One Batch At A Time

**Files:**
- Modify: `src/stock_data/yahoo.py`
- Test: `tests/test_yahoo.py`

- [ ] **Step 1: Change Yahoo tests to consume one yielded batch**

Import `Iterator` nowhere in tests. Add this helper near the imports:

```python
def download_one(client: YahooClient, symbols: list[str], start: date, end: date):
    batches = list(client.download_batches(symbols, start, end))
    assert len(batches) == 1
    return batches[0]
```

Replace each single-batch call shaped like:

```python
result = client.download(symbols, start, end)
```

with:

```python
result = download_one(client, symbols, start, end)
```

For the configured-chunks test, consume the iterator:

```python
batches = list(
    client.download_batches(
        ["TCS.NS", "INFY.NS"], date(2026, 6, 1), date(2026, 6, 5)
    )
)
assert len(batches) == 2
assert download.call_count == 2
```

- [ ] **Step 2: Add a failing test proving the second request is lazy**

Add to `tests/test_yahoo.py`:

```python
def test_download_batches_requests_next_chunk_only_when_consumed(mocker) -> None:
    download = mocker.patch(
        "stock_data.yahoo.yf.download",
        return_value=pd.DataFrame({"Close": [1.0]}),
    )
    client = YahooClient(
        YahooConfig(interval="1d", batch_size=1, timeout_seconds=30, threads=False)
    )

    batches = client.download_batches(
        ["TCS.NS", "INFY.NS"], date(2026, 6, 1), date(2026, 6, 5)
    )
    next(batches)
    assert download.call_count == 1

    next(batches)
    assert download.call_count == 2
```

- [ ] **Step 3: Run Yahoo tests to verify they fail**

Run:

```bash
pytest tests/test_yahoo.py -v
```

Expected: FAIL because `YahooClient` has no `download_batches`.

- [ ] **Step 4: Implement lazy Yahoo batch iteration**

In `src/stock_data/yahoo.py`, import `Iterator`:

```python
from collections.abc import Iterator
```

Add ordered chunk membership to `DownloadBatch`:

```python
@dataclass(frozen=True)
class DownloadBatch:
    symbols: tuple[str, ...]
    frames: dict[str, pd.DataFrame]
    errors: dict[str, str]
```

Replace `YahooClient.download` and change `_download_chunk` so each call owns and
returns only one chunk's data:

```python
def download_batches(
    self, symbols: list[str], start: date, end: date
) -> Iterator[DownloadBatch]:
    for chunk in _chunks(symbols, self.config.batch_size):
        yield self._download_chunk(chunk, start, end)

def _download_chunk(
    self,
    symbols: list[str],
    start: date,
    end: date,
) -> DownloadBatch:
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    LOGGER.info(
        "Downloading batch symbols=%d interval=%s start=%s end=%s",
        len(symbols),
        self.config.interval,
        start,
        end,
    )
    try:
        batch = yf.download(tickers=symbols, **self._parameters(start, end))
    except Exception as exc:
        LOGGER.exception("Yahoo batch failed symbols=%s", symbols)
        error = YahooDownloadError(symbols, self.config.interval, start, end, exc)
        errors.update({symbol: str(error) for symbol in symbols})
        return DownloadBatch(tuple(symbols), frames, errors)
    frames.update(split_batch_frame(batch, symbols))
    for symbol in set(symbols).difference(frames):
        self._retry_symbol(symbol, start, end, frames, errors)
    return DownloadBatch(tuple(symbols), frames, errors)
```

Delete the old accumulating `download` method. Keep `_retry_symbol`,
`_parameters`, and `_chunks` unchanged.

- [ ] **Step 5: Run Yahoo tests and line-limit checks**

Run:

```bash
pytest tests/test_yahoo.py -v
ruff check src/stock_data/yahoo.py tests/test_yahoo.py
wc -l src/stock_data/yahoo.py tests/test_yahoo.py
```

Expected: all Yahoo tests PASS; Ruff PASS; each file below 800 lines and each
changed function below 80 lines.

- [ ] **Step 6: Commit Yahoo iterator**

```bash
git add src/stock_data/yahoo.py tests/test_yahoo.py
git commit -m "Stream Yahoo downloads by batch"
```

### Task 2: Fully Process Each Batch Before Downloading Next Batch

**Files:**
- Modify: `src/stock_data/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Adapt `FakeYahoo` to yield configured batches**

Replace `FakeYahoo` in `tests/test_service.py` with:

```python
class FakeYahoo:
    def __init__(self, errors=None, batch_size=None, events=None) -> None:
        self.requests = []
        self.errors = errors or {}
        self.batch_size = batch_size
        self.events = events

    def download_batches(self, symbols, start, end):
        size = self.batch_size or len(symbols)
        for index in range(0, len(symbols), size):
            chunk = symbols[index : index + size]
            self.requests.append((chunk, start, end))
            if self.events is not None:
                self.events.append(f"download:{','.join(chunk)}")
            frame = pd.DataFrame(
                {
                    "Open": [1.0],
                    "High": [2.0],
                    "Low": [0.5],
                    "Close": [1.5],
                    "Volume": [10],
                },
                index=pd.DatetimeIndex([f"{end} 09:15"], name="Datetime"),
            )
            frames = {
                symbol: frame for symbol in chunk if symbol not in self.errors
            }
            errors = {
                symbol: self.errors[symbol]
                for symbol in chunk
                if symbol in self.errors
            }
            yield DownloadBatch(tuple(chunk), frames, errors)
```

Extend `FakeStore` and `FakeIndicators` constructors with optional `events`, and
append these events in `replace` and `refresh` before existing behavior:

```python
self.events.append(f"write:{symbol}")
self.events.append(f"indicator:{symbol}")
```

Guard both appends with `if self.events is not None`.

Extend `build_service` with `batch_size=None, events=None`, then pass both into
the fakes.

Update the normalization-failure test's direct batch construction to include
ordered symbols and patch `download_batches` with an iterator:

```python
mocker.patch.object(
    service.yahoo,
    "download_batches",
    return_value=iter([DownloadBatch(("TCS.NS",), {"TCS.NS": malformed}, {})]),
)
```

- [ ] **Step 2: Add failing batch-order and result-order tests**

Add to `tests/test_service.py`:

```python
def test_batch_is_fully_processed_before_next_download() -> None:
    events = []
    service = build_service(batch_size=1, events=events)

    service.update(
        ["TCS.NS", "INFY.NS"],
        datetime(2026, 6, 8, 16, 30, tzinfo=IST),
    )

    assert events == [
        "download:TCS.NS",
        "write:TCS.NS",
        "indicator:TCS.NS",
        "download:INFY.NS",
        "write:INFY.NS",
        "indicator:INFY.NS",
    ]


def test_results_preserve_input_order_across_batches() -> None:
    service = build_service(batch_size=1, errors={"BAD.NS": "missing"})

    summary = service.update(
        ["INFY.NS", "BAD.NS", "TCS.NS"],
        datetime(2026, 6, 8, 16, 30, tzinfo=IST),
    )

    assert [result.symbol for result in summary.results] == [
        "INFY.NS",
        "BAD.NS",
        "TCS.NS",
    ]
```

- [ ] **Step 3: Run service tests to verify they fail**

Run:

```bash
pytest tests/test_service.py -v
```

Expected: FAIL because `UpdateService` still calls `download`.

- [ ] **Step 4: Consume and finish each yielded batch in `UpdateService`**

In `src/stock_data/service.py`, replace the main body of `update` after timezone
validation:

```python
results = []
for batch in self.yahoo.download_batches(
    symbols, self.initial_start, now.date()
):
    batch_results = [
        self._process_symbol(symbol, batch.frames, batch.errors, now)
        for symbol in batch.symbols
    ]
    results.extend(self._refresh_indicators(batch_results))
ordered = sorted(results, key=lambda result: symbols.index(result.symbol))
return UpdateSummary(tuple(ordered))
```

Delete `_process_group`, which is no longer used.

This keeps indicator refresh inside the iterator loop. Advancing to the next
Yahoo batch cannot happen until all current-batch price and indicator work
finishes.

- [ ] **Step 5: Run focused tests and line-limit checks**

Run:

```bash
pytest tests/test_service.py tests/test_yahoo.py -v
ruff check src/stock_data/service.py tests/test_service.py
wc -l src/stock_data/service.py tests/test_service.py
```

Expected: all focused tests PASS; Ruff PASS; each file below 800 lines and each
changed function below 80 lines.

- [ ] **Step 6: Commit streamed service processing**

```bash
git add src/stock_data/service.py tests/test_service.py
git commit -m "Process stock updates one batch at a time"
```

### Task 3: Document RAM Behavior And Verify Repository

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document batch processing behavior**

Replace the first sentence of the README batch paragraph with:

```markdown
Symbols are downloaded in configurable batches. Each batch is fully normalized,
written, and processed for indicators before the next batch is downloaded, so
peak update RAM scales primarily with `yahoo.batch_size` rather than total symbol
count. Lower batch sizes reduce peak RAM but increase request count and likely
runtime.
```

Keep the existing retry and partial-failure sentences immediately afterward.

- [ ] **Step 2: Run complete verification**

Run:

```bash
pytest -v
ruff check src tests
ruff format --check src tests
git diff --check
wc -l src/stock_data/yahoo.py src/stock_data/service.py tests/test_yahoo.py tests/test_service.py README.md
```

Expected: all tests PASS; Ruff checks PASS; no whitespace errors; every file
below 800 lines and every changed function below 80 lines.

- [ ] **Step 3: Inspect final diff for scope**

Run:

```bash
git status --short
git diff --stat HEAD
git diff HEAD -- src/stock_data/yahoo.py src/stock_data/service.py tests/test_yahoo.py tests/test_service.py README.md
```

Expected: only requested streaming-batch implementation, tests, and README
documentation differ from the task's starting point. Preserve unrelated
`.dev-resources/prompts/.txt` changes without modifying or committing them.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md
git commit -m "Document streamed batch RAM behavior"
```
