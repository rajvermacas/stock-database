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
        "depth_p90": depth.quantile(0.90),
        "retrace_median": (df["retrace_pct"].drop_nulls() * 100).median(),
        "dominant_anchor": df["anchor"].mode().to_list()[:1],
        "success_rate": df.filter(pl.col("resolved"))["success"].mean(),
        "survivor_mfe_median": df.filter(pl.col("success"))["mfe_pct"].median(),
    }
```

`depth_iqr` IS the stock's own pullback band; `depth_p90` is its deep edge. The buy
window runs P25→P90, not the bare IQR: by construction 25% of the stock's OWN valid
dips are deeper than P75, so treating the IQR as a hard gate rejects a quarter of its
own history. Inside the IQR = "typical"; between P75 and P90 = "deeper than usual but
still its own behavior"; beyond P90 = atypical (caution label, Block 8). There is no
global depth threshold anywhere.

## Block 7b — Learned turn trigger (the stock's own rebound signature)

What did a *real* turn look like for THIS stock? Learn it from its own winning dips —
never a hardcoded "1 ATR" or a fixed EMA. For each successful event, find the first
up-thrust after the low (first bar whose `close` > the prior bar's `high` — a structural
primitive, like the fractal-pivot definition), then measure how far price had lifted off
the low **in the stock's own ATR** and the **highest EMA it genuinely reclaimed** (low was
below it, thrust close above it). Aggregate: median lift, modal reclaim-EMA, median lag.
All observable at that historical bar — no look-ahead. `success_key` selects which outcome
flag marks a winner (`"success"` for a single-symbol run; screening passes `"success_base"`,
the comparable @base yardstick).

```python
from collections import Counter

def learn_turn_trigger(df, events, success_key="success", min_winners=5):
    emas = ["ema_10", "ema_20", "ema_50", "ema_100", "ema_200"]
    idx_of = df.with_row_index("i")
    lifts, reclaims, lags = [], [], []
    for ev in events:
        if not ev.get(success_key):
            continue                                   # learn only from winners
        i = idx_of.filter(pl.col("trade_timestamp") == ev["low_ts"]).select("i").item()
        low_row = df.row(i, named=True)
        atr_L = low_row["atr_14"]
        if atr_L is None or atr_L == 0:
            continue                                   # warm-up low; cannot scale
        fwd = df.slice(i + 1)
        if fwd.height < 2:
            continue
        prev_high = fwd["high"].shift(1)
        thrust_mask = (fwd["close"] > prev_high).fill_null(False)
        tpos = next((j for j, m in enumerate(thrust_mask) if m), None)
        if tpos is None:
            continue                                   # recovered without an up-thrust bar
        trow = fwd.row(tpos, named=True)
        lifts.append((trow["close"] - ev["low"]) / atr_L)     # lift in the stock's own ATR
        lags.append(tpos + 1)                          # 1-based bars: low -> first thrust
        rec = "none"
        for e in reversed(emas):                       # highest genuinely reclaimed EMA
            le, te = low_row.get(e), trow.get(e)
            if le is not None and te is not None and ev["low"] < le and trow["close"] > te:
                rec = e
                break
        reclaims.append(rec)
    if len(lifts) < min_winners:
        return {"turn_learnable": False, "winners_used": len(lifts),
                "reason": "too few winning dips with an up-thrust to learn a trigger"}
    return {
        "turn_learnable": True,
        "winners_used": len(lifts),
        "learned_lift": float(pl.Series(lifts).median()),          # ATR-multiple, learned
        "learned_reclaim_ema": Counter(reclaims).most_common(1)[0][0],
        "learned_turn_lag": float(pl.Series(lags).median()),
    }
