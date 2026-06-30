"""
Pullback-gated de-risk backtest on HOURLY data.

Entry signal = faithful, walk-forward operationalization of the pullback-finder
grammar's BUY label ("buy-the-dip-turned"):
  1. uptrend at the turn bar  (close>ema_50 and ema_50 rising vs 20 bars ago)
  2. the dip depth (H->L)/H landed in the stock's OWN depth band (IQR of its PRIOR dips)
  3. the turn is confirmed: first up-thrust after the low (close>prev high) with
     lift >= the stock's LEARNED ATR-lift (median of prior winning dips)  OR
     a genuine reclaim of its LEARNED reclaim-EMA.
Signature (band, learned_lift, learned_ema) is learned ONLY from dips strictly
BEFORE the candidate (>=5 prior events and >=5 prior winners) -> no look-ahead.
k=5 fractal pivots fixed across names (disclosed approximation of the per-stock k).

Entry = the up-thrust bar's CLOSE. Forward sim identical to the daily study:
  A=50%@+3% | B=33%@+6% | C=100% BE-after+5% | D=100% no-derisk | Hold=buy&hold.
Initial -3% stop; trail close*0.97 after +15% close. Horizon H bars.
Conservative fills: adverse checked first; stop fills min(open,stop), tgt max(open,tgt).
A random-entry control runs the SAME machinery on the same hourly bars + horizon.
"""
import logging
import numpy as np
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pb")

K = 5                 # fractal half-window
H = 420               # forward horizon in hourly bars (~60 trading days @ 7 bars/day)
LEARN_HZN = 15        # bars after a dip low to judge "winner" (Block 6 default)
THRUST_WIN = 15       # bars to search for the first up-thrust after a low
MIN_PRIOR = 5         # min prior events / winners before a signal can fire
STOP, T3, T6, ARM, BE, TRAIL = 0.03, 0.03, 0.06, 0.15, 0.05, 0.03
COST = 0.0015
EMAS = ["ema_10", "ema_20", "ema_50", "ema_100", "ema_200"]


def load_sym(path):
    df = (pl.scan_parquet(path)
          .select("trade_timestamp", "open", "high", "low", "close")
          .sort("trade_timestamp").collect())
    if df.height < 250:
        return None
    df = df.with_columns([pl.col("close").ewm_mean(span=s, adjust=False).alias(f"ema_{s}")
                          for s in (10, 20, 50, 100, 200)])
    tr = pl.max_horizontal(pl.col("high") - pl.col("low"),
                           (pl.col("high") - pl.col("close").shift(1)).abs(),
                           (pl.col("low") - pl.col("close").shift(1)).abs())
    df = df.with_columns(tr.alias("tr")).with_columns(
        pl.col("tr").rolling_mean(14).alias("atr_14"))
    w = 2 * K + 1
    df = df.with_columns([
        (pl.col("high") == pl.col("high").rolling_max(w, center=True)).alias("is_ph"),
        (pl.col("low") == pl.col("low").rolling_min(w, center=True)).alias("is_pl")])
    return df


def zigzag(ts, hi, lo, is_ph, is_pl):
    piv = []
    for i in range(len(ts)):
        if is_ph[i]:
            piv.append((i, "H", hi[i]))
        if is_pl[i]:
            piv.append((i, "L", lo[i]))
    piv.sort(key=lambda x: x[0])
    zz = []
    for i, kind, price in piv:
        if zz and zz[-1][1] == kind:
            if (kind == "H" and price > zz[-1][2]) or (kind == "L" and price < zz[-1][2]):
                zz[-1] = (i, kind, price)
        else:
            zz.append((i, kind, price))
    return zz


def pullback_events(zz):
    """Held dips: H preceded by L and followed by a higher-L. Returns dip dicts."""
    ev = []
    for i in range(2, len(zz)):
        if zz[i][1] == "L" and zz[i - 1][1] == "H":
            Hp, Lp = zz[i - 1], zz[i]
            prev_L = next((zz[j] for j in range(i - 2, -1, -1) if zz[j][1] == "L"), None)
            if prev_L is None or Lp[2] <= prev_L[2]:
                continue                       # reversal (broke prior low) -> not a pullback
            ev.append({"hi_idx": Hp[0], "hi": Hp[2], "lo_idx": Lp[0], "lo": Lp[2],
                       "depth": (Hp[2] - Lp[2]) / Hp[2]})
    return ev


