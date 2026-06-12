# Chart Structure Analysis Skill Design

## Goal

Create a project-local Codex skill that analyzes a requested stock chart using the
repository's OHLCV data and reports both:

- generic market structure, including swing sequence, trend, range/channel,
  support/resistance, and breakout state;
- ranked named chart patterns with evidence, contradictions, status, confidence,
  confirmation level, and invalidation level.

Run same-pattern historical outcome analysis only when the user explicitly requests it.

## Scope

Create the skill at:

```text
.agents/skills/analyze-chart-structure/
```

Initially support:

- double top and double bottom;
- head and shoulders and inverse head and shoulders;
- ascending, descending, and symmetrical triangles;
- ascending and descending channels;
- horizontal ranges;
- support/resistance breakouts and breakdowns.

Do not generate trading recommendations or silently treat developing patterns as
confirmed.

## Skill Architecture

```text
analyze-chart-structure/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   └── pattern-rules.md
└── scripts/
    └── analyze_structure.py
```

`SKILL.md` coordinates the workflow and requires compliance with
`talk-to-stock-data`. It explains when to run the bundled script, how to interpret its
output, and when historical analysis is permitted.

`scripts/analyze_structure.py` performs deterministic structural analysis with Polars
and emits structured JSON. It loads prices through
`.agents/skills/talk-to-stock-data/scripts/stock_frame.py`.

`references/pattern-rules.md` defines pattern evidence, contradictions, confirmation,
invalidation, and scoring semantics without bloating `SKILL.md`.

`agents/openai.yaml` provides discovery metadata and a default prompt.

## Inputs

Require:

- one Yahoo-style symbol;
- requested timeframe;
- analysis window, expressed as dates or a number of periods.

When the user supplies dates, use those dates exactly. When the user does not specify a
window, use the latest 120 completed periods and disclose it. Reject empty symbols,
ambiguous timeframes, windows too short for structural analysis, and unavailable data.

Use an exact stored timeframe when available. Otherwise derive a compatible timeframe
through `stock_frame.py`. Report requested timeframe, source timeframe, and whether the
result was derived.

## Data And Calculation Rules

- Follow all `talk-to-stock-data` rules.
- Use Polars for market-data reads, transformations, aggregations, and calculations.
- Keep the query lazy through one final collection.
- Use adjusted OHLC prices and Yahoo-provided volume.
- Detect swings with volatility-adjusted prominence and minimum separation.
- Normalize tolerances by ATR or local price percentage so rules work across price
  levels and timeframes.
- Keep pattern thresholds explicit and deterministic.
- Fail clearly when insufficient observations or volatility context make classification
  unreliable.

No function may exceed 80 lines and no file may exceed 800 lines.

## Analysis Pipeline

1. Resolve and load the requested timeframe and window.
2. Calculate required on-demand structural features, including ATR when needed.
3. Detect significant swing highs and swing lows.
4. Classify generic structure:
   - higher highs/higher lows, lower highs/lower lows, mixed, or insufficient;
   - trend direction and strength;
   - channel or horizontal range;
   - nearest support and resistance;
   - breakout, breakdown, retest, rejection, or no-break state.
5. Evaluate all supported named-pattern rules.
6. Rank applicable patterns by deterministic confidence score.
7. Emit structured evidence, contradictions, status, and price levels.
8. If explicitly requested, evaluate independent historical occurrences matching the
   selected pattern's structural rules and summarize subsequent outcomes.

## Pattern Classification

Each candidate pattern must include:

- `name`;
- `confidence`, from 0 to 1;
- `status`: `developing`, `confirmed`, or `invalidated`;
- `evidence`;
- `contradictions`;
- `confirmation_level`;
- `invalidation_level`.

Confidence measures rule agreement, not probability of future performance.

A pattern is:

- `developing` when its required structural pivots exist but confirmation has not
  occurred;
- `confirmed` only after its defined confirmation event occurs;
- `invalidated` when price violates its structural invalidation rule.

Do not report a named pattern when required pivots are absent. Report competing
interpretations when their scores are close, and state why classification is ambiguous.

## Script Output

Emit JSON with this conceptual shape:

```json
{
  "data": {
    "symbol": "SUNFLAG.NS",
    "requested_interval": "1h",
    "source_interval": "1h",
    "derived": false,
    "start": "2026-06-05T09:15:00+05:30",
    "end": "2026-06-12T15:15:00+05:30",
    "observations": 42
  },
  "structure": {
    "swing_sequence": "lower-highs-lower-lows",
    "trend": "bearish",
    "formation": "descending-channel",
    "support": [],
    "resistance": [],
    "breakout_state": "no-break"
  },
  "patterns": [],
  "warnings": []
}
```

Use clear exceptions and a nonzero exit code for invalid inputs, unavailable data, or
insufficient history. Log detailed diagnostics through the repository's logging
conventions without polluting JSON stdout.

## Historical Same-Pattern Outcomes

Do not run historical outcome analysis by default.

When explicitly requested:

- use the selected pattern's structural rules rather than generic path similarity;
- use the current setup length unless the user specifies another length;
- exclude overlapping occurrences;
- disclose thresholds and occurrence count;
- measure subsequent outcomes over user-supplied horizons, or 5, 10, and 20 periods
  when none are supplied, and disclose the selected horizons;
- distinguish pattern confirmation from future price outcome;
- warn when the sample is too small for strong conclusions.

## User-Facing Output

Present:

1. generic structure classification;
2. ranked named patterns;
3. evidence and contradictory evidence;
4. pattern status;
5. confirmation and invalidation levels;
6. requested/source timeframe and analyzed dates;
7. assumptions and limitations.

Only include historical occurrence tables and outcome summaries when explicitly
requested.

## Verification

Add focused automated tests using synthetic OHLCV fixtures for:

- each supported named pattern;
- generic uptrend, downtrend, channel, and range structures;
- developing, confirmed, and invalidated states;
- ambiguous competing patterns;
- insufficient history and malformed inputs;
- explicit-only historical analysis behavior.

Run a real-data smoke test for `SUNFLAG.NS` on the hourly June 5, 2026 through latest
window. Verify that the skill reports bearish generic structure and treats any reversal
pattern as developing rather than confirmed.

Validate the skill with `quick_validate.py`, verify every added file remains below 800
lines, and verify every function remains below 80 lines.

## Success Criteria

- The skill is discoverable and passes skill validation.
- Repeated analysis of identical data produces identical structural results.
- Generic structure and named-pattern evidence are both reported.
- Developing patterns are never mislabeled as confirmed.
- Historical same-pattern analysis runs only on explicit request.
- Output discloses timeframe resolution, dates, thresholds, ambiguity, and insufficient
  data.
