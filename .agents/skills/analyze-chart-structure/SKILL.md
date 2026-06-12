---
name: analyze-chart-structure
description: Classify generic stock-chart structure and named structural patterns from local OHLCV data, with evidence, contradictions, developing/confirmed/invalidated status, confidence, confirmation, and invalidation levels. Use for chart-pattern identification, swing structure, support/resistance, channels, ranges, triangles, double tops/bottoms, head-and-shoulders, and explicitly requested same-pattern historical outcomes.
---

# Analyze Chart Structure

Follow every `talk-to-stock-data` rule. Require one symbol and timeframe. Use explicit
dates or an explicit period count when supplied; otherwise use and disclose the latest
120 completed periods. Acquire missing requested stock data through that skill.

Run `scripts/analyze_structure.py`, then report generic structure before ranked named
patterns. Explain evidence and contradictions. State that confidence is not probability.
Never call a developing pattern confirmed.

Read `references/pattern-rules.md` when explaining classification rules. Run historical
same-pattern analysis only when the user explicitly requests it.
