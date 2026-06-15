# Screening Blocks — the Stage-A grammar (companion to pullback-finder)

Stage A is a cheap, fully vectorized net over the WHOLE universe in one streaming pass.
It picks WHO to deep-analyze; Stage B (pullback-finder blocks) decides the verdict. So
Stage A is deliberately inclusion-biased — a borderline keep is fine (Stage B culls it),
a wrong drop is not (Stage B never sees it).

Run everything read-only from the repo root with `.venv/bin/python` via heredoc. Never
write a scratch file into the repo.

## Block A1 — proxy net at one window W

```python
import polars as pl

def proxy_net(interval, W, m=3, R=8, lb=20):
    """Symbols in an uptrend whose RECENT dip reached their own typical dip band.
    Band from local-trough drawdowns (~per-event depth); today = deepest dip in last R."""
    lf = (pl.scan_parquet(f"market-data/prices/{interval}/*.parquet")
          .select("symbol", "trade_timestamp", "high", "close")
          .sort("symbol", "trade_timestamp"))
    lf = lf.with_columns(pl.col("high").rolling_max(W).over("symbol").alias("peak"))
    lf = lf.with_columns(((pl.col("peak") - pl.col("close")) / pl.col("peak")).alias("dd"))
    # local trough = close is the min within +/- m bars (cheap mini-pivot, vectorized)
    lf = lf.with_columns(
        (pl.col("close") == pl.col("close").rolling_min(2 * m + 1, center=True).over("symbol"))
        .alias("trough"))
    lf = lf.with_columns(
        pl.when(pl.col("trough")).then(pl.col("dd")).otherwise(None).alias("dd_tr"))
    g = lf.group_by("symbol", maintain_order=True).agg([
        pl.len().alias("bars"),
        pl.col("close").last().alias("close"),
        pl.col("close").ewm_mean(span=50, adjust=False).last().alias("ema50"),
        pl.col("close").ewm_mean(span=50, adjust=False).slice(-lb, 1).first().alias("ema50p"),
        (pl.col("dd_tr").quantile(0.25) * 100).alias("band_lo"),
        (pl.col("dd_tr").quantile(0.75) * 100).alias("band_hi"),
        (pl.col("dd").tail(R).max() * 100).alias("recent_dip"),
    ])
    return (g.filter(pl.col("bars") >= max(60, W))
             .filter((pl.col("close") > pl.col("ema50")) & (pl.col("ema50") > pl.col("ema50p")))
             # inclusion-biased: recent dip reached its lower band, not absurdly deep
             .filter((pl.col("recent_dip") >= pl.col("band_lo")) &
                     (pl.col("recent_dip") <= 1.5 * pl.col("band_hi")))
             .collect(engine="streaming"))
```

`band_lo/band_hi` are this stock's own typical dip range (25–75th pct of trough dips).
`recent_dip` is the deepest dip in the last `R` bars — a dip that printed a low and
bounced still counts. The `1.5 * band_hi` cap rejects only blatant reversals; Stage B
makes the fine call.

## Block A2 — W self-calibration (run every screen; data drifts)

W is NOT a frozen constant. Build the shortlist at three windows and measure agreement.
If they agree, W is non-critical today; if not, take the union (inclusion-biased) and say so.

```python
def calibrate_W(interval, windows=(60, 120, 240), threshold=0.85):
    sets = {W: set(proxy_net(interval, W)["symbol"].to_list()) for W in windows}
    inter = set.intersection(*sets.values())
    union = set.union(*sets.values())
    overlap = len(inter) / len(union) if union else 0.0
    if overlap >= threshold:
        mid = windows[len(windows) // 2]
        return {"mode": "stable", "overlap": overlap, "W_used": mid,
                "shortlist": sorted(sets[mid])}
    return {"mode": "sensitive", "overlap": overlap, "W_used": list(windows),
            "shortlist": sorted(union)}
```

The result's `mode`/`overlap`/`W_used` MUST be disclosed in the report. `threshold=0.85`
is itself stated and adjustable. Windows scale to the interval (these suit 1h).

## Block A3 — choppiness → k (per stock, computed; never a hardcoded default)