def annotate(ev, o, h, l, c, atr, emas):
    """Add thrust bar, lift, reclaim-ema, winner flag to each event."""
    n = len(c)
    for e in ev:
        li = e["lo_idx"]
        thrust = None
        for j in range(li + 1, min(li + 1 + THRUST_WIN, n)):
            if c[j] > h[j - 1]:
                thrust = j
                break
        e["thrust"] = thrust
        if thrust is not None and atr[li] and atr[li] > 0:
            e["lift"] = (c[thrust] - e["lo"]) / atr[li]
            rec = "none"
            for em in reversed(EMAS):
                el, et = emas[em][li], emas[em][thrust]
                if el and et and e["lo"] < el and c[thrust] > et:
                    rec = em
                    break
            e["reclaim"] = rec
        else:
            e["lift"], e["reclaim"] = None, None
        # winner (Block 6): new high > hi before -3% stop within LEARN_HZN after low
        stop = e["lo"] * (1 - STOP)
        win = False
        for j in range(li + 1, min(li + 1 + LEARN_HZN, n)):
            if l[j] <= stop:
                break
            if h[j] > e["hi"]:
                win = True
                break
        e["winner"] = win
    return ev


def pullback_entries(df):
    """Walk-forward: return entry bar indices that fire 'buy-the-dip-turned'."""
    ts = df["trade_timestamp"].to_numpy()
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    atr = df["atr_14"].to_numpy()
    emas = {em: df[em].to_numpy() for em in EMAS}
    e50 = emas["ema_50"]
    ev = pullback_events(zigzag(ts, h, l, df["is_ph"].to_numpy(), df["is_pl"].to_numpy()))
    ev = annotate(ev, o, h, l, c, atr, emas)
    ev.sort(key=lambda x: x["lo_idx"])
    entries, depths, winners_lift, winners_rec = [], [], [], []
    for e in ev:
        t = e["thrust"]
        if t is not None and len(depths) >= MIN_PRIOR and len(winners_lift) >= MIN_PRIOR:
            band_lo, band_hi = np.percentile(depths, 25), np.percentile(depths, 75)
            learned_lift = float(np.median(winners_lift))
            uptrend = (t >= 20 and c[t] > e50[t] and e50[t] > e50[t - 20])
            in_band = band_lo <= e["depth"] <= band_hi
            lift_ok = e["lift"] is not None and e["lift"] >= learned_lift
            rec_ok = e["reclaim"] is not None and e["reclaim"] != "none"
            if uptrend and in_band and (lift_ok or rec_ok) and t < len(c) - H - 1:
                entries.append(t)
        depths.append(e["depth"])              # grow signature AFTER (walk-forward)
        if e["winner"] and e["lift"] is not None:
            winners_lift.append(e["lift"])
            winners_rec.append(e["reclaim"])
    return entries, (o, h, l, c)


# ---- forward sim (identical mechanics to the daily study) -------------------
def sim_fixed(o, h, l, c, i, p0, target):
    tp, sl = p0 * (1 + target), p0 * (1 - STOP)
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1, False
        if h[d] >= tp:
            return max(o[d], tp) / p0 - 1, True
    return c[end] / p0 - 1, False


def sim_runner(o, h, l, c, i, p0):
    sl, armed, mae = p0 * (1 - STOP), False, 0.0
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        mae = min(mae, l[d] / p0 - 1)
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1, armed, mae
        if not armed and c[d] >= p0 * (1 + ARM):
            armed = True
        if armed:
            sl = max(sl, c[d] * (1 - TRAIL))
    return c[end] / p0 - 1, armed, mae


def sim_varc(o, h, l, c, i, p0):
    sl, be, arm = p0 * (1 - STOP), False, False
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1
        if not be and c[d] >= p0 * (1 + BE):
            be, sl = True, max(sl, p0)
        if not arm and c[d] >= p0 * (1 + ARM):
            arm = True
        if arm:
            sl = max(sl, c[d] * (1 - TRAIL))
    return c[end] / p0 - 1