```

`learned_lift` is the stock's typical ATR-lift by its first up-thrust (median; tunable +
disclosed). `learned_reclaim_ema` is the EMA its rebounds genuinely reclaim (`none` is a
valid structural answer, like `dominant_anchor`). `< min_winners` usable winners →
`turn_learnable=False`; the caller must treat that as low-confidence, never invent a value.

## Block 8 — Current state (today's label)

Two hard-won rules are baked in. (1) Every depth is measured off the **live swing
high** (Block 8a), never the bare confirmed pivot — the confirmed high can be months
stale in a persistent rally, which flips a real deep dip into a negative "depth".
(2) Band membership is judged on the **live dip's LOW** (`dip_depth`, wick-to-wick,
same units as the historical events), never on today's close: a dip that tagged the
band and then turned — the exact setup being hunted — bounces its close back out of
the band, so a close-based gate mislabels the best entries as "wait".

```python
def current_state(df, zz, sig, trigger=None, late_rebound=0.62):
    last = df.row(df.height - 1, named=True)
    if not zz:
        return {"label": "no-match", "why": "no confirmed swing structure at all"}
    live = live_pullback_low(df, zz)          # Block 8b — anchored on the LIVE high (8a)
    ref = live["ref_high"]                    # the real reference high
    last_L = next((p for p in reversed(zz) if p[1] == "L"), None)
    structural_floor = last_L[2] if last_L else None  # last confirmed higher-low
    near_term = live["live_low"] if live["live_low"] is not None else structural_floor
    cur_depth = (ref["high"] - last["close"]) / ref["high"] * 100   # >= 0 by construction
    dip_depth = live.get("depth_from_high_pct")       # the dip LOW's depth — the gate
    lo, deep = sig["depth_iqr"][0], sig["depth_p90"]
    structure_intact = (live["live_low"] is None or structural_floor is None
                        or live["live_low"] > structural_floor)
    uptrend = last["ema_50"] > df["ema_50"][-20] and structure_intact
    rebound_frac = None                       # how much of the dip is already retraced
    if live["live_low"] is not None and ref["high"] > live["live_low"]:
        rebound_frac = (last["close"] - live["live_low"]) / (ref["high"] - live["live_low"])
    out = {"cur_depth": cur_depth, "dip_depth": dip_depth, "band": sig["depth_iqr"],
           "deep_edge": deep,
           "ref_high": ref["high"], "ref_high_ts": ref["high_ts"],
           "ref_high_confirmed": ref["confirmed"],
           "live_low": live["live_low"], "live_low_depth": dip_depth,
           "near_term_invalidation": near_term,    # QUOTE THIS as the stop, not the floor
           "structural_floor": structural_floor,   # confirmed HL; below it = trend break
           "rebound_frac": rebound_frac, "structure_intact": structure_intact,
           "success_rate": sig["success_rate"], "uptrend": uptrend}
    if not uptrend:
        out["label"] = "no-match"
        out["why"] = ("live low broke the confirmed higher-low (reversal, not pullback)"
                      if not structure_intact else "ema_50 not rising — no uptrend to dip in")
    elif dip_depth is None or dip_depth < lo:
        out["label"] = "pullback-coming/wait"
        out["why"] = "no dip yet as deep as its own band"
    elif dip_depth > deep:
        out["label"] = "dip-deeper-than-usual"
        out["why"] = "uptrend intact but the dip exceeds its own P90 depth — atypical, caution"
    elif rebound_frac is not None and rebound_frac > late_rebound:
        out["label"] = "late-rebound/watch"
        out["why"] = "dip already retraced most of the way back — buying here is a chase"
    else:
        out["label"] = "buyable-dip-now"
    # turn gate: an in-band live dip is a buy ONLY once the learned turn is reproduced
    if trigger is not None and out["label"] in ("buyable-dip-now", "dip-deeper-than-usual"):
        tr = live_turn(df, zz, trigger)            # Block 8c
        out["turn"] = tr
        if out["label"] == "buyable-dip-now":
            if tr["turn_learnable"] is False or tr["confirmed"] is None:
                out["label"] = "buyable-dip-now/turn-unconfirmable"
            elif tr["confirmed"]:
                out["label"] = "buy-the-dip-turned"
            else:
                out["label"] = "wait-not-turned"
    return out
