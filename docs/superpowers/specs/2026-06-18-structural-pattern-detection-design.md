# Structural Pattern Detection — Design Spec

- **Date:** 2026-06-18
- **Branch:** `feature/structural-pattern-detection`
- **Status:** approved design, pre-implementation
- **Skills touched:** `stock-screening` (new Stage S + blocks S1–S5), reuses `pullback-finder` blocks 1–3, 6, A7, A4. `pullback-finder` itself is **not modified**.

## 1. Problem

Both `pullback-finder` and `stock-screening` are single-axis: "how deep is the dip, does
it bounce." A stock in a strong uptrend **pressing its highs** (no dip) is invisible —
`now_off_high` small → WATCH, and the skill has no notion of structure forming.

Motivating case: **CEMPRO.NS** — EMAs stacked 10>20>50>100>200, price above all, +118%/60d,
5.6% off ATH, coiling tightly at highs. A textbook continuation/structural buy that the
dip screen cannot surface. The user also rejects naming patterns (no inverse-H&S / double-
bottom templates) — detection must be **pattern-agnostic**.

## 2. Goal / non-goals

**Goal (v1):** a **structural lens** added to `stock-screening` that detects, pattern-
agnostically, that a *meaningful structure is forming* for a stock, judged against the
stock's **own** history, and emits a **STRUCTURE-BUY / WATCH / SPEC** tier with a learned
stop — integrated into the existing screen report as a separate section.

**Non-goals (v1):** no cross-stock analog pooling; no matrix-profile engine; no refactor of
the existing pullback signature; no bidirectional (short) setups beyond the free
STRUCTURE-AVOID byproduct. These are explicitly deferred (§10).

## 3. Locked decisions

| Decision | Choice | Why |
|---|---|---|
| v1 deliverable | Detection **+ buy/watch tier + learned stop**, in the screen report | User pick |
| Detection engine | **Pivot-analog kNN** over the existing zigzag | Reuses grammar, interpretable, no heavy deps |
| Analog pool | **Per-stock only** | Honors learn-per-stock law; cross-stock is v2 |
| Directionality | **Bullish** (buy screen); AVOID is a free byproduct | Scope |

## 4. The law — no hardcoded pattern params

Every value that **sizes or thresholds** the pattern is learned per stock at run time and
disclosed. The ONLY fixed values allowed are the same scaffolding the existing skill already
justifies:

- **3% hard stop** — the trader's risk knob.
- **`H_base = 15`** — the cross-stock comparability yardstick.
- **Pure statistical floors** — a min-sample count (≈5) and a stated quantile `q`.

Grammar (definitional primitives — what a thing *is*) is fine and not a tuned constant: a
fractal pivot (`max within ±k bars`), an up-thrust (`close > prior high`), "a structure needs
≥ 3 pivots." A **window length, neighbour count, or match radius is NOT grammar** — it is a
tuned pattern param and must be learned.

| Learned per stock | Fixed scaffolding (disclosed) |
|---|---|
| `m` (window), match radius, analog count, edge cutoff (vs base rate), `H_stock`, stop anchor + buffer, **completion trigger** (reused `learn_turn_trigger`) | 3% stop · `H_base=15` · min-sample floor · quantile `q` |

## 5. Architecture

A **Stage S** lens runs parallel to the dip funnel (Stage A→B→C). One run → one report file
with two clearly walled-off sections (dip + structural); rows are tagged `lens` (`dip` |
`struct`) and the two lenses **never cross-rank**.

**Stage S net (cheap pre-filter):** whole universe → keep names **in an uptrend**
(`close > ema50 > ema50_prev`, reused) **with enough pivot history** to learn `m` and build a
library. Inclusion-biased, like Stage A.

**Reuse map (no rewrites of pullback-finder):**

| Reused | From | For |
|---|---|---|
| `add_indicators` | Block 1 | EMAs / ATR |
| `fractal_flags` + `zigzag` | Blocks 2–3 | the pivot skeleton |
| `outcome` (double-barrier) | Block 6 | forward labels, 3% stop |
| `learn_horizon` / `H_stock` | Block A7 | per-stock clock |
| `volume_fade` | Block A4 | optional conviction flag |

**New blocks:** S1 fingerprint · S2 library · S3 match · S4 stop · S5 tier.

## 6. Engine (S1–S3)

### S1 — Shape fingerprint (scale + time invariant)
A window of `m` pivots → min-max normalize the `m` pivot **prices** to [0,1] (relative
heights, kills price level) + normalize the `m` pivot **bar-indices** to [0,1] (spacing).
Canonicalize every window to **start on a Low** (parity). Result: a `2m` vector. Same shape at
any price/scale → same fingerprint. No pattern is named — only encoded. (Normalization +
start-parity are representation, not tuned values.)

### `m` — learned per stock by predictive validation
`m` is the window length whose shape-analogs best **predict forward outcomes out-of-sample
on that stock** (`learn_m_predictive`). Over a candidate range derived from the stock's pivot
supply (`m` from 3 up to the largest window whose train split still holds ≥ a stat-floor of
windows), split history train/validation; build the library on train, match the validation
windows, and score **separation** = (realized success among above-median-score matches) −
(below-median). Pick the `m` with the best separation; disclose `m` + its separation. **No `m`
separates (≤ 0) → the structural lens has no edge for that stock → low-confidence, never
forced.** This folds the out-of-sample test into the engine: `m` is chosen *because* it
predicts, not assumed. (An early density×`H_stock` heuristic was rejected — it collapsed to
the 3-pivot floor for ~60% of names incl. CEMPRO, degenerating to a single-pullback match.)
Within a stock `m` is then constant, so all its fingerprints share length (per-stock pool).

