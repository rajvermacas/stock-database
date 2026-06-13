# stock-screening skill — Pullback Universe Screener (Design)

**Date:** 2026-06-13
**Status:** Approved design, pending spec review → implementation plan
**Work type:** General workflow (a new Claude Code skill)
**Companion:** `pullback-finder` (reused, not modified)

---

## 1. Problem

The existing pullback screen (run via `pullback-finder`'s universe workflow) has a
selection bug and a performance wall, surfaced while running it live on the 1h
universe (172 symbols):

- **Hole A — wrong selector (accuracy).** Stage-1 ranks symbols by *raw* depth off a
  fixed-window high, then deep-analyzes only the top N (15). But buyability =
  depth vs the stock's **own** typical dip, not a global ranking. A calm stock
  dipping 3% (deeply in its own band, a real buy) ranks below a wild stock dipping
  8% (just noise / a reversal) and never reaches deep analysis. **Real dippers
  ranked below the cut are silently missed.**
- **Hole B — k hardcoded.** pullback-finder *intends* the fractal window `k` to be
  derived per stock from its choppiness, but ships no formula; in practice it
  collapses to a hardcoded constant (the live run used `k=6` for all 15), violating
  the per-stock intent.
- **Hole C — up-leg not confirmed.** The "is this a real uptrend leg, not range
  chop?" check (rising EMA over the leg) is described but was skipped.
- **Hole D — volume ignored.** Classic pullback quality (fading volume into the dip)
  is never measured though `volume` is in the schema.
- **Hole E — performance.** Deep analysis is a Python loop per symbol (re-read
  parquet, dict-zip ATR map, row-loop zigzag). Fine for 15; fixing Hole A means
  judging *everyone* by own-band, which would make a naive loop over ~91 survivors
  slow.

Accuracy and performance are linked: fixing A (judge everyone by own band) makes E
bite. The skill must do both.

## 2. Goal & Non-goals

**Goal:** A new `stock-screening` skill that screens the whole Parquet universe for
buy-on-pullback candidates, judging each stock against **its own** dip behavior,
fast, with every pattern parameter derived/validated against current data at run
time (not frozen).

**Non-goals (YAGNI):**
- Not a multi-strategy framework. **Pullback only.** Other screens = other skills
  later.
- Does not modify `pullback-finder`. That skill stays the per-stock grammar; this
  skill orchestrates the universe screen and *reuses* its blocks.
- Not financial advice; structural evidence only.

## 3. Required input

- **Timeframe is mandatory and user-supplied** (same rule as pullback-finder). Never
  assume/default. If absent, ask before doing anything. Any Yahoo interval allowed;
  only `1d`/`1h` on disk — fetch others via the project pipeline, fail fast on a
  failed download. Whole universe is the default scope (no symbol argument).

## 4. Architecture — two-stage funnel

```
Universe (e.g. 172 symbols on 1h)
   │  Stage A — cheap vectorized NET  (one streaming Polars pass, all symbols)
   ▼
Shortlist (~15–30: dipping inside their OWN normal band, in an uptrend)
   │  Stage B — bespoke DEEP confirm  (pullback-finder grammar, per shortlisted stock)
   ▼
Confirmed candidates (exact band, bounce rate, live low + floor, stops, volume flag)
   │  Stage C — tier + report
   ▼
Ranked buy list  (or "no buyable dips today")
```

Principle: **cheap vectorized step picks WHO to look at; expensive bespoke step
decides the verdict.** A rough proxy in Stage A can only change the shortlist, never
produce a wrong final answer — Stage B recomputes everything exactly.

### 4.1 Stage A — self-calibrating proxy net (vectorized, whole universe)

Per stock, computed in one streaming Polars pass over the glob
`market-data/prices/<interval>/*.parquet`, `group_by("symbol")`:

1. **Trailing peak** at each bar: `peak_t = rolling_max(high, W)` (trailing, backward
   only — no look-ahead).
2. **Dip series**: `drawdown_t = (peak_t - close_t) / peak_t` for every bar — the
   stock's historical distribution of "how far below its recent peak."
3. **Own proxy band**: `q25, q75` of `drawdown_t` over history (the middle-50% of its
   dips = its normal dip range). Cheap stand-in for pullback-finder's exact IQR band.
4. **Today's dip**: `today = (peak_now - close_now) / peak_now`.
5. **Uptrend filter** (reused from existing Block 9): `bars >= 60` AND
   `close > ema_50` AND `ema_50` rising over a lookback.
6. **In-band now?** `q25 <= today <= q75` AND uptrend → shortlist this symbol.

Dip measured off **close** in Stage A (stabler); Stage B uses the intrabar **low**
for the exact live low.

**W self-calibration (every run, because data drifts).** W is NOT a frozen constant.
Build the shortlist at three windows — `W ∈ {60, 120, 240}` (short/medium/long
peak-memory on 1h; scale to the interval) — and measure agreement:

```
overlap = |S60 ∩ S120 ∩ S240| / |S60 ∪ S120 ∪ S240|     (Jaccard)
```

- **Stable** (overlap ≥ 0.85): W is non-critical today → use the medium-W shortlist,
  disclose *"W-stable, shortlist robust."*
- **Sensitive** (overlap < 0.85): pullback durations vary enough that one window
  can't see them all → take the **union** of the three shortlists (safe — Stage B
  culls extras), disclose *"W-sensitive this run, widened net."*