```

`dip_depth` (the live low, wick-to-wick off the live high) decides band membership;
`cur_depth` (today's close) only says where price sits inside the dip. `rebound_frac`
guards the other side: a dip that already retraced more than `late_rebound` (trader's
fixed model knob, like the 3% stop — disclose it) is a chase, not an entry.
`dip-deeper-than-usual` keeps the turn info attached but never upgrades to BUY — an
atypically deep dip is evidence the character changed. The uptrend test is EMA slope
plus intact structure, deliberately NOT `close > ema_50`: dips below the 50-EMA are
normal (Block 5 stocks anchoring at ema_100/200 are below it by construction). The
matched past events (their dates) are the audit trail — always list them.

## Block 8a — Live swing high (the real reference high)

The confirmed zigzag is blind to the current high in TWO ways: `center=True` nulls
the last `k` bars (a fresh peak is invisible — and a fresh peak is where every new
pullback starts), and a persistent rally prints **no H pivot at all** because each
local max is exceeded within `k` bars — months can pass without a confirmed high.
Measuring "depth" off that stale pivot yields negative depths on ~a third of an
uptrending universe and mislabels real pullbacks as "near high / wait". Recover the
real reference from raw bars: the max high after the last confirmed LOW = the top of
the current leg.

```python
def live_swing_high(df, zz):
    last_L = next((p for p in reversed(zz) if p[1] == "L"), None)
    scope = df if last_L is None else df.filter(pl.col("trade_timestamp") > last_L[0])
    if scope.height == 0:
        raise ValueError("no bars after the last confirmed low — cannot anchor a live high")
    i = scope["high"].arg_max()
    high, high_ts = scope["high"][i], scope["trade_timestamp"][i]
    last_H = next((p for p in reversed(zz) if p[1] == "H"), None)
    return {"high": high, "high_ts": high_ts,
            "confirmed": last_H is not None and last_H[0] == high_ts}
```

Works for both pivot orders: `…L,H` + decline → picks the confirmed H (or a higher
edge-zone bar); `…H,L` + fresh leg → picks the current leg's raw top even though no H
pivot exists yet. `confirmed=False` flags that the reference is an unconfirmed raw
bar — disclose it, but never fall back to the stale pivot.

When a `trigger` (Block 7b) is passed, the `buyable-dip-now` state is split by the live turn
(Block 8c): `buy-the-dip-turned` (the dip reproduced the stock's learned trigger — a buy),
`wait-not-turned` (in band but no turn yet — the falling-knife hold, quote the buy trigger),
or `buyable-dip-now/turn-unconfirmable` (trigger unlearnable / warm-up — low-confidence).
Without a `trigger` the original `buyable-dip-now` label is unchanged (backward compatible).

## Block 8b — Live pullback low (the forming, unconfirmed swing)

The confirmed zigzag CANNOT see the most recent swing: `center=True` nulls the last
`k` bars, so the latest higher-low sits in the unconfirmable edge zone. **Invalidation
must NOT be read off confirmed pivots alone** — scan raw bars since the LIVE swing
high (Block 8a, never the stale confirmed pivot: scanning from a months-old confirmed
high returns a months-old "live low" and a garbage stop) to recover the live
higher-low. This is resolution-independent (reads raw lows), so it finds the recent
bottom regardless of `k` — no need to re-run at a finer `k`.

```python
def live_pullback_low(df, zz):
    ref = live_swing_high(df, zz)                  # Block 8a — the real reference high
    since = df.filter(pl.col("trade_timestamp") > ref["high_ts"])
    if since.height == 0:
        return {"live_low": None, "ref_high": ref}   # the high IS the last bar; no dip yet
    i = since["low"].arg_min()
    return {
        "live_low": since["low"][i],
        "live_low_ts": since["trade_timestamp"][i],
        "depth_from_high_pct": (ref["high"] - since["low"][i]) / ref["high"] * 100,
        "ref_high": ref,
    }
