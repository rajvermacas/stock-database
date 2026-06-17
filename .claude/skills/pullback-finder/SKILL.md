---
name: pullback-finder
description: Find pullbacks in the Parquet stock universe (or for one named symbol) by learning each stock's OWN pullback signature from its history, then labeling its current state. Use when the user asks to screen for pullbacks, "is X pulling back / in a buyable dip", or to study how a stock pulls back. Requires a user-supplied timeframe.
---

# Pullback Finder

Find pullbacks by reading each stock's own history. A pullback is NOT a fixed rule:
in a bullish trend a valid pullback is recognized from how THAT stock has pulled back
before. So first learn the stock's own pullback signature from its data, then check
whether the current state matches it.

This skill is a **grammar, not an engine**. It ships Polars building blocks and a
schema reference. YOU write and run bespoke Polars on the fly for each stock,
composing the blocks like words into sentences. Static, one-size pipelines are
wrong — every stock's nature differs.

## Required input

- **Timeframe is mandatory and user-supplied.** Never assume or default it. If the
  user did not give one, ask before doing anything. ANY Yahoo interval is allowed
  (`1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo`), so the trader can zoom in. Only
  `1d` and `1h` are on disk; for anything else, if the data is missing **fetch it**
  via the project pipeline (`references/data.md` → "Fetching a missing timeframe",
  which uses COMMANDS.md). Fine intraday intervals have short Yahoo history → few
  events → expect the low-confidence rule to fire; disclose it.
- Symbol is optional: none → universe screener; symbol given → single-stock report.

## How to use the grammar

1. Read `references/data.md` for schema and the lazy-scan idiom.
2. Read `references/building-blocks.md` — the blocks. Adapt every parameter (`k`,
   noise filter, depth bands) to the stock from its own data; never hardcode a
   global value.
3. See `references/worked-example.md` for one stock strung end-to-end.

## Workflow — single symbol

0. **Resolve the data** for the requested interval: if
   `market-data/prices/<interval>/<SYMBOL>.parquet` is missing, fetch it first
   (`references/data.md` → "Fetching a missing timeframe"); respect the Yahoo
   history caps and fail fast on a failed download.
1. `load` → `add_indicators` (Block 1). Check `df.height`; if too short to warm the
   EMAs you use, say so.
2. `fractal_flags` → `zigzag` (Blocks 2–3); pick `k` from the stock's choppiness.
3. `pullback_events` (Block 4): keep HL-holding dips; reversals are logged failures.
4. For each event: `anchor_for_low` (5) + `outcome` (6).
5. `signature` (7): the stock's own depth band, dominant anchor, success rate. Then
   `learn_turn_trigger` (7b): the stock's learned rebound trigger (`learned_lift` in its own
   ATR, `learned_reclaim_ema`, `learned_turn_lag`) from its winning dips.
6. `current_state` (8) — pass `trigger=` so it runs `live_turn` (8c) internally. Read the
   label: `buy-the-dip-turned` (turned — a buy), `wait-not-turned` (in band, no turn yet —
   the falling-knife hold), `buyable-dip-now/turn-unconfirmable` (trigger unlearnable —
   low-confidence), plus the older `pullback-coming/wait` / `no-match`. Read both
   invalidation levels: `near_term_invalidation` (the live higher-low) is the stop you quote;
   `structural_floor` is the deeper full-trend-break level. Also read `turn`: `path` (which of
   lift/reclaim fired), `cur_lift` vs `learned_lift`, and `trigger_lift_price` /
   `trigger_ema_price` (the buy trigger to quote when not yet turned).
7. Decide whether to **zoom in** (see "When to zoom in"): if the call turns on the
   exact swing low / stop or the anchor frame is too thin, drop one frame finer
   (fetching it if needed) and fold the sharper low/stop into the report.
8. Write the report in the plain style below (NOT a stats dump).

## Workflow — universe screener

1. `universe_gate` (Block 9): keep symbols in an uptrend; sort by current depth to
   find dippers. Disclose how many symbols were excluded for short history.
