# stock-screening Skill Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to carry out this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `stock-screening` Claude Code skill — a pullback-only universe
screener that judges each stock against its OWN dip behavior, fast, with every pattern
parameter derived/validated against current data at run time.

**Approach:** Two-stage funnel. Stage A is a cheap vectorized "proxy net" over the whole
Parquet universe (one streaming Polars pass) with a self-calibrating window W; it picks
WHO to deep-analyze. Stage B runs `pullback-finder`'s exact per-stock blocks (composed,
not copied) only on the shortlist, with per-stock computed `k`, a confirmed up-leg, and a
volume-fade annotation. Stage C tiers and reports, honestly empty when nothing qualifies.

**Tools / Inputs:** Polars 1.41.2 via `.venv/bin/python` (heredoc, read-only);
`market-data/prices/<interval>/*.parquet`; companion skill
`.claude/skills/pullback-finder/references/building-blocks.md`; approved spec
`docs/superpowers/specs/2026-06-13-stock-screening-pullback-design.md`.

---

## Structure / Decomposition

Two deliverable files under `.claude/skills/stock-screening/`:

- **`SKILL.md`** — the workflow doc: required input, the two-stage funnel overview,
  output style + report format, the no-frozen-constants law, hard rules, failure
  handling. Consumes the grammar in `references/screening-blocks.md`.
- **`references/screening-blocks.md`** — the screening-specific Polars grammar:
  Stage-A proxy net, W self-calibration, choppiness→k, volume-fade, confirmed-up-leg
  guard, and the Stage-B composition recipe that calls `pullback-finder`'s blocks.

`pullback-finder` is **not modified**. Validation runs read-only via heredoc — no scratch
files in the repo; the only files authored are the two skill files above.

Constraints (global): each file ≤ 800 lines, each function ≤ 80 lines, fail-fast with
clear exceptions (no silent fallbacks). The 3% stop / 15-bar horizon are the trader's
fixed risk model; everything else (W, k, noise, bands) is derived per run.

All validation done-checks below were dry-run on the live 1h universe (172 symbols) while
writing this plan, so the expected outputs are real, not hypothetical.

---

### Task 1: Scaffold skill + SKILL.md frontmatter and skeleton

**Inputs/Outputs:**
- Create: `.claude/skills/stock-screening/SKILL.md`
- Create: `.claude/skills/stock-screening/references/` (directory)
- Done-check: `ls .claude/skills/stock-screening/SKILL.md` resolves; frontmatter has the
  three required keys.

- [ ] **Step 1: Create SKILL.md with frontmatter + section skeleton**

Write `.claude/skills/stock-screening/SKILL.md` starting with this frontmatter and the
section headers (bodies filled in Task 7):

```markdown
---
name: stock-screening
description: Screen the whole Parquet stock universe for buy-on-pullback candidates, judging each stock against its OWN historical dip behavior. Two-stage funnel — a fast vectorized own-band proxy net, then bespoke per-stock confirmation via the pullback-finder grammar. Use when the user asks to screen/scan the universe for pullback buys. Requires a user-supplied timeframe. Companion to pullback-finder.
---

# Stock Screening — Pullback Universe Screener

## Required input
## Workflow — the two-stage funnel
## Stage A — proxy net (see references/screening-blocks.md)
## Stage B — bespoke confirm (composes pullback-finder)
## Stage C — tier + report
## The law — no frozen pattern constants
## Output style
## Hard rules
## Failure handling
```

- [ ] **Step 2: Verify it's done**

