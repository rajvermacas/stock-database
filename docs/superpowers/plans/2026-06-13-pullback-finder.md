# pullback-finder Skill Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to carry out this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Claude Code skill `pullback-finder` that is a *grammar of Polars building blocks* (not an engine), so the agent composes bespoke Polars on the fly per stock to learn each stock's own pullback signature from history and label its current state.

**Approach:** Author four files under `.claude/skills/pullback-finder/` — `SKILL.md` (methodology + hard rules), `references/data.md` (schema + scan idioms), `references/building-blocks.md` (the verified Polars grammar), `references/worked-example.md` (one real stock end-to-end). No monolithic analysis scripts. Every code block in the references has already been run against real data and works.

**Tools / Inputs:** Polars 1.41.2 (`.venv/bin/python`), Parquet under `market-data/prices/{1d,1h}/<SYMBOL>.parquet`, design spec `docs/superpowers/specs/2026-06-13-pullback-finder-design.md`.

---

## Verified data facts (ground truth for all snippets)

- Price schema: `symbol(str), trade_timestamp(Datetime us, Asia/Kolkata), open, high, low, close (f64), volume(i64)`.
- Stored intervals: `1d` (177 symbols), `1h` (172 symbols). Universe list: `market-data/metadata/symbols.csv` (header `symbol`).
- 1d history depth: min 36, median 381, max 1593 bars. **Thin history is normal** — fail-fast / low-confidence on small event counts is central, not an edge case.
- Filenames are Yahoo-style: `ABSLAMC.NS.parquet`. Timestamps are timezone-aware `Asia/Kolkata`.
- Prototype result on ABSLAMC.NS 1d (k=5 fractal, HL-holding filter): **10 pullback events, depth 4.3%–17.1%, median ≈9.3%**. Weekly derive from 381 daily bars = 80 weekly bars (too few to mine — must be disclosed).

---

## Task 1: Scaffold skill + data reference

**Inputs/Outputs:**
- Create: `.claude/skills/pullback-finder/references/data.md`
- Done-check: file exists; the scan idiom in it runs and prints the schema.

- [ ] **Step 1: Create the data reference**

Create `.claude/skills/pullback-finder/references/data.md`:

````markdown
# Data Reference — Parquet Market Data

Read-only. Run everything from the repo root with `.venv/bin/python`. Polars 1.41.2.

## Layout

```
market-data/
  prices/<interval>/<SYMBOL>.parquet   # OHLCV per symbol
  metadata/symbols.csv                 # universe list (header: symbol)
```

- Stored intervals: `1d`, `1h`. Symbols Yahoo-style, e.g. `ABSLAMC.NS`.
- One file per symbol per interval. Filename = `<SYMBOL>.parquet`.

## Prices schema

`symbol(str), trade_timestamp(Datetime[us, Asia/Kolkata]), open, high, low, close(f64), volume(i64)`

- `trade_timestamp` is timezone-aware `Asia/Kolkata`. Keep any timestamp literal
  tz-aware so it stays a pushdown-eligible predicate.
- 1d history is short for many names (min 36, median 381, max 1593 bars). Always
  check row count before trusting any statistic.

## Lazy scan idiom (pushdown)

```python
import polars as pl

lf = (
    pl.scan_parquet("market-data/prices/1d/ABSLAMC.NS.parquet")
    .select("trade_timestamp", "open", "high", "low", "close", "volume")
    .sort("trade_timestamp")
)
df = lf.collect()  # one collect per question
print(df.schema, df.height)
```

- Start from `scan_parquet`, never `read_parquet`. `.select(...)` early (projection
  pushdown); `.filter(...)` right after the scan (predicate pushdown).
- Whole-universe scans: pass a glob `market-data/prices/1d/*.parquet` to one
  `scan_parquet` and `group_by` — never loop `read_parquet` per file.
- Use `collect(engine="streaming")` for whole-universe aggregations.

## Deriving a non-stored timeframe

