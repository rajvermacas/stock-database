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

## Block 5 — Anchor at the pullback low

Which structural thing did each pullback low tag? Measure distance from the low to
each EMA in ATR units (computed, not eyeballed). The nearest EMA within ~1 ATR is
the anchor for that event; "none" is a valid, informative answer.

```python
def anchor_for_low(df, low_ts):
    row = df.filter(pl.col("trade_timestamp") == low_ts).row(0, named=True)
    atr = row["atr_14"]
    if atr is None or atr == 0:
        raise ValueError(f"no ATR at {low_ts} (warm-up); need more history")
    dists = {ema: (row["low"] - row[ema]) / atr
             for ema in ("ema_10","ema_20","ema_50","ema_100","ema_200")
             if row[ema] is not None}
    nearest = min(dists, key=lambda e: abs(dists[e]))
    return {"anchor": nearest if abs(dists[nearest]) <= 1.0 else "none",
            "atr_dist": dists[nearest]}
```

Horizontal-support anchor: compare the low to prior pivot-high/low prices; if within
~1 ATR of a cluster of prior pivots, the anchor is that level. Add this when EMAs are
not the thing the stock respects.

## Block 6 — Forward outcome (double-barrier)

From each pullback low, does the stock resume to a new high before violating risk?
Risk barriers are the **trader's fixed model** (hard stop %, time-stop bars) —
explicit inputs, stated in output, distinct from the learned pattern bands.

```python
def outcome(df, ev, stop_pct=0.03, horizon=15):
    idx = df.with_row_index("i").filter(
        pl.col("trade_timestamp") == ev["low_ts"]).select("i").item()
    fwd = df.slice(idx + 1, horizon)               # bars after the low
    if fwd.height == 0:
        return {"resolved": False}                 # too recent to judge
    entry = ev["low"]
    stop = entry * (1 - stop_pct)
    hi, lo, H = fwd["high"], fwd["low"], ev["high"]
    bars_to_new_high = next((j for j, h in enumerate(hi) if h > H), None)
    bars_to_stop     = next((j for j, l in enumerate(lo) if l <= stop), None)
    success = bars_to_new_high is not None and (
        bars_to_stop is None or bars_to_new_high <= bars_to_stop)
    mfe = (hi.max() - entry) / entry
    return {"resolved": True, "success": success,
            "mfe_pct": mfe * 100, "bars_to_resume": bars_to_new_high}
```

## Block 7 — Signature (aggregate the stock's events)

```python
def signature(events):
    df = pl.DataFrame(events)
    n = df.height
    if n < 5:
        return {"n_events": n, "confidence": "low — insufficient history"}
    depth = df["depth_pct"] * 100
    return {
        "n_events": n,
        "confidence": "ok",
        "depth_median": depth.median(),
        "depth_iqr": [depth.quantile(0.25), depth.quantile(0.75)],
        "retrace_median": (df["retrace_pct"].drop_nulls() * 100).median(),
        "dominant_anchor": df["anchor"].mode().to_list()[:1],
        "success_rate": df.filter(pl.col("resolved"))["success"].mean(),
        "survivor_mfe_median": df.filter(pl.col("success"))["mfe_pct"].median(),
    }
```

`depth_iqr` IS the stock's own pullback band. A current dip inside it is "typical";
outside it is not. There is no global depth threshold anywhere.

## Block 8 — Current state (today's label)

