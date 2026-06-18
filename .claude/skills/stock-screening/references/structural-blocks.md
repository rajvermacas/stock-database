# Structural Blocks — the Stage-S grammar (pattern-agnostic, companion to pullback-finder)

Stage S is a second lens, run in parallel to the dip funnel. It detects that a *structure
is forming* — pattern-agnostically, **without any named template** — by encoding the recent
zigzag-pivot window as a scale-invariant shape fingerprint, matching it against the stock's
**own** historical shapes, and reading what those analogs did next. A pullback is just one
shape; this generalizes to all of them.

Run everything read-only from the repo root with `.venv/bin/python` via heredoc, composing
these blocks with `pullback-finder`'s Blocks 1–8 and `screening-blocks`' A7. Never write a
scratch file into the repo — the sole permitted write is the final report.

**The law holds here too:** every value that *sizes or thresholds* the pattern is learned per
stock and disclosed — the window `m` (S4, by predictive validation), the match radius (S3),
the edge cutoff (S5, vs the stock's own base_rate), the completion trigger (reused
`learn_turn_trigger`). The only fixed values are the scaffolding the dip lens already
justifies: the **3% stop**, `H_base=15`, and pure statistical floors (min-sample ≈5, the
quantile `q`, the train fraction). A window length / neighbour count / match radius is **not**
grammar — it is learned.

## Block S1 — scale + time invariant shape fingerprint

```python
import numpy as np

def fingerprint(win):
    """win = [(bar_index:int, kind:'L'|'H', price:float), ...] ascending, canonical
    start='L'. Returns a 2m vector: prices min-maxed to [0,1] (kills price level) ++
    bar-indices min-maxed to [0,1] (spacing). Same shape at any scale/offset -> same fp."""
    pr = np.array([p for _, _, p in win], float)
    ix = np.array([float(i) for i, _, _ in win], float)
    def nm(a):
        rng = a.max() - a.min()
        return (a - a.min()) / rng if rng > 0 else np.zeros_like(a)
    return np.concatenate([nm(pr), nm(ix)])
```

## Block S2 — per-stock shape library + base rate (no look-ahead)

```python
def _bar_index(df):
    return {t: i for i, t in enumerate(df["trade_timestamp"].to_list())}

def _windows(piv, m):
    """All m-pivot windows that start on a Low (canonical parity)."""
    return [piv[s:s + m] for s in range(len(piv) - m + 1) if piv[s][1] == "L"]

def _label_window(df, win, H_base, H_stock, stop_pct, n):
    """Forward outcome from the window's LAST pivot (entry=last pivot price): a new high
    above the window's max within H_base before the 3% stop (Block 6). None = unresolved
    or insufficient forward bars (no look-ahead)."""
    last_i = win[-1][0]
    if last_i + H_stock >= n:
        return None
    ev = {"low_ts": df["trade_timestamp"][last_i], "low": win[-1][2],
          "high": max(p for _, _, p in win)}
    sb = outcome(df, ev, stop_pct, H_base)
    return bool(sb["success"]) if sb.get("resolved") else None

def build_library(df, piv, m, H_base, H_stock, lo=0, hi=None, stop_pct=0.03):
    """Library of (fingerprint -> success@base) over windows whose last pivot index is in
    [lo, hi). base_rate = unconditional success@base — the benchmark a structure must beat."""
    n = df.height
    hi = n if hi is None else hi
    lib, base = [], []
    for win in _windows(piv, m):
        if not (lo <= win[-1][0] < hi):
            continue
        y = _label_window(df, win, H_base, H_stock, stop_pct, n)
        if y is None:
            continue
        lib.append({"fp": fingerprint(win), "success_base": y, "last_i": win[-1][0]})
        base.append(y)
    return {"lib": lib, "n": len(lib),
            "base_rate": (sum(base) / len(base)) if base else None}
```

## Block S3 — learned match radius + live shape match

