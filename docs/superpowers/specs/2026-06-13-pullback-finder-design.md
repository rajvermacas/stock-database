# pullback-finder — Design Spec

**Date:** 2026-06-13
**Branch:** feature/claude-code-skills
**Status:** Approved design, pending implementation plan
**Work type:** Software — a Claude Code agent skill

## Problem

The trader wants to find pullbacks across the Parquet stock universe, and for a
named stock, by reading each stock's *own* historical data and pattern. A pullback
is not a fixed rule: in a bullish trend, a valid pullback must be recognized from
how *that specific stock* has pulled back before. So the skill must first learn an
individual stock's pullback definition from its history, then check whether the
current state matches that definition.

## Core Principle — grammar, not engine

Every stock's nature is different, so **static logic is rejected**. The skill does
NOT ship monolithic scripts that encode a fixed pullback pipeline. Instead it ships:

- a thin **reference** describing the Parquet schema and how to query it, and
- a **grammar of fundamental Polars building blocks** — small, documented,
  composable snippets.

The **agent writes and executes bespoke Polars on the fly for each stock**,
composing the building blocks like words into sentences. Every per-stock parameter
(pivot window, noise filter, depth/retrace bands, what counts as "extended") is
**derived from that stock's own data distribution**, never a global constant. Only
by composing fresh code per stock can each stock's characteristics be surfaced.

This mirrors the *spirit* of the existing `talk-to-parquet` skill (reference +
primitives, agent composes queries) but is written fresh and specialized for
pullback discovery. It does **not** depend on or reuse any existing skill —
existing skills may carry latent issues; this skill is fully standalone.

## Scope

- Pure price/volume technical analysis over `market-data/` Parquet. No fundamentals.
- **Timeframe is a required argument supplied by the user** — never assumed,
  never defaulted. Validate it; fail fast if absent or unsupported. Stored
  intervals `1d` and `1h` are read directly; other frames (e.g. `1wk`) are derived
  on the fly via Polars `group_by_dynamic` and disclosed as on-demand.
- Optional symbol argument:
  - **no symbol** → universe screener,
  - **symbol given** → single-stock report.
- Output is candidate discovery + labeling, not a full buy adjudication and not
  position sizing.

## The mechanism — how it finds historic pullbacks and patterns

The agent performs this workflow by composing building blocks into bespoke Polars
per stock. Every number is computed, never eyeballed or invented.

1. **Prep (chosen timeframe).** Read OHLCV price Parquet for the symbol; if the
   frame is not stored, derive bars via `group_by_dynamic`. Compute internally with
   Polars: EMAs 10/20/50/100/200, ATR(14), rolling highs/lows. Fully self-computed;
   no dependency on precalculated indicator files.
2. **Swing pivots (zigzag/fractal).** Swing high = bar's high is the max within ±k
   bars (k chosen for the stock); swing low symmetric. Filter micro-noise with a
   minimum inter-pivot move (ATR-relative). Result: an alternating pivot sequence
   L/H/L/H with timestamps and prices.
3. **Mark uptrend up-legs.** An up-leg = swing-low → swing-high inside HH/HL
   structure, confirmed by rising pivot-lows and price above a rising longer EMA.
   Only pullbacks inside uptrends count.
4. **Extract pullback events.** After an up-leg high `H`, the pullback is the
   decline to the next swing-low `L` **iff `L` holds above the prior higher-low**
   (structure intact = a pullback). If `L` breaks the higher-low it is a reversal,
   not a pullback — excluded, and logged as a failed outcome for the preceding leg.
5. **Measure each event (the "pattern").** All computed:
   - `depth_pct` = (H − L) / H
   - `retrace_pct` = (H − L) / (H − leg_start_low) — give-back of the up-leg
   - `anchor` — at `L`, the nearest structural reference: which EMA (within x·ATR),
     which horizontal support (a prior pivot cluster), or a rising trendline fit
     through previous swing-lows; record type + distance in ATR
   - `duration_bars` (H → L), volume dry-up flag, up-leg slope
   - **outcome** — forward-simulate from `L` in Polars: did price make a new high
     above `H` within a time-stop window (continuation success) before violating
     −X% / breaking the higher-low (fail)? Record success bool, forward MFE,
     bars-to-resume.
6. **Build the signature (aggregate the events).** `n_events`, median + IQR of
   depth / retrace / duration, `dominant_anchor` (most-frequent anchor type + its
   hold/success rate), continuation `success_rate`, survivor MFE, expectancy.
   This is the stock's own learned pullback definition.