Uses the battle-tested Choppiness Index (reuses Block 1's ATR inputs). Fibonacci bands
(38.2 / 50 / 61.8) map the stock's median choppiness to a fractal `k`. Choppier → larger
k (needs a more dominant pivot); smoother → smaller k.

```python
import math

def choppiness_k(df, n=14):
    """Median Choppiness Index over history → fractal k in {4,6,8,10}, clamped [4,12]."""
    log10n = math.log10(n)
    d = df.with_columns(pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("close").shift(1)).abs(),
            (pl.col("low") - pl.col("close").shift(1)).abs()).alias("tr"))
    d = d.with_columns([
        pl.col("tr").rolling_sum(n).alias("atrsum"),
        pl.col("high").rolling_max(n).alias("hh"),
        pl.col("low").rolling_min(n).alias("ll")])
    d = d.with_columns(
        (100 * (pl.col("atrsum") / (pl.col("hh") - pl.col("ll"))).log10() / log10n).alias("ci"))
    ci = d["ci"].median()
    if ci is None:
        raise ValueError("choppiness undefined — insufficient history for Choppiness Index")
    k = 4 if ci <= 38.2 else 6 if ci <= 50 else 8 if ci <= 61.8 else 10
    return {"ci_median": ci, "k": max(4, min(12, k))}
```

Disclose the computed `k` (and `ci_median`) per stock in the report. The spread is
data-dependent — a universe of similarly choppy names will share a `k`; that is correct,
not a bug. The requirement is that `k` is computed from the stock, not a literal.

## Block A4 — volume-fade annotation (quality flag, NOT a gate)

Healthy pullbacks dry up on volume into the dip. Compare average volume on the dip
(confirmed high → live low) vs the prior up-leg (prior confirmed low → confirmed high).
Ratio < 1 = fading = healthy. This annotates conviction; it never rejects a candidate.
Zero/None-volume bars (exchange open-hour no-prints, halted bars) are dropped from each
leg first so they don't drag the means — they are data artifacts, not genuine quiet hours,
and the two legs rarely hold the same count of them. If a leg then has no real-volume bars
left it returns `None`, shown as "n/a" in the report — never an error, never a rejection.
(A single illiquid name must not abort a universe screen.)

```python
def volume_fade(df, leg_start_ts, high_ts, live_low_ts):
    """dip avg volume / up-leg avg volume. <1 = volume fading into the dip (healthy).
    Zero/None-volume bars (open-hour no-prints, halted bars) are dropped from BOTH legs
    first — they are artifacts, not real quiet hours, and would bias each mean toward zero
    unevenly (the legs rarely carry the same count of them)."""
    upleg = df.filter((pl.col("trade_timestamp") > leg_start_ts) &
                      (pl.col("trade_timestamp") <= high_ts) &
                      (pl.col("volume") > 0))
    dip = df.filter((pl.col("trade_timestamp") > high_ts) &
                    (pl.col("trade_timestamp") <= live_low_ts) &
                    (pl.col("volume") > 0))
    if upleg.height == 0 or dip.height == 0:
        return {"vol_fade_ratio": None, "fading": None}   # no real-volume bars left; disclose
    up_v = upleg["volume"].mean()
    dip_v = dip["volume"].mean()
    if not up_v or not dip_v:
        return {"vol_fade_ratio": None, "fading": None}   # degenerate mean; too thin to judge
    ratio = dip_v / up_v
    return {"vol_fade_ratio": ratio, "fading": ratio < 1.0}
```

## Block A5 — confirmed up-leg guard (reject range chop)

A pullback only counts if the up-leg was a real uptrend, not sideways noise. Require the
50-EMA to be rising across the leg (uses Block 1's `ema_50`).

```python
def upleg_is_uptrend(df, leg_start_ts, high_ts):
    seg = df.filter((pl.col("trade_timestamp") >= leg_start_ts) &
                    (pl.col("trade_timestamp") <= high_ts))
    if seg.height < 2:
        return False
    return seg["ema_50"][-1] > seg["ema_50"][0]
```

## Block A6 — Stage-B recipe: confirm each shortlisted stock

For each symbol from `calibrate_W(...)["shortlist"]`, compose pullback-finder's blocks
(in `../../pullback-finder/references/building-blocks.md`) — do NOT copy them into the
repo, paste them into the same heredoc — with these screening additions:

1. `df = add_indicators(load(sym, interval))` (Block 1).
2. `k = choppiness_k(df.select("high","low","close"))["k"]` (Block A3) — per stock.
3. `zz = zigzag(fractal_flags(df, k))` (Blocks 2–3); noise filter from the stock's ATR.
4. `events = pullback_events(zz)` (Block 4), keeping only events whose up-leg passes
   `upleg_is_uptrend(df, leg_start_ts, high_ts)` (Block A5).
5. Learn the horizon: `H = learn_horizon(df, events)` (Block A7). If `H["H_stock"] is
   None` (too few recoveries), use the fixed yardstick `H_base = 15` and mark the stock
   low-confidence. Always keep `H_base` available — it is the comparable ruler.
6. Per event: `anchor_for_low` (5) + **two** `outcome` (6) passes, both with the fixed
   `stop_pct=0.03` (the only frozen risk knob):
   - `outcome(df, ev, stop_pct=0.03, horizon=H_base)` → tag each event `success_base`.
   - `outcome(df, ev, stop_pct=0.03, horizon=H["H_stock"])` → tag each event
     `success_learned`.
   Aggregate to `bounce@base` and `bounce@learned`; record `Δ = bounce@learned −
   bounce@base`, plus `H["recovery_class"]` and `H_stock` in trading days. The signature's
   own-clock `success_rate` uses `success_learned`.
7. `sig = signature(events)` (Block 7); `state = current_state(df, zz, sig)` (Block 8,
   runs `live_pullback_low` internally).
8. `vf = volume_fade(df, leg_start_ts, high_ts, live_low_ts)` (Block A4) on the live dip
   — annotation only. For the live (unconfirmed) dip, `leg_start_ts` = the last confirmed
   low before the last confirmed high; `high_ts` = the last confirmed high; `live_low_ts`
   = the live low's timestamp from `live_pullback_low`.
9. Compute each stop's % from the latest close: `(close - level) / close * 100` for
   `near_term_invalidation` and `structural_floor`.

`n_events < 5` for a symbol → label it low-confidence; never invent a signature.
This is the SAME math pullback-finder uses for a single symbol — Stage B is that workflow
run on each survivor, with computed `k`, the up-leg guard, the volume annotation, and the
learned horizon. **Only the 3% stop is frozen; the horizon is learned per stock** (Block
A7), and both the comparable (`@base`) and own-clock (`@learned`) bounce are reported.

## Block A7 — learned recovery horizon (per stock; never the static 15)

The horizon is no longer a frozen risk constant — it is learned from how long THIS stock
historically takes to resume. Two passes avoid circularity: "success" (Block 6) is
*defined using* the horizon, so the horizon must be learned **independently of success** —
from raw bars-to-new-high, ignoring the stop. The clamp is stated in TRADING DAYS so it is
interval-portable.

```python
import math

def bars_per_day(df):
    """Median candles per trading day, read from the data (≈7 for 1h NSE, 1 for 1d)."""
    per = df.group_by(pl.col("trade_timestamp").dt.date()).len()["len"]
    return max(1.0, float(per.median()))

def learn_horizon(df, events, q=0.75, h_max_days=6.0, h_min_days=0.5, min_recovered=5):
    """Pass 1 — per-stock recovery horizon from UNCAPPED bars-to-new-high (stop ignored).
    H_stock = clamp(ceil(P75 of recovery latency)), expressed via trading-day bounds."""
    bpd = bars_per_day(df)
    h_min, h_max = max(3, round(h_min_days * bpd)), round(h_max_days * bpd)
    idx_of, lat = df.with_row_index("i"), []
    for ev in events:
        i = idx_of.filter(pl.col("trade_timestamp") == ev["low_ts"]).select("i").item()
        fwd = df.slice(i + 1)                          # every bar after the low, uncapped
        bn = next((j for j, h in enumerate(fwd["high"]) if h > ev["high"]), None)
        if bn is not None:
            lat.append(bn + 1)                         # 1-based bars-to-recover
    if len(lat) < min_recovered:
        return {"H_stock": None, "recovered": len(lat), "bars_per_day": bpd,
                "reason": "too few recoveries — fall back to H_base, low-confidence"}
    s = pl.Series(lat)
    H = max(h_min, min(h_max, math.ceil(s.quantile(q))))
    return {"H_stock": H, "median_bars": float(s.median()), "p75_bars": float(s.quantile(0.75)),
            "recovered": len(lat), "n_events": len(events), "bars_per_day": bpd,
            "clamped": H in (h_min, h_max), "recovery_class": recovery_class(H, bpd),
            "trading_days": round(H / bpd, 1)}

def recovery_class(H_stock, bpd):
    days = H_stock / bpd
    # trading-day buckets: <=3d fast, <=1wk medium, >1wk slow (1 week = 5 trading days)
    return "fast" if days <= 3.0 else "medium" if days <= 5.0 else "slow"
```

`q=0.75` gives the dip enough room that ~¾ of historical recoveries would have completed —
a buffer without chasing the long tail; both `q` and the trading-day clamp are stated and
tunable, and disclosed every run. Because a longer horizon can only *add* wins, always
report `bounce@learned` beside the fixed-yardstick `bounce@base` (`H_base = 15`) and the
gap `Δ`: a large `Δ` on a `slow` stock is borrowed time, not a fast edge (Stage C tiers on
this). `H_base` is the comparable ruler shared by every stock; `H_stock` is the per-stock
verdict horizon.