```

Two invalidation levels result, and the report must give both: the **live higher-low**
= near-term stop (this pullback failing → a lower-low forming), and the **prior
confirmed low** = structural floor (full uptrend break). Worked case: STYLAMIND.NS 1h
— confirmed high ₹3,279, live low ₹3,026 (near-term), prior confirmed low ₹2,772
(floor). Quoting ₹2,772 as "where you'd be wrong" is the bug; ₹3,026 is the real stop.

## Block 8c — Live turn check (the falling-knife gate)

Is the LIVE dip reproducing the stock's learned turn marker? **Union:** confirmed if the
live lift off the low has reached `learned_lift` (in the stock's own ATR) **OR** the dip
genuinely reclaimed `learned_reclaim_ema` (the live low broke below that EMA and close is
now back above it — a bare "close above EMA" on a shallow dip that never lost it is NOT a
reclaim). Returns the unmet-path trigger PRICE(s) so a not-yet name shows exactly what to
reclaim to flip to BUY. `confirmed is None` = cannot judge (trigger unlearnable / ATR
warm-up / no live dip) → low-confidence, never a buy.

```python
def live_turn(df, zz, trigger):
    if not trigger.get("turn_learnable"):
        return {"turn_learnable": False, "confirmed": None,
                "why": trigger.get("reason", "trigger not learnable")}
    live = live_pullback_low(df, zz)               # Block 8b — the forming low
    if live["live_low"] is None:
        return {"turn_learnable": True, "confirmed": None,
                "why": "no live dip (last high is the last bar)"}
    last = df.row(df.height - 1, named=True)
    atr_now = last["atr_14"]
    if atr_now is None or atr_now == 0:
        return {"turn_learnable": True, "confirmed": None,
                "why": "ATR warm-up — cannot scale live lift"}
    close, low = last["close"], live["live_low"]
    cur_lift = (close - low) / atr_now                            # lift in own ATR
    lift_ok = cur_lift >= trigger["learned_lift"]
    ema = trigger["learned_reclaim_ema"]
    ema_now = last.get(ema) if ema != "none" else None
    ema_at_low = None                                            # genuine reclaim needs the
    if ema != "none":                                            # dip to have BROKEN the EMA
        low_row = df.filter(pl.col("trade_timestamp") == live["live_low_ts"]).row(0, named=True)
        ema_at_low = low_row.get(ema)
    reclaim_ok = (ema_now is not None and ema_at_low is not None
                  and low < ema_at_low and close > ema_now)
    path = []
    if lift_ok: path.append("lift")
    if reclaim_ok: path.append("reclaim")
    return {
        "turn_learnable": True,
        "confirmed": bool(lift_ok or reclaim_ok),
        "path": path,                                            # which path(s) fired
        "cur_lift": cur_lift,
        "learned_lift": trigger["learned_lift"],
        "trigger_lift_price": low + trigger["learned_lift"] * atr_now,   # reclaim for lift path
        "reclaim_ema": ema,
        "trigger_ema_price": ema_now,                            # reclaim for ema path (None if 'none')
        "broke_ema": (ema_at_low is not None and low < ema_at_low),
        "live_low": low,
        "live_low_ts": live["live_low_ts"],
    }
```

A fresh-low last bar gives `cur_lift ≈ 0` and no reclaim → `confirmed=False` (the knife,
correctly held back). "Already bounced far past the trigger" is NOT decided here — Block 8's
`rebound_frac` / `late-rebound/watch` label handles it.

## Block 9 — Universe gate (Stage-1 screener)

Cheap, fully vectorized posture check over the whole universe; deep per-stock
analysis (Blocks 1–8) runs only on survivors.

```python
def universe_gate(interval="1d", lookback=20, high_lookback=60):
    lf = (pl.scan_parquet(f"market-data/prices/{interval}/*.parquet")
          .select("symbol","trade_timestamp","high","close")
          .sort("symbol","trade_timestamp"))
    g = (lf.group_by("symbol", maintain_order=True).agg([
            pl.col("close").last().alias("close"),
            pl.col("close").ewm_mean(span=50, adjust=False).last().alias("ema_50"),
            pl.col("close").ewm_mean(span=50, adjust=False).slice(-lookback,1).first().alias("ema_50_prev"),
            pl.col("high").tail(high_lookback).max().alias("recent_high"),
            pl.len().alias("bars"),
        ]))
    out = (g.filter(pl.col("bars") >= 60)
            .with_columns(((pl.col("recent_high")-pl.col("close"))/pl.col("recent_high")*100).alias("depth"))
            .filter(pl.col("ema_50") > pl.col("ema_50_prev"))
            .collect(engine="streaming"))
    return out  # rising-EMA symbols; sort/slice by depth to pick dippers
```

The gate is a rising-EMA posture check ONLY — deliberately NOT `close > ema_50`,
which silently drops every name currently below its 50-EMA mid-pullback, i.e. the
exact stocks the screen exists to find (Blocks 2–8 on the survivors do the real
judging). `recent_high` uses a longer window than the slope check so a multi-week dip
still measures against its real top. `bars >= 60` drops names too short to judge —
disclose how many were excluded.