def simulate(entries_by_sym):
    acc = {k: [] for k in ("A", "B", "C", "D", "Hold")}
    h3, h6, armed, mae = [], [], [], []
    for (o, h, l, c), idxs in entries_by_sym:
        for i in idxs:
            p0 = c[i]
            if p0 <= 0:
                continue
            f3, ok3 = sim_fixed(o, h, l, c, i, p0, T3)
            f6, ok6 = sim_fixed(o, h, l, c, i, p0, T6)
            run, arm, m = sim_runner(o, h, l, c, i, p0)
            cc = sim_varc(o, h, l, c, i, p0)
            end = min(i + H, len(c) - 1)
            acc["A"].append(0.5 * f3 + 0.5 * run)
            acc["B"].append((1 / 3) * f6 + (2 / 3) * run)
            acc["C"].append(cc)
            acc["D"].append(run)
            acc["Hold"].append(c[end] / p0 - 1)
            h3.append(ok3)
            h6.append(ok6)
            armed.append(arm)
            mae.append(m)
    return {k: np.array(v) for k, v in acc.items()} | {
        "h3": np.array(h3), "h6": np.array(h6), "armed": np.array(armed),
        "mae": np.array(mae), "n": len(h3)}


def stop_sweep(entries_by_sym, widths):
    res = {w: [] for w in widths}
    for (o, h, l, c), idxs in entries_by_sym:
        for i in idxs:
            p0 = c[i]
            if p0 <= 0:
                continue
            for w in widths:
                end = min(i + H, len(c) - 1)
                sl, armed = p0 * (1 - w), False
                out = c[end] / p0 - 1
                for d in range(i + 1, end + 1):
                    if l[d] <= sl:
                        out = min(o[d], sl) / p0 - 1
                        break
                    if not armed and c[d] >= p0 * (1 + ARM):
                        armed = True
                    if armed:
                        sl = max(sl, c[d] * (1 - TRAIL))
                res[w].append(out)
    return {w: np.array(v) for w, v in res.items()}


def report(tag, d):
    print(f"\n##### {tag}  (n={d['n']:,})")
    print(f"P(+3 before -3): {100*d['h3'].mean():5.1f}%   "
          f"P(+6 before -3): {100*d['h6'].mean():5.1f}%   "
          f"P(reach +15%): {100*d['armed'].mean():5.1f}%   "
          f"mean MAE: {100*d['mae'].mean():5.2f}%")
    for k in ("A", "B", "C", "D", "Hold"):
        x = d[k]
        print(f"  {k:4s} mean {100*x.mean():6.2f}% | med {100*np.median(x):6.2f}% | "
              f"win {100*(x>0).mean():5.1f}% | full-loss {100*(x<=-0.029).mean():5.1f}% | "
              f"p95 {100*np.percentile(x,95):6.2f}% | net {100*(x.mean()-COST):5.2f}%")


def main():
    import glob
    files = sorted(glob.glob("market-data/prices/1h/*.parquet"))
    pb_entries, rnd_entries = [], []
    for f in files:
        df = load_sym(f)
        if df is None:
            continue
        idxs, arrs = pullback_entries(df)
        if idxs:
            pb_entries.append((arrs, idxs))
        o, h, l, c = arrs
        rnd = list(range(0, len(c) - H - 1, 25))      # every 25th bar control
        if rnd:
            rnd_entries.append((arrs, rnd))
    log.info("pullback entries: %d across %d symbols",
             sum(len(i) for _, i in pb_entries), len(pb_entries))

    pb, rnd = simulate(pb_entries), simulate(rnd_entries)
    print("\n================ HOURLY: PULLBACK-GATED vs RANDOM ENTRY ================")
    print("Legend: A=50%@+3% B=33%@+6% C=100%BE-5% D=100%no-derisk Hold=buy&hold | H=420 1h bars")
    report("RANDOM entry (control)", rnd)
    report("PULLBACK entry (buy-the-dip-turned)", pb)

    widths = [0.03, 0.05, 0.08, 0.10]
    sw = stop_sweep(pb_entries, widths)
    print("\n##### PULLBACK-entry stop-width sweep (100% runner, trail after +15%)")
    for w in widths:
        x = sw[w]
        print(f"  stop -{int(w*100):2d}%: mean {100*x.mean():6.2f}% | med {100*np.median(x):6.2f}% | "
              f"win {100*(x>0).mean():5.1f}% | full-loss {100*(x<=-0.029).mean():5.1f}%")


if __name__ == "__main__":
    main()
