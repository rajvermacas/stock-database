#!/usr/bin/env python3
"""
bullish_dip_regain_scan.py
==========================

Screen the project's Parquet market data for the pattern:

    "bigger timeframe is bullish -> shorter timeframe dips and starts to regain"

A fractal momentum-pullback idea read off a fixed four-rung timeframe ladder, using
ONLY the precalculated `rsi_14` column at each interval's EXACT stored timeframe -- no
resampling, no recalculation -- per the talk-to-parquet rules.

Legs (all AND-ed; each reads precalculated rsi_14 at its own interval)
----------------------------------------------------------------------
1. Bigger timeframe is BULLISH        monthly rsi_14 > bull_rsi_min
                                  AND  weekly  rsi_14 > bull_rsi_min

2. Shorter timeframe DIPS  (daily)    a real pullback from strength:
       peak = max daily rsi_14 over the last `daily_peak_lookback` sessions
       peak > daily_peak_min                  (it was strong recently)
       cur <= peak - daily_drop_min           (rsi has actually fallen >= drop)
       daily_zone_lo <= cur <= daily_zone_hi  (moderate dip: not still-strong, not broken)

3. ...and STARTS TO REGAIN  (hourly)  the recovery is underway right now:
       low = min hourly rsi_14 over the last `hourly_dip_lookback` bars
       low < hourly_dip_below                 (it fell below the midline), AND EITHER
         cur > hourly_reclaim                 (already reclaimed the midline), OR
         cur > prev  AND  cur >= low + hourly_recovery_min
                                              (still rising AND recovered off the low)
   The OR matters: a name that has reclaimed 50 has usually stopped rising on the very
   last bar, while a name still visibly rising is often a hair below 50 -- demanding both
   at once on the same bar almost never co-occurs.

Every leg consumes precalculated indicators at the exact stored interval; nothing is
resampled or recomputed. The four per-interval legs are independent lazy aggregations
(one row per symbol each) inner-joined on `symbol`; a symbol missing any interval is
counted and disclosed, never silently dropped or substituted.

Usage
-----
    .venv/bin/python scripts/bullish_dip_regain_scan.py
    .venv/bin/python scripts/bullish_dip_regain_scan.py --daily-drop-min 12 --zone 45 57
    .venv/bin/python scripts/bullish_dip_regain_scan.py --hourly-recovery-min 8

All analysis is read-only.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.logging_config import configure_logging

logger = logging.getLogger("stock_data.bullish_dip_regain")

# Interval directory -> short prefix used for that leg's columns and as-of label.
LADDER = {"1mo": "mo", "1wk": "wk", "1d": "d", "1h": "h"}


# --------------------------------------------------------------------------------------
# Configuration -- every screen threshold, with defaults agreed during design.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ScreenConfig:
    data_root: str = "market-data"

    # --- Leg 1: bigger timeframe is bullish (monthly AND weekly) --------------------
    bull_rsi_min: float = 60.0

    # --- Leg 2: shorter timeframe dips (daily) -------------------------------------
    daily_peak_lookback: int = 10     # sessions to look back for the recent RSI peak
    daily_peak_min: float = 60.0      # that peak must clear this (dipped FROM strength)
    daily_drop_min: float = 10.0      # RSI must have fallen at least this far (real dip)
    daily_zone_lo: float = 45.0       # current RSI floor (deeper => breakdown, excluded)
    daily_zone_hi: float = 55.0       # current RSI ceiling (higher => it never dipped)

    # --- Leg 3: ...and starts to regain (hourly) -----------------------------------
    hourly_dip_lookback: int = 15     # bars to look back for the intraday dip
    hourly_dip_below: float = 50.0    # the dip must have pierced this (below midline)
    hourly_reclaim: float = 50.0      # "reclaimed" branch: current RSI back above this
    hourly_recovery_min: float = 6.0  # "rising off low" branch: RSI pts recovered off low

    def __post_init__(self) -> None:
        if self.daily_zone_lo >= self.daily_zone_hi:
            raise ValueError(
                f"daily_zone_lo ({self.daily_zone_lo}) must be < "
                f"daily_zone_hi ({self.daily_zone_hi})"
            )
        if self.hourly_recovery_min < 0:
            raise ValueError("hourly_recovery_min must be >= 0")
        if self.daily_peak_lookback < 1 or self.hourly_dip_lookback < 1:
            raise ValueError("lookback windows must be >= 1")


# --------------------------------------------------------------------------------------
# Lazy per-interval legs.  Each returns one row per symbol; all reads are pushdown-friendly
# (projection to 3 columns, rsi-null predicate) and stay lazy until the single collect.
# --------------------------------------------------------------------------------------
def _indicator_glob(cfg: ScreenConfig, interval: str) -> str:
    """Glob for one interval's indicator files; fail fast if absent or empty."""
    directory = Path(cfg.data_root) / "indicators" / interval
    if not directory.is_dir():
        raise FileNotFoundError(f"Missing indicator directory: {directory}")
    if not any(directory.glob("*.parquet")):
        raise FileNotFoundError(f"No parquet indicator files in: {directory}")
    return str(directory / "*.parquet")


