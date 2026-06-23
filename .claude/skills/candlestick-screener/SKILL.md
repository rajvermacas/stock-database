---
name: candlestick-screener
description: Screen the whole Parquet stock universe for ANY candlestick pattern the user names or describes, on a user-supplied timeframe. The pattern detector is built on demand from a candle-anatomy grammar — there is no fixed pattern list. Reports (A) a universe ranking of stocks by next-bar win-rate after the pattern and (B) the stocks printing the pattern on the latest bar, each annotated with its own historical reliability. Use when the user asks to scan/screen the universe for a candlestick pattern (three white soldiers, bullish engulfing, hammer, morning star, …) or for any custom multi-candle setup described in words.
---

# Candlestick Screener

Screen the whole universe for **any** candlestick pattern, on a **user-supplied
timeframe**, and report two things:

- **Section A — Edge study:** every stock ranked by what happens the **next bar**
  after the pattern completes (win % = profit vs loss, average & median move),
  judged against each stock's *own* baseline and the universe baseline, gated by a
  minimum occurrence count so the ranking is not single-sample noise.
- **Section B — Live signals:** the stocks whose **latest bar** completes the pattern
  right now, each annotated with that stock's historical reliability from Section A.

This skill is a **grammar, not a catalog.** It contains no hardcoded list of patterns.
Whatever pattern the user names ("three black crows") or describes ("a long red candle,
then a doji, then a long green that closes above the first candle's midpoint"), you
build its detector at run time from the candle primitives in
`references/candle-grammar.md`, then run the universe screen in
`references/screen-procedure.md`. **Read both reference files before running anything.**
Read-only against `market-data/`.

## Required input

- **Pattern** — a name or a free-text description. Mandatory. If the request is
  ambiguous (e.g. "strong bullish candles"), translate it into an explicit definition
  and **state that definition in the report**; if it is uninterpretable, name what is
  unclear and ask.
- **Timeframe** — mandatory and user-supplied. **Never assume or default it.** If the
  user did not give one, ask before doing anything. Resolution rules in
  `references/screen-procedure.md` (Step 0): `1d`/`1h` are on disk; coarser intervals
  are derived from `1d`; finer non-stored intervals are fetched. Disclose which.
- **Scope is the whole universe** (`market-data/prices/<interval>/*.parquet`). For a
  single named symbol, the same grammar applies — just scope the scan to that file.

## Data layout

```
market-data/prices/<interval>/<SYMBOL>.parquet   # OHLCV per symbol, one file each
market-data/metadata/symbols.csv                 # universe list
```

Schema: `symbol, trade_timestamp (tz-aware Asia/Kolkata), open, high, low, close, volume`.
Stored intervals: `1d`, `1h`. Prices are corporate-action adjusted. Run everything from
the repo root with `.venv/bin/python` (Polars). See
`../pullback-finder/references/data.md` for the full data + fetching reference.

## Workflow

1. **Translate the pattern → a Polars boolean mask** using `references/candle-grammar.md`.
   Decide the pattern's directional intent (bullish ⇒ a "win" is the next bar *up*;
   bearish ⇒ next bar *down*). For named patterns use the standard definition; when the
   strict definition risks being too rare, follow the strictness ladder (offer a
   disclosed relaxed variant). **Always report the exact mask you used, in words.**
2. **Run the screen** with `references/screen-procedure.md`: one Polars pass computes the
   per-stock table once; Section A ranks it; Section B filters the live signals. Apply
   the minimum-occurrence gate (adaptive) and compute the baselines.
3. **Report** both sections in chat with the mandatory disclosures (below). Never write
   scratch files to the repo.

## Non-negotiable rules

- **Fail fast, no fallbacks** (per the project's global rules). Missing timeframe → ask.
  Timeframe unresolvable → clear error, stop. Pattern uninterpretable → name the
  ambiguity. Zero occurrences universe-wide → report that plainly. Never silently
  shorten the range, substitute a symbol, resample indicators, or invent data.
- **Sort before any lag.** A glob scan is *not* globally sorted; you MUST
  `.sort("symbol", "trade_timestamp")` before any `shift(...).over("symbol")`, or every
  pattern and forward-return is wrong. This is the single most important correctness rule.
- **Statistical honesty.** A 100% win-rate on n=1 is noise, not an edge. Enforce the
  minimum-occurrence gate, always show the universe baseline and the pooled win-rate for
  context, and fall back to pooled-only reporting when the pattern is too rare per stock
  to rank (this is expected for strict definitions — see the grammar's strictness ladder).
- **Compute on demand.** Patterns and forward returns are computed from OHLC at run time;
  state this. Never use the precalculated indicator files for pattern logic.

## Output contract

Report with every screen:

- the pattern, **the exact definition/mask used**, and its directional intent;
- requested timeframe, the source interval, and whether it was on-disk / derived / fetched;
- universe size scanned and the analyzed date range;
- the outcome definition (next-bar close-to-close return; horizon if not 1);
- the minimum-occurrence threshold and how many stocks qualified;
- the **universe baseline** next-bar win-rate and the **pooled** pattern win-rate;
- Section A: a concise top-N ranking table (never a full dump);
- Section B: the live-signal table with per-stock historical reliability and confidence flags;
- exclusions (insufficient lookback for the pattern, or no forward bar yet).
