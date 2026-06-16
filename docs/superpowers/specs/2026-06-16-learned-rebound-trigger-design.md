# Learned Rebound Trigger — Design Spec

**Date:** 2026-06-16
**Skills touched:** `pullback-finder` (owns the new grammar), `stock-screening` (consumes it)
**Status:** approved design, ready for implementation plan

## Problem

The current verdict `BUY THE DIP` fires on **in-band depth + uptrend intact + live low
above floor + a fair historical bounce rate**. None of those conditions check whether the
*live* dip has actually **stopped falling and turned up**. A stock still cutting fresh lows
inside its own band is labelled `BUY` exactly like one that has begun to rebound — the
classic falling-knife trap. The user wants buy candidates that show a **sign of rebound**,
not knives.

The data for a turn is half-present (`live_pullback_low`, Block 8b, returns `live_low_ts`
and `depth_from_high_pct`) but **no block measures the turn and no verdict tier uses it**.

## Goal

Add a **per-stock learned rebound trigger**: learn from each stock's own history what its
*first real sign of a turn* looked like, then require the live dip to reproduce that marker
before it can be a BUY. Everything turn-related is **learned from the stock's data**, never
a hardcoded threshold — consistent with the skill's existing law ("no frozen pattern
constants").

## Non-goals

- No change to how dips are detected, how the depth band / anchor / horizon / bounce rates
  are learned (Blocks 2–7 stay).
- No new fixed risk knobs. The 3% stop and `H_base=15` ruler are unchanged.
- Not the discriminative (winners-vs-knives) or structural-higher-low approaches — those
  were considered and rejected for KISS / edge-zone-confirmation reasons.

## Approach: learn from winners

### Decisions locked with the user
- **Verdict shape:** *Confirmed turn* — a measurable lift off the live low plus an up-thrust
  (not merely "exclude knives", not "wait for a structural higher-low").
- **Learning method:** learn the trigger from the stock's **own successful past dips**.
- **Live confirm logic:** **union** — confirmed if EITHER the learned lift OR the learned
  EMA reclaim fires; report which path fired.
- **Scope:** the new blocks live in **pullback-finder**; **stock-screening composes** them
  and never modifies pullback-finder.
- **Up-thrust primitive:** first bar after the low that **closes above the prior bar's
  high**. A structural definition (like the fractal-pivot definition), not a tuned number.

### 1. Learned rebound signature (extend Block 7 `signature`)

For each **successful** past pullback event (higher-low held per Block 4, recovered per
Block 6), measure the **early turn marker** at the first up-thrust after the low. All
quantities are observable in real time at that historical bar — **no look-ahead**.

For an event with low at `low_ts`, low price `L`, ATR at the low `atr_L`:

- Walk bars strictly after `low_ts`. The **first up-thrust** = first bar whose
  `close > previous bar's high`. Call it bar `T`.
- **lift** = `(close_T − L) / atr_L`. ATR is the stock's own volatility scale; the magnitude
  is learned.
- **reclaim** = the **highest** EMA (`ema_10/20/50/100/200`) that the low `L` was *below*
  and `close_T` is *above* — i.e. the strongest level genuinely reclaimed during the turn;
  `none` if the up-thrust close reclaimed no EMA it had been below.
- **turn lag** = `index(T) − index(low)` in bars.
- If no up-thrust exists after the low (e.g. recovered via a gap with no qualifying bar),
  drop that event from the trigger learning and disclose the dropped count.

Aggregate over the winners:

- `learned_lift` = **median** of `lift` over winners (tunable + disclosed; median chosen
  over q25 to avoid over-early triggering — stated and adjustable).
- `learned_reclaim_ema` = **mode** of `reclaim` over winners (`none` is valid, like
  `dominant_anchor`).
