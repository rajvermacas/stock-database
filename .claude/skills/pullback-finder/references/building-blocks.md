# Building Blocks — the Polars grammar

These are **words, not sentences**. Adapt each block to the stock in front of you;
do not run them as a fixed pipeline. Pick every parameter (`k`, noise filter, depth
bands) from THIS stock's own data, never a global constant. Vectorized Polars does
the heavy lifting; the only Python-loop step is the sequential zigzag walk over the
already-reduced pivot set (Block 3), which is inherently sequential and tiny.

Load once per stock:

```python
import polars as pl

def load(symbol, interval):
    path = f"market-data/prices/{interval}/{symbol}.parquet"
    df = pl.scan_parquet(path).select(
        "trade_timestamp","open","high","low","close","volume"
    ).sort("trade_timestamp").collect()
    if df.height == 0:
        raise ValueError(f"no rows for {symbol} {interval}")
    return df
```

## Block 1 — Indicators (EMA, ATR)

```python
def add_indicators(df):
    df = df.with_columns([
        pl.col("close").ewm_mean(span=10, adjust=False).alias("ema_10"),
        pl.col("close").ewm_mean(span=20, adjust=False).alias("ema_20"),
        pl.col("close").ewm_mean(span=50, adjust=False).alias("ema_50"),
        pl.col("close").ewm_mean(span=100, adjust=False).alias("ema_100"),
        pl.col("close").ewm_mean(span=200, adjust=False).alias("ema_200"),
    ])
    df = df.with_columns(
        pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("close").shift(1)).abs(),
            (pl.col("low")  - pl.col("close").shift(1)).abs(),
        ).alias("tr")
    ).with_columns(pl.col("tr").rolling_mean(window_size=14).alias("atr_14"))
    return df
```

EMAs are computed on demand — disclose that. With < ~200 bars the longer EMAs are
warming up and the early rows are unreliable; check `df.height` first.

## Block 2 — Fractal pivots

A swing high = its `high` is the max within ±k bars; swing low symmetric. Choose `k`
from the stock's choppiness (start k=5 on daily; raise it for noisy names, lower for
smooth ones — justify the choice from the chart, not a default).

```python
def fractal_flags(df, k=5):
    w = 2 * k + 1
    return df.with_columns([
        (pl.col("high") == pl.col("high").rolling_max(w, center=True)).alias("is_ph"),
        (pl.col("low")  == pl.col("low").rolling_min(w, center=True)).alias("is_pl"),
    ])
```

The edges (first/last k bars) cannot be confirmed pivots — `rolling_*(center=True)`
yields nulls there, so they are not flagged. The latest unconfirmed swing is handled
separately in the current-state block.

## Block 3 — Zigzag (alternating pivots)

Raw fractal flags can place two highs (or two lows) in a row. Collapse to an
alternating L/H/L/H sequence, keeping the most extreme when the same type repeats.
This is a sequential walk over the small flagged set — Python here is correct and
clearer than a contorted vectorized version.

```python
def zigzag(flagged):
    piv = []
    for r in flagged.iter_rows(named=True):
        if r["is_ph"]: piv.append((r["trade_timestamp"], "H", r["high"]))
        if r["is_pl"]: piv.append((r["trade_timestamp"], "L", r["low"]))
    piv.sort(key=lambda x: x[0])
    zz = []
    for t, kind, price in piv:
        if zz and zz[-1][1] == kind:
            if (kind == "H" and price > zz[-1][2]) or (kind == "L" and price < zz[-1][2]):
                zz[-1] = (t, kind, price)
        else:
            zz.append((t, kind, price))
    return zz  # list of (timestamp, "H"|"L", price), strictly alternating
```

Optional noise filter: drop a pivot whose move from the previous pivot is smaller
than `noise_mult * atr` at that bar (pick `noise_mult` from how much the stock
wiggles — do not hardcode a global value).

## Block 4 — Up-legs and pullback events

A pullback only counts inside an uptrend. For each `H` preceded by a `L` and
followed by a `L`, it is a pullback iff the following low holds **above the prior
low** (higher-low intact = pullback, not a reversal). A low that breaks the prior
low is a reversal — exclude it as a structural failure of the preceding leg.

```python
def pullback_events(zz):
    events = []
    for i in range(2, len(zz)):
        if zz[i][1] == "L" and zz[i-1][1] == "H":
            H, L = zz[i-1], zz[i]
            prev_L = next((zz[j] for j in range(i-2, -1, -1) if zz[j][1] == "L"), None)
            if prev_L is None:
                continue
            leg_start = prev_L  # the higher-low the up-leg launched from
            held = L[2] > prev_L[2]
            depth_pct = (H[2] - L[2]) / H[2]
            retrace_pct = (H[2] - L[2]) / (H[2] - leg_start[2]) if H[2] > leg_start[2] else None
            events.append({
                "high_ts": H[0], "high": H[2],
                "low_ts": L[0], "low": L[2],
                "leg_start": leg_start[2],
                "held": held,                  # False = reversal, not a pullback
                "depth_pct": depth_pct,
                "retrace_pct": retrace_pct,
            })
    return [e for e in events if e["held"]]   # keep pullbacks; failures already logged
```

Confirm the up-leg is genuinely an uptrend, not just any H-after-L: require price
around `H` to sit above a rising longer EMA (e.g. `ema_50` rising over the leg). Add
that check from Block 1's columns when the stock's structure is ambiguous.