7. **Classify current state (both-labeled).** Recompute current structure: in an
   uptrend now? latest high `H_now`, current price.
   - dipping, `current_depth` inside the historical depth IQR, tagging
     `dominant_anchor`, structure intact → **buyable-dip-now** (cite the resembling
     past events and their `success_rate`);
   - near `H_now`, extended from the anchor by ~ the historical pre-pullback run-up
     → **pullback-coming / wait**;
   - else **no-match**.

The "patterns" the trader sees are the matched historical events listed with dates,
so the resemblance is auditable.

## Skill contents

No monolithic scripts. The skill is reference material + a grammar:

- **`SKILL.md`** — methodology and how to wield the grammar. Spells out the
  workflow above as a process the agent performs by composing fresh Polars per
  stock, deriving every threshold from the stock itself. Hard rules: timeframe
  required; fail fast on missing symbol / insufficient history / stale data (quote
  and stop); thin `n_events` (e.g. < 5) → label **insufficient-history,
  low-confidence**, never fabricate; never a global magic number; every number
  computed; survivorship bias disclosed; read-only analysis.
- **`references/data.md`** — minimal: Parquet layout, OHLCV schema, intervals
  (`1d`/`1h` stored, others derived), `Asia/Kolkata` timezone-aware
  `trade_timestamp`, lazy `scan_parquet` idiom with predicate/projection pushdown.
- **`references/building-blocks.md`** — the grammar: small, documented, composable
  Polars snippets the agent adapts (not runs verbatim):
  - swing pivots / zigzag (fractal ±k, ATR-relative noise filter)
  - EMA / ATR / rolling-extreme expressions
  - up-leg detection (HH/HL + rising EMA posture)
  - pullback-event extraction (decline holding prior higher-low) + depth / retrace /
    anchor / duration measures
  - forward double-barrier outcome (new-high vs −X% / HL-break, MFE) as a forward
    Polars scan
  - per-stock aggregation → signature (median + IQR, dominant anchor, success_rate)
  - multi-symbol **gate** block (glob + `group_by`) for the cheap Stage-1 screen
- **`references/worked-example.md`** — ONE real stock strung end-to-end, showing the
  blocks composed into a "sentence." Illustrative proof of expressiveness, not the
  engine.

## Flow

- **Single symbol** (with required `--timeframe`): agent composes blocks → mines
  events → builds the signature with the stock's own bands → labels today → reports
  signature + matched past events (dates, auditable) + invalidation (prior
  higher-low) + caveats (sample size, freshness).
- **Screener**: agent runs the gate block once across the universe (uptrend +
  currently dipping/extended) to shrink it, then performs the bespoke per-stock deep
  analysis only on the handful of survivors. Output: ranked table — symbol, label,
  match quality, `success_rate`, `n_events`, typical vs current depth, anchor,
  invalidation.

## Failure handling / honesty

- Timeframe missing or unsupported → raise, stop.
- Missing symbol / insufficient history / stale data → quote the error, stop. No
  partial analysis, no fabricated numbers.
- `n_events` below the minimum → explicit low-confidence label, never a guess.
- **Pattern** thresholds (pivot window, noise filter, depth/retrace/extension bands)
  are derived from the stock's own distribution and disclosed; no silent global
  defaults or fallbacks (per project fail-fast rule). The **risk** barriers used in
  the outcome simulation (hard stop %, time-stop horizon) are the trader's fixed
  risk model — explicit, documented inputs, not pattern logic — and are stated, not
  hidden. These are distinct: pattern bands are learned per stock; risk barriers are
  the trader's constants.
- Survivorship bias (universe selected today) disclosed.

## Constraints (project rules)

- Reference/doc files under 800 lines; split if larger.
- Polars lazy scans with predicate/projection pushdown; one final `collect()` per
  question; expressions over Python loops.
- No reuse of other skills' code; standalone.

## Build phases

1. `references/data.md` — schema + scan idioms, verified against real files.
2. `references/building-blocks.md` — the grammar; each block validated by running it
   on a couple of real symbols on the fly.
3. `SKILL.md` — methodology tying the blocks into the per-stock workflow and the
   both-labeled output, with the hard rules.
4. `references/worked-example.md` — agent executes the full grammar on one real
   stock end-to-end (proof the grammar is expressive enough); screener gate
   validated across the universe.

## Success criteria

- For a named symbol + timeframe, the agent composes Polars on the fly to produce a
  signature whose listed historical pullback events are auditable against the real
  chart, plus a current label (buyable-dip-now / pullback-coming / no-match) with
  cited evidence.
- The screener gate returns only stocks currently in an uptrend and dipping or
  extended, and deep analysis runs only on those.
- No static per-stock thresholds appear anywhere; every band is derived from the
  stock's own data and disclosed.
- Fail-fast behavior holds for missing timeframe, missing symbol, thin history, and
  stale data.
