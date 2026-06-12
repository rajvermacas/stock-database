# Backtest Findings (phase 4)

Generated 2026-06-12 by `scripts/backtest.py` over 54,075 (symbol, day) rows,
2020-03-27 → 2026-05-22, 169 stocks (indices excluded). Risk model: enter at
close, hard −3% stop on future lows, 15-bar time stop. Regenerate any time:

```
.venv/bin/python .claude/skills/swing-buy-check/scripts/backtest.py
```

## Results

| Group | n | Stop-out | Expectancy | Survivor med. MFE |
|---|---|---|---|---|
| Baseline (all days) | 54,075 | 69.6% | **+0.93%** | 12.5% |
| Breakout | 1,223 | 70.2% | +0.82% | 12.6% |
| Breakout, veto passed | 640 | 69.2% | +0.64% | 11.4% |
| Breakout, veto failed | 583 | 71.4% | +1.03% | 13.8% |
| EMA pullback | 11,352 | 70.2% | +0.51% | 11.3% |
| Support bounce | 899 | 67.6% | +0.61% | 11.0% |
| Extended days (>2 ATR above EMA20) | 4,445 | 71.6% | **+1.34%** | 14.0% |
| Non-extended days | 49,630 | 69.4% | +0.90% | 12.4% |

## What this means for verdicts

1. **Setup labels alone carry no edge.** Every setup proxy underperforms the
   all-days baseline. A verdict must NEVER claim a setup type itself is
   favorable — selection quality has to come from the analog stats, structure
   confluence, and market context, and grades should say so.
2. **The 3% stop dominates everything.** ~70% stop-out regardless of entry
   type. Stop-survival facts (1h noise, anchors) are the highest-leverage part
   of the evaluation — weight them above setup classification.
3. **Extension-veto evidence is INVERTED under mechanical exits.** Extended
   stocks kept running on average (momentum continuation). The veto stays —
   it reflects the user's entries-at-structure style and caps variance, not
   expectancy — but verdicts must not claim it is profit-protective. Frame it
   as: "extended = higher stop-out odds and no structural stop, hence wait",
   never "extended = lower returns".
4. **Win-rate reality check.** ~30% of entries survive the stop; survivors'
   median MFE ≈ 12% (MFE is the best price seen, not a realized exit). The
   user's 20%-win/15%-winner model is at the optimistic edge of what the data
   supports — say so when expectancy math comes up.

## Caveats (always disclose when citing)

- **Survivorship bias**: the universe is symbols selected TODAY (momentum
  tilted), so baseline and extended-day numbers are inflated. Relative
  comparisons are more trustworthy than absolute expectancies.
- Setups are **vectorized proxies**, not the live classifier (rolling-extreme
  levels instead of pivot clusters; no volume confirmation, no RS filter, no
  respected-EMA condition). The live classifier is stricter; proxies bound it
  from below.
- No costs, no slippage, no gap-through-stop modelling (losses capped at
  exactly −3%; real losses run worse on gaps).
- Single overlapping-window sample; entries on consecutive days are correlated.
