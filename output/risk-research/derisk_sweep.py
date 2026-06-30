"""Stop-width sensitivity: is the -3% stop the leak?

Reuses the loader + runner idea: 100% size, fixed initial stop, trail (close*0.97)
after +15% close, horizon 60d. Sweep the initial stop width and report.
Also an ATR-based stop (k * atr_percent_14 at entry) for the volatility-scaled view.
"""
import logging
import numpy as np
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sweep")

H, STEP, ARM, TRAIL = 60, 5, 0.15, 0.03


def load():
    px = (pl.scan_parquet("market-data/prices/1d/*.parquet")
          .select("symbol", "trade_timestamp", "open", "high", "low", "close"))
    ind = (pl.scan_parquet("market-data/indicators/1d/*.parquet")
           .select("symbol", "trade_timestamp", "atr_percent_14"))
    df = px.join(ind, on=["symbol", "trade_timestamp"], how="left").drop_nulls(
        ["open", "high", "low", "close"]).collect(engine="streaming")
    out = {}
    for sym, sub in df.partition_by("symbol", as_dict=True).items():
        s = sub.sort("trade_timestamp")
        key = sym[0] if isinstance(sym, tuple) else sym
        out[key] = (s["open"].to_numpy(), s["high"].to_numpy(), s["low"].to_numpy(),
                    s["close"].to_numpy(), s["atr_percent_14"].to_numpy())
    return out


def runner(o, h, l, c, i, p0, stop_frac):
    sl = p0 * (1 - stop_frac)
    armed = False
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1
        if not armed and c[d] >= p0 * (1 + ARM):
            armed = True
        if armed:
            sl = max(sl, c[d] * (1 - TRAIL))
    return c[end] / p0 - 1


def main():
    uni = load()
    log.info("loaded %d symbols", len(uni))
    fixed = [0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
    atr_k = [2.0, 3.0]
    res = {f"fix {int(s*100)}%": [] for s in fixed}
    res.update({f"ATR x{k:g}": [] for k in atr_k})
    for sym, (o, h, l, c, ap) in uni.items():
        n = len(c)
        if n <= H + 1:
            continue
        for i in range(0, n - H - 1, STEP):
            p0 = c[i]
            if p0 <= 0:
                continue
            for s in fixed:
                res[f"fix {int(s*100)}%"].append(runner(o, h, l, c, i, p0, s))
            a = ap[i]
            if a is None or not np.isfinite(a) or a <= 0:
                continue
            for k in atr_k:
                res[f"ATR x{k:g}"].append(runner(o, h, l, c, i, p0, k * a / 100.0))
    print("\n=== STOP-WIDTH SWEEP (100% size, trail after +15%, H=60d) ===")
    print(f"{'stop':10s} {'mean':>8s} {'median':>8s} {'win%':>7s} "
          f"{'fullloss%':>10s} {'p95':>8s} {'std':>7s}  n")
    order = [f"fix {int(s*100)}%" for s in fixed] + [f"ATR x{k:g}" for k in atr_k]
    for name in order:
        x = np.array(res[name])
        # "full loss" threshold scales loosely; report <= -2.9% as a fixed ref plus stop-rel
        print(f"{name:10s} {100*x.mean():7.2f}% {100*np.median(x):7.2f}% "
              f"{100*(x>0).mean():6.1f}% {100*(x<=-0.029).mean():9.1f}% "
              f"{100*np.percentile(x,95):7.2f}% {100*x.std():6.2f}%  {len(x):,}")


if __name__ == "__main__":
    main()