2. Run the single-symbol workflow (steps 1–6) ONLY on the handful of survivors.
3. Output a short ranked list, one plain line per stock:
   `SYMBOL — <action>: dipping X% vs its usual Y% dip; bounces ~Z% of the time;
   buy zone ₹A–B, wrong below ₹C (−X% from price)`. Put the raw numbers table in
   the details footer, one row per analyzed stock, columns:
   `Symbol | n dips | usual dip % | now off high % | live-low dip % | bounce rate |
   live low ₹ (−%) | floor ₹ (−%) | latest candle`. Mark a row ⚠ when the floor's % is
   smaller than the live low's % (live low sits below the floor → near-term structure
   cracked). (`dip %`, `now off high %` and `live-low dip %` are measured from the swing
   HIGH = pullback depth; the `(−%)` beside each ₹ stop is measured from the latest CLOSE =
   stop distance — same low, two reference points.) `latest candle` is the
   `trade_timestamp` of the most recent bar each stock was analyzed on (`YYYY-MM-DD HH:MM`,
   from `last["trade_timestamp"]`) — surfaced to fact-check which candle the row used.

## When to zoom in (multi-timeframe intelligence)

The user's timeframe is the **anchor** (the frame they trade). Be intelligent about
dropping to a **finer** frame to sharpen the call — decide this yourself, fetch the
finer data if absent (`references/data.md`), and present it as an additive zoom, never
a silent swap of the anchor.

Timeframe ladder, coarse → fine:
`1mo · 1wk · 1d · 1h · 30m · 15m · 5m · 1m`. "Zoom in" = move one (occasionally two)
steps finer.

**Zoom in when the verdict turns on precision the anchor frame can't give:**

- Label is **buyable-dip-now**, or a **live low sits in/near the band** → zoom finer
  to pin the exact swing low and place a tight structural stop. (A 3% stop usually
  cannot sit on a higher-frame structure; the finer frame is where the real
  higher-low lives.)
- The **forming low is in the anchor frame's edge zone** (unconfirmable, `center=True`
  nulled it) and the call hinges on whether the higher-low held → a finer frame
  confirms or denies it directly.
- `cur_depth` is **right at a band edge** (borderline buyable vs wait) → the finer
  frame breaks the tie.
- `n_events < 5` on the anchor frame → a finer frame may hold enough events to escape
  low-confidence. Use it as supporting evidence, clearly labeled as a different frame
  with its own (usually shorter) history — not as if it were the anchor's signature.

**Do NOT zoom when** the anchor verdict is a clean no-match, price is mid-structure
far from any decision, or the finer data would breach a Yahoo history cap and arrive
too thin to trust. Say why you didn't.

**What the finer frame is for:** locating the swing low, confirming the higher-low
holds, and timing/stop placement — structure and precision. It is NOT a second
opinion on the thesis; a finer frame's short history can't carry a full bounce-rate.
Disclose the zoom, the frame used, and that it was fetched if so.

