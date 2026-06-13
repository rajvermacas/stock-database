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
