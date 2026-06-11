---
name: find-similar-stock-setups
description: Find same-stock historical daily setups similar to a symbol's latest 10-day chart using hierarchical chart, pace, candle, volume, trend-context, and momentum distances. Use for historical analogs, similar chart setups, matching past scenarios, or subsequent outcomes for one stock.
---

# Find Similar Stock Setups

Find up to 200 non-overlapping historical setups from the same stock.

## Workflow

1. Follow `talk-to-stock-data` data rules.
2. Require one Yahoo-style symbol.
3. Run from repository root:

```bash
python .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  --symbol CHENNPETRO.NS \
  --prices-root market-data/prices \
  --indicators-root market-data/indicators
```

4. Present latest setup dates, rejection counts, match count, closest matches, combined
   distance, subgroup distances, and aggregate future outcomes.

## Fixed Semantics

- Compare latest 10-day daily setup only against same stock's history.
- Preserve direction, pace, chart shape, candles, volatility, volume, trend context, and
  momentum through separate subgroup distances.
- Use balanced combined distance across subgroups.
- Enforce hard context gates and non-overlapping historical matches.
- Return all available matches when fewer than 200 survive.
- Exclude windows containing daily close moves above 40%.
- Use no recency weighting.

Never silently relax gates, permit overlap, or invent missing data.

Similarity distance is not a probability. Prices and indicators are raw, unadjusted;
corporate actions may distort results.