(Coarser frames are context, not zoom: if the anchor setup contradicts the next frame
up, name the conflict and let it cap conviction — don't average frames.)

## Output style — talk to a trader, not a statistician

Lead with the answer in plain words. Hide the machinery (no "IQR", "ATR", "MFE",
"fractal", "k=8", "noise filter" in the main body). Use prices and plain percentages,
not statistics. The whole report a busy trader reads is the top part; the numbers
live in a small footer for anyone who wants to check.

Required shape (single symbol):

```
**<SYMBOL> — <timeframe> → <BUY THE DIP | WAIT (not turned) | AVOID>. <one-line reason>.**

<1–3 plain sentences: where price is vs its recent high, whether a dip is actually happening,
and — the key addition — whether the dip has shown this stock's own sign of a turn yet.>

**How this stock usually dips:** when it pulls back it normally drops about <X–Y%>
before trying to bounce, and it recovers about <half / two-thirds / N in 10> of the
time — so call the reliability <weak / fair / strong> in plain words.

**What to watch for / what to do:** <the buy zone in ₹, or "it's in the zone now">,
and one line on conviction (size small if reliability is weak).

**Turn check (the knife gate):** only call BUY THE DIP when the dip has reproduced this
stock's learned turn — lifted to about its usual ATR-bounce off the low, or genuinely
reclaimed the EMA its rebounds reclaim. If it has not turned yet, say **WAIT (not turned)**
and quote the **buy trigger** in ₹ ("turns on a close above ₹<trigger_ema_price>, or a lift
to ₹<trigger_lift_price>"). A dip still making fresh lows is a falling knife — never a buy.

**Where you'd be wrong:** close below **₹<live higher-low> (−X% from price)** breaks
this pullback (near-term stop). The deeper floor is **₹<prior confirmed higher-low>
(−Y% from price)** — below that the whole uptrend is broken. Quote the near-term level
as the working stop.

<If you zoomed: **Zoom (<finer frame>):** one line on the sharper swing low / stop the
finer frame revealed, noted as a different, shorter-history frame.>

---
*Details: <n> past dips found · usual depth <X–Y%> · bounce rate <0.NN> · usual
anchor <ema_NN or "no clean EMA — structural"> · stops: near-term ₹<live HL> (−X%),
floor ₹<prior HL> (−Y%). Computed on <timeframe> data, as of <YYYY-MM-DD HH:MM>
(latest candle, `last["trade_timestamp"]` — fact-check the bar used); EMAs derived on
the fly. Structural evidence, not financial advice.*
```

Translate every term: depth band → "usually dips X–Y%"; success_rate → "bounces N%
of the time"; dominant_anchor 'none' → "dips don't reliably tag an EMA — they're
structural"; invalidation → "where you'd be wrong". If `n_events < 5`, say plainly
"too few past pullbacks to trust — low confidence" and stop dressing it up.

Always print each ₹ stop level (live higher-low AND structural floor) with its %
distance below the latest close — a price alone hides how tight or loose the stop is.
Compute the % in Polars from the level and the latest close (`(close − level)/close
* 100`), never eyeball it. A floor whose % is smaller than the live low's % means the
live low sits below the floor → near-term structure already cracked; flag it.

## Hard rules

- **Never write a file into the repository.** Do not create `.py` scratch files,
  notebooks, or output files anywhere under the project. Run composed Polars by
  piping a heredoc to `.venv/bin/python` (`.venv/bin/python - <<'PY' ... PY`) or
  `-c`. If a throwaway script is genuinely unavoidable, put it under `/tmp/` only.
  Analysis is read-only against `market-data/`; the only artifact is your reported
  answer.
- Timeframe missing/unsupported → ask or raise; never proceed on a guess.
- Fetching market data for a missing interval is allowed and expected (it lands in
  gitignored `market-data/prices/` — that is the data lake, not a forbidden scratch
  file; the `/tmp` config is the only file you author). A failed fetch
  (`Failed`/non-zero exit) → quote the Yahoo error and stop; never analyze a partial
  or empty download.
- **Never delete or overwrite anything under `market-data/prices/`.** It is the
  persistent data lake — keep every fetched interval/symbol file, even data you
  pulled for a single analysis. Only add to it; never clean it up.
- Missing symbol / no rows / stale data → quote the error, stop. No partial analysis,
  no fabricated numbers.
- `n_events < 5` → label **insufficient-history, low-confidence**; never invent a
  signature from 1–2 events.
- **The turn is learned, never assumed.** Learn the rebound trigger per stock from its own
  winning dips (Block 7b) and confirm it live (Block 8c); a dip is BUY only once it
  reproduces that trigger (lift in the stock's own ATR **or** a genuine reclaim of its learned
  EMA — union). A live dip still printing fresh lows (no lift, no genuine reclaim) is
  `wait-not-turned`, the falling-knife hold, never a buy. `< 5` winning dips with an up-thrust
  → `turn-unconfirmable, low-confidence`; never invent a lift or an EMA.
- **Never quote invalidation off confirmed pivots alone.** The latest swing is
  unconfirmable at the chart edge (`center=True` nulls the last `k` bars), so the
  forming higher-low is invisible to the confirmed list. Recover it with
  `live_pullback_low` (Block 8b, raw-bar scan) and report TWO levels: near-term (the
  live higher-low = the stop) and structural floor (prior confirmed higher-low = full
  trend break). Quoting the deep floor as the stop is a bug.
- Pattern thresholds (pivot window, noise filter, depth/retrace bands) are derived
  per stock from its own distribution and disclosed. Risk barriers (3% hard stop,
  ~10–15 bar time stop) are the trader's fixed model — explicit, stated, distinct
  from pattern bands.
- Every number is computed in Polars, never eyeballed from a chart or invented.
- Read-only. Disclose survivorship bias (universe selected today) and on-demand EMA
  calculation.

This is structural evidence, not financial advice.
