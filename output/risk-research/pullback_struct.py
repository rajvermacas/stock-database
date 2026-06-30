"""
Final test: your A/D design with the STRUCTURAL stop (live higher-low = the dip low,
minus a small buffer) instead of a flat -3%. +3% target on half A kept. Runner trails
close*0.97 after +15% close, never below the structural stop. Same pullback entries as
before; flat-3% computed on the SAME entries for a clean head-to-head.

Reports realized return AND risk context: structural-stop distance per trade and the
R-multiple (return / initial risk) so wider stops aren't credited as 'free' return.
"""
import sys
import numpy as np
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pullback_backtest as pb  # reuse loader + grammar plumbing

BUF = 0.003          # structural stop placed 0.3% below the live higher-low (dip low)
H, ARM, TRAIL, T3 = pb.H, pb.ARM, pb.TRAIL, pb.T3


def entries_with_lows(df):
    """Same walk-forward 'buy-the-dip-turned' detector, but also return each entry's dip low."""
    ts = df["trade_timestamp"].to_numpy()
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    atr = df["atr_14"].to_numpy()
    emas = {em: df[em].to_numpy() for em in pb.EMAS}
    e50 = emas["ema_50"]
    ev = pb.pullback_events(pb.zigzag(ts, h, l, df["is_ph"].to_numpy(), df["is_pl"].to_numpy()))
    ev = pb.annotate(ev, o, h, l, c, atr, emas)
    ev.sort(key=lambda x: x["lo_idx"])
    out, depths, wl = [], [], []
    for e in ev:
        t = e["thrust"]
        if t is not None and len(depths) >= pb.MIN_PRIOR and len(wl) >= pb.MIN_PRIOR:
            blo, bhi = np.percentile(depths, 25), np.percentile(depths, 75)
            learned = float(np.median(wl))
            up = (t >= 20 and c[t] > e50[t] and e50[t] > e50[t - 20])
            in_band = blo <= e["depth"] <= bhi
            lift_ok = e["lift"] is not None and e["lift"] >= learned
            rec_ok = e["reclaim"] not in (None, "none")
            if up and in_band and (lift_ok or rec_ok) and t < len(c) - H - 1:
                out.append((t, e["lo"]))          # entry bar + dip low (structural stop ref)
        depths.append(e["depth"])
        if e["winner"] and e["lift"] is not None:
            wl.append(e["lift"])
    return out, (o, h, l, c)


def fixed_struct(o, h, l, c, i, p0, sl, target):
    tp = p0 * (1 + target)
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1
        if h[d] >= tp:
            return max(o[d], tp) / p0 - 1
    return c[end] / p0 - 1


def runner_struct(o, h, l, c, i, p0, sl):
    armed = False
    end = min(i + H, len(c) - 1)
    for d in range(i + 1, end + 1):
        if l[d] <= sl:
            return min(o[d], sl) / p0 - 1, armed
        if not armed and c[d] >= p0 * (1 + ARM):
            armed = True
        if armed:
            sl = max(sl, c[d] * (1 - TRAIL))
    return c[end] / p0 - 1, armed


def run():
    import glob
    A_s, D_s, A_f, D_f, Hold = [], [], [], [], []
    risk, Rmult_D, armed_s = [], [], []
    n = 0
    for f in sorted(glob.glob("market-data/prices/1h/*.parquet")):
        df = pb.load_sym(f)
        if df is None:
            continue
        ent, (o, h, l, c) = entries_with_lows(df)
        for i, lo in ent:
            p0 = c[i]
            sl = lo * (1 - BUF)
            r0 = (p0 - sl) / p0                 # structural initial risk (stop distance)
            if p0 <= 0 or r0 <= 0:
                continue
            # structural-stop design
            fa = fixed_struct(o, h, l, c, i, p0, sl, T3)
            rn, arm = runner_struct(o, h, l, c, i, p0, sl)
            A_s.append(0.5 * fa + 0.5 * rn)
            D_s.append(rn)
            risk.append(r0)
            Rmult_D.append(rn / r0)
            armed_s.append(arm)
            # flat -3% on the SAME entry
            f3, _ = pb.sim_fixed(o, h, l, c, i, p0, T3)
            rnf, _, _ = pb.sim_runner(o, h, l, c, i, p0)
            A_f.append(0.5 * f3 + 0.5 * rnf)
            D_f.append(rnf)
            end = min(i + H, len(c) - 1)
            Hold.append(c[end] / p0 - 1)
            n += 1
    return dict(A_s=np.array(A_s), D_s=np.array(D_s), A_f=np.array(A_f),
                D_f=np.array(D_f), Hold=np.array(Hold), risk=np.array(risk),
                R=np.array(Rmult_D), armed=np.array(armed_s), n=n)


def line(tag, x, risk=None):
    s = (f"  {tag:18s} mean {100*x.mean():6.2f}% | med {100*np.median(x):6.2f}% | "
         f"win {100*(x>0).mean():5.1f}% | p95 {100*np.percentile(x,95):6.2f}% | "
         f"net {100*(x.mean()-pb.COST):5.2f}%")
    return s


def main():
    d = run()
    print(f"\n================ FINAL: STRUCTURAL stop vs flat -3%  (same {d['n']:,} pullback entries) ================")
    r = d["risk"] * 100
    print(f"\nStructural stop distance from entry: median {np.median(r):.2f}% | "
          f"mean {r.mean():.2f}% | IQR {np.percentile(r,25):.2f}-{np.percentile(r,75):.2f}% | "
          f"share wider than 3%: {100*(d['risk']>0.03).mean():.0f}%")
    print(f"P(reach +15% & arm), structural: {100*d['armed'].mean():.1f}%")

    print("\n-- Your design A (50%@+3% + runner), +3% target kept --")
    print(line("flat -3% stop", d["A_f"]))
    print(line("STRUCTURAL stop", d["A_s"]))
    print("\n-- Runner-only D (100%, trail after +15%) --")
    print(line("flat -3% stop", d["D_f"]))
    print(line("STRUCTURAL stop", d["D_s"]))
    print(line("buy & hold (anchor)", d["Hold"]))

    print(f"\nRisk-adjusted (runner D, structural): mean R-multiple = {d['R'].mean():.2f}  "
          f"(return per unit of initial risk; >0 = edge after risk)")
    print(f"Flat -3% runner D mean R-multiple    = {(d['D_f'].mean()/0.03):.2f}")


if __name__ == "__main__":
    main()