```python
def current_state(df, zz, sig):
    last = df.row(df.height - 1, named=True)
    last_high = next((p for p in reversed(zz) if p[1] == "H"), None)
    if last_high is None:
        return {"label": "no-match", "why": "no confirmed swing high"}
    live = live_pullback_low(df, zz)               # Block 8b — recover edge-zone low
    hi_idx = max(i for i, p in enumerate(zz) if p[1] == "H")
    structural_floor = next((zz[j][2] for j in range(hi_idx - 1, -1, -1)
                             if zz[j][1] == "L"), None)   # prior confirmed HL = deep floor
    near_term = live["live_low"] if live["live_low"] is not None else structural_floor
    cur_depth = (last_high[2] - last["close"]) / last_high[2] * 100
    lo, hi = sig["depth_iqr"]
    uptrend = last["close"] > last["ema_50"] and last["ema_50"] > df["ema_50"][-20]
    out = {"cur_depth": cur_depth, "band": sig["depth_iqr"],
           "live_low": live["live_low"],
           "live_low_depth": live.get("depth_from_high_pct"),
           "near_term_invalidation": near_term,    # QUOTE THIS as the stop, not the floor
           "structural_floor": structural_floor,   # deeper break = full trend reversal
           "success_rate": sig["success_rate"], "uptrend": uptrend}
    if uptrend and lo <= cur_depth <= hi:
        out["label"] = "buyable-dip-now"
    elif uptrend and cur_depth < lo:
        out["label"] = "pullback-coming/wait"
        out["why"] = "near high, shallower than typical pullback band"
    else:
        out["label"] = "no-match"
    return out
```

`cur_depth` is measured off the latest close. A dip can tag the band and then bounce
before the last bar — so also check `live_low_depth`: if it landed in the band, a
swing low may already be in even when `cur_depth` looks shallow. The matched past
events (their dates) are the audit trail — always list them.

## Block 8b — Live pullback low (the forming, unconfirmed swing)

The confirmed zigzag CANNOT see the most recent swing: `center=True` nulls the last
`k` bars, so the latest higher-low sits in the unconfirmable edge zone. **Invalidation
must NOT be read off confirmed pivots alone** — scan raw bars since the last confirmed
high to recover the live higher-low. This is resolution-independent (reads raw lows),
so it finds the recent bottom regardless of `k` — no need to re-run at a finer `k`.

```python
def live_pullback_low(df, zz):
    last_high = next((p for p in reversed(zz) if p[1] == "H"), None)
    if last_high is None:
        raise ValueError("no confirmed swing high")
    since = df.filter(pl.col("trade_timestamp") > last_high[0])
    if since.height == 0:
        return {"live_low": None}            # high is the last bar; nothing formed yet
    i = since["low"].arg_min()
    return {
        "live_low": since["low"][i],
        "live_low_ts": since["trade_timestamp"][i],
        "depth_from_high_pct": (last_high[2] - since["low"][i]) / last_high[2] * 100,
    }
```

Two invalidation levels result, and the report must give both: the **live higher-low**
= near-term stop (this pullback failing → a lower-low forming), and the **prior
confirmed low** = structural floor (full uptrend break). Worked case: STYLAMIND.NS 1h
— confirmed high ₹3,279, live low ₹3,026 (near-term), prior confirmed low ₹2,772
(floor). Quoting ₹2,772 as "where you'd be wrong" is the bug; ₹3,026 is the real stop.

## Block 9 — Universe gate (Stage-1 screener)

Cheap, fully vectorized posture check over the whole universe; deep per-stock
analysis (Blocks 1–8) runs only on survivors.

```python
def universe_gate(interval="1d", lookback=20):
    lf = (pl.scan_parquet(f"market-data/prices/{interval}/*.parquet")
          .select("symbol","trade_timestamp","high","close")
          .sort("symbol","trade_timestamp"))
    g = (lf.group_by("symbol", maintain_order=True).agg([
            pl.col("close").last().alias("close"),
            pl.col("close").ewm_mean(span=50, adjust=False).last().alias("ema_50"),
            pl.col("close").ewm_mean(span=50, adjust=False).slice(-lookback,1).first().alias("ema_50_prev"),
            pl.col("high").tail(lookback).max().alias("recent_high"),
            pl.len().alias("bars"),
        ]))
    out = (g.filter(pl.col("bars") >= 60)
            .with_columns(((pl.col("recent_high")-pl.col("close"))/pl.col("recent_high")*100).alias("depth"))
            .filter((pl.col("close") > pl.col("ema_50")) & (pl.col("ema_50") > pl.col("ema_50_prev")))
            .collect(engine="streaming"))
    return out  # symbols in an uptrend; sort/slice by depth to pick dippers
```

`bars >= 60` drops names too short to judge — disclose how many were excluded.
