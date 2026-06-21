#!/usr/bin/env python3
"""
rounding_bottom_scan.py
=======================

Screen the project's Parquet market data for rounding-bottom / cup ("U") setups,
following the talk-to-parquet conventions: Polars lazy scans, predicate + projection
pushdown, expressions over Python, indicators consumed at their exact stored interval.

Pattern engine
--------------
Fit a least-squares parabola  close ~ a + b*t + c*t^2  to the last N bars of every
symbol. Because t is the fixed integer grid 0..N-1, the design matrix X = [1, t, t^2]
is IDENTICAL for every symbol, so (X'X)^-1 is precomputed ONCE in NumPy (an O(1) 3x3
inverse, not per-row work). Each symbol's fit then collapses to four closed-form sums

    Sy = sum(close)
    Sty = sum(t * close)
    St2y = sum(t^2 * close)
    Syy = sum(close^2)

which Polars evaluates as parallel aggregations in a single pass -- no map_elements,
no UDFs, no Python loop over rows or files.

    [a, b, c]^T = M @ [Sy, Sty, St2y]^T          (M = (X'X)^-1)
    SS_res      = Syy - (a*Sy + b*Sty + c*St2y)  (normal-equations identity)
    SS_tot      = Syy - Sy^2 / N
    R^2         = 1 - SS_res / SS_tot

    c > 0        -> convex: a U, not an n-shaped rollover (hard gate)
    R^2          -> how cleanly price obeys the curve; a sharp V fits a parabola poorly
    vertex_frac  -> -b / (2c), normalised to [0,1]: where the modeled trough sits.
                    ~0.5 == a symmetric U; near the edges == a J / one-sided drift.

Shape alone is necessary but not sufficient, so each candidate is confirmed against
the PRECALCULATED indicator file at the SAME stored interval (latest in-window bar):
EMA stack alignment, RSI, relative volume, and distance from the 365-day high -- the
features that separate an actionable, breaking-out cup from a stock still pinned at
its lows. Raw window volume gives a base-vs-right-side expansion ratio.

Usage
-----
    .venv/bin/python rounding_bottom_scan.py                 # scan market-data/ (1d)
    .venv/bin/python rounding_bottom_scan.py --interval 1h
    .venv/bin/python rounding_bottom_scan.py --window 60 --top 30
    .venv/bin/python rounding_bottom_scan.py --no-require-momentum   # find forming U's
    .venv/bin/python rounding_bottom_scan.py --demo         # self-test on synthetic data

All analysis is read-only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import polars as pl


# --------------------------------------------------------------------------------------
# Configuration -- every knob a swing trader might want to turn, with defaults tuned for
# a daily-bar base spanning roughly two to three months.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ScanConfig:
    interval: str = "1d"
    window: int = 55              # bars in the analysis window (the cup)
    lookback_days: int = 200      # calendar floor for pushdown; must exceed `window`
    rim_bars: int = 8             # bars averaged at each edge to estimate the rims
    freshness_days: int = 6       # latest bar must be this recent (drops stale/delisted)

    # --- shape gates -------------------------------------------------------------------
    r2_min: float = 0.50          # min parabola fit quality
    depth_min_pct: float = 6.0    # cup must be at least this deep (rim -> trough)
    depth_max_pct: float = 55.0   # ...and no deeper (avoid falling-knife wreckage)
    vertex_lo: float = 0.30       # modeled trough must sit in the central band
    vertex_hi: float = 0.70
    recovery_min: float = 0.45    # latest close must have recovered >= this frac of depth
    dwell_band: float = 0.06      # "near the bottom" = within this frac of the window low

    # --- confirmation ------------------------------------------------------------------
    require_momentum: bool = True # gate: latest close must be > ema_20 (actionable now)
    rsi_lo: float = 50.0          # healthy-momentum RSI band for scoring
    rsi_hi: float = 78.0
    vol_expansion_ref: float = 1.0  # right-side/base volume ratio that earns full marks
    near_high_ref_pct: float = 25.0 # |dist from 365d high| that zeroes the position score

    # --- ideal depth for scoring (triangular preference) -------------------------------
    depth_ideal_pct: float = 18.0
    depth_tol_pct: float = 14.0

    # --- composite score weights (sum to 1.0) ------------------------------------------
    weights: dict = field(default_factory=lambda: {
        "fit": 0.22, "symmetry": 0.15, "dwell": 0.13, "depth": 0.10,
        "momentum": 0.18, "volume": 0.10, "position": 0.12,
    })

    top_n: int = 25


# --------------------------------------------------------------------------------------
# Closed-form quadratic fit constants for a fixed window length.
# --------------------------------------------------------------------------------------
def _fit_constants(n: int) -> dict[str, float]:
    """Precompute (X'X)^-1 rows for t = 0..n-1.  Returns scalar coefficients so the
    per-symbol fit is a linear combination of aggregated sums -- zero per-row Python."""
    t = np.arange(n, dtype=float)
    X = np.column_stack([np.ones(n), t, t**2])      # (n, 3)
    M = np.linalg.inv(X.T @ X)                       # (3, 3)
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = M
    return dict(a0=a0, a1=a1, a2=a2, b0=b0, b1=b1, b2=b2, c0=c0, c1=c1, c2=c2)


# --------------------------------------------------------------------------------------
# Lazy pipeline.
# --------------------------------------------------------------------------------------
def _max_timestamp(prices_glob: str) -> "pl.Datetime":
    """Cheap metadata probe: latest timestamp in the universe (one column, one row)."""
    ts = (
        pl.scan_parquet(prices_glob)
        .select(pl.col("trade_timestamp").max())
        .collect(engine="streaming")
    )
    if ts.height == 0 or ts.item() is None:
        raise FileNotFoundError(f"No price data found for glob: {prices_glob}")
    return ts.item()


def _price_window(prices_glob: str, floor, cfg: ScanConfig) -> pl.LazyFrame:
    """Last `window` bars per symbol, with a 0-based in-window time index `t`.

    Pushdown-friendly: projection (.select) and the calendar predicate (.filter on
    trade_timestamp) sit directly on the scan so unused columns and old row groups are
    never read.  The last-N-per-symbol step (rank over symbol) cannot be pushed into the
    reader, so the calendar floor first prunes each symbol to ~lookback_days of bars.
    """
    return (
        pl.scan_parquet(prices_glob)
        .select("symbol", "trade_timestamp", "close", "volume")
        .filter(pl.col("trade_timestamp") >= floor)
        .with_columns(
            _rn=pl.col("trade_timestamp")
            .rank(method="ordinal", descending=True)
            .over("symbol")
        )
        .filter(pl.col("_rn") <= cfg.window)
        .with_columns(
            t=(pl.col("trade_timestamp").rank(method="ordinal").over("symbol") - 1)
            .cast(pl.Int32)
        )
    )


def _shape_features(pw: pl.LazyFrame, cfg: ScanConfig) -> pl.LazyFrame:
    """One group_by('symbol') pass -> the raw sums and rim/volume aggregates.  Every
    expression is independent so Polars runs them in parallel within the agg context."""
    w, third = cfg.window, cfg.window // 3
    return (
        pw.group_by("symbol").agg(
            n=pl.len(),
            sy=pl.col("close").sum(),
            sty=(pl.col("t") * pl.col("close")).sum(),
            st2y=(pl.col("t").pow(2) * pl.col("close")).sum(),
            syy=pl.col("close").pow(2).sum(),
            wmin=pl.col("close").min(),
            wmax=pl.col("close").max(),
            last_close=pl.col("close").sort_by("t").last(),
            last_ts=pl.col("trade_timestamp").max(),
            left_rim=pl.col("close").filter(pl.col("t") < cfg.rim_bars).mean(),
            right_rim=pl.col("close")
            .filter(pl.col("t") >= w - cfg.rim_bars).mean(),
            # fraction of the window spent within dwell_band of the low (roundness):
            dwell=(pl.col("close") <= pl.col("close").min() * (1 + cfg.dwell_band))
            .mean(),
            vol_base=pl.col("volume")
            .filter((pl.col("t") >= third) & (pl.col("t") < 2 * third)).mean(),
            vol_right=pl.col("volume").filter(pl.col("t") >= 2 * third).mean(),
        )
    )


def _derive_shape(shape: pl.LazyFrame, K: dict[str, float], cfg: ScanConfig) -> pl.LazyFrame:
    """Turn the raw sums into interpretable, scale-free shape metrics + sub-scores.

    R^2 is invariant to affine scaling of price, so it is comparable across symbols as
    is.  The curvature SIGN (the U/non-U gate) is likewise scale-invariant.  Depth,
    recovery and rim balance are expressed as ratios/percentages, so nothing here
    depends on a stock's absolute price.  Divisions are guarded with when/then so
    degenerate (flat) windows yield nulls and fall out at the gate rather than NaN.
    """
    sy, sty, st2y, syy = (pl.col(c) for c in ("sy", "sty", "st2y", "syy"))
    a = K["a0"] * sy + K["a1"] * sty + K["a2"] * st2y
    b = K["b0"] * sy + K["b1"] * sty + K["b2"] * st2y
    c = K["c0"] * sy + K["c1"] * sty + K["c2"] * st2y

    ss_res = syy - (a * sy + b * sty + c * st2y)
    ss_tot = syy - sy.pow(2) / pl.col("n")
    rim = pl.max_horizontal("left_rim", "right_rim")

    return shape.with_columns(
        curvature=c,
        r2=pl.when(ss_tot > 1e-12).then(1 - ss_res / ss_tot).otherwise(None),
        vertex_frac=pl.when(c.abs() > 1e-12)
        .then((-b / (2 * c)) / (cfg.window - 1))
        .otherwise(None),
        rim=rim,
        depth_pct=pl.when(rim > 0).then((rim - pl.col("wmin")) / rim * 100).otherwise(None),
        recovery_frac=pl.when((rim - pl.col("wmin")).abs() > 1e-9)
        .then((pl.col("last_close") - pl.col("wmin")) / (rim - pl.col("wmin")))
        .otherwise(None),
        rim_balance=pl.when(pl.col("left_rim") > 0)
        .then(pl.col("right_rim") / pl.col("left_rim")).otherwise(None),
        vol_expansion=pl.when(pl.col("vol_base") > 0)
        .then(pl.col("vol_right") / pl.col("vol_base")).otherwise(None),
    )


def _indicators_latest(ind_glob: str, floor, cfg: ScanConfig) -> pl.LazyFrame:
    """Latest in-window indicator row per symbol, read at the EXACT stored interval --
    no resampling, no joining onto a derived timeframe (per the skill's hard rule)."""
    return (
        pl.scan_parquet(ind_glob)
        .select(
            "symbol", "trade_timestamp", "ema_10", "ema_20", "ema_50",
            "rsi_14", "relative_volume_20", "distance_from_365d_high_percent",
        )
        .filter(pl.col("trade_timestamp") >= floor)
        .with_columns(
            _rn=pl.col("trade_timestamp")
            .rank(method="ordinal", descending=True).over("symbol")
        )
        .filter(pl.col("_rn") == 1)
        .drop("_rn")
    )


def _score(joined: pl.LazyFrame, cfg: ScanConfig) -> pl.LazyFrame:
    """Confirmation sub-scores + weighted composite.  Null indicators (e.g. a symbol
    without 365d warm-up) score 0 on their component rather than crashing the row."""
    w = cfg.weights
    clip01 = lambda e: e.clip(0.0, 1.0)

    s_fit = clip01(pl.col("r2"))
    s_sym = clip01(1 - 2 * (pl.col("vertex_frac") - 0.5).abs())
    s_dwell = clip01(pl.col("dwell") / 0.40)
    s_depth = clip01(1 - (pl.col("depth_pct") - cfg.depth_ideal_pct).abs() / cfg.depth_tol_pct)

    ema_stack = (pl.col("ema_10") > pl.col("ema_20")) & (pl.col("ema_20") > pl.col("ema_50"))
    above_20 = pl.col("last_close") > pl.col("ema_20")
    rsi_ok = pl.col("rsi_14").is_between(cfg.rsi_lo, cfg.rsi_hi)
    s_mom = (
        0.50 * above_20.fill_null(False).cast(pl.Float64)
        + 0.30 * ema_stack.fill_null(False).cast(pl.Float64)
        + 0.20 * rsi_ok.fill_null(False).cast(pl.Float64)
    )
    s_vol = clip01((pl.col("vol_expansion") - 1.0) / cfg.vol_expansion_ref).fill_null(0.0)
    s_pos = clip01(
        1 - pl.col("distance_from_365d_high_percent").abs() / cfg.near_high_ref_pct
    ).fill_null(0.0)

    composite = (
        w["fit"] * s_fit + w["symmetry"] * s_sym + w["dwell"] * s_dwell
        + w["depth"] * s_depth + w["momentum"] * s_mom + w["volume"] * s_vol
        + w["position"] * s_pos
    )
    return joined.with_columns(
        s_fit=s_fit, s_sym=s_sym, s_dwell=s_dwell, s_depth=s_depth,
        s_mom=s_mom, s_vol=s_vol, s_pos=s_pos,
        above_ema20=above_20, ema_stack=ema_stack,
        score=composite,
    )


def scan_rounding_bottoms(
    prices_glob: str, ind_glob: str, cfg: ScanConfig
) -> tuple[pl.DataFrame, dict]:
    """Run the full screen.  Returns (candidates_sorted, diagnostics).

    The heavy work is ONE streaming collect that materialises a single per-symbol row;
    gating, ranking and exclusion accounting then happen eagerly on that tiny frame.
    """
    max_ts = _max_timestamp(prices_glob)
    floor = max_ts - timedelta(days=cfg.lookback_days)
    fresh_floor = max_ts - timedelta(days=cfg.freshness_days)
    K = _fit_constants(cfg.window)

    pw = _price_window(prices_glob, floor, cfg)
    shape = _derive_shape(_shape_features(pw, cfg), K, cfg)
    ind = _indicators_latest(ind_glob, floor, cfg)

    scored_lf = _score(
        shape.join(ind, on="symbol", how="left").with_columns(
            pl.col("symbol").cast(pl.Categorical)
        ),
        cfg,
    )

    # ---- single heavy collect -> one row per symbol ----
    scored = scored_lf.collect(engine="streaming")

    # ---- eager gating on the small per-symbol frame ----
    gate = (
        (pl.col("n") == cfg.window)
        & (pl.col("curvature") > 0)
        & (pl.col("r2") >= cfg.r2_min)
        & pl.col("depth_pct").is_between(cfg.depth_min_pct, cfg.depth_max_pct)
        & pl.col("vertex_frac").is_between(cfg.vertex_lo, cfg.vertex_hi)
        & (pl.col("recovery_frac") >= cfg.recovery_min)
        & (pl.col("last_ts") >= fresh_floor)
    )
    if cfg.require_momentum:
        gate = gate & pl.col("above_ema20").fill_null(False)

    candidates = (
        scored.filter(gate)
        .sort(["score", "symbol"], descending=[True, False])
        .head(cfg.top_n)
    )

    diagnostics = {
        "interval": cfg.interval,
        "window": cfg.window,
        "analyzed_from": floor,
        "analyzed_to": max_ts,
        "freshness_floor": fresh_floor,
        "symbols_scanned": scored.height,
        "full_window": int((scored["n"] == cfg.window).sum()),
        "short_window_excluded": int((scored["n"] != cfg.window).sum()),
        "missing_indicators": int(scored["ema_20"].is_null().sum()),
        "passed_gate": int(scored.filter(gate).height),
    }
    return candidates, diagnostics


# --------------------------------------------------------------------------------------
# Reporting (talk-to-parquet output rules).
# --------------------------------------------------------------------------------------
def report(candidates: pl.DataFrame, diag: dict, cfg: ScanConfig) -> None:
    print("=" * 78)
    print("ROUNDING-BOTTOM / CUP SCAN")
    print("=" * 78)
    print(f"Requested timeframe : {diag['interval']}  (source interval, NOT derived)")
    print(f"Window              : last {diag['window']} bars per symbol")
    print(f"Analyzed range      : {diag['analyzed_from']:%Y-%m-%d} -> {diag['analyzed_to']:%Y-%m-%d}")
    print(f"Freshness floor     : latest bar must be >= {diag['freshness_floor']:%Y-%m-%d}")
    print()
    print("Shape metric        : LS parabola close ~ a + b*t + c*t^2 on t=0..N-1")
    print("                      curvature c>0 (U), R^2 = fit quality, vertex = trough pos")
    print("Indicators          : PRECALCULATED, read at exact 1x interval (no resample),")
    print("                      latest in-window bar (EMA stack, RSI, rel-vol, 365d-high)")
    print("Volume expansion     : window right-third / middle-third mean volume (raw)")
    print()
    print(f"Symbols scanned     : {diag['symbols_scanned']}")
    print(f"  full {cfg.window}-bar window : {diag['full_window']}")
    print(f"  excluded (short)  : {diag['short_window_excluded']}  (insufficient lookback)")
    print(f"  missing indicators: {diag['missing_indicators']}  (no 365d warm-up / coverage)")
    print(f"  passed all gates  : {diag['passed_gate']}")
    print(f"  momentum gate     : close > ema_20 {'REQUIRED' if cfg.require_momentum else 'off (forming-U mode)'}")
    print("=" * 78)

    if candidates.height == 0:
        print("No symbols matched the cup criteria in this run.")
        return

    show = candidates.select(
        pl.col("symbol").cast(pl.Utf8),
        pl.col("score").round(3),
        pl.col("r2").round(2).alias("fit_r2"),
        pl.col("vertex_frac").round(2).alias("trough@"),
        pl.col("depth_pct").round(1).alias("depth%"),
        pl.col("recovery_frac").round(2).alias("recov"),
        pl.col("rim_balance").round(2).alias("rim_R/L"),
        pl.col("vol_expansion").round(2).alias("vol_x"),
        pl.col("rsi_14").round(0).alias("rsi"),
        pl.col("distance_from_365d_high_percent").round(1).alias("d_hi%"),
        pl.col("last_close").round(2).alias("close"),
    )
    with pl.Config(tbl_rows=cfg.top_n, tbl_cols=show.width, tbl_width_chars=160):
        print(show)
    print()
    print("Legend: trough@ ~0.5 = symmetric U | recov = frac of cup retraced up from low |")
    print("        rim_R/L >1 = right rim above left (strong) | vol_x >1 = volume expanding |")
    print("        d_hi% = distance from 365-day high (closer to 0 = nearer breakout).")


# --------------------------------------------------------------------------------------
# Self-test: synthesise known shapes, prove the ranker separates U's from non-U's.
# --------------------------------------------------------------------------------------
def _demo(cfg: ScanConfig) -> None:
    import shutil
    from pathlib import Path

    root = Path("/tmp/rb_demo")
    if root.exists():
        shutil.rmtree(root)
    pdir = root / "market-data" / "prices" / cfg.interval
    idir = root / "market-data" / "indicators" / cfg.interval
    pdir.mkdir(parents=True)
    idir.mkdir(parents=True)

    n_hist = 330
    rng = np.random.default_rng(7)
    ts = pl.datetime_range(
        pl.datetime(2025, 1, 1), pl.datetime(2025, 1, 1) + timedelta(days=n_hist - 1),
        interval="1d", time_zone="Asia/Kolkata", eager=True,
    )[:n_hist]
    w = cfg.window
    x = np.linspace(-1, 1, w)  # window axis for shaping the last w bars

    def build(shape: np.ndarray, base: float, noise: float, vol_profile: np.ndarray):
        """Construct a 330-bar close series whose final `w` bars follow `shape`."""
        pre = base + np.linspace(-base * 0.04, 0, n_hist - w) + rng.normal(0, base * noise * 0.5, n_hist - w)
        tail = base * (1 + shape) + rng.normal(0, base * noise, w)
        close = np.concatenate([pre, tail])
        close = np.maximum(close, base * 0.2)
        vol = np.concatenate([
            rng.uniform(0.8, 1.2, n_hist - w) * 1e5,
            vol_profile * 1e5,
        ])
        return close, vol

    flat_vol = rng.uniform(0.8, 1.2, w) * 1.0
    rising_vol = np.linspace(0.7, 2.2, w) * (1 + rng.uniform(-0.1, 0.1, w))
    u = -0.20 * (1 - x**2)                       # clean U, ~20% deep, symmetric
    u_deep = -0.40 * (1 - x**2)                  # deep U
    cup_handle = u.copy(); cup_handle[-6:] -= 0.05 * np.linspace(0, 1, 6)  # U + small dip
    v = -0.22 * (1 - np.abs(x))                   # true V-bottom: convex, dips at center,
    #                                               but low dwell -> should rank BELOW U's
    n_top = 0.18 * (1 - x**2)                     # inverted-U rollover (curvature < 0)
    down = -0.30 * (x + 1) / 2                     # steady downtrend
    up = 0.25 * (x + 1) / 2                        # steady uptrend
    chop = 0.02 * np.sin(np.linspace(0, 9 * np.pi, w))  # shallow chop
    half_u = -0.22 * (1 - x**2); half_u[w // 2:] = half_u[w // 2]  # U left half, still at lows

    specs = {
        "UCLEAN.NS":  (u, 480, 0.010, rising_vol),
        "UDEEP.NS":   (u_deep, 920, 0.012, rising_vol),
        "CUPHANDLE.NS": (cup_handle, 1180, 0.010, rising_vol),
        "USYM2.NS":   (u, 64, 0.012, rising_vol),
        "VSHARP.NS":  (v, 350, 0.010, rising_vol),
        "NTOP.NS":    (n_top, 700, 0.010, flat_vol),
        "DOWNTRD.NS": (down, 540, 0.010, flat_vol),
        "UPTRD.NS":   (up, 260, 0.010, rising_vol),
        "CHOP.NS":    (chop, 410, 0.012, flat_vol),
        "ATLOWS.NS":  (half_u, 600, 0.010, flat_vol),
    }

    for sym, (shape, base, noise, volp) in specs.items():
        close, vol = build(shape, base, noise, volp)
        df = pl.DataFrame({
            "symbol": [sym] * n_hist,
            "trade_timestamp": ts,
            "open": close * (1 + rng.normal(0, 0.002, n_hist)),
            "high": close * (1 + np.abs(rng.normal(0, 0.004, n_hist))),
            "low": close * (1 - np.abs(rng.normal(0, 0.004, n_hist))),
            "close": close,
            "volume": vol.astype(np.int64),
        })
        df.write_parquet(pdir / f"{sym}.parquet")

        # synthesise the indicator columns the scanner reads (real files come precalc'd)
        ind = (
            df.lazy().sort("trade_timestamp")
            .with_columns(
                ema_10=pl.col("close").ewm_mean(span=10),
                ema_20=pl.col("close").ewm_mean(span=20),
                ema_50=pl.col("close").ewm_mean(span=50),
                _d=pl.col("close").diff(),
                relative_volume_20=pl.col("volume") / pl.col("volume").rolling_mean(20),
                _h365=pl.col("close").rolling_max(252),
            )
            .with_columns(
                _gain=pl.when(pl.col("_d") > 0).then(pl.col("_d")).otherwise(0.0),
                _loss=pl.when(pl.col("_d") < 0).then(-pl.col("_d")).otherwise(0.0),
            )
            .with_columns(
                _ag=pl.col("_gain").ewm_mean(alpha=1 / 14),
                _al=pl.col("_loss").ewm_mean(alpha=1 / 14),
            )
            .with_columns(
                rsi_14=100 - 100 / (1 + pl.col("_ag") / pl.col("_al")),
                distance_from_365d_high_percent=(pl.col("close") / pl.col("_h365") - 1) * 100,
            )
            .drop("_d", "_gain", "_loss", "_ag", "_al", "_h365")
            .drop_nulls()  # mimic the 365d warm-up: no null rows
            .collect()
        )
        ind.write_parquet(idir / f"{sym}.parquet")

    print(f"[demo] wrote {len(specs)} synthetic symbols to {root}\n")
    cands, diag = scan_rounding_bottoms(
        str(pdir / "*.parquet"), str(idir / "*.parquet"), cfg
    )
    report(cands, diag, cfg)
    print("\n[demo] EXPECTED: UCLEAN/UDEEP/CUPHANDLE/USYM2 rank top; VSHARP lower;")
    print("[demo]           NTOP (curv<0), DOWNTRD, UPTRD, CHOP, ATLOWS (no recovery) filtered.")


# --------------------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="Scan Parquet market data for rounding-bottom/cup setups.")
    p.add_argument("--interval", default="1d", choices=["1d", "1h"])
    p.add_argument("--window", type=int, default=None)
    p.add_argument("--top", type=int, default=None)
    p.add_argument("--no-require-momentum", action="store_true",
                   help="drop the close>ema_20 gate to surface still-forming U's")
    p.add_argument("--demo", action="store_true", help="run the synthetic self-test")
    args = p.parse_args()

    overrides = {"interval": args.interval}
    if args.window:
        overrides["window"] = args.window
    if args.top:
        overrides["top_n"] = args.top
    if args.no_require_momentum:
        overrides["require_momentum"] = False
    cfg = ScanConfig(**overrides)

    if args.demo:
        _demo(cfg)
        return

    base = "market-data"
    prices_glob = f"{base}/prices/{cfg.interval}/*.parquet"
    ind_glob = f"{base}/indicators/{cfg.interval}/*.parquet"
    cands, diag = scan_rounding_bottoms(prices_glob, ind_glob, cfg)
    report(cands, diag, cfg)


if __name__ == "__main__":
    main()