Only `1d` and `1h` are stored. For weekly/monthly, derive from `1d` and disclose it
as on-demand:

```python
wk = (
    df.group_by_dynamic("trade_timestamp", every="1w", closed="left")
      .agg(pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
           pl.col("close").last(), pl.col("volume").sum())
)
```

Note: 381 daily bars → only ~80 weekly bars. Derived long timeframes often have too
few bars to mine pullbacks — say so.
````

- [ ] **Step 2: Verify it's done**

Run the scan idiom from the reference against a real file:
```bash
cd /workspaces/stock-database && .venv/bin/python -c "
import polars as pl
df = pl.scan_parquet('market-data/prices/1d/ABSLAMC.NS.parquet').select('trade_timestamp','open','high','low','close','volume').sort('trade_timestamp').collect()
print(df.schema, df.height)"
```
Expected: prints the 6-column schema and `381`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pullback-finder/references/data.md
git commit -m "feat(pullback-finder): add data reference"
```

---

## Task 2: Building-blocks grammar — indicators + pivots

**Inputs/Outputs:**
- Create: `.claude/skills/pullback-finder/references/building-blocks.md` (start it here; later tasks append)
- Done-check: the indicator + fractal-pivot blocks run on ABSLAMC.NS and print pivots.

- [ ] **Step 1: Create building-blocks.md with the intro + first two blocks**

Create `.claude/skills/pullback-finder/references/building-blocks.md`:

````markdown
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
````

- [ ] **Step 2: Verify it's done**

```bash
cd /workspaces/stock-database && .venv/bin/python -c "
import polars as pl
df = pl.scan_parquet('market-data/prices/1d/ABSLAMC.NS.parquet').select('trade_timestamp','open','high','low','close','volume').sort('trade_timestamp').collect()
df = df.with_columns([pl.col('close').ewm_mean(span=20, adjust=False).alias('ema_20')])
w=11
f = df.with_columns([(pl.col('high')==pl.col('high').rolling_max(w,center=True)).alias('is_ph'),(pl.col('low')==pl.col('low').rolling_min(w,center=True)).alias('is_pl')])
print('highs', f['is_ph'].sum(), 'lows', f['is_pl'].sum())"
```
Expected: `highs 22 lows 23` (k=5 on ABSLAMC.NS).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pullback-finder/references/building-blocks.md
git commit -m "feat(pullback-finder): grammar blocks 1-2 (indicators, pivots)"
```

---

## Task 3: Building-blocks grammar — zigzag, up-legs, pullback events

**Inputs/Outputs:**
- Modify: `.claude/skills/pullback-finder/references/building-blocks.md` (append blocks 3–4)
- Done-check: extracting events on ABSLAMC.NS yields 10 HL-holding pullbacks.

- [ ] **Step 1: Append blocks 3 and 4**

Append to `references/building-blocks.md`:

````markdown
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
````

- [ ] **Step 2: Verify it's done**

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import polars as pl
df = pl.scan_parquet('market-data/prices/1d/ABSLAMC.NS.parquet').select('trade_timestamp','high','low').sort('trade_timestamp').collect()
w=11
f = df.with_columns([(pl.col('high')==pl.col('high').rolling_max(w,center=True)).alias('is_ph'),(pl.col('low')==pl.col('low').rolling_min(w,center=True)).alias('is_pl')])
piv=[]
for r in f.iter_rows(named=True):
    if r['is_ph']: piv.append((r['trade_timestamp'],'H',r['high']))
    if r['is_pl']: piv.append((r['trade_timestamp'],'L',r['low']))
piv.sort(key=lambda x:x[0]); zz=[]
for t,k,p in piv:
    if zz and zz[-1][1]==k:
        if (k=='H' and p>zz[-1][2]) or (k=='L' and p<zz[-1][2]): zz[-1]=(t,k,p)
    else: zz.append((t,k,p))