def _rsi_lazy(glob: str) -> pl.LazyFrame:
    """Lazy scan projected to (symbol, trade_timestamp, rsi_14), rsi nulls dropped.

    rsi_14 is null until its 14-bar lookback is satisfied; dropping nulls per interval
    means a symbol short on bars at one interval falls out of that leg (and the inner
    join), rather than contributing a spurious 'latest' value.
    """
    return (
        pl.scan_parquet(glob)
        .select("symbol", "trade_timestamp", "rsi_14")
        .filter(pl.col("rsi_14").is_not_null())
    )


def _regime_leg(glob: str, prefix: str) -> pl.LazyFrame:
    """Bullish leg (monthly/weekly): latest rsi_14 + as-of timestamp + bar count."""
    by_ts = pl.col("rsi_14").sort_by("trade_timestamp")
    return _rsi_lazy(glob).group_by("symbol").agg(
        pl.len().alias(f"{prefix}_n"),
        pl.col("trade_timestamp").max().alias(f"{prefix}_ts"),
        by_ts.last().alias(f"{prefix}_rsi"),
    )


def _daily_leg(glob: str, cfg: ScreenConfig) -> pl.LazyFrame:
    """Daily dip leg: current rsi_14 and the recent peak over the lookback window."""
    by_ts = pl.col("rsi_14").sort_by("trade_timestamp")
    return _rsi_lazy(glob).group_by("symbol").agg(
        pl.len().alias("d_n"),
        pl.col("trade_timestamp").max().alias("d_ts"),
        by_ts.last().alias("d_cur"),
        by_ts.tail(cfg.daily_peak_lookback).max().alias("d_peak"),
    )


def _hourly_leg(glob: str, cfg: ScreenConfig) -> pl.LazyFrame:
    """Hourly regain leg: current rsi_14, the previous bar (the one-bar turn-up), and
    the recent dip-low over the lookback window."""
    by_ts = pl.col("rsi_14").sort_by("trade_timestamp")
    return _rsi_lazy(glob).group_by("symbol").agg(
        pl.len().alias("h_n"),
        pl.col("trade_timestamp").max().alias("h_ts"),
        by_ts.last().alias("h_cur"),
        by_ts.tail(2).first().alias("h_prev"),
        by_ts.tail(cfg.hourly_dip_lookback).min().alias("h_min"),
    )


# --------------------------------------------------------------------------------------
# Screen: join legs, evaluate the four predicates, gate, and account for exclusions.
# --------------------------------------------------------------------------------------
def _conditions(cfg: ScreenConfig) -> dict[str, pl.Expr]:
    """The four leg predicates as named boolean expressions over the joined frame."""
    return {
        "cond_monthly": pl.col("mo_rsi") > cfg.bull_rsi_min,
        "cond_weekly": pl.col("wk_rsi") > cfg.bull_rsi_min,
        "cond_daily": (
            (pl.col("d_peak") > cfg.daily_peak_min)
            & (pl.col("d_cur") <= pl.col("d_peak") - cfg.daily_drop_min)
            & pl.col("d_cur").is_between(cfg.daily_zone_lo, cfg.daily_zone_hi)
        ),
        "cond_hourly": (
            (pl.col("h_min") < cfg.hourly_dip_below)
            & (
                (pl.col("h_cur") > cfg.hourly_reclaim)
                | (
                    (pl.col("h_cur") > pl.col("h_prev"))
                    & (pl.col("h_cur") >= pl.col("h_min") + cfg.hourly_recovery_min)
                )
            )
        ),
    }