```python
def learn_radius(lib, q=0.25, cap=200):
    """Match radius = q-quantile of the stock's OWN pairwise fingerprint distances over a
    capped sample. 'Same shape' is defined by the stock's distribution, not a fixed eps."""
    F = np.array([e["fp"] for e in lib["lib"]])
    if len(F) < 2:
        raise ValueError("library too small to learn a radius")
    idx = np.random.default_rng(0).choice(len(F), size=min(cap, len(F)), replace=False)
    S = F[idx]
    D = np.linalg.norm(S[:, None, :] - S[None, :, :], axis=2)
    iu = np.triu_indices(len(S), k=1)
    return float(np.quantile(D[iu], q))

def live_window(df, zz, m):
    """Last m-1 confirmed pivots + the live forming extreme since the last confirmed pivot,
    canonical start on 'L'. None if no forming bar or parity cannot be satisfied."""
    bi = _bar_index(df)
    piv = [(bi[t], k, p) for (t, k, p) in zz if t in bi]
    if len(piv) < m:
        return None
    last = piv[-1]
    since = df.filter(pl.col("trade_timestamp") > df["trade_timestamp"][last[0]])
    if since.height == 0:
        return None
    if last[1] == "H":
        i = since["low"].arg_min(); forming = (last[0] + 1 + i, "L", since["low"][i])
    else:
        i = since["high"].arg_max(); forming = (last[0] + 1 + i, "H", since["high"][i])
    win = piv[-(m - 1):] + [forming]
    if win[0][1] != "L":                       # fix parity by shifting one pivot older
        win = piv[-m:-1] + [forming]
    return win if len(win) == m and win[0][1] == "L" else None

def match_live(df, zz, lib, m, radius, min_sample=5):
    """All library windows within `radius` of the live fingerprint -> score vs base_rate."""
    lw = live_window(df, zz, m)
    if lw is None:
        return {"applicable": False, "why": "no forming window"}
    lf = fingerprint(lw)
    F = np.array([e["fp"] for e in lib["lib"]])
    sel = [lib["lib"][i] for i in np.where(np.linalg.norm(F - lf, axis=1) <= radius)[0]]
    if len(sel) < min_sample:
        return {"applicable": True, "low_conf": True, "analogs": len(sel),
                "score": None, "base_rate": lib["base_rate"], "live_win": lw}
    sb = [e["success_base"] for e in sel]
    return {"applicable": True, "low_conf": False, "analogs": len(sel),
            "score": float(np.mean(sb)), "dispersion": float(np.std(sb)),
            "base_rate": lib["base_rate"], "edge": float(np.mean(sb)) - lib["base_rate"],
            "live_win": lw}
```

## Block S4 — learned shape-window m by predictive validation (never a fixed window)

```python
def learn_m_predictive(df, zz, H_base, H_stock, min_sample=5, train_frac=0.6, stop_pct=0.03):
    """Pick m whose shape-analogs best SEPARATE forward outcomes out-of-sample on THIS stock:
    build the library on a train split, match the validation split, and score
    separation = success(above-median match score) - success(below-median). m is chosen
    BECAUSE it predicts. low_edge=True if no m separates (>0) -> low-confidence, never forced."""
    bi = _bar_index(df)
    piv = [(bi[t], k, p) for (t, k, p) in zz if t in bi]
    n = df.height
    Tbar = int(n * train_frac)
    cands = []
    for m in range(3, 16):
        cnt = sum(1 for w in _windows(piv, m) if w[-1][0] < Tbar and w[-1][0] + H_stock < n)
        if cnt >= 3 * min_sample:
            cands.append(m)
        elif cands:
            break
    if not cands:
        cands = [3]
    results = {}
    for m in cands:
        train = build_library(df, piv, m, H_base, H_stock, lo=0, hi=Tbar, stop_pct=stop_pct)
        if train["n"] < min_sample:
            continue
        rad = learn_radius(train)
        F = np.array([e["fp"] for e in train["lib"]])
        preds, ys = [], []
        for w in _windows(piv, m):
            li = w[-1][0]
            if li < Tbar or li + H_stock >= n:
                continue
            y = _label_window(df, w, H_base, H_stock, stop_pct, n)
            if y is None:
                continue
            sel = np.where(np.linalg.norm(F - fingerprint(w), axis=1) <= rad)[0]
            if len(sel) < min_sample:
                continue
            preds.append(float(np.mean([train["lib"][i]["success_base"] for i in sel])))
            ys.append(y)
        if len(preds) < 2 * min_sample:
            continue
        preds, ys = np.array(preds), np.array(ys)
        hi_mask = preds >= np.median(preds)
        if hi_mask.sum() == 0 or (~hi_mask).sum() == 0:
            continue
        results[m] = float(ys[hi_mask].mean() - ys[~hi_mask].mean())
    if not results:
        return {"m": min(cands), "separation": None, "low_edge": True, "tried": {}}
    best = max(results, key=results.get)
    return {"m": best, "separation": results[best], "low_edge": results[best] <= 0,
            "tried": results}
```

## Block S5 — structural stop + tier (edge significance is statistical, never a fixed 0.5)