ev=[]
for i in range(2,len(zz)):
    if zz[i][1]=='L' and zz[i-1][1]=='H':
        pl_=next((zz[j] for j in range(i-2,-1,-1) if zz[j][1]=='L'),None)
        if pl_ and zz[i][2]>pl_[2]: ev.append(round((zz[i-1][2]-zz[i][2])/zz[i-1][2]*100,1))
print('events', len(ev), ev)
PY
```
Expected: `events 10 [12.0, 6.2, 9.2, 11.1, 7.0, 4.3, 10.8, 9.6, 17.1, 9.3]`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pullback-finder/references/building-blocks.md
git commit -m "feat(pullback-finder): grammar blocks 3-4 (zigzag, events)"
```

---

## Task 4: Building-blocks grammar — anchor, outcome, signature, current-state, gate

**Inputs/Outputs:**
- Modify: `.claude/skills/pullback-finder/references/building-blocks.md` (append blocks 5–9)
- Done-check: signature + outcome run on ABSLAMC.NS and print a success_rate and median depth; gate runs over the universe glob.

- [ ] **Step 1: Append blocks 5–9**

Append to `references/building-blocks.md`:

````markdown
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
    cur_depth = (last_high[2] - last["close"]) / last_high[2] * 100
    lo, hi = sig["depth_iqr"]
    uptrend = last["close"] > last["ema_50"] and last["ema_50"] > df["ema_50"][-20]
    if uptrend and lo <= cur_depth <= hi:
        return {"label": "buyable-dip-now", "cur_depth": cur_depth,
                "band": sig["depth_iqr"], "success_rate": sig["success_rate"]}
    if uptrend and cur_depth < lo:
        return {"label": "pullback-coming/wait", "cur_depth": cur_depth,
                "why": "near high, shallower than typical pullback band"}
    return {"label": "no-match", "cur_depth": cur_depth, "uptrend": uptrend}
```

The matched past events (their dates) are the audit trail — always list them so the
trader can eyeball the resemblance.

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
````

- [ ] **Step 2: Verify it's done**

Signature/outcome on one stock and the gate over the universe:
```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import polars as pl
# gate over universe
lf = pl.scan_parquet('market-data/prices/1d/*.parquet').select('symbol','trade_timestamp','high','close').sort('symbol','trade_timestamp')
g = (lf.group_by('symbol', maintain_order=True).agg([
      pl.col('close').last().alias('close'),
      pl.col('close').ewm_mean(span=50, adjust=False).last().alias('ema_50'),
      pl.col('close').ewm_mean(span=50, adjust=False).slice(-20,1).first().alias('ema_50_prev'),
      pl.len().alias('bars')]))
out = g.filter((pl.col('bars')>=60)&(pl.col('close')>pl.col('ema_50'))&(pl.col('ema_50')>pl.col('ema_50_prev'))).collect(engine='streaming')
print('universe uptrend survivors:', out.height, 'of 177')
assert out.height > 0
print('OK')
PY
```
Expected: prints a survivor count between 1 and 177 and `OK`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pullback-finder/references/building-blocks.md
git commit -m "feat(pullback-finder): grammar blocks 5-9 (anchor, outcome, signature, state, gate)"
```

---

## Task 5: SKILL.md — methodology and hard rules

**Inputs/Outputs:**
- Create: `.claude/skills/pullback-finder/SKILL.md`
- Done-check: front-matter `name`/`description` present; file references the three reference docs and states the required-timeframe and fail-fast rules.

- [ ] **Step 1: Write SKILL.md**

Create `.claude/skills/pullback-finder/SKILL.md`:

````markdown
---
name: pullback-finder
description: Find pullbacks in the Parquet stock universe (or for one named symbol) by learning each stock's OWN pullback signature from its history, then labeling its current state. Use when the user asks to screen for pullbacks, "is X pulling back / in a buyable dip", or to study how a stock pulls back. Requires a user-supplied timeframe.
---

# Pullback Finder