def _universe_counts(cfg: ScreenConfig) -> dict[str, int]:
    """Distinct symbols carrying a non-null rsi_14 at each interval (coverage)."""
    counts: dict[str, int] = {}
    for interval in LADDER:
        counts[interval] = (
            _rsi_lazy(_indicator_glob(cfg, interval))
            .select(pl.col("symbol").n_unique())
            .collect(engine="streaming")
            .item()
        )
    return counts


def screen(cfg: ScreenConfig) -> tuple[pl.DataFrame, dict]:
    """Run the four-leg screen. Returns (matches sorted by symbol, diagnostics).

    Each leg is an independent lazy per-symbol aggregation; the four are inner-joined on
    `symbol` (a match must exist at all four intervals). One streaming collect builds the
    tiny per-symbol frame; conditions and gating then run eagerly on it.
    """
    globs = {iv: _indicator_glob(cfg, iv) for iv in LADDER}
    joined = _regime_leg(globs["1mo"], "mo")
    for leg in (
        _regime_leg(globs["1wk"], "wk"),
        _daily_leg(globs["1d"], cfg),
        _hourly_leg(globs["1h"], cfg),
    ):
        joined = joined.join(leg, on="symbol", how="inner")

    conds = _conditions(cfg)
    frame = joined.with_columns(**conds).collect(engine="streaming")

    cond_cols = list(conds)
    matches = (
        frame.filter(pl.all_horizontal([pl.col(c) for c in cond_cols])).sort("symbol")
    )
    return matches, _diagnostics(frame, cfg)


def _diagnostics(frame: pl.DataFrame, cfg: ScreenConfig) -> dict:
    """Per-interval coverage, cumulative funnel, and as-of timestamps for disclosure."""
    order = ["cond_monthly", "cond_weekly", "cond_daily", "cond_hourly"]
    individual = {c: int(frame[c].sum()) for c in order}

    cumulative: dict[str, int] = {}
    running = pl.repeat(True, frame.height, eager=True)
    for c in order:
        running = running & frame[c]
        cumulative[c] = int(running.sum())

    return {
        "universe": _universe_counts(cfg),
        "common": frame.height,
        "individual": individual,
        "cumulative": cumulative,
        "final": cumulative[order[-1]],
        "as_of": {
            "monthly": frame["mo_ts"].max(),
            "weekly": frame["wk_ts"].max(),
            "daily": frame["d_ts"].max(),
            "hourly": frame["h_ts"].max(),
        },
    }


# --------------------------------------------------------------------------------------
# Reporting (talk-to-parquet output rules): source interval, as-of, formula, exclusions.
# --------------------------------------------------------------------------------------
def _fmt_ts(value) -> str:
    return "n/a" if value is None else f"{value:%Y-%m-%d %H:%M}"