Run: `ls .claude/skills/stock-screening/SKILL.md && head -5 .claude/skills/stock-screening/SKILL.md`
Expected: path prints; first lines show `---` then `name: stock-screening`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/stock-screening/SKILL.md
git commit -m "feat(stock-screening): scaffold skill + frontmatter"
```

---

### Task 2: Stage-A proxy net block

**Inputs/Outputs:**
- Create: `.claude/skills/stock-screening/references/screening-blocks.md`
- Done-check: heredoc running the block on 1h returns a non-empty shortlist and the
  known BUY names (OLAELEC at W=60; CARTRADE/SHILPAMED/MRPL/SIGMAADV at W≤120) appear.

- [ ] **Step 1: Write the proxy-net block into screening-blocks.md**

Start the file with a header and Block A1. This is the validated definition: band from
TROUGH drawdowns (≈ per-event depth, not per-bar), today = deepest dip in the last `R`
bars (catches a dip that already bounced), inclusion-biased filter.

````markdown
# Screening Blocks — the Stage-A grammar (companion to pullback-finder)

Stage A is a cheap, fully vectorized net over the WHOLE universe in one streaming pass.
It picks WHO to deep-analyze; Stage B (pullback-finder blocks) decides the verdict. So
Stage A is deliberately inclusion-biased — a borderline keep is fine (Stage B culls it),
a wrong drop is not (Stage B never sees it).

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
````

- [ ] **Step 2: Verify it's done**

Run:
```bash
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "/tmp")
# paste Block A1 here or import via the doc; quick inline check:
import polars as pl
exec(open("/dev/stdin").read()) if False else None
PY
```
Simpler concrete done-check — copy Block A1 into a heredoc and run:
```bash
.venv/bin/python - <<'PY'
# <paste proxy_net from Block A1>
for W in (60,120,240):
    s = proxy_net("1h", W)
    names = set(s["symbol"].to_list())
    print(W, len(names), "OLAELEC", "OLAELEC.NS" in names)
PY
```
Expected (matches validated dry-run): `W=60 → 44, OLAELEC True`; `W=120 → 37, OLAELEC False`;
`W=240 → 28, OLAELEC False`. Shortlists non-empty; OLAELEC present at W=60.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/stock-screening/references/screening-blocks.md
git commit -m "feat(stock-screening): Stage-A proxy net block (validated)"
```

---

### Task 3: W self-calibration block

**Inputs/Outputs:**
- Modify: `.claude/skills/stock-screening/references/screening-blocks.md` (append Block A2)
- Done-check: heredoc prints a Jaccard overlap and a union shortlist; on current 1h data
  overlap ≈ 0.51 (< 0.85) → "sensitive" → union (~47 names).

- [ ] **Step 1: Append Block A2**

````markdown
## Block A2 — W self-calibration (run every screen; data drifts)

W is NOT a frozen constant. Build the shortlist at three windows and measure agreement.
If they agree, W is non-critical today; if not, take the union (inclusion-biased) and say so.

```python
def calibrate_W(interval, windows=(60, 120, 240), threshold=0.85):
    sets = {W: set(proxy_net(interval, W)["symbol"].to_list()) for W in windows}
    inter = set.intersection(*sets.values())
    union = set.union(*sets.values())
    overlap = len(inter) / len(union) if union else 0.0
    if overlap >= threshold:
        mid = windows[len(windows) // 2]
        return {"mode": "stable", "overlap": overlap, "W_used": mid,
                "shortlist": sorted(sets[mid])}
    return {"mode": "sensitive", "overlap": overlap, "W_used": list(windows),
            "shortlist": sorted(union)}
```

The result's `mode`/`overlap`/`W_used` MUST be disclosed in the report. `threshold=0.85`
is itself stated and adjustable. Windows scale to the interval (these suit 1h).
```
````

- [ ] **Step 2: Verify it's done**

Run (Block A1 + A2 pasted into the heredoc):
```bash
.venv/bin/python - <<'PY'
# <paste proxy_net + calibrate_W>
r = calibrate_W("1h")
print(r["mode"], round(r["overlap"], 2), "shortlist", len(r["shortlist"]))
for s in ["OLAELEC.NS","CARTRADE.NS","SHILPAMED.NS","MRPL.NS","SIGMAADV.NS"]:
    print("  survives:", s, s in r["shortlist"])
PY
```
Expected: `sensitive 0.51 shortlist 47`; all five known BUYs print `survives: ... True`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/stock-screening/references/screening-blocks.md
git commit -m "feat(stock-screening): W self-calibration block (validated)"
```

---

### Task 4: choppiness→k block