Cost: 3 vectorized passes, not 172 loops. Deterministic, self-documenting. The
threshold 0.85 is itself disclosed and adjustable.

Rationale for self-calibrating W (not per-stock dynamic W): the in-band test is a
self-referential percentile (today vs this stock's own history, both via the same W),
so it is largely W-invariant within a sane range; truly per-stock W would require
each stock's pullback *duration* — which needs the Stage-B event mining, a circular
dependency. The only real failure (W shorter than a long pullback → peak falls out of
window → dip understated → false exclude) is caught by including the long W=240 and
taking the union when windows disagree.

### 4.2 Stage B — bespoke deep confirm (pullback-finder companion)

For each shortlisted symbol, run pullback-finder's blocks (load → indicators →
fractal → zigzag → pullback_events → anchor → outcome → signature → live low →
current_state). All **pattern parameters computed per stock, not hardcoded:**

- **k computed from choppiness (fixes B).** Define a measured choppiness statistic and
  map it to `k` via a disclosed formula, clamped to a sane range. Candidate measure:
  `choppiness = (count of zig-zag direction changes per 100 bars)` or
  `median(|close.pct_change|) / median(atr_pct)`; map smoother → smaller k, choppier
  → larger k; `k = clamp(round(f(choppiness)), 4, 12)`. Exact statistic + mapping
  finalized in the implementation plan; the requirement is: **k is computed,
  per-stock, deterministic, and disclosed — never a literal default.**
- **Noise filter** (zigzag) likewise derived from the stock's wiggle (ATR multiple),
  not a global constant.
- **Up-leg confirmed (fixes C):** require the up-leg to sit above a rising longer EMA
  (e.g. `ema_50` rising over the leg) before counting an H→L as a pullback, per
  Block 4's note.
- **Volume-fade quality flag (fixes D):** measure whether volume **fades into the dip**
  (down-leg average volume < up-leg average volume, or a downward volume slope across
  the pullback bars). Output as a per-candidate boolean/score quality flag; it does
  NOT gate the candidate, it annotates conviction. Computed in Polars from the
  `volume` column.
- **Exact outputs:** own depth band (IQR), bounce rate, dominant anchor, live low
  (near-term stop) + structural floor, **each stop with its % distance from the
  latest close** (per the standardized output format).

`n_events < 5` on a shortlisted survivor → label **low-confidence**, never invent a
signature.

### 4.3 Stage C — tier + report

Tier confirmed candidates: **BUY THE DIP / SPECULATIVE (thin history) / CAUTION
(structure cracked) / AVOID (dip far beyond own band = reversal risk)**. Output the
standardized universe format:

- Ranked plain line per buy candidate:
  `SYMBOL — <action>: dipping X% vs its usual Y% dip; bounces ~Z% of the time;
  buy zone ₹A–B, wrong below ₹C (−X% from price)`.