### S2 — Historical library (per stock)
Slide the `m`-window over the stock's **own** confirmed zigzag history. Each window →
fingerprint + **dual-clock forward outcome** from its last pivot (Block 6: `success@base15` +
`success@H_stock` + realized MFE). Label only windows with ≥ `H_stock` forward bars — **no
look-ahead**. Also compute the stock's **base_rate** = unconditional P(new high within
`H_stock` from any pivot) — the benchmark a structure must beat.

### S3 — Live match (kNN)
Live fingerprint = last `m−1` **confirmed** pivots + the **live forming** pivot. Distance =
Euclidean on the fingerprint (DTW is a v2 upgrade). Match = **all** historical windows within
the **learned match radius** = a low quantile (`q`) of the stock's **own** pairwise-distance
distribution ("same shape" defined by the stock; no fixed ε, no fixed `k`).
`structure_score = mean(success@base)` over the matched analogs; also `success@learned`,
analog count, dispersion. **< min-sample analogs in radius → low-confidence (SPEC), never
invent.**

**Edge is relative:** a structure qualifies only when `structure_score > base_rate` beyond
noise (given analog count + dispersion) — never an absolute 0.5. The bar is the stock's own
unconditional odds.

## 7. Stop + tiering (S4–S5)

### S4 — Structural stop (learned)
Anchor = the structure's **base** (lowest pivot in the live `m`-window — definitional floor)
minus a **learned buffer** = the stock's own ATR-noise below that low. `anchor_exists` iff
`(close − anchor)/close ≤ 3%`. Doesn't fit → can't place a 3% structural stop → WATCH
(stop-survival veto). 3% is fixed; the anchor + buffer are structural / learned.

### S5 — Tiers (`lens = struct`)
| Tier | Condition |
|---|---|
| **STRUCTURE-BUY** | ≥ min-sample analogs · `score > base_rate` (beyond noise) · `anchor_exists` · uptrend · **completion trigger fired** — the live forming leg lifts off the structure's base, confirmed by the stock's **learned** turn trigger (reuse `learn_turn_trigger` / `live_turn`, Blocks 7b/8c), never a fixed level |
| **STRUCTURE-WATCH** | shape + edge present, trigger not fired yet **or** stop doesn't fit 3% → quote completion-trigger ₹ / needed stop |
| **STRUCTURE-SPEC** | < min-sample analogs (sparse) **or** edge within noise of base_rate |
| **STRUCTURE-AVOID** (free byproduct) | `score << base_rate` — shape historically preceded drops |

## 8. Report integration

Same report file, a **separate `## Structural lens` section** with its own table — columns:
`Symbol | m | analogs | score vs base (edge) | H_stock (≈days) | trigger | stop ₹ (−%) |
latest candle` — plus its own ranked buy-lines ("matches N past SYMBOL setups, M% rose, edge
+X over base; trigger ₹A, stop ₹B"). The dip section is unchanged.

**Disclosures (struct, per stock):** `m` (+ the pivots-per-`H_stock` it came from), match
radius (+ `q`), analog count, `score` vs `base_rate` + dispersion, stop anchor + buffer,
trigger. Global scaffolding line: 3% · `H_base=15` · min-sample floor · `q`.

## 9. Failure handling

| Situation | Behaviour |
|---|---|
| Too few pivots to learn `m` / build library | Exclude, disclose count |
| < min-sample analogs in radius | STRUCTURE-SPEC (low-confidence); never invent |
| No forming window (price at a new high, < `m−1` confirmed pivots) | Not applicable; skip + disclose |
| Stop won't fit 3% | STRUCTURE-WATCH (stop-survival) |
| `H_stock` unlearnable (< min recoveries) | Fall back to `H_base`, low-confidence |
| Per-symbol exception | try/except, disclose; never abort the universe run |

## 10. Verification — success criteria

1. **No-look-ahead** unit test — library labels use only post-window bars.
2. **Scale-invariance** unit test — the same pivot shape at any price/scale → identical fingerprint.
3. **Out-of-sample separation** (the real edge test) — walk-forward: build the library on bars
   ≤ T, score live matches at T, measure realized forward outcome after T across the universe.
   **No separation from `base_rate` out-of-sample → the lens has no edge; report that, do not
   ship a toothless tier.** Per-stock `m` is already chosen by this same separation criterion
   (§6); this universe gate aggregates and confirms across stocks.
4. **CEMPRO sanity** — CEMPRO surfaces as STRUCTURE-BUY or -WATCH (no longer invisible).
5. **Law audit** — grep the new blocks: every sizing/threshold traces to a learned value or
   the disclosed scaffolding list; no stray literals.

## 11. Deferred (future)

- Cross-stock analog fallback when per-stock analogs are sparse (disclosed, low-confidence).
- Matrix-profile (STUMPY) motif engine as an alternative/augment when pivot analogs are thin.
- DTW distance for elastic spacing / variable-length structures.
- Bidirectional (short) setups beyond the AVOID byproduct.
- Folding the existing pullback signature in as a special case of shape-analog matching.

## 12. Read by

This spec must read as evidence-driven structural screening, not a pattern catalogue. It is
structural evidence, not financial advice.
