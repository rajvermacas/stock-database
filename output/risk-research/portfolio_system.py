"""
Capstone: event-driven PORTFOLIO backtest of the proposed risk system, optimised for
risk-adjusted return (Calmar = CAGR / max drawdown).

System under test (hourly single-name pullback book, daily-managed):
  ENTRY   : pullback 'buy-the-dip-turned' (walk-forward grammar) ...
  REGIME  : ... only when the equal-weight market is risk-on (EW index > its 200-day
            EMA, prior-day, no look-ahead). Regime-off -> no NEW entries; opens ride.
  SIZING  : volatility-based. Each trade risks RISK_PCT of current equity; shares =
            risk / (ATR_MULT * ATR_at_entry). Capped at MAX_POS_PCT of equity, no leverage.
  STOP    : ATR chandelier. Initial = entry - ATR_MULT*ATR. Then ratchet:
            stop = max(stop, highest_close_since_entry - ATR_MULT*ATR_now). Winners run.
  EXIT    : trail hit (fill min(open,stop)) or MAX_HOLD bars (dead-money time stop).
  DIVERSIFY: <= MAX_POS concurrent names.

Reported vs two benchmarks on the SAME window:
  (1) same system, regime filter OFF   -> isolates the regime lever
  (2) buy & hold the equal-weight index -> the 'just hold' anchor
Metrics: CAGR, max drawdown, Calmar, exposure, trade count, win rate.
"""
import glob
import logging
import sys
import numpy as np
import polars as pl

import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pullback_backtest as pb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("port")

RISK_PCT = 0.0075        # 0.75% of equity risked per trade
ATR_MULT = 3.0           # initial stop & chandelier trail distance, in ATR
MAX_POS = 20             # max concurrent positions (diversification cap)
MAX_POS_PCT = 0.12       # max notional per position
MAX_HOLD = 420           # hourly-bar time stop (~60 trading days)
START = 1_000_000.0
COST = 0.0010            # 0.1% per side (STT+charges+slippage), charged on entry & exit


def entry_idxs(df):
    ts = df["trade_timestamp"].to_list()
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    atr = df["atr_14"].to_numpy()
    emas = {em: df[em].to_numpy() for em in pb.EMAS}
    e50 = emas["ema_50"]
    ev = pb.annotate(pb.pullback_events(pb.zigzag(
        ts, h, l, df["is_ph"].to_numpy(), df["is_pl"].to_numpy())), o, h, l, c, atr, emas)
    ev.sort(key=lambda x: x["lo_idx"])
    idxs, depths, wl = set(), [], []
    for e in ev:
        t = e["thrust"]
        if t is not None and len(depths) >= pb.MIN_PRIOR and len(wl) >= pb.MIN_PRIOR:
            blo, bhi = np.percentile(depths, 25), np.percentile(depths, 75)
            up = (t >= 20 and c[t] > e50[t] and e50[t] > e50[t - 20])
            lift_ok = e["lift"] is not None and e["lift"] >= float(np.median(wl))
            if up and blo <= e["depth"] <= bhi and (lift_ok or e["reclaim"] not in (None, "none")):
                idxs.add(t)
        depths.append(e["depth"])
        if e["winner"] and e["lift"] is not None:
            wl.append(e["lift"])
    return idxs, ts, o, h, l, c, atr


def build_index():
    """Equal-weight market level from daily closes. Robust to bad single-symbol prints:
    clipped daily returns, MEDIAN across the universe."""
    df = (pl.scan_parquet("market-data/prices/1d/*.parquet")
          .select("symbol", "trade_timestamp", "close").collect(engine="streaming"))
    wide = (df.sort("symbol", "trade_timestamp")
            .with_columns(pl.col("trade_timestamp").dt.date().alias("d"))
            .group_by("symbol", "d").agg(pl.col("close").last())
            .sort("symbol", "d")
            .with_columns(pl.col("close").pct_change().over("symbol").clip(-0.3, 0.3).alias("r")))
    idx = (wide.group_by("d").agg(pl.col("r").median().alias("mret")).sort("d")
           .with_columns((1 + pl.col("mret").fill_null(0)).cum_prod().alias("lvl")))
    return idx


def regime_from(idx, span):
    """regime ON when the EW index closed above its `span`-day EMA the PRIOR day."""
    g = idx.with_columns(pl.col("lvl").ewm_mean(span=span, adjust=False).alias("e"))
    g = g.with_columns((pl.col("lvl") > pl.col("e")).shift(1).alias("on"))
    return {d: bool(o) for d, o in zip(g["d"].to_list(), g["on"].to_list()) if o is not None}


