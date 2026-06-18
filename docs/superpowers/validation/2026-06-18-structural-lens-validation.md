# Structural Lens — Validation Gate (2026-06-18)

Validation of the Stage-S structural lens (`references/structural-blocks.md`, Blocks S1–S6)
on the 1h universe (176 symbols). Spec §10. **Decision: SHIP STRUCTURE-BUY.**

## 1. Universe run (Stage S, 1h)

```
analyzed: 176 | skipped: 0
tiers: 1 STRUCTURE-BUY · 95 STRUCTURE-WATCH · 52 STRUCTURE-SPEC · 28 STRUCTURE-AVOID
```
- The single BUY: **PGHL.NS** — m=5 (sep +0.30), edge +0.387, 7 analogs, stop −1.2% (placeable), turn ✓.
- The bar is appropriately strict: BUY needs edge beyond 1 SE + a 3%-placeable stop + uptrend + confirmed turn.

## 2. Out-of-sample separation (the edge gate)

Separation = realized success(above-median match score) − realized success(below-median).

**Selection-biased estimate (NOT the gate):** per-stock `m` is *chosen* to maximize validation
separation, so reusing that number is optimistic. Mean **0.405**, 98.8% positive — inflated by
the max-over-m selection. Recorded only for transparency; **not** used for the decision.

**Honest nested estimate (THE GATE):** `m` chosen on the **first 80%** of each stock; separation
measured only on the **untouched last 20%** the selection never saw.

```
3711 held-out test windows · 171 stocks
realized success | positive-edge match:  0.515  (n = 2068)
realized success | negative-edge match:  0.181  (n = 1643)
pooled realized (all test matches):      0.367
CLEAN OOS SEPARATION:                    0.334
```

A **33-point** spread on data the model never trained on, across 171 stocks. The selection bias
was real but small (0.405 → 0.334). The structural score has genuine, honest predictive edge.

## 3. CEMPRO sanity (the motivating case)

```
CEMPRO.NS → STRUCTURE-SPEC | m=5 (sep +0.20) | 14 analogs | score 0.286 vs base 0.244 (edge +0.041)
            turn ✓ | stop ₹1075.6 (−9.4%)
```
CEMPRO is **no longer invisible** — it surfaces in the structural lens (it was absent from the
dip-only screen). The honest verdict is SPEC, not BUY: the structure has turned, but its edge is
within noise of its base rate **and** the structural stop is 9.4% away (a 3% stop cannot be
placed). Surfaced and correctly tiered, not forced.

## 4. Law audit

`grep` of `structural-blocks.md` for numeric literals: every hit is a structural primitive
(`rng>0`, `m-1`, last-row index), a definitional floor (`<2` pairwise, `<5` min-sample, `3`
min-pivots), a compute cap (`cap=200`, RNG seed `0`), display rounding, or the null edge
threshold (`0`). **No tuned pattern constant.** `m`, the match radius, the edge cutoff, and the
completion trigger are all learned per stock and disclosed — the law holds.

## 5. Deviation from spec

Spec §7 S4 specified "structure base minus a **learned buffer**." v1 ships the **base itself** as
the stop anchor (no buffer) — a learned ATR buffer is deferred to v2 to avoid a hardcoded
multiple. Flagged in the plan (Revision 1) and here.

## 6. Decision

**SHIP STRUCTURE-BUY.** Honest OOS separation 0.334 (0.515 vs 0.181, 3711 held-out windows) is a
clear, robust edge that survives a held-out test split. The lens is not toothless; the BUY tier
is warranted. The strict tier rules keep it honest (1 BUY of 176, CEMPRO correctly SPEC).