- `learned_turn_lag` = **median** of `turn lag` (used to bound "fresh" vs "already
  bounced").

Guard: fewer than 5 recovered events that produced an up-thrust → **cannot learn the
trigger** → mark `turn = unconfirmable, low-confidence`. No default invented. (Consistent
with the existing `n_events < 5` / `min_recovered` rules.)

### 2. Live test (new Block 8c `live_turn`)

From the live low (Block 8b `live_pullback_low`) and the bars since it:

- `cur_lift = (last_close − live_low) / atr_now`
- `reclaimed_live` = is `last_close` back above `learned_reclaim_ema` (if not `none`)

Label:

- **turn confirmed** if `cur_lift ≥ learned_lift` **OR** `reclaimed_live` (union). Record
  which path(s) fired and the **trigger level** = the price that would satisfy the unmet
  path (the `live_low + learned_lift * atr_now` price, and/or the `learned_reclaim_ema`
  value) — this is what a not-yet name must reach to flip to BUY.
- **not turned yet** if neither path fires (basing / still falling).
- **already bounced** if `cur_lift` is well past `learned_lift` *and* price is at/above the
  prior swing high (defer to the existing WATCH/already-bounced handling; the turn block
  does not need a new constant — "near old high" reuses the existing swing-high comparison).
- **unconfirmable / low-confidence** if the trigger could not be learned (§1 guard).

### 3. Verdict changes

**pullback-finder** — `current_state` (Block 8) gains the live-turn label; the report's
verdict line and "Where you'd be wrong / what to watch" reflect it:

- in-band + uptrend + **turn ✓** → `BUY THE DIP`
- in-band + uptrend + **not turned** → `WAIT` (basing; knife risk) — quote the **buy
  trigger** ("lift to ~₹X, or close back above EMA_N")
- in-band but **lifted past trigger near old high** → already bounced (`WATCH`)
- trigger unlearnable → say so plainly, low-confidence

**stock-screening** — the turn becomes a **required condition for the BUY tier** (the knife
gate). Stage C tiers change:

- `BUY THE DIP` now also requires **turn ✓** (on top of in-band + uptrend + live low above
  floor + `bounce@base` fair).
- New **`WAIT` / not-turned** tier: cleared everything *except* the turn — still in band,
  still falling or basing. The watchlist (re-screen next bar) instead of silently buying a
  knife.
- `WATCH`/already-bounced, `CAUTION`, `AVOID`, `SPECULATIVE`, `PATIENT` unchanged in
  meaning. A `PATIENT`/`SPECULATIVE` candidate still requires the turn to be a buy; without
  it, it drops to `WAIT`.
- Footer gains a **`turn`** column (`✓` + path that fired / `—` not yet / `n/a`
  unconfirmable) and the **trigger level** the not-yet names must reclaim.

### 4. Scope / code layout

- **pullback-finder/references/building-blocks.md:** extend Block 7 `signature` with the
  learned trigger fields; add **Block 8c `live_turn`**; wire the live-turn label into Block
  8 `current_state`.
- **pullback-finder/SKILL.md:** workflow steps (single + universe), output style (verdict +
  trigger in the report shape), hard rules (turn learned, unconfirmable→low-confidence).
- **stock-screening/references/screening-blocks.md:** Block A6 recipe calls `live_turn`;
  Block A8 report renderer adds the `turn` column + trigger level.
- **stock-screening/SKILL.md:** Stage B step, Stage C tiers (BUY gate + WAIT tier), output
  style (footer column + ranked-line trigger), the law (trigger is a learned pattern param),
  failure-handling table (unlearnable trigger row).
- Honors "**do not modify pullback-finder**" from stock-screening: screening pastes/composes
  the blocks, single source of truth in pullback-finder.

## Fixed-vs-learned ledger

| Quantity | Status |
|---|---|
| lift magnitude (`learned_lift`, own ATR) | **learned** per stock from winners |
| reclaim EMA (`learned_reclaim_ema`) | **learned** per stock (mode), `none` valid |
| turn lag (`learned_turn_lag`) | **learned** per stock |
| 3% hard stop | fixed — trader risk model (unchanged) |
| `H_base = 15` | fixed — cross-stock comparability ruler (unchanged) |
| up-thrust = close > prior bar high | structural definition (grammar), not a tuned constant |
| winner = recovered per Block 6 | structural definition (grammar) |

## Failure handling

| Situation | Behaviour |
|---|---|
| < 5 recovered events with an up-thrust | trigger unlearnable → `turn = unconfirmable, low-confidence`; never invent a threshold |
| No up-thrust after a winner's low (gap recovery) | drop that event from trigger learning; disclose dropped count |
| `live_low` is the last bar (fresh low) | `cur_lift ≈ 0` → not turned (knife) — exactly the case the gate catches |
| `learned_reclaim_ema = none` | union reduces to the lift path only; disclose |
| ATR warm-up / `atr_now` null | cannot compute `cur_lift` → low-confidence, disclose (reuses existing ATR warm-up handling) |

## Success criteria / verification

1. **Knife** (fresh low on the last bar): old skill → `BUY`; new skill → `WAIT` / not
   turned.
2. **Lifted matching its history** (`cur_lift ≥ learned_lift` or EMA reclaimed): → `BUY`
   with `turn ✓` and the path that fired shown.
3. **Thin history** (< 5 recovered with up-thrust): → `unconfirmable / low-confidence`, no
   invented threshold.
4. **Screener run on the 1h universe:** BUY count drops vs the pre-change run; every
   surviving BUY shows `turn ✓` + path; the new `WAIT` tier lists the not-yet names with
   their trigger level; report file (Block A8) carries the new column.
5. Every learned trigger value (`learned_lift`, `learned_reclaim_ema`, `learned_turn_lag`)
   is disclosed per stock in the output — no silent constant.

## Resolved questions

- Confirm logic: **union** (either path), report which fired.
- Aggregation: **median** lift, **mode** reclaim EMA — stated, tunable, disclosed.
- Trigger lives in **pullback-finder**; screening composes.
- Up-thrust primitive: **close > prior bar high**.

*Structural evidence, not financial advice.*