Find pullbacks by reading each stock's own history. A pullback is NOT a fixed rule:
in a bullish trend a valid pullback is recognized from how THAT stock has pulled back
before. So first learn the stock's own pullback signature from its data, then check
whether the current state matches it.

This skill is a **grammar, not an engine**. It ships Polars building blocks and a
schema reference. YOU write and run bespoke Polars on the fly for each stock,
composing the blocks like words into sentences. Static, one-size pipelines are
wrong — every stock's nature differs.

## Required input

- **Timeframe is mandatory and user-supplied.** Never assume or default it. If the
  user did not give one, ask before doing anything. Stored: `1d`, `1h`. Other frames
  (e.g. `1wk`) are derived from `1d` on the fly and disclosed; warn when the derived
  series is too short (381 daily → ~80 weekly bars).
- Symbol is optional: none → universe screener; symbol given → single-stock report.

## How to use the grammar

1. Read `references/data.md` for schema and the lazy-scan idiom.
2. Read `references/building-blocks.md` — the blocks. Adapt every parameter (`k`,
   noise filter, depth bands) to the stock from its own data; never hardcode a
   global value.
3. See `references/worked-example.md` for one stock strung end-to-end.

## Workflow — single symbol

1. `load` → `add_indicators` (Block 1). Check `df.height`; if too short to warm the
   EMAs you use, say so.
2. `fractal_flags` → `zigzag` (Blocks 2–3); pick `k` from the stock's choppiness.
3. `pullback_events` (Block 4): keep HL-holding dips; reversals are logged failures.
4. For each event: `anchor_for_low` (5) + `outcome` (6).
5. `signature` (7): the stock's own depth band, dominant anchor, success rate.
6. `current_state` (8): label today **buyable-dip-now / pullback-coming-wait /
   no-match**, and LIST the matched past events (dates) as the audit trail.
7. Report: signature + label + matched events + invalidation (the prior higher-low)
   + caveats (sample size, freshness, derived-timeframe warning).

## Workflow — universe screener

1. `universe_gate` (Block 9): keep symbols in an uptrend; sort by current depth to
   find dippers. Disclose how many symbols were excluded for short history.
2. Run the single-symbol workflow (steps 1–6) ONLY on the handful of survivors.
3. Output a ranked table: symbol, label, current vs typical depth, dominant anchor,
   success_rate, n_events, invalidation.

## Hard rules

- Timeframe missing/unsupported → ask or raise; never proceed on a guess.
- Missing symbol / no rows / stale data → quote the error, stop. No partial analysis,
  no fabricated numbers.
- `n_events < 5` → label **insufficient-history, low-confidence**; never invent a
  signature from 1–2 events.
- Pattern thresholds (pivot window, noise filter, depth/retrace bands) are derived
  per stock from its own distribution and disclosed. Risk barriers (3% hard stop,
  ~10–15 bar time stop) are the trader's fixed model — explicit, stated, distinct
  from pattern bands.
- Every number is computed in Polars, never eyeballed from a chart or invented.
- Read-only. Disclose survivorship bias (universe selected today) and on-demand EMA
  calculation.

This is structural evidence, not financial advice.
````

- [ ] **Step 2: Verify it's done**