def report(matches: pl.DataFrame, diag: dict, cfg: ScreenConfig) -> None:
    uni, asof = diag["universe"], diag["as_of"]
    print("=" * 82)
    print("BULLISH-DIP-REGAIN SCAN  (bigger TF bullish -> shorter TF dips & regains)")
    print("=" * 82)
    print("Source              : PRECALCULATED rsi_14, each leg at its EXACT stored")
    print("                      interval (1mo/1wk/1d/1h) -- nothing resampled or recomputed")
    print(f"Leg 1 bullish       : monthly rsi>{cfg.bull_rsi_min:g} AND weekly rsi>{cfg.bull_rsi_min:g}")
    print(f"Leg 2 daily dip     : peak({cfg.daily_peak_lookback}d)>{cfg.daily_peak_min:g}, "
          f"cur<=peak-{cfg.daily_drop_min:g}, cur in [{cfg.daily_zone_lo:g},{cfg.daily_zone_hi:g}]")
    print(f"Leg 3 hourly regain : min({cfg.hourly_dip_lookback}h)<{cfg.hourly_dip_below:g}, then "
          f"cur>{cfg.hourly_reclaim:g} OR (cur>prev & cur>=low+{cfg.hourly_recovery_min:g})")
    print("-" * 82)
    print(f"As-of (latest bar)  : monthly {_fmt_ts(asof['monthly'])} | weekly {_fmt_ts(asof['weekly'])}")
    print(f"                      daily   {_fmt_ts(asof['daily'])} | hourly {_fmt_ts(asof['hourly'])}")
    print(f"Coverage (symbols)  : 1mo={uni['1mo']} 1wk={uni['1wk']} 1d={uni['1d']} 1h={uni['1h']}"
          f"  ->  {diag['common']} present at ALL four (others excluded)")
    print("-" * 82)
    cum = diag["cumulative"]
    print("Funnel (cumulative AND):")
    print(f"  monthly rsi>{cfg.bull_rsi_min:g} ............. {cum['cond_monthly']:>3}")
    print(f"  + weekly  rsi>{cfg.bull_rsi_min:g} ........... {cum['cond_weekly']:>3}")
    print(f"  + daily   real dip ........... {cum['cond_daily']:>3}")
    print(f"  + hourly  regain => MATCHES .. {cum['cond_hourly']:>3}")
    print("=" * 82)

    if matches.height == 0:
        print("No symbols matched. Loosen a leg (e.g. --daily-drop-min, --zone, "
              "--hourly-recovery-min) to calibrate.")
        return

    show = matches.select(
        pl.col("symbol").cast(pl.Utf8),
        pl.col("mo_rsi").round(1).alias("mo"),
        pl.col("wk_rsi").round(1).alias("wk"),
        pl.col("d_peak").round(1).alias("d_peak"),
        pl.col("d_cur").round(1).alias("d_cur"),
        pl.col("h_min").round(1).alias("h_min"),
        pl.col("h_prev").round(1).alias("h_prev"),
        pl.col("h_cur").round(1).alias("h_cur"),
        (pl.col("h_cur") - pl.col("h_min")).round(1).alias("h_off"),
    )
    with pl.Config(tbl_rows=show.height, tbl_cols=show.width, tbl_width_chars=120):
        print(show)
    print()
    print("Legend: mo/wk = latest monthly/weekly RSI (bullish) | d_peak->d_cur = daily")
    print("        pullback from strength | h_min->h_prev->h_cur = hourly dip then turn |")
    print("        h_off = RSI pts recovered off the hourly low (>50 cur = already reclaimed).")


# --------------------------------------------------------------------------------------
def _build_config(args: argparse.Namespace) -> ScreenConfig:
    """Map only the CLI flags the user actually set onto ScreenConfig overrides."""
    overrides: dict[str, Any] = {"data_root": args.data_root}
    simple = {
        "bull_rsi_min": args.bull_rsi_min,
        "daily_peak_lookback": args.daily_peak_lookback,
        "daily_peak_min": args.daily_peak_min,
        "daily_drop_min": args.daily_drop_min,
        "hourly_dip_lookback": args.hourly_dip_lookback,
        "hourly_dip_below": args.hourly_dip_below,
        "hourly_reclaim": args.hourly_reclaim,
        "hourly_recovery_min": args.hourly_recovery_min,
    }
    overrides.update({k: v for k, v in simple.items() if v is not None})
    if args.zone is not None:
        overrides["daily_zone_lo"], overrides["daily_zone_hi"] = args.zone
    return ScreenConfig(**overrides)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Scan Parquet market data for bigger-TF-bullish / shorter-TF-dip-regain setups."
    )
    p.add_argument("--data-root", default="market-data")
    p.add_argument("--bull-rsi-min", type=float, default=None)
    p.add_argument("--daily-peak-lookback", type=int, default=None)
    p.add_argument("--daily-peak-min", type=float, default=None)
    p.add_argument("--daily-drop-min", type=float, default=None)
    p.add_argument("--zone", type=float, nargs=2, metavar=("LO", "HI"), default=None,
                   help="daily current-RSI pullback zone, inclusive (default 45 55)")
    p.add_argument("--hourly-dip-lookback", type=int, default=None)
    p.add_argument("--hourly-dip-below", type=float, default=None)
    p.add_argument("--hourly-reclaim", type=float, default=None)
    p.add_argument("--hourly-recovery-min", type=float, default=None)
    args = p.parse_args()

    cfg = _build_config(args)
    configure_logging(Path(cfg.data_root) / "logs")
    logger.info("Bullish-dip-regain scan config: %s", cfg)

    matches, diag = screen(cfg)
    logger.info(
        "Coverage %s | common=%d | funnel=%s | matches=%d",
        diag["universe"], diag["common"], diag["cumulative"], diag["final"],
    )
    logger.info("Matches: %s", matches["symbol"].to_list())
    report(matches, diag, cfg)


if __name__ == "__main__":
    main()
