"""
De-risk strategy backtest on the daily Parquet universe.

Question (from the trading-design discussion):
  Compare ways of making a swing trade "de-risked", and quantify the base rates
  the design assumes:
    - P(tag +3% before -3%)   -> does the 50%@+3% de-risk usually arm?
    - P(tag +6% before -3%)   -> alternative 33%@+6% de-risk
    - P(reach +15% before -3%) -> does the runner "graduate" to trailing?

Variants compared (entry = a bar's close; -3% initial stop on everything):
  A : sell 50% @ +3%, runner(50%) single -3% stop, trail (close*0.97) after +15% close
  B : sell 33% @ +6%, runner(67%) same runner rule
  C : keep 100%, move stop -> breakeven after +5% close, trail after +15% close
  D : keep 100% (no de-risk), -3% stop, trail after +15% close      [control]
  H : buy & exit at horizon close (no management)                   [anchor]

Methodology / assumptions (stated, conservative):
  - Daily bars. Horizon H = 60 trading days; unexited trades marked out at close.
  - Entries sampled every STEP=5 bars per symbol to cut overlap autocorrelation.
  - Same-day ambiguity: ADVERSE checked before favourable (worst-case).
  - Gap fills: stop fills at min(open, stop); target at max(open, target).
  - Arming/trailing use that day's CLOSE, applied to SUBSEQUENT days (no look-ahead).
  - Gross first; a 0.15%/exit cost proxy applied for the 'net' view.
"""
import glob
import logging
import numpy as np
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("derisk")

H = 60          # holding horizon in trading days
STEP = 5        # entry sampling stride per symbol
STOP = 0.03     # -3% initial stop
T3, T6 = 0.03, 0.06
ARM = 0.15      # +15% close arms the trail
BE = 0.05       # +5% close arms breakeven (variant C)
TRAIL = 0.03    # trail distance once armed
COST = 0.0015   # per-exit cost proxy for the 'net' view


def load_universe():
    lf = (pl.scan_parquet("market-data/prices/1d/*.parquet")
          .select("symbol", "trade_timestamp", "open", "high", "low", "close")
          .drop_nulls())
    df = lf.collect(engine="streaming")
    out = {}
    for sym, sub in df.partition_by("symbol", as_dict=True).items():
        s = sub.sort("trade_timestamp")
        out[sym[0] if isinstance(sym, tuple) else sym] = (
            s["open"].to_numpy(), s["high"].to_numpy(),
            s["low"].to_numpy(), s["close"].to_numpy())
    return out


def sim_fixed(o, h, l, c, i, p0, target):
    """One leg: take-profit at +target, else -STOP stop, else horizon close."""
    tp, sl = p0 * (1 + target), p0 * (1 - STOP)
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        if l[d] <= sl:                       # adverse first
            return min(o[d], sl) / p0 - 1, "stop", d - i
        if h[d] >= tp:
            return max(o[d], tp) / p0 - 1, "target", d - i
    return c[end] / p0 - 1, "horizon", end - i


def sim_runner(o, h, l, c, i, p0):
    """Single -STOP stop; after +ARM close, trail at close*(1-TRAIL), ratchet up."""
    sl = p0 * (1 - STOP)
    armed = False
    end = min(i + H, len(c) - 1)
    mae = 0.0
    for d in range(i + 1, end + 1):
        mae = min(mae, l[d] / p0 - 1)
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1, "stop", d - i, armed, mae
        if not armed and c[d] >= p0 * (1 + ARM):
            armed = True
        if armed:
            sl = max(sl, c[d] * (1 - TRAIL))
    return c[end] / p0 - 1, "horizon", end - i, armed, mae


def sim_variant_c(o, h, l, c, i, p0):
    """100% size: stop->BE after +BE close, trail after +ARM close."""
    sl = p0 * (1 - STOP)
    be_done = arm_done = False
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1
        if not be_done and c[d] >= p0 * (1 + BE):
            be_done, sl = True, max(sl, p0)
        if not arm_done and c[d] >= p0 * (1 + ARM):
            arm_done = True
        if arm_done:
            sl = max(sl, c[d] * (1 - TRAIL))
    return c[end] / p0 - 1


