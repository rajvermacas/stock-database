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
