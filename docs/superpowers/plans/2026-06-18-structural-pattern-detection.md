# Structural Pattern Detection Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to carry out this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pattern-agnostic **structural lens** to the `stock-screening` skill that detects a forming structure via per-stock pivot-shape analogs and emits a STRUCTURE-BUY/WATCH/SPEC/AVOID tier with a learned stop, in a separate report section.

**Approach:** Author new blocks **S0–S5 + a renderer** as Python-in-markdown in `references/structural-blocks.md` (the skill composes them in a heredoc at run time, exactly like `screening-blocks.md`). Reuse `pullback-finder` blocks 1–3, 6, 7b, 8c and `screening-blocks` A7. Every sizing/threshold is **learned per stock** (only the 3% stop, `H_base=15`, and stat floors are fixed). Validate the edge **out-of-sample vs each stock's base_rate** before shipping the BUY tier.

**Tools / Inputs:** `.venv/bin/python`, `polars`, `numpy`; `market-data/prices/{1h,1d}/*.parquet`; spec `docs/superpowers/specs/2026-06-18-structural-pattern-detection-design.md`; existing blocks in `.claude/skills/pullback-finder/references/building-blocks.md` and `.claude/skills/stock-screening/references/screening-blocks.md`.

---

## Structure / Decomposition

| File | Responsibility |
|---|---|
| **Create** `.claude/skills/stock-screening/references/structural-blocks.md` | Blocks S0 (`learn_m`), S1 (`fingerprint`), S2 (`build_library`), S3 (`learn_radius`/`live_window`/`match_live`), S4 (`structural_stop`), S5 (`tier_struct`) + Stage-S driver recipe + `render_struct_section`. Mirror of `screening-blocks.md` style. Keep < 800 lines; if exceeded, split the renderer into `structural-report.md`. |
| **Modify** `.claude/skills/stock-screening/SKILL.md` | Add Stage S to the workflow, the structural output style, extend "The law", add failure rows. |
| **Create** `docs/superpowers/validation/2026-06-18-structural-lens-validation.md` | Recorded results of the OOS-separation gate, CEMPRO sanity, law audit. |
| **Test-only** `/tmp/sblocks.py` | Accumulates the blocks as written, imported by each done-check heredoc. Never committed. |

**Reused, never modified:** `load`, `add_indicators`, `fractal_flags`, `zigzag`, `outcome`, `learn_turn_trigger`, `live_turn` (building-blocks.md); `learn_horizon`, `bars_per_day` (screening-blocks.md).

**Deviation from spec (conscious, flagged):** spec §7 S4 says "structure base **minus a learned buffer**." v1 uses the **base itself** as the anchor (no buffer) — adding an ATR buffer needs a learned multiple, which is deferred to v2 to avoid a hardcoded constant. Recorded in the validation note.

**Test scaffold convention:** after writing a block into `structural-blocks.md`, append the same code to `/tmp/sblocks.py` so done-checks can `from sblocks import *`. Bootstrap `/tmp/sblocks.py` in Task 1 with the reused blocks pasted from the two existing reference files.

---

### Task 1: Scaffold + Block S0 `learn_m`

**Inputs/Outputs:**
- Create: `.claude/skills/stock-screening/references/structural-blocks.md`
- Create (test-only): `/tmp/sblocks.py`
- Done-check: `learn_m` returns an int ≥ 3 for CEMPRO.NS 1h.

- [ ] **Step 1: Bootstrap the test module.** Create `/tmp/sblocks.py` and paste into it, verbatim, these functions from the existing reference files: `load`, `add_indicators`, `fractal_flags`, `zigzag`, `outcome`, `learn_turn_trigger`, `live_turn`, `live_pullback_low` (from `pullback-finder/references/building-blocks.md`) and `bars_per_day`, `learn_horizon`, `recovery_class` (from `stock-screening/references/screening-blocks.md`). Add `import polars as pl`, `import numpy as np`, `import math` at the top.