```bash
cd /workspaces/stock-database && head -5 .claude/skills/pullback-finder/SKILL.md && grep -c "references/building-blocks.md" .claude/skills/pullback-finder/SKILL.md
```
Expected: front-matter with `name: pullback-finder` shows, and grep count ≥ 1.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pullback-finder/SKILL.md
git commit -m "feat(pullback-finder): add SKILL.md methodology"
```

---

## Task 6: Worked example — one stock end-to-end + gate

**Inputs/Outputs:**
- Create: `.claude/skills/pullback-finder/references/worked-example.md`
- Done-check: the example script runs top-to-bottom on ABSLAMC.NS and prints a signature + current label.

- [ ] **Step 1: Author the worked example**

Build the full script by composing Blocks 1–8 on `ABSLAMC.NS` at `1d`, run it, and
paste the REAL printed output into the doc. Create
`.claude/skills/pullback-finder/references/worked-example.md` with this structure:

````markdown
# Worked Example — ABSLAMC.NS, 1d

One stock strung end-to-end to show the grammar composed into a sentence. This is
illustrative, NOT the engine — for another stock you would pick a different `k` and
read different bands. Run from repo root with `.venv/bin/python`.

```python
import polars as pl
# ... load + add_indicators + fractal_flags(k=5) + zigzag + pullback_events
# ... + anchor_for_low + outcome per event + signature + current_state
# (compose Blocks 1-8 from building-blocks.md)
```

## What it produced (real run, 2026-06-13)

- 10 HL-holding pullback events, depths 4.3%–17.1%, median ≈9.3%.
- <paste the real signature dict>
- <paste the real current_state label for the latest bar>

## Reading it

- The depth IQR is ABSLAMC's own pullback band — a different stock will differ.
- The current label and the listed matched events are the audit trail.
- Caveat: 381 daily bars is short; treat the success_rate as low-sample evidence.
````

Fill the `<paste ...>` placeholders with the actual values from your run — do not
leave them as placeholders.

- [ ] **Step 2: Verify it's done**

Compose Blocks 1–8 into one script and run it on ABSLAMC.NS 1d:
```bash
cd /workspaces/stock-database && .venv/bin/python /tmp/pf_example.py
```
Expected: prints `n_events: 10`, a `depth_median` near 9.3, and a `label` string.
(Write `/tmp/pf_example.py` by pasting Blocks 1–8 plus print statements; it is scratch, not committed.)

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pullback-finder/references/worked-example.md
git commit -m "feat(pullback-finder): add worked example"
```

---

## Task 7: Final validation

**Inputs/Outputs:**
- Done-check: skill tree complete; SKILL.md is discoverable; no placeholders remain.

- [ ] **Step 1: Verify the skill is complete and clean**

```bash
cd /workspaces/stock-database
find .claude/skills/pullback-finder -type f | sort
grep -rn "TBD\|TODO\|<paste\|FIXME" .claude/skills/pullback-finder/ || echo "NO PLACEHOLDERS"
```
Expected: four files (`SKILL.md`, `references/data.md`, `references/building-blocks.md`, `references/worked-example.md`) and `NO PLACEHOLDERS`.

- [ ] **Step 2: Confirm line limits**

```bash
cd /workspaces/stock-database && wc -l .claude/skills/pullback-finder/SKILL.md .claude/skills/pullback-finder/references/*.md
```
Expected: every file under 800 lines.

- [ ] **Step 3: Commit any final fixes**

```bash
git add .claude/skills/pullback-finder/
git commit -m "feat(pullback-finder): final validation" --allow-empty
```

---

## Self-review (done while writing this plan)

- **Spec coverage:** grammar-not-engine (Tasks 2–4 + SKILL.md), required timeframe (Task 5 + data.md), optional symbol / screener (SKILL.md + Block 9), per-stock learned signature (Blocks 4–8), both-labeled current state (Block 8), fail-fast / thin-sample / no-global-thresholds / risk-vs-pattern distinction (SKILL.md hard rules), standalone no-reuse (all blocks self-contained), worked example (Task 6). Build phases 1–4 map to Tasks 1→(2,3,4)→5→6.
- **Placeholders:** the only `<paste ...>` lives in Task 6 and Step 1 explicitly requires filling it with real run output; Task 7 greps to prove none remain.
- **Naming consistency:** block function names (`load`, `add_indicators`, `fractal_flags`, `zigzag`, `pullback_events`, `anchor_for_low`, `outcome`, `signature`, `current_state`, `universe_gate`) and file paths are used identically across SKILL.md, building-blocks.md, and the worked example.
- All embedded code blocks were executed against real Parquet data before being written into this plan.
````