```python
def structural_stop(df, live_win, stop_pct=0.03):
    """Anchor = the structure base (lowest pivot in the live window) = structural
    invalidation. anchor_exists iff that base sits within the 3% hard-stop band.
    (A learned sub-base buffer is deferred to v2 to avoid a hardcoded multiple.)"""
    close = df["close"][-1]
    base = min(p for _, _, p in live_win)
    dist = (close - base) / close
    return {"anchor": base, "dist_pct": dist * 100.0, "anchor_exists": dist <= stop_pct}

def tier_struct(match, stop, uptrend, turn_confirmed, sel):
    """STRUCTURE-BUY needs: a validated-edge m, enough analogs, edge beyond one standard
    error of the analog success estimate, a 3%-placeable stop, an uptrend, AND a confirmed
    completion turn. Otherwise WATCH/SPEC/AVOID. No hardcoded score cutoff."""
    if not match.get("applicable"):
        return "STRUCTURE-NA"
    if sel.get("low_edge") or match.get("low_conf"):
        return "STRUCTURE-SPEC"
    se = match["dispersion"] / math.sqrt(match["analogs"]) if match["analogs"] else 1.0
    if match["edge"] < -se:
        return "STRUCTURE-AVOID"
    if match["edge"] <= se:                          # edge within noise of base_rate
        return "STRUCTURE-SPEC"
    if not stop["anchor_exists"] or not uptrend:
        return "STRUCTURE-WATCH"
    return "STRUCTURE-BUY" if turn_confirmed is True else "STRUCTURE-WATCH"
```

## Block S6 — Stage-S driver (per stock) + report section

```python
def analyze_struct(sym, interval, H_base=15):
    """Full per-stock structural pass. Returns a row dict or {"_skip": reason}."""
    df = add_indicators(load(sym, interval))
    zz = zigzag(fractal_flags(df, 6))                # k reused from the dip lens convention
    if len([p for p in zz if p[1] == "L"]) < 5:
        return {"_skip": "too few pivots"}
    evs = pullback_events(zz)
    if len(evs) < 5:
        return {"_skip": "too few pullback events"}
    Hh = learn_horizon(df, evs); H_stock = Hh.get("H_stock") or H_base
    sel = learn_m_predictive(df, zz, H_base, H_stock); m = sel["m"]
    bi = _bar_index(df); piv = [(bi[t], k, p) for (t, k, p) in zz if t in bi]
    lib = build_library(df, piv, m, H_base, H_stock)
    if lib["n"] < 5 or lib["base_rate"] is None:
        return {"_skip": "library too thin"}
    match = match_live(df, zz, lib, m, learn_radius(lib))
    if not match.get("applicable"):
        return {"_skip": match.get("why", "no live structure")}
    stop = structural_stop(df, match["live_win"])
    last = df.row(df.height - 1, named=True)
    uptrend = last["close"] > last["ema_50"] and last["ema_50"] > df["ema_50"][-20]
    for e in evs:
        ob = outcome(df, e, 0.03, H_base); e["success_base"] = bool(ob["success"]) if ob.get("resolved") else False
    trig = learn_turn_trigger(df, evs, success_key="success_base")
    turn = live_turn(df, zz, trig) if trig.get("turn_learnable") else {"confirmed": None}
    tier = tier_struct(match, stop, uptrend, turn.get("confirmed"), sel)
    return {"symbol": sym, "tier": tier, "m": m, "m_sep": sel.get("separation"),
            "analogs": match.get("analogs"), "score": match.get("score"),
            "base_rate": round(lib["base_rate"], 3), "edge": match.get("edge"),
            "H_stock": H_stock, "trading_days": Hh.get("trading_days"),
            "stop": round(stop["anchor"], 2), "stop_pct": round(-stop["dist_pct"], 1),
            "turn": turn.get("confirmed"), "latest": last["trade_timestamp"]}

def render_struct_section(rows, summary):
    """Markdown '## Structural lens' section: table + disclosures. Rows already rounded."""
    cols = ["Symbol", "tier", "m (sep)", "analogs", "score/base (edge)", "H≈days",
            "turn", "stop ₹ (−%)", "latest candle"]
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    body = []
    for r in rows:
        sc = "low-conf" if r["score"] is None else f"{round(r['score'],3)}/{r['base_rate']} ({r['edge']:+.3f})"
        ms = f"{r['m']}" + (f" ({r['m_sep']:+.2f})" if r.get("m_sep") is not None else "")
        td = f"{r['H_stock']}≈{r['trading_days']}d" if r.get("trading_days") else f"{r['H_stock']}"
        tn = {True: "✓", False: "—", None: "n/a"}[r["turn"]]
        body.append("| " + " | ".join([r["symbol"], r["tier"], ms, str(r["analogs"]),
                     sc, td, tn, f"{r['stop']} ({r['stop_pct']}%)", str(r["latest"])[:16]]) + " |")
    disc = ("_Structural disclosures: m chosen per stock by out-of-sample separation (sep shown); "
            "match radius = q25 of own pairwise fp-distance; edge = score − base_rate, "
            "significant beyond 1 SE; 3% stop · H_base=15 · min-sample 5 · train-frac 0.6 fixed; "
            "per-stock analogs only._")
    return "\n".join([f"## Structural lens — {summary}", head, sep] + body + ["", disc])
```
