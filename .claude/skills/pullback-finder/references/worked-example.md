# Worked Example — ABSLAMC.NS, 1d

One stock strung end-to-end to show the grammar composed into a sentence. This is
illustrative, NOT the engine — for another stock you would pick a different `k` and
read different bands. Run from repo root with `.venv/bin/python`.

```python
import polars as pl
# Compose Blocks 1-8 from building-blocks.md:
#   df = add_indicators(load("ABSLAMC.NS", "1d"))
#   zz = zigzag(fractal_flags(df, k=5))
#   events = pullback_events(zz)
#   for e in events:
#       e.update(anchor_for_low(df, e["low_ts"]))
#       e.update(outcome(df, e))          # trader's risk model: stop_pct=0.03, horizon=15
#   sig = signature(events)
#   state = current_state(df, zz, sig)
```

The merge step matters: each event dict from `pullback_events` is enriched in place
with the `anchor` (Block 5) and the `resolved`/`success`/`mfe_pct` outcome keys
(Block 6) BEFORE `signature` (Block 7) aggregates them — `signature` reads those
columns.

## What it produced (real run, 2026-06-13)

- 10 HL-holding pullback events, depths 4.3%–17.1%.
- Signature:
  - `n_events`: 10, `confidence`: ok
  - `depth_median`: 9.46
  - `depth_iqr`: [6.99, 11.07]  ← ABSLAMC's own pullback band
  - `dominant_anchor`: ['ema_20']
  - `success_rate`: 0.8
  - `survivor_mfe_median`: 17.53
- Current state (latest bar): `{'label': 'pullback-coming/wait', 'cur_depth': -1.07,
  'why': 'near high, shallower than typical band'}` — price sits at/above the last
  confirmed swing high (negative current depth), i.e. not yet in its typical
  6.99–11.07% dip band, so the label is wait-for-the-dip rather than buyable-now.

## Reading it

- The depth IQR [6.99, 11.07] is ABSLAMC's own pullback band — a different stock will
  differ. There is no global threshold.
- `dominant_anchor` ema_20 means this stock's dips most often tag the 20 EMA; use
  that, not folklore about which EMA "should" matter.
- The current label plus the listed matched events (their dates) are the audit trail.
- Caveat: 381 daily bars is short and the universe is survivor-selected; treat the
  0.8 success_rate as low-sample evidence, not a guarantee.