- [ ] **Step 2: Write `structural-blocks.md` intro + Block S0.** Create the file with a heading paragraph (mirror `screening-blocks.md`'s intro: read-only, compose in a heredoc, the only repo write is the report) and this block:

```python
## Block S0 — learned shape-window m (never a fixed window)

def learn_m(df, zz, H_stock, min_pivots=3):
    """m = the stock's pivot density (pivots/bar) x its own H_stock, floored at the
    definitional minimum (a structure needs >=3 pivots). Learned from THIS stock's
    cadence + clock; disclosed. min_pivots is a definitional floor, not a tuned value."""
    if df.height == 0 or len(zz) < min_pivots:
        raise ValueError("insufficient pivots to learn m")
    density = len(zz) / df.height            # pivots per bar, this stock
    return max(min_pivots, round(density * H_stock))
```

- [ ] **Step 3: Mirror to test module + done-check.** Append S0 to `/tmp/sblocks.py`, then run:

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import sys; sys.path.insert(0,"/tmp"); from sblocks import *
df=add_indicators(load("CEMPRO.NS","1h")); zz=zigzag(fractal_flags(df,6))
evs=[]  # learn_horizon needs events; use a coarse pullback proxy for H_stock
from sblocks import learn_horizon
# minimal events: consecutive (H,L) lows for horizon learning
H=learn_horizon(df, [{'low_ts':t,'high':p} for (t,k,p) in zz if k=='L'][:50]) if zz else {}
Hs=H.get('H_stock') or 15
print("m =", learn_m(df, zz, Hs), "| H_stock =", Hs, "| pivots =", len(zz), "| bars =", df.height)
PY
```
Expected: `m = <int >=3>`, H_stock printed, pivots/bars printed. (If `learn_horizon` errors on the proxy events, that is fine — fall back `Hs=15` is already wired.)

- [ ] **Step 4: Commit.**

```bash
git add .claude/skills/stock-screening/references/structural-blocks.md
git commit -m "feat(structural-lens): Block S0 learned shape-window m"
```

---

### Task 2: Block S1 `fingerprint` + scale-invariance unit

**Inputs/Outputs:**
- Modify: `.claude/skills/stock-screening/references/structural-blocks.md` (append S1)
- Done-check: identical fingerprint for the same shape scaled x10 and shifted +1000.

- [ ] **Step 1: Write Block S1.** Append:

```python
## Block S1 — scale + time invariant shape fingerprint

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

- [ ] **Step 2: Mirror + done-check.** Append S1 to `/tmp/sblocks.py`, then run:

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import sys; sys.path.insert(0,"/tmp"); from sblocks import *
w=[(0,'L',100.0),(3,'H',120.0),(7,'L',110.0),(10,'H',140.0),(15,'L',125.0)]
w2=[(0,'L',100.0*10+1000),(3,'H',120.0*10+1000),(7,'L',110.0*10+1000),(10,'H',140.0*10+1000),(15,'L',125.0*10+1000)]
import numpy as np
print("len =", len(fingerprint(w)), "(expect 10)")
print("scale-invariant:", np.allclose(fingerprint(w), fingerprint(w2)))
PY
```
Expected: `len = 10 (expect 10)` and `scale-invariant: True`.

- [ ] **Step 3: Commit.**

```bash
git add .claude/skills/stock-screening/references/structural-blocks.md
git commit -m "feat(structural-lens): Block S1 scale+time invariant fingerprint"
```

---

### Task 3: Block S2 `build_library` + base_rate + no-look-ahead unit

**Inputs/Outputs:**
- Modify: `structural-blocks.md` (append S2)
- Done-check: CEMPRO library is non-empty, `base_rate` in [0,1], every labeled window has `last_i + H_stock < df.height`.

- [ ] **Step 1: Write Block S2.** Append:

```python
## Block S2 — per-stock shape library + base rate (no look-ahead)

def _bar_index(df):
    return {t: i for i, t in enumerate(df["trade_timestamp"].to_list())}

def build_library(df, zz, m, H_base, H_stock, stop_pct=0.03):
    """Library of (fingerprint -> dual-clock outcome) over the stock's OWN history.
    Outcome from each window's LAST pivot (entry=last pivot price): new high above the
    window's max within H, before the 3% stop (reuse Block 6 `outcome`). No look-ahead:
    skip windows lacking H_stock forward bars. base_rate = unconditional success@base."""
    bi = _bar_index(df); n = df.height
    piv = [(bi[t], k, p) for (t, k, p) in zz if t in bi]
    lib, base = [], []
    for s in range(len(piv) - m + 1):
        win = piv[s:s + m]
        if win[0][1] != "L":                       # canonical start on a Low
            continue
        last_i = win[-1][0]
        if last_i + H_stock >= n:                   # no look-ahead
            continue
        ev = {"low_ts": df["trade_timestamp"][last_i], "low": win[-1][2],
              "high": max(p for _, _, p in win)}
        sb = outcome(df, ev, stop_pct, H_base)
        if not sb.get("resolved"):
            continue
        sl = outcome(df, ev, stop_pct, H_stock)
        lib.append({"fp": fingerprint(win), "last_i": last_i,
                    "success_base": bool(sb["success"]),
                    "success_learned": bool(sl["success"]) if sl.get("resolved") else bool(sb["success"])})
        base.append(lib[-1]["success_base"])
    return {"lib": lib, "n": len(lib),
            "base_rate": (sum(base) / len(base)) if base else None}
```

- [ ] **Step 2: Mirror + done-check.** Append S2 to `/tmp/sblocks.py`, then run:

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import sys; sys.path.insert(0,"/tmp"); from sblocks import *
df=add_indicators(load("CEMPRO.NS","1h")); zz=zigzag(fractal_flags(df,6))
Hs=15; m=learn_m(df,zz,Hs)
L=build_library(df,zz,m,15,Hs)
print("m =",m,"| library n =",L["n"],"| base_rate =",L["base_rate"])
assert L["n"]>0, "empty library"
assert all(e["last_i"]+Hs < df.height for e in L["lib"]), "LOOK-AHEAD LEAK"
assert 0.0 <= L["base_rate"] <= 1.0
print("no-look-ahead OK")
PY
```
Expected: non-zero `library n`, `base_rate` printed in [0,1], `no-look-ahead OK`.

- [ ] **Step 3: Commit.**

```bash
git add .claude/skills/stock-screening/references/structural-blocks.md
git commit -m "feat(structural-lens): Block S2 per-stock library + base_rate (no look-ahead)"
```

---

### Task 4: Block S3 `learn_radius` / `live_window` / `match_live`

**Inputs/Outputs:**
- Modify: `structural-blocks.md` (append S3)
- Done-check: CEMPRO yields a radius > 0, an analog count, and a `score`/`edge` (or a `low_conf` flag).

- [ ] **Step 1: Write Block S3.** Append:

```python
## Block S3 — learned match radius + live shape match

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
        win = (piv[-m:-1] + [forming])
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
            "score_learned": float(np.mean([e["success_learned"] for e in sel])),
            "base_rate": lib["base_rate"], "edge": float(np.mean(sb)) - lib["base_rate"],
            "live_win": lw}
```

- [ ] **Step 2: Mirror + done-check.** Append S3 to `/tmp/sblocks.py`, then run:

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import sys; sys.path.insert(0,"/tmp"); from sblocks import *
df=add_indicators(load("CEMPRO.NS","1h")); zz=zigzag(fractal_flags(df,6))
Hs=15; m=learn_m(df,zz,Hs); L=build_library(df,zz,m,15,Hs)
r=learn_radius(L); M=match_live(df,zz,L,m,r)
print("m =",m,"| radius =",round(r,4),"| analogs =",M.get("analogs"),
      "| score =",M.get("score"),"| base =",round(L['base_rate'],3),"| edge =",M.get("edge"))
assert r>0 and M["applicable"]
print("S3 OK")
PY
```
Expected: `radius > 0`, an analog count, `score`/`edge` printed (or `low_conf` path), `S3 OK`.

- [ ] **Step 3: Commit.**

```bash
git add .claude/skills/stock-screening/references/structural-blocks.md
git commit -m "feat(structural-lens): Block S3 learned radius + live shape match"
```

---

### Task 5: Block S4 `structural_stop` + Block S5 `tier_struct`

**Inputs/Outputs:**
- Modify: `structural-blocks.md` (append S4, S5)
- Done-check: CEMPRO yields a stop anchor + `anchor_exists` bool and a tier token.

- [ ] **Step 1: Write Blocks S4 + S5.** Append:

```python
## Block S4 — structural stop (the structure's own floor; 3% is the only fixed knob)

def structural_stop(df, live_win, stop_pct=0.03):
    """Anchor = the structure base (lowest pivot in the live window) = structural
    invalidation. anchor_exists iff that base sits within the 3% hard-stop band.
    (A learned sub-base buffer is deferred to v2 to avoid a hardcoded multiple.)"""
    close = df["close"][-1]
    base = min(p for _, _, p in live_win)
    dist = (close - base) / close
    return {"anchor": base, "dist_pct": dist * 100.0, "anchor_exists": dist <= stop_pct}

## Block S5 — structural tier (edge significance is statistical, never a fixed 0.5)

def tier_struct(match, stop, uptrend, turn_confirmed):
    """STRUCTURE-BUY needs: enough analogs, edge beyond one standard error of the analog
    success estimate, a 3%-placeable stop, an uptrend, AND a confirmed completion turn
    (reuse live_turn). Otherwise WATCH/SPEC/AVOID. No hardcoded score cutoff."""
    if not match.get("applicable"):
        return "STRUCTURE-NA"
    if match.get("low_conf"):
        return "STRUCTURE-SPEC"
    se = match["dispersion"] / math.sqrt(match["analogs"]) if match["analogs"] else 1.0
    if match["edge"] < -se:
        return "STRUCTURE-AVOID"
    if match["edge"] <= se:                         # edge within noise of base_rate
        return "STRUCTURE-SPEC"
    if not stop["anchor_exists"] or not uptrend:
        return "STRUCTURE-WATCH"
    return "STRUCTURE-BUY" if turn_confirmed is True else "STRUCTURE-WATCH"
```

- [ ] **Step 2: Mirror + done-check.** Append S4+S5 to `/tmp/sblocks.py`, then run:

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import sys; sys.path.insert(0,"/tmp"); from sblocks import *
df=add_indicators(load("CEMPRO.NS","1h")); zz=zigzag(fractal_flags(df,6))
Hs=15; m=learn_m(df,zz,Hs); L=build_library(df,zz,m,15,Hs); r=learn_radius(L)
M=match_live(df,zz,L,m,r)
st=structural_stop(df, M["live_win"]); last=df.row(df.height-1,named=True)
up = last["close"]>last["ema_50"] and last["ema_50"]>df["ema_50"][-20]
t=tier_struct(M, st, up, None)
print("stop ₹",round(st["anchor"],2),"(",round(st["dist_pct"],1),"%) exists=",st["anchor_exists"],"| tier =",t)
assert t in {"STRUCTURE-BUY","STRUCTURE-WATCH","STRUCTURE-SPEC","STRUCTURE-AVOID","STRUCTURE-NA"}
print("S4+S5 OK")
PY
```
Expected: a stop ₹ + `anchor_exists` bool + a valid tier token, `S4+S5 OK`.

- [ ] **Step 3: Commit.**

```bash
git add .claude/skills/stock-screening/references/structural-blocks.md
git commit -m "feat(structural-lens): Block S4 structural stop + Block S5 tier"
```

---

### Task 6: Stage-S driver + `render_struct_section`

**Inputs/Outputs:**
- Modify: `structural-blocks.md` (append driver recipe + renderer). If the file would exceed 800 lines, move the renderer to a new `structural-report.md` and reference it.
- Done-check: Stage S over the 1h universe prints a markdown section containing a CEMPRO row.

- [ ] **Step 1: Write the Stage-S driver recipe + renderer.** Append:

```python
## Block S6 — Stage-S driver (per stock) + report section

def analyze_struct(sym, interval, H_base=15):
    """Full per-stock structural pass. Returns a row dict or {"_skip": reason}."""
    df = add_indicators(load(sym, interval))
    zz = zigzag(fractal_flags(df, 6))                # k reused from the dip lens convention
    if len([p for p in zz if p[1] == "L"]) < 3:
        return {"_skip": "too few pivots"}
    Hh = learn_horizon(df, [{"low_ts": t, "high": p} for (t, k, p) in zz if k == "L"])
    H_stock = Hh.get("H_stock") or H_base
    m = learn_m(df, zz, H_stock)
    lib = build_library(df, zz, m, H_base, H_stock)
    if lib["n"] < 5 or lib["base_rate"] is None:
        return {"_skip": "library too thin"}
    radius = learn_radius(lib)
    match = match_live(df, zz, lib, m, radius)
    if not match.get("applicable"):
        return {"_skip": match.get("why", "no live structure")}
    stop = structural_stop(df, match["live_win"])
    last = df.row(df.height - 1, named=True)
    uptrend = last["close"] > last["ema_50"] and last["ema_50"] > df["ema_50"][-20]
    trig = learn_turn_trigger(df, [{"low_ts": t, "low": p, "high": p, "success_base": True}
                                   for (t, k, p) in zz if k == "L"], success_key="success_base")
    turn = live_turn(df, zz, trig) if trig.get("turn_learnable") else {"confirmed": None}
    tier = tier_struct(match, stop, uptrend, turn.get("confirmed"))
    close = last["close"]
    return {"symbol": sym, "tier": tier, "m": m, "analogs": match["analogs"],
            "score": match.get("score"), "base_rate": round(lib["base_rate"], 3),
            "edge": match.get("edge"), "H_stock": H_stock,
            "trading_days": Hh.get("trading_days"),
            "stop": round(stop["anchor"], 2), "stop_pct": round(-stop["dist_pct"], 1),
            "turn": turn.get("confirmed"), "latest": last["trade_timestamp"]}

def render_struct_section(rows, disclosures):
    """Markdown '## Structural lens' section: table + disclosures. Rows already rounded."""
    cols = ["Symbol", "tier", "m", "analogs", "score/base (edge)", "H≈days",
            "turn", "stop ₹ (−%)", "latest candle"]
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    body = []
    for r in rows:
        sc = "low-conf" if r["score"] is None else f"{r['score']}/{r['base_rate']} ({r['edge']:+.3f})"
        td = f"{r['H_stock']}≈{r['trading_days']}d" if r.get("trading_days") else f"{r['H_stock']}"
        tn = {True: "✓", False: "—", None: "n/a"}[r["turn"]]
        body.append("| " + " | ".join([r["symbol"], r["tier"], str(r["m"]), str(r["analogs"]),
                     sc, td, tn, f"{r['stop']} ({r['stop_pct']}%)", str(r["latest"])[:16]]) + " |")
    disc = ("_Structural disclosures: m learned per stock (pivots/bar × H_stock); match radius "
            "= q25 of own pairwise fp-distance; edge = score − base_rate, significant beyond 1 SE; "
            "3% stop · H_base=15 · min-sample 5 fixed; per-stock analogs only._")
    return "\n".join(["## Structural lens", disclosures, head, sep] + body + ["", disc])
```

- [ ] **Step 2: Mirror + done-check.** Append Block S6 to `/tmp/sblocks.py`, then run:

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'
import sys, glob, os; sys.path.insert(0,"/tmp"); from sblocks import *
syms=[os.path.basename(p)[:-8] for p in glob.glob("market-data/prices/1h/*.parquet")]
rows=[]
for s in syms:
    try:
        r=analyze_struct(s,"1h")
    except Exception as e:
        continue
    if "_skip" not in r: rows.append(r)
order={"STRUCTURE-BUY":0,"STRUCTURE-WATCH":1,"STRUCTURE-SPEC":2,"STRUCTURE-AVOID":3,"STRUCTURE-NA":4}
rows.sort(key=lambda r:(order.get(r["tier"],9), -(r["edge"] or -9)))
md=render_struct_section(rows, f"{len(rows)} analyzed")
print(md[:1500])
assert any(r["symbol"]=="CEMPRO.NS" for r in rows), "CEMPRO not surfaced by structural lens"
print("\nCEMPRO surfaced:", [ (r["tier"],r["edge"]) for r in rows if r["symbol"]=="CEMPRO.NS"])
PY
```
Expected: a `## Structural lens` table prints; assertion passes (CEMPRO present with a tier).

- [ ] **Step 3: Commit.**

```bash
git add .claude/skills/stock-screening/references/structural-blocks.md
git commit -m "feat(structural-lens): Stage-S driver + report section renderer"
```

---

### Task 7: Wire `SKILL.md`

**Inputs/Outputs:**
- Modify: `.claude/skills/stock-screening/SKILL.md`
- Done-check: grep confirms the new Stage S, tier tokens, and reference file are wired and internally consistent.

- [ ] **Step 1: Add Stage S to the workflow.** In the "Workflow — the two-stage funnel" area, add a parallel paragraph after Stage C:

> **Stage S — structural lens (parallel).** Independently of the dip funnel, run the
> pattern-agnostic structural pass (`references/structural-blocks.md`, Blocks S0–S6) over the
> same universe: per stock, learn `m` (S0), build the own-shape library + base_rate (S2),
> learn the match radius (S3), match the live forming shape, score it vs the stock's
> base_rate, and tier it (S5) with a learned structural stop (S4). Emit a **separate
> `## Structural lens` report section** (S6). The structural tiers NEVER cross-rank with the
> dip tiers — they are two lenses in one report.

- [ ] **Step 2: Add the structural output style.** After the dip "Output style" section, add a "Structural lens output" subsection documenting the table columns from `render_struct_section` (`Symbol | tier | m | analogs | score/base (edge) | H≈days | turn | stop ₹ (−%) | latest candle`) and the four tier meanings: STRUCTURE-BUY (forming shape whose analogs beat the stock's base rate beyond noise, stop placeable, turn confirmed), STRUCTURE-WATCH (edge present, trigger not fired or stop > 3%), STRUCTURE-SPEC (<5 analogs or edge within noise), STRUCTURE-AVOID (analogs underperformed base rate — shape preceded drops).

- [ ] **Step 3: Extend "The law".** Append one sentence to the law block:

> The structural lens follows the same law: `m`, the match radius, the edge cutoff (vs the
> stock's base_rate, significant beyond one standard error), and the completion trigger are
> all learned per stock and disclosed; only the 3% stop, `H_base=15`, and the min-sample
> floor are fixed.

- [ ] **Step 4: Add failure rows.** Append to the "Failure handling" table:

```markdown
| Too few pivots / thin library (struct) | Skip the structural row; disclose count. |
| < 5 shape analogs in radius (struct) | STRUCTURE-SPEC (low-confidence); never invent. |
| No live forming structure (at new high) (struct) | Not applicable; skip + disclose. |
| Structural stop > 3% band | STRUCTURE-WATCH (stop-survival), never BUY. |
```

- [ ] **Step 5: Done-check.** Run:

```bash
cd /workspaces/stock-database && grep -c "Stage S\|Structural lens\|STRUCTURE-BUY\|structural-blocks.md" .claude/skills/stock-screening/SKILL.md
```
Expected: a count ≥ 4 (all anchors present).

- [ ] **Step 6: Commit.**

```bash
git add .claude/skills/stock-screening/SKILL.md
git commit -m "feat(structural-lens): wire Stage S into stock-screening SKILL.md"
```

---

### Task 8: Validation gate — OOS separation, CEMPRO sanity, law audit

**Inputs/Outputs:**
- Create: `docs/superpowers/validation/2026-06-18-structural-lens-validation.md`
- Done-check: validation note records the OOS matched-score vs base_rate result and a ship/no-ship decision for the BUY tier.

- [ ] **Step 1: Run the out-of-sample separation backtest.** Run (records to a temp file you will summarize):

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY' | tee /tmp/struct_oos.txt
import sys, glob, os, numpy as np; sys.path.insert(0,"/tmp"); from sblocks import *
def split_eval(sym, frac=0.7, H_base=15):
    df=add_indicators(load(sym,"1h")); zz=zigzag(fractal_flags(df,6))
    if len(zz)<10: return []
    T=int(df.height*frac)
    dtr=df.slice(0,T)
    zz_tr=[(t,k,p) for (t,k,p) in zz if t<=df["trade_timestamp"][T-1]]
    if len([p for p in zz_tr if p[1]=='L'])<5: return []
    Hh=learn_horizon(dtr,[{"low_ts":t,"high":p} for (t,k,p) in zz_tr if k=='L']); Hs=Hh.get("H_stock") or H_base
    m=learn_m(dtr,zz_tr,Hs); lib=build_library(dtr,zz_tr,m,H_base,Hs)
    if lib["n"]<5 or lib["base_rate"] is None: return []
    r=learn_radius(lib); bi={t:i for i,t in enumerate(df["trade_timestamp"].to_list())}
    piv=[(bi[t],k,p) for (t,k,p) in zz if t in bi]
    out=[]
    for s in range(len(piv)-m+1):
        win=piv[s:s+m]
        if win[0][1]!='L' or win[-1][0]<T or win[-1][0]+Hs>=df.height: continue
        fp=fingerprint(win); F=np.array([e["fp"] for e in lib["lib"]])
        sel=[lib["lib"][i] for i in np.where(np.linalg.norm(F-fp,axis=1)<=r)[0]]
        if len(sel)<5: continue
        pred=np.mean([e["success_base"] for e in sel])
        ev={"low_ts":df["trade_timestamp"][win[-1][0]],"low":win[-1][2],"high":max(p for _,_,p in win)}
        oc=outcome(df,ev,0.03,H_base)
        if oc.get("resolved"): out.append((pred-lib["base_rate"], bool(oc["success"]), lib["base_rate"]))
    return out
rows=[]
for p in glob.glob("market-data/prices/1h/*.parquet"):
    try: rows+=split_eval(os.path.basename(p)[:-8])
    except Exception: pass
import numpy as np
edges=np.array([e for e,_,_ in rows]); succ=np.array([s for _,s,_ in rows]); base=np.array([b for _,_,b in rows])
print("OOS matched windows:", len(rows))
if len(rows):
    hi = edges>0
    print("base_rate (pooled):", round(base.mean(),3))
    print("realized success | positive-edge matches:", round(succ[hi].mean(),3), "n=",int(hi.sum()))
    print("realized success | negative-edge matches:", round(succ[~hi].mean(),3), "n=",int((~hi).sum()))
    print("SEPARATION (pos-edge minus base):", round(succ[hi].mean()-base.mean(),3))
PY
```
Expected: prints pooled base_rate and realized success for positive-edge vs negative-edge OOS matches.

- [ ] **Step 2: Run CEMPRO sanity + law audit.** Run:

```bash
cd /workspaces/stock-database && .venv/bin/python - <<'PY'; sys=__import__("sys"); 
import sys; sys.path.insert(0,"/tmp"); from sblocks import *
r=analyze_struct("CEMPRO.NS","1h"); print("CEMPRO:", r.get("tier"), "edge", r.get("edge"), r.get("_skip",""))
PY
echo "--- law audit: stray numeric literals in structural blocks (allowed: 3/0.03 stop, 15 H_base, 5 floor, 0.25 q, 6 k, 50/20 reused EMA windows) ---"
grep -nE '[^a-zA-Z_][0-9]+\.?[0-9]*' .claude/skills/stock-screening/references/structural-blocks.md | grep -vE '#|H_base|stop_pct|min_pivots|min_sample|0\.25|q=|span|ema_50|, 6\)|0\.03|, 15|, 3\)|, 5|2 \* |, 20' | head -30
```
Expected: CEMPRO prints a tier; the audit lists only justified scaffolding constants (no stray tuned literals). Investigate anything unexpected.

- [ ] **Step 3: Write the validation note.** Create `docs/superpowers/validation/2026-06-18-structural-lens-validation.md` with: the OOS numbers from Step 1, the CEMPRO tier from Step 2, the law-audit result, and an explicit **decision**:
  - If positive-edge OOS success clearly exceeds base_rate → **ship STRUCTURE-BUY**.
  - If no separation → **demote: keep STRUCTURE-WATCH/SPEC/AVOID only, disable BUY**, and record why. (Honest no-edge outcome is a valid result, per spec §10.3.)

- [ ] **Step 4: Commit.**

```bash
git add docs/superpowers/validation/2026-06-18-structural-lens-validation.md
git commit -m "test(structural-lens): OOS separation gate + CEMPRO sanity + law audit"
```

---

## Self-Review

**Spec coverage:** §5 architecture → Tasks 1–7; §6 engine (S1–S3, learned m) → Tasks 1–4; §7 stop+tiers → Task 5; §8 report → Task 6; §9 failures → Task 7 step 4; §10 verification → Task 8 (no-look-ahead unit T3, scale-invariance unit T2, OOS separation T8, CEMPRO sanity T8, law audit T8); §4 law → enforced per block + audited T8. **Flagged deviation:** §7 "learned buffer" trimmed to base-only anchor in v1 (recorded in plan structure note + validation).

**Placeholder scan:** no TBD/TODO; every block ships full code; every done-check is a concrete runnable command with an expected signal.

**Naming/output consistency:** `learn_m`, `fingerprint`, `build_library`, `learn_radius`, `live_window`, `match_live`, `structural_stop`, `tier_struct`, `analyze_struct`, `render_struct_section` used consistently across tasks; tier tokens `STRUCTURE-BUY/WATCH/SPEC/AVOID/NA` consistent across code, renderer, SKILL.md, and spec. `/tmp/sblocks.py` accumulation convention applied uniformly.
