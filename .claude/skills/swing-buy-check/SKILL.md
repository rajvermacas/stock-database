---
name: swing-buy-check
description: Decide whether a stock is a swing-trade buy candidate using structural technical analysis (chart structure, support/resistance, EMAs, price action) over the project's Parquet market data. Use when the user asks "should I buy X", "is X a buy", "check X for entry", or wants a setup/entry evaluation for a symbol.
---

# Swing Buy Check

Evaluate one stock as a swing-trade entry candidate for a trader with a **hard 3%
stop loss**, soft ~15% profit aspiration, and a holding period of days to 2–3 weeks.
Scripts compute every number; you interpret and author the verdict. You never
compute, estimate, or invent a number.

## Workflow

1. Run the fact script from the repository root:

   ```
   .venv/bin/python .claude/skills/swing-buy-check/scripts/evaluate.py SYMBOL
   ```

   Stdout is one JSON document of measurements (weekly, daily, hourly-entry,
   setup candidates, vetoes, analogs, market context). Stderr is the log.
   Non-zero exit = data problem: report the error verbatim and stop. Never
   produce a verdict from partial data. One recoverable case: if the error
   names a missing/stale index file (^NSEI, ^CRSLDX, ^NSEMDCP50), refresh it
   and rerun:

   ```
   .venv/bin/stock-data --config config/stock-data-1d.toml update-symbol '^NSEI'
   ```

2. Read `references/interpretation.md` for the setup taxonomy, grade rubric, and
   phase-label caveats before authoring a verdict. Read
   `references/backtest-findings.md` for what the taxonomy is and is not worth
   in this universe — setup labels alone carry no edge; stop-survival and
   analog stats are the highest-leverage evidence.

3. Adjudicate. The script emits candidates and evidence, not conclusions:
   - Zero candidates → verdict is "no setup"; say what is missing.
   - Multiple candidates → pick the dominant frame and explain why.
   - Phase labels lag — always cross-check `unconfirmed_leg` (move since the
     last confirmed pivot) before trusting a phase label.
   - Weekly context arbitrates conflicts: a daily setup against weekly
     structure is counter-trend and its grade is capped at C.

4. Apply vetoes mechanically — they are not negotiable judgment calls:
   - `extension_veto` true → verdict at most **wait** (state what a valid
     pullback would look like).
   - `stop_survival_veto` true → verdict at most **wait**; a 3% stop cannot be
     placed structurally, and that alone disqualifies entry today.

## Verdict format

```
Verdict: buy candidate | watchlist | wait | no setup / avoid
Setup: <type or "none">, grade A/B/C (rubric in references/interpretation.md)
Timeframe alignment: weekly <read> | daily <read> | 1h <read>
Invalidation: <price> — <structural reason, from script facts>
Stop check: 3% stop vs <median_daily_dip_percent>% median daily noise; anchor at <price or none>
Headroom: <nearest resistance + distance, or "none overhead">; historical up-legs median <x>%
Analogs: n=<n>, stop-out <x>%, survivor median MFE <x>%, mechanical expectancy <x>%/trade
Market: <index regime one-liner> | breadth <pct_above_ema_200>% above 200EMA
Caveats: <data freshness, missing evidence, lagging labels, anything excluded>
```

Every number in the verdict must appear in the script JSON. Cite the structural
reason for the invalidation level (e.g. "1h higher low at 1058"), never a round
number or a bare percentage.

## Hard rules

- No arithmetic on raw price rows; no eyeballing patterns from data dumps.
- A "buy candidate" verdict requires: at least one setup candidate, zero vetoes,
  AND a structural stop anchor inside the 3% band (`anchor_exists` true).
- Script exception → quote it, stop. No fallback analysis, no partial verdict.
- Always disclose: weekly indicators are calculated on demand from daily closes;
  daily/hourly indicators are precalculated at their stored intervals.
- This is structural evidence, not financial advice — state assumptions, never
  certainty about outcomes.