def simulate(syms, regime, use_regime):
    cash, eq_bar, opens = START, [], {}            # opens: sym -> dict; eq_bar: per-bar equity
    tl = sorted({t for s in syms.values() for t in s["ts"]})
    for s in syms.values():
        s["pos"] = {t: i for i, t in enumerate(s["ts"])}
    trades, days, exdays = [], set(), set()
    for t in tl:
        day = t.date()
        for sym in list(opens.keys()):                           # --- manage opens (exits) ---
            s = syms[sym]
            i = s["pos"].get(t)
            if i is None:
                continue
            p = opens[sym]
            lo, op, cl, atr = s["l"][i], s["o"][i], s["c"][i], s["atr"][i]
            if lo <= p["stop"]:                                  # stop/trail hit
                cash += p["sh"] * min(op, p["stop"]) * (1 - COST)
                trades.append(min(op, p["stop"]) / p["entry"] - 1)
                del opens[sym]
                continue
            p["hi"] = max(p["hi"], cl)
            if atr is not None and np.isfinite(atr) and atr > 0:
                p["stop"] = max(p["stop"], p["hi"] - ATR_MULT * atr)
            p["mtm"], p["bars"] = cl, p["bars"] + 1
            if p["bars"] >= MAX_HOLD:                            # time stop
                cash += p["sh"] * cl * (1 - COST)
                trades.append(cl / p["entry"] - 1)
                del opens[sym]
        on = regime.get(day, False) if use_regime else True      # --- entries ---
        if on:
            equity = cash + sum(o["sh"] * o["mtm"] for o in opens.values())
            for sym, s in syms.items():
                i = s["pos"].get(t)
                if i is None or i not in s["sig"] or sym in opens or len(opens) >= MAX_POS:
                    continue
                atr, entry = s["atr"][i], s["c"][i]
                if atr is None or not np.isfinite(atr) or atr <= 0:
                    continue
                sh = (RISK_PCT * equity) / (ATR_MULT * atr)
                notional = sh * entry
                cap = min(cash / (1 + COST), MAX_POS_PCT * equity)
                if notional > cap:
                    sh, notional = cap / entry, cap
                if sh <= 0 or notional * (1 + COST) > cash:
                    continue
                cash -= notional * (1 + COST)
                opens[sym] = {"sh": sh, "entry": entry, "stop": entry - ATR_MULT * atr,
                              "hi": entry, "mtm": entry, "bars": 0}
        eq_bar.append(cash + sum(o["sh"] * o["mtm"] for o in opens.values()))
        days.add(day)
        if opens:
            exdays.add(day)
    return np.array(eq_bar), len(days), trades, len(exdays) / max(len(days), 1)


def metrics(name, eq, n_days, trades, expo):
    years = max(n_days, 1) / 252
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1
    peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min()
    calmar = cagr / abs(mdd) if mdd < 0 else float("inf")
    tr = np.array(trades) if trades else np.array([0.0])
    print(f"{name:34s} | CAGR {100*cagr:6.2f}% | maxDD {100*mdd:6.2f}% | "
          f"Calmar {calmar:5.2f} | expo {100*expo:4.0f}% | "
          f"trades {len(trades):4d} | win {100*(tr>0).mean():4.1f}% | "
          f"finalx {eq[-1]/eq[0]:.2f}")


def main():
    idx = build_index()
    regime = regime_from(idx, 200)
    syms = {}
    for f in sorted(glob.glob("market-data/prices/1h/*.parquet")):
        df = pb.load_sym(f)
        if df is None:
            continue
        sig, ts, o, h, l, c, atr = entry_idxs(df)
        if not sig:
            continue
        sym = f.split("/")[-1].replace(".parquet", "")
        syms[sym] = {"sig": sig, "ts": list(ts), "o": o, "h": h, "l": l, "c": c, "atr": atr}
    log.info("symbols with signals: %d", len(syms))

    regime50 = regime_from(idx, 50)
    eq_on, d_on, tr_on, ex_on = simulate(syms, regime, True)
    eq_50, d_50, tr_50, ex_50 = simulate(syms, regime50, True)
    eq_off, d_off, tr_off, ex_off = simulate(syms, regime, False)

    # benchmark: equal-weight index buy & hold over the SAME date window as the hourly book
    hourly_start = min(t.date() for s in syms.values() for t in s["ts"])
    bench = (idx.filter(pl.col("d") >= hourly_start).sort("d")["lvl"].to_numpy())
    bench = bench[np.isfinite(bench)]
    # what fraction of the hourly window was regime-ON (context for the filter)
    rdays = [d for d in (idx.filter(pl.col("d") >= hourly_start)["d"].to_list()) if regime.get(d)]
    on_frac = len(rdays) / max(idx.filter(pl.col("d") >= hourly_start).height, 1)
    print("\n================ PORTFOLIO RESULTS (risk-adjusted, net of 0.1%/side) ================")
    print(f"hourly window from {hourly_start}; market regime-ON(200d) {100*on_frac:.0f}% of the window")
    metrics("SYSTEM regime-ON (200d EMA)", eq_on, d_on, tr_on, ex_on)
    metrics("SYSTEM regime-ON (50d EMA)", eq_50, d_50, tr_50, ex_50)
    metrics("SYSTEM no regime filter", eq_off, d_off, tr_off, ex_off)
    metrics("Equal-weight index buy&hold", bench, len(bench), [], 1.0)
    print("\nParams: risk/trade 0.75%, stop+trail 3xATR, <=20 names, 12% max/pos, 60d time-stop, "
          "0.1%/side cost. Drawdown computed per hourly bar.")


if __name__ == "__main__":
    main()