def run():
    uni = load_universe()
    log.info("loaded %d symbols", len(uni))
    rA, rB, rC, rD, rH = [], [], [], [], []
    hit3, hit6, armed_flags, mae_all, runner_ret = [], [], [], [], []
    n_entries = 0
    for sym, (o, h, l, c) in uni.items():
        n = len(c)
        if n <= H + 1:
            continue
        for i in range(0, n - H - 1, STEP):
            p0 = c[i]
            if p0 <= 0:
                continue
            f3, k3, _ = sim_fixed(o, h, l, c, i, p0, T3)
            f6, _, _ = sim_fixed(o, h, l, c, i, p0, T6)
            run_r, _, _, armed, mae = sim_runner(o, h, l, c, i, p0)
            cR = sim_variant_c(o, h, l, c, i, p0)
            end = min(i + H, n - 1)
            holdret = c[end] / p0 - 1
            rA.append(0.5 * f3 + 0.5 * run_r)
            rB.append((1/3) * f6 + (2/3) * run_r)
            rC.append(cR)
            rD.append(run_r)
            rH.append(holdret)
            hit3.append(k3 == "target")
            hit6.append(f6 >= T6 - 1e-9)
            armed_flags.append(armed)
            mae_all.append(mae)
            runner_ret.append(run_r)
            n_entries += 1
    log.info("simulated %d entries", n_entries)
    return dict(A=np.array(rA), B=np.array(rB), C=np.array(rC), D=np.array(rD),
               Hold=np.array(rH), hit3=np.array(hit3), hit6=np.array(hit6),
               armed=np.array(armed_flags), mae=np.array(mae_all),
               runner=np.array(runner_ret), n=n_entries)


def stats(name, r, net=False):
    x = r - COST if net else r
    return (f"{name:5s} | mean {100*x.mean():6.2f}% | median {100*np.median(x):6.2f}% | "
            f"win {100*(x>0).mean():5.1f}% | full-loss<=-2.9% {100*(x<=-0.029).mean():5.1f}% | "
            f"p5 {100*np.percentile(x,5):6.2f}% | p95 {100*np.percentile(x,95):6.2f}% | "
            f"std {100*x.std():5.2f}%")


def main():
    d = run()
    print("\n================  HEADLINE BASE RATES  (H=%d trading days)  ================" % H)
    print(f"entries simulated      : {d['n']:,}")
    print(f"P(tag +3% before -3%)  : {100*d['hit3'].mean():.1f}%")
    print(f"P(tag +6% before -3%)  : {100*d['hit6'].mean():.1f}%")
    print(f"P(reach +15% & arm)    : {100*d['armed'].mean():.1f}%   (runner 'graduates' to trailing)")
    print(f"mean MAE (heat taken)  : {100*d['mae'].mean():.2f}%   p5 worst {100*np.percentile(d['mae'],5):.2f}%")
    print(f"  runner mean ret           : {100*d['runner'].mean():.2f}%")
    print(f"  runner | armed (reached15): {100*d['runner'][d['armed']].mean():.2f}%   "
          f"n={d['armed'].sum():,}")
    print(f"  runner | not armed        : {100*d['runner'][~d['armed']].mean():.2f}%")

    print("\n================  VARIANT COMPARISON — GROSS  ================")
    for k in ["A", "B", "C", "D", "Hold"]:
        print(stats(k, d[k], net=False))
    print("\n================  VARIANT COMPARISON — NET (-0.15%/exit proxy)  ================")
    for k in ["A", "B", "C", "D", "Hold"]:
        print(stats(k, d[k], net=True))

    print("\nLegend: A=50%@+3%  B=33%@+6%  C=100% BE-after-5%  D=100% no-derisk  Hold=buy&hold 60d")


if __name__ == "__main__":
    main()
