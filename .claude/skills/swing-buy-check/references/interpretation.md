# Interpretation Guide

How to read the fact JSON from `evaluate.py` and grade what it shows. The script
measures; this file tells you what the measurements mean and where they mislead.

## Setup taxonomy

| Candidate | What the script checked | What YOU still verify |
|---|---|---|
| `breakout` | Close crossed a multi-touch level within last 5 bars; distance past it in ATRs; rel volume on the break bar | Volume ≥ ~1.5× on break; `still_enterable` true (≤1 ATR past level); base behind the break (contraction ratio < 1 is supporting evidence) |
| `ema_pullback` | Price within 0.75 ATR of a respected (hold-rate ≥ 0.6), rising EMA | Daily phase is markup at some scale; 1h `recent_labels` show a higher low forming at the tag, not freefall through it |
| `support_bounce` | Price within 0.75 ATR above a multi-touch support; last-bar close location | `last_bar_close_location` ≥ ~0.6 and/or up close = reactive bar; level's `last_touch` recent enough to matter |

## Grade rubric

Start at B, then adjust:

- **A** — setup type's verification points all confirmed, weekly and daily aligned,
  1h structure agrees, stop anchor sits directly behind a level or respected EMA,
  headroom ≥ 10% with historical up-leg median supporting a 12%+ run.
- **B** — setup valid but one supporting element is weak (volume unconvincing,
  headroom thin, 1h mixed).
- **C** — setup technically present but counter-trend vs weekly, or multiple weak
  elements. Counter-trend ALWAYS caps at C.

Grade is evidence quality, not conviction. Say which element set the grade.

## Reading structure correctly

- **Phase labels lag by design.** Pivots need `window` future bars to confirm, so a
  strong current leg is invisible in swing labels. ALWAYS read `unconfirmed_leg`:
  35 bars and +77% since the last pivot low means the "correction" label describes
  ancient history. Scales disagree often — scale_3 reacts fast, scale_10 is the
  macro skeleton. Name the disagreement instead of averaging it.
- **`contraction.ratio`** < 0.8 = coiling (base-building evidence); > 1.2 = expanding
  swings (climax or volatility regime change).
- **`pivot_lines`**: both lines positive slope with r2 > 0.8 = rising channel;
  highs flat + lows rising = ascending coil; converging slopes = triangle. These are
  fit statistics — name the geometry only when r2 supports it.
- **`up_leg_stats`** answer "can this stock plausibly run 12–15% inside the holding
  window?" — median up-leg below ~10% means the 15% aspiration relies on an outlier.

## Reading the stop facts

- `noise.median_daily_dip_percent` × 1.5 must fit inside 3% for `stop_covers_noise`.
  A failure means ordinary intraday noise will hit the stop regardless of setup
  quality — this is the most common and most legitimate disqualifier.
- `stop_anchors.anchors_within_band` lists 1h swing lows inside the 3% band. The
  invalidation you quote should be the highest anchor that sits behind structure,
  minus nothing — the user's stop math is theirs; you supply the structural level.
- No anchor + clean setup = "wait for an entry near structure", not "avoid".

## Respected EMAs

`respect.per_ema` shows touch-and-hold counts per EMA over ~6 months. The EMAs in
`respected` are the ones THIS stock actually rides — use them, not folklore about
which EMA "should" matter. Zero respected EMAs is itself information: the stock
doesn't trade technically around EMAs (common in low-liquidity names or after
regime changes), so EMA-pullback logic is weak evidence for it.

## Reading analog statistics

The analog block answers: when charts looked geometrically like this one, what
happened to a trader entering at close with a hard 3% stop and a 15-bar time
stop? Read it against the user's economics, not in isolation:

- **Breakeven floor is 16.7%** win rate (3% stop, 15% average winner). Quote
  `stop_out_rate_percent` against it: 70% stop-out = 30% survival — comfortably
  above floor IF survivor MFE is large. 90%+ stop-out is near-unsalvageable.
- **`mechanical_expectancy_percent`** is the expectancy of the dumb baseline
  policy (stop −3%, exit day 15). Negative = entering here lost money on
  average historically. Positive ≥ +1% = genuinely favorable geometry.
- **`stopped` is path-based**: a neighbor counts as stopped if low ever touched
  −3%, even if it recovered later. That IS the user's reality — never reframe a
  stopped-but-recovered neighbor as a win.
- **Small survivor counts** (< 5) make MFE medians anecdote, not statistics —
  say so explicitly.
- Statistical similarity ≠ contextual similarity: scan `nearest_examples`
  dates — neighbors clustered in one market regime (e.g. a crash month) deserve
  a disclosed discount.

## Reading market context

Regime is **context that caps grades, never a gate**. Indices: ^NSEI (large
caps), ^CRSLDX (Nifty 500 — closest proxy for this universe), ^NSEMDCP50
(midcaps). Breadth comes from the stock universe itself.

- All three indices below 200EMA with falling breadth → cap any setup at C and
  say the market is the reason.
- Split regime (e.g. large caps weak, midcaps strong) is common — weigh the
  index that matches the stock's size segment, and say which one you weighed.
- `pct_within_5pct_of_365d_high` is the sharpest breadth number: > 25% means
  leaders are plentiful; < 10% means strength is narrow and breakouts fail more.
- No NSE smallcap index exists on Yahoo — for smallcaps, lean on breadth and
  ^NSEMDCP50 and disclose the gap.

## Secondary context

`secondary_context` (RSI, ADX, relative volume, 365d-high distance) is context,
never a vote. Use it to color the narrative ("trend one-sided, ADX 56") and to
catch blow-off conditions, not to overrule structure.
