# Stream Batched Stock Updates Design

## Goal

Reduce peak RAM during stock updates by fully processing one configured Yahoo
batch before downloading the next batch.

Peak RAM must scale primarily with `yahoo.batch_size`, rather than total symbol
count. Disk format, command behavior, and configuration remain unchanged.

## Current Problem

`YahooClient.download()` downloads symbols in configured chunks, but accumulates
every split pandas frame in one `DownloadBatch`. `UpdateService` starts
normalization, Parquet writes, and indicator refreshes only after all chunks
finish downloading.

This makes peak RAM grow with the complete requested symbol universe despite
Yahoo requests already being chunked.

## Architecture

`YahooClient` will expose a batch iterator that yields one completed
`DownloadBatch` per configured symbol chunk. Each yielded batch owns frames and
errors only for symbols in that chunk.

`UpdateService` will consume batches sequentially. It will normalize and
atomically write each symbol in the current batch, refresh indicators for its
nonfailed symbols, retain only lightweight `SymbolResult` values, then request
the next batch.

`YahooClient` remains responsible for:

- Splitting symbols according to `yahoo.batch_size`.
- Making Yahoo requests.
- Splitting batch responses into symbol frames.
- Retrying omitted symbols individually once.
- Reporting download errors by symbol.

`UpdateService` remains responsible for:

- Normalizing symbol frames.
- Writing price Parquet files.
- Refreshing indicators.
- Isolating processing failures by symbol.
- Returning the final ordered update summary.

## Data Flow

For each configured symbol chunk:

1. Download the Yahoo batch.
2. Split the response into per-symbol pandas frames.
3. Retry any omitted symbol individually once.
4. Yield frames and errors for only that chunk.
5. Normalize and atomically replace each successful symbol's price file.
6. Refresh indicators immediately for each nonfailed symbol result.
7. Retain only `SymbolResult` values after the chunk finishes.
8. Release chunk frames before downloading the next chunk.

Final results remain ordered according to the input symbol list.

At any point, expected large in-memory objects are limited to one Yahoo batch,
one symbol's normalized Polars frame, and one symbol's indicator calculation.

## Error Handling

A failed Yahoo batch produces failed results for every symbol in that batch.
Processing then continues with the next batch.

A symbol omitted from a successful batch receives the existing single-symbol
retry. If that retry fails or returns no usable data, only that symbol fails.

Normalization, price storage, or indicator refresh failures remain isolated to
the affected symbol. Existing valid atomic storage behavior remains unchanged.

No fallback values or silent recovery paths will be introduced.

## Compatibility

No configuration fields, CLI arguments, Parquet schemas, storage paths, retry
rules, or summary semantics will change.

`yahoo.batch_size` becomes the primary peak-RAM tuning control. Lower values
reduce peak RAM but increase request count and likely runtime.

## Testing

Tests will verify:

- Yahoo batches are yielded independently instead of accumulated.
- The second Yahoo batch starts only after first-batch price processing and
  indicator refresh complete.
- Batch failures continue to later batches and remain isolated by symbol.
- Missing-symbol individual retry behavior remains unchanged.
- Final results preserve input symbol order.
- Existing price storage and indicator behavior remain unchanged.

Verification commands:

```bash
pytest -v
ruff check src tests
ruff format --check src tests
```

## Out Of Scope

- Incremental history downloads.
- Parallel batch processing.
- Symbol-at-a-time Yahoo requests.
- Changes to Parquet compression or disk footprint.
- Changes to indicator formulas or storage.