- Footer table, one row per analyzed stock, columns:
  `Symbol | n dips | usual dip % | now off high % | live-low dip % | bounce rate |
  volume-fade | live low ₹ (−%) | floor ₹ (−%)`. Mark ⚠ when floor % < live-low % (live
  low below floor → near-term structure cracked). Dip %/now-off-high %/live-low dip %
  are measured from the swing HIGH (depth); each `(−%)` beside a ₹ stop is from the
  latest CLOSE (stop distance).
- **Disclosures every run:** the W-stability result (stable/sensitive + the value(s)
  used), computed `k` per stock, count excluded for short history, survivorship bias
  (universe selected on today's uptrend), on-the-fly EMA/ATR.

**Empty shortlist → report plainly "no buyable dips today."** Never force picks, never
fall back to closest-to-band names.

## 5. Cross-cutting law — no frozen pattern constants

> Every **pattern** parameter (W, k, noise filter, depth bands) is derived from or
> validated against the current data **at screen time** and disclosed in the output.
> None is a hardcoded constant trusted across runs, because the universe and each
> stock's behavior drift.
>
> **Risk** knobs (3% hard stop, ~15-bar horizon) stay fixed — they are the trader's
> model, stated explicitly and kept distinct from pattern parameters.

## 6. Companion relationship to pullback-finder (DRY)

- `stock-screening` **references** `pullback-finder/references/building-blocks.md` for
  the per-stock math (Blocks 1–8) rather than duplicating it. Stage B composes those
  blocks; the proxy net (Stage A), self-calibration, tiering, and report live in
  `stock-screening`.
- `pullback-finder` is **not edited** by this work.
- Single-symbol questions still go to `pullback-finder` directly; `stock-screening` is
  the universe path.

## 7. Hard rules (inherited + new)

- Read-only against `market-data/`. **Never write a file into the repository**; run
  composed Polars via heredoc to `.venv/bin/python`; any unavoidable scratch file goes
  under `/tmp/` only.
- **Never delete or overwrite anything under `market-data/prices/`** — persistent data
  lake; only add (fetched intervals) to it.
- Timeframe missing/unsupported → ask or raise. Missing symbol / no rows / stale data
  / failed fetch → quote the error and stop; no partial analysis, no fabricated
  numbers.
- Every number computed in Polars, never eyeballed.

## 8. Failure handling

| Situation | Behavior |
|---|---|
| No timeframe given | Ask; never default. |
| Requested interval not on disk | Fetch via pipeline (respect Yahoo caps); fail fast on failed download. |
| Symbol file missing / empty | Quote error, skip that symbol, disclose. |
| Shortlist empty | Report "no buyable dips today." No forced picks. |
| Survivor with < 5 past dips | Label low-confidence; do not invent a signature. |
| W-sensitive run | Use union shortlist; disclose. |

## 9. File structure (the new skill)

```
.claude/skills/stock-screening/
  SKILL.md                       # workflow, output style, hard rules, the law
  references/
    screening-blocks.md          # Stage-A proxy net + W self-calibration + k formula
    (links to pullback-finder/references/building-blocks.md for Stage B math)
```

Respect the 800-line/file and 80-line/function limits; split references if they grow.

## 10. Success criteria (how we verify it works)

1. **Fixes Hole A:** on the same 1h data, the shortlist includes at least one
   in-band dipper that the old raw-depth top-15 missed (demonstrated by comparison).
2. **Self-calibration visible:** every run's output states the W-stability result and
   the W(s) used.
3. **No hidden constants:** every pattern parameter in the output (W, k, noise, bands)
   is shown as computed/derived; only the 3% stop + horizon appear as fixed risk
   knobs.
4. **Computed k:** per-stock k values differ across stocks and are disclosed (not all
   equal).
5. **Volume-fade present:** each candidate row carries a volume-fade flag.
6. **Empty-shortlist path:** when nothing is in-band, output is "no buyable dips
   today," not a forced list.
7. **Performance:** deep (Stage B) work runs only on the shortlist (~15–30), not the
   full universe; Stage A is a single streaming pass.

## 11. Open items for the implementation plan

- Finalize the exact choppiness statistic and the choppiness→k mapping.
- Finalize the volume-fade definition (ratio vs slope) and its display.
- Confirm W set + overlap threshold per interval (the {60,120,240}/0.85 are starting
  points to validate, themselves disclosed).