**Inputs/Outputs:**
- Modify: `screening-blocks.md` (append Block A3)
- Done-check: heredoc prints CI_median and k for sample stocks; k is computed per stock
  and spans ≥2 distinct values (e.g. SIGMAADV→4, OLAELEC/CARTRADE→6).

- [ ] **Step 1: Append Block A3**

Uses the battle-tested Choppiness Index (reuses Block 1's ATR inputs). Fibonacci bands
(38.2 / 50 / 61.8) map the stock's median choppiness to a fractal `k`. Choppier → larger
k (needs a more dominant pivot); smoother → smaller k.

````markdown
## Block A3 — choppiness → k (per stock, computed; never a hardcoded default)

```python
import math

def choppiness_k(df, n=14):
    """Median Choppiness Index over history → fractal k in {4,6,8,10}, clamped [4,12]."""
    log10n = math.log10(n)
    d = df.with_columns(pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("close").shift(1)).abs(),
            (pl.col("low") - pl.col("close").shift(1)).abs()).alias("tr"))
    d = d.with_columns([
        pl.col("tr").rolling_sum(n).alias("atrsum"),
        pl.col("high").rolling_max(n).alias("hh"),
        pl.col("low").rolling_min(n).alias("ll")])
    d = d.with_columns(
        (100 * (pl.col("atrsum") / (pl.col("hh") - pl.col("ll"))).log10() / log10n).alias("ci"))
    ci = d["ci"].median()
    if ci is None:
        raise ValueError("choppiness undefined — insufficient history for Choppiness Index")
    k = 4 if ci <= 38.2 else 6 if ci <= 50 else 8 if ci <= 61.8 else 10
    return {"ci_median": ci, "k": max(4, min(12, k))}
```

Disclose the computed `k` (and `ci_median`) per stock in the report. The spread is
data-dependent — a universe of similarly choppy names will share a `k`; that is correct,
not a bug. The requirement is that `k` is computed from the stock, not a literal.
```
````

- [ ] **Step 2: Verify it's done**

Run:
```bash
.venv/bin/python - <<'PY'
import polars as pl
# <paste choppiness_k>
def load(s):
    return pl.scan_parquet(f"market-data/prices/1h/{s}.parquet").select("high","low","close").collect()
ks = {s: choppiness_k(load(s))["k"] for s in
      ["OLAELEC.NS","CARTRADE.NS","SIGMAADV.NS","STLTECH.NS","MRPL.NS"]}
print(ks); print("distinct k values:", len(set(ks.values())))
PY
```
Expected: a dict like `{OLAELEC:6, CARTRADE:6, SIGMAADV:4, ...}`; `distinct k values` ≥ 2.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/stock-screening/references/screening-blocks.md
git commit -m "feat(stock-screening): choppiness->k block (validated)"
```

---

### Task 5: volume-fade + confirmed-up-leg guard block

**Inputs/Outputs:**
- Modify: `screening-blocks.md` (append Block A4 + Block A5)
- Done-check: heredoc computes a finite volume-fade ratio for a shortlisted stock and the
  up-leg guard returns a bool.

- [ ] **Step 1: Append Block A4 (volume-fade) and Block A5 (up-leg guard)**

````markdown
## Block A4 — volume-fade annotation (quality flag, NOT a gate)

Healthy pullbacks dry up on volume into the dip. Compare average volume on the dip
(confirmed high → live low) vs the prior up-leg (prior confirmed low → confirmed high).
Ratio < 1 = fading = healthy. This annotates conviction; it never rejects a candidate.

```python
def volume_fade(df, leg_start_ts, high_ts, live_low_ts):
    """dip avg volume / up-leg avg volume. <1 = volume fading into the dip (healthy)."""
    upleg = df.filter((pl.col("trade_timestamp") > leg_start_ts) &
                      (pl.col("trade_timestamp") <= high_ts))
    dip = df.filter((pl.col("trade_timestamp") > high_ts) &
                    (pl.col("trade_timestamp") <= live_low_ts))
    if upleg.height == 0 or dip.height == 0:
        return {"vol_fade_ratio": None, "fading": None}   # too thin to judge; disclose
    up_v = upleg["volume"].mean()
    dip_v = dip["volume"].mean()
    if up_v is None or up_v == 0:
        raise ValueError("up-leg has no volume — cannot compute volume-fade")
    ratio = dip_v / up_v
    return {"vol_fade_ratio": ratio, "fading": ratio < 1.0}
```

## Block A5 — confirmed up-leg guard (reject range chop)

A pullback only counts if the up-leg was a real uptrend, not sideways noise. Require the
50-EMA to be rising across the leg (uses Block 1's `ema_50`).

```python
def upleg_is_uptrend(df, leg_start_ts, high_ts):
    seg = df.filter((pl.col("trade_timestamp") >= leg_start_ts) &
                    (pl.col("trade_timestamp") <= high_ts))
    if seg.height < 2:
        return False
    return seg["ema_50"][-1] > seg["ema_50"][0]
```
````

- [ ] **Step 2: Verify it's done**

Run (compose pullback-finder's load/add_indicators/fractal_flags/zigzag/live_pullback_low
to get the timestamps, then call A4/A5 on OLAELEC):
```bash
.venv/bin/python - <<'PY'
import polars as pl
# <paste pullback-finder blocks: load, add_indicators, fractal_flags, zigzag, live_pullback_low>
# <paste choppiness_k, volume_fade, upleg_is_uptrend>
df = add_indicators(load("OLAELEC.NS","1h"))
k = choppiness_k(df.select("high","low","close"))["k"]
zz = zigzag(fractal_flags(df, k))
hi = next(p for p in reversed(zz) if p[1]=="H")
hi_idx = max(i for i,p in enumerate(zz) if p[1]=="H")
leg_start_ts = next(zz[j][0] for j in range(hi_idx-1,-1,-1) if zz[j][1]=="L")
ll = live_pullback_low(df, zz)
vf = volume_fade(df, leg_start_ts, hi[0], ll["live_low_ts"])
print("k", k, "vol_fade", vf, "upleg_uptrend", upleg_is_uptrend(df, leg_start_ts, hi[0]))
PY
```
Expected: `k` is 4–12; `vol_fade` has a finite `vol_fade_ratio` (a float) and a bool
`fading`; `upleg_uptrend` is `True` or `False` (not an error).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/stock-screening/references/screening-blocks.md
git commit -m "feat(stock-screening): volume-fade + up-leg guard blocks (validated)"
```

---

### Task 6: Stage-B composition recipe

**Inputs/Outputs:**
- Modify: `screening-blocks.md` (append Block A6 — the recipe, prose + glue, no new math)
- Done-check: heredoc runs the full Stage-B chain on 3 shortlisted symbols and prints, per
  symbol, `k`, depth band, bounce rate, live low, floor, and volume-fade.

- [ ] **Step 1: Append Block A6 (the composition recipe)**

````markdown
## Block A6 — Stage-B recipe: confirm each shortlisted stock

For each symbol from `calibrate_W(...)["shortlist"]`, compose pullback-finder's blocks
(in `../pullback-finder/references/building-blocks.md`) — do NOT copy them, paste them
into the same heredoc — with these screening additions:

1. `df = add_indicators(load(sym, interval))` (Block 1).
2. `k = choppiness_k(df.select("high","low","close"))["k"]` (Block A3) — per stock.
3. `zz = zigzag(fractal_flags(df, k))` (Blocks 2–3); noise filter from the stock's ATR.
4. `events = pullback_events(zz)` (Block 4), keeping only events whose up-leg passes
   `upleg_is_uptrend(df, leg_start_ts, high_ts)` (Block A5).
5. Per event: `anchor_for_low` (5) + `outcome` (6, stop_pct=0.03, horizon=15 — fixed risk).
6. `sig = signature(events)` (Block 7); `state = current_state(df, zz, sig)` (Block 8,
   runs `live_pullback_low` internally).
7. `vf = volume_fade(df, leg_start_ts, high_ts, state["live_low"]_ts)` (Block A4) on the
   live dip — annotation only.
8. Compute each stop's % from the latest close: `(close - level)/close*100` for
   `near_term_invalidation` and `structural_floor`.

`n_events < 5` for a symbol → label it low-confidence; never invent a signature.
This is the SAME math pullback-finder uses for a single symbol — Stage B is that workflow
run on each survivor, with computed `k`, the up-leg guard, and the volume annotation.
```
````

- [ ] **Step 2: Verify it's done**

Run the full chain on 3 names (paste pullback-finder blocks + A3/A4/A5):
```bash
.venv/bin/python - <<'PY'
import polars as pl
# <paste pullback-finder blocks 1-8 + 8b> and <choppiness_k, volume_fade, upleg_is_uptrend>
for sym in ["CARTRADE.NS","SHILPAMED.NS","MRPL.NS"]:
    df = add_indicators(load(sym,"1h"))
    k = choppiness_k(df.select("high","low","close"))["k"]
    zz = zigzag(fractal_flags(df,k))
    evs = pullback_events(zz)
    for e in evs:
        e["anchor"]=anchor_for_low(df,e["low_ts"]); e.update(outcome(df,e))
    sig = signature(evs); st = current_state(df, zz, sig)
    print(sym, "k",k, "n",sig.get("n_events"), "band",sig.get("depth_iqr"),
          "sr",sig.get("success_rate"), "live",st.get("live_low"), "floor",st.get("structural_floor"))
PY
```
Expected: each line shows a numeric `k`, `n` ≥ 5, a 2-value depth band, a bounce rate
between 0 and 1, and finite live/floor prices (consistent with the earlier screen, e.g.
CARTRADE band ≈ 4–6%, sr ≈ 0.58).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/stock-screening/references/screening-blocks.md
git commit -m "feat(stock-screening): Stage-B composition recipe"
```

---

### Task 7: Complete SKILL.md (workflow, output, law, rules)

**Inputs/Outputs:**
- Modify: `.claude/skills/stock-screening/SKILL.md` (fill the skeleton sections from Task 1)
- Done-check: every skeleton header has a body; the report format + footer-table columns
  match the standardized format; the law and failure table are present.

- [ ] **Step 1: Fill the SKILL.md bodies**

Fill each section with this content (concise, trader-facing):

- **Required input:** timeframe mandatory + user-supplied (ask if absent; any Yahoo
  interval; only 1d/1h on disk, fetch others, fail fast). Whole universe is default scope.
- **Workflow — the funnel:** Stage A `calibrate_W(interval)` → shortlist + mode/overlap;
  Stage B run the Block A6 recipe on each shortlisted symbol; Stage C tier + report.
- **Stage C tiers:** BUY THE DIP / SPECULATIVE (n<... thin) / CAUTION (live low below
  floor) / AVOID (recent dip > own band = reversal risk).
- **Output style — ranked line:**
  `SYMBOL — <action>: dipping X% vs its usual Y% dip; bounces ~Z% of the time; buy zone
  ₹A–B, wrong below ₹C (−X% from price)`.
- **Output style — footer table columns:**
  `Symbol | n dips | usual dip % | now off high % | live-low dip % | bounce rate |
  vol-fade | live low ₹ (−%) | floor ₹ (−%)`. Mark ⚠ when floor % < live-low %. Dip
  %/now/live-low dip % are from the swing HIGH (depth); each `(−%)` is from the latest
  CLOSE (stop distance).
- **Disclosures every run:** W mode (stable/sensitive), overlap, W(s) used; computed `k`
  per stock; count excluded for short history; survivorship bias; on-the-fly EMA/ATR.
- **The law:** every pattern param (W, k, noise, bands) derived/validated against current
  data at screen time and disclosed; no frozen constants. Risk knobs (3% stop, 15-bar
  horizon) fixed = trader's model, stated.
- **Hard rules:** read-only against `market-data/`; never write a repo file (run Polars
  via heredoc; `/tmp` only if unavoidable); never delete/overwrite under
  `market-data/prices/`; every number computed in Polars, never eyeballed.
- **Failure handling table:**

| Situation | Behavior |
|---|---|
| No timeframe | Ask; never default. |
| Interval not on disk | Fetch via pipeline (respect Yahoo caps); fail fast on failed download. |
| Symbol file missing/empty | Quote error, skip symbol, disclose. |
| Shortlist empty | Report "no buyable dips today." No forced picks. |
| Survivor with < 5 dips | Label low-confidence; do not invent a signature. |
| W-sensitive run | Use union shortlist; disclose mode + overlap. |

- [ ] **Step 2: Verify it's done**

Run: `grep -c '^##' .claude/skills/stock-screening/SKILL.md` → expect ≥ 9 sections; then
`grep -n "no buyable dips today\|vol-fade\|3% stop\|union" .claude/skills/stock-screening/SKILL.md`
→ each phrase resolves to a line.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/stock-screening/SKILL.md
git commit -m "feat(stock-screening): complete SKILL.md workflow + output + law"
```

---

### Task 8: End-to-end dry run + limits check + self-review

**Inputs/Outputs:**
- Modify: none (verification + any fixes surfaced)
- Done-check: full screen runs on 1h producing a ranked list + footer; file/function
  limits pass; success criteria from the spec are met.

- [ ] **Step 1: Full end-to-end dry run on 1h**

Compose all blocks (Stage A `calibrate_W` → Stage B recipe on the shortlist → tier) in one
heredoc and produce the ranked list + footer table for the 1h universe. Confirm the output
shape matches Task 7's format and includes the W-mode disclosure line.

- [ ] **Step 2: Verify success criteria + limits**

Confirm against the spec §10:
- Shortlist includes ≥1 in-band dipper outside the old raw-depth top-15 (dry-run showed 18,
  e.g. FORTIS/GRASIM) — Hole A fixed.
- Output states W mode + overlap (dry-run: `sensitive 0.51`).
- Per-stock `k` shown and computed (≥2 distinct values).
- Each candidate row carries a vol-fade value.
- Empty-shortlist path prints "no buyable dips today" (force by filtering to an
  impossible band to confirm the branch).
Then limits:
```bash
wc -l .claude/skills/stock-screening/SKILL.md .claude/skills/stock-screening/references/screening-blocks.md
```
Expected: each ≤ 800 lines. Eyeball each function ≤ 80 lines (all blocks above are well
under). If any file exceeds 800, split references by stage.

- [ ] **Step 3: Self-review + commit**

Re-read the spec sections against the two files; fix any gap inline. Then:
```bash
git add -A .claude/skills/stock-screening/
git commit -m "test(stock-screening): end-to-end dry run + limits verified"
```

---

## Self-Review (plan vs spec)

- **Spec §4.1 Stage-A proxy + self-calibrating W** → Tasks 2, 3 (validated; trough-band +
  recent-dip fix folded in after dry-run showed the per-bar/latest-close version wrongly
  dropped OLAELEC).
- **Spec §4.2 Stage-B computed-k / up-leg / volume-fade / stops-with-%** → Tasks 4, 5, 6.
- **Spec §4.3 Stage-C tiers + report + disclosures + empty-shortlist** → Task 7 (+ Task 8
  verifies the empty path).
- **Spec §5 the law** → Task 7 (law section) and enforced by Tasks 2–4 (no constant `k`/`W`).
- **Spec §6 companion-not-edit** → Block A6 composes pullback-finder; no task modifies it.
- **Spec §7/§8 hard rules + failure handling** → Task 7.
- **Spec §9 file structure** → Tasks 1, 2 (two files); Task 8 enforces ≤800-line limit.
- **Spec §10 success criteria** → Task 8.
- **Spec §11 open items (k formula, volume-fade def, W set/threshold)** → finalized:
  choppiness→k = median Choppiness Index + Fib bands (Task 4); volume-fade = dip/up-leg
  avg-volume ratio (Task 5); W = {60,120,240}, threshold 0.85 (Task 3). No open items remain.

No placeholders; names consistent (`proxy_net`, `calibrate_W`, `choppiness_k`,
`volume_fade`, `upleg_is_uptrend`, `screening-blocks.md`) across all tasks.
