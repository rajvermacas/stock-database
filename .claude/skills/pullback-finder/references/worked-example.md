# Worked Example — ABSLAMC.NS, 1d

One stock strung end-to-end to show the grammar composed into a sentence. This is
illustrative, NOT the engine — for another stock you would pick a different `k` and
read different bands. Run from repo root with `.venv/bin/python`.

```python
import polars as pl
# Compose Blocks 1-8c from building-blocks.md:
#   df = add_indicators(load("ABSLAMC.NS", "1d"))
#   zz = zigzag(fractal_flags(df, k=5))
#   events = pullback_events(zz)
#   for e in events:
#       e.update(anchor_for_low(df, e["low_ts"]))
#       e.update(outcome(df, e))          # trader's risk model: stop_pct=0.03, horizon=15
#   sig = signature(events)
#   trigger = learn_turn_trigger(df, events)          # Block 7b
#   state = current_state(df, zz, sig, trigger=trigger)   # Blocks 8 + 8a/8b/8c inside
```

The merge step matters: each event dict from `pullback_events` is enriched in place
with the `anchor` (Block 5) and the `resolved`/`success`/`mfe_pct` outcome keys
(Block 6) BEFORE `signature` (Block 7) aggregates them — `signature` reads those
columns.

## What it produced (real run, 2026-07-01 data)

- 30 HL-holding pullback events over 1,168 daily bars.
- Signature:
  - `n_events`: 30, `confidence`: ok
  - `depth_median`: 7.89
  - `depth_iqr`: [5.90, 9.59]  ← ABSLAMC's own pullback band; `depth_p90`: 11.95 (deep edge)
  - `dominant_anchor`: ['ema_20']
  - `success_rate`: 0.73
  - `survivor_mfe_median`: 12.62
- Learned turn (7b): `learned_lift` 1.89 ATR, `learned_reclaim_ema` ema_20, lag ~3 bars.
- Current state: live swing high ₹1,224.9 (2026-06-22, a confirmed pivot —
  `ref_high_confirmed: True`), live low ₹1,122.9 → `dip_depth` 8.33% (inside its
  5.90→11.95 buy window), `rebound_frac` 0.21 (not late), structure intact, and the
  dip genuinely reclaimed its learned ema_20 → **`label: buy-the-dip-turned`**
  (`turn.path: ['reclaim']`). Stops: near-term ₹1,122.9 (live higher-low),
  structural floor ₹979.1.
- Contrast (same day, APARINDS.NS): the last CONFIRMED high was ₹12,327 (Apr 21) but
  the live swing high recovered by Block 8a was ₹17,157 (Jun 24, edge zone) — dip
  depth 15.5%, in band, but a fresh low with `cur_lift` 0.13 vs learned 1.71 →
  `wait-not-turned`, buy trigger quoted at ₹15,183 (ema_20 reclaim). Under the old
  confirmed-pivot depth this stock read as −18% "near high / wait" — the exact bug
  Blocks 8a/8b now prevent.

## Reading it

- The depth band [5.90 → 11.95 P90] is ABSLAMC's own — a different stock will differ.
  There is no global threshold.
- Band membership came from `dip_depth` (the live LOW, wick-to-wick) — NOT today's
  close: the close has already lifted off the low (that lift is the turn), so a
  close-based gate would have mislabeled this exact buy as "wait".
- `dominant_anchor` ema_20 means this stock's dips most often tag the 20 EMA; use
  that, not folklore about which EMA "should" matter.
- The current label plus the listed matched events (their dates) are the audit trail.
- Caveat: the universe is survivor-selected; treat the 0.73 success_rate as evidence,
  not a guarantee.
