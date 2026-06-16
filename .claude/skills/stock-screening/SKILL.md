---
name: stock-screening
description: Screen the whole Parquet stock universe for buy-on-pullback candidates, judging each stock against its OWN historical dip behavior. Two-stage funnel — a fast vectorized own-band proxy net, then bespoke per-stock confirmation via the pullback-finder grammar. Use when the user asks to screen/scan the universe for pullback buys. Requires a user-supplied timeframe. Companion to pullback-finder.
---

# Stock Screening — Pullback Universe Screener

Screen the whole universe for buy-on-pullback candidates, judging each stock against
**its own** dip behavior — not a global depth ranking. A two-stage funnel: a cheap
vectorized net picks WHO to look at; the bespoke pullback-finder grammar decides the
verdict on the survivors. Every pattern parameter is derived from current data at run
time, never frozen. Companion to `pullback-finder` (composed, never modified).

The Stage-A grammar lives in `references/screening-blocks.md`; the per-stock math is
`pullback-finder`'s `references/building-blocks.md` (Blocks 1–8). Read both before
running. Read-only against `market-data/`.

## Required input

- **Timeframe is mandatory and user-supplied.** Never assume or default it; if the user
  did not give one, ask before doing anything. Any Yahoo interval is allowed
  (`1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo`). Only `1d` and `1h` are on disk; for
  anything else, fetch it first (`../pullback-finder/references/data.md` → "Fetching a
  missing timeframe"), respecting Yahoo history caps; fail fast on a failed download.
- **Scope is the whole universe** (`market-data/prices/<interval>/*.parquet`). No symbol
  argument — single-symbol questions go to `pullback-finder` directly.

## Workflow — the two-stage funnel

1. **Stage A — proxy net + self-calibration.** Run `calibrate_W(interval)` (Blocks
   A1–A2). It returns the shortlist plus `mode` (stable/sensitive), `overlap`, and the
   `W_used`. Disclose all three. Disclose how many symbols were excluded for short
   history (`bars < max(60, W)`).
2. **Stage B — bespoke confirm.** For each shortlisted symbol, run the Block A6 recipe:
   compose `pullback-finder`'s Blocks 1–8 with per-stock `k` (`choppiness_k`, Block A3),
   the up-leg guard (`upleg_is_uptrend`, Block A5), the volume-fade annotation
   (`volume_fade`, Block A4), and the per-stock learned horizon (`learn_horizon`, Block
   A7). Also learn the per-stock rebound trigger (`learn_turn_trigger`, Block 7b) and confirm
   it on the live dip (`live_turn`, Block 8c) — the falling-knife gate. Fixed risk knob:
   `stop_pct=0.03` (the only frozen risk parameter). The horizon is
   learned (`H_stock`); every event is scored at **both** `H_base=15` (comparable
   yardstick) and `H_stock` (own clock) — see the comparability clause in "The law".
3. **Stage C — tier + report.** Tier the confirmed candidates, present the report in chat
   (lead + table), then write the full report to a markdown file under `output/` (Block A8).

## Stage A — proxy net (see references/screening-blocks.md)

Blocks A1–A2. One streaming Polars pass over the whole glob, per symbol: trailing-peak →
drawdown series → own band from trough drawdowns (q25–q75) → "recent dip reached its own
band?" + uptrend filter. Inclusion-biased on purpose: a borderline keep is fine (Stage B
culls it); a wrong drop is fatal (Stage B never sees it). `W` self-calibrates across
{60,120,240}; on disagreement (overlap < 0.85) it takes the **union** and says so.

## Stage B — bespoke confirm (composes pullback-finder)

Block A6. The SAME math `pullback-finder` runs for a single symbol, applied to each
survivor, with: `k` computed per stock (not a literal), only pullbacks whose up-leg has a
rising 50-EMA, a volume-fade flag on the live dip, and a learned recovery horizon
`H_stock` (Block A7). Produces each stock's own depth band, **dual bounce rate**
(`bounce@base` at the fixed `H_base` yardstick + `bounce@learned` at `H_stock`, with their
gap `Δ`), recovery class (fast/medium/slow), dominant anchor, live low (near-term stop) +
structural floor, each stop with its **% distance from the latest close**. `n_events < 5`
→ low-confidence; never invent a signature. Fewer than 5 events that ever recover → cannot
learn the horizon: fall back to `H_base` and label low-confidence. Stage B also learns each
survivor's **rebound trigger** from its own winning dips (lift in its ATR + the EMA its
rebounds reclaim) and checks whether the live dip has reproduced it — `turn confirmed`
True/False/None. A BUY requires `True`.

## Stage C — tier + report

Tier confirmed candidates. **"Dipping now" is required for a BUY** — Stage A's net is
inclusion-biased and catches names that dipped recently but have since recovered to a new
high; those are not dip-buys.

- **BUY THE DIP** — price is *still in the dip now* (`now off high` is positive and inside
  the stock's own band), uptrend intact, live low above floor, `bounce@base` fair or better
  (≈ 0.5+), **and the turn is confirmed** (`state["turn"]["confirmed"] is True` — the live dip
  lifted to its learned ATR-bounce or genuinely reclaimed its learned EMA). Rank by
  `bounce@base` first, then prefer `fast`/`medium` recovery and a small `Δ`; a fading-volume
  dip and deepest-in-band break ties. Lead with the few highest-conviction names. Quote each
  pick's recovery class, expected hold, and **which turn path fired** (lift / reclaim).
- **WAIT / not-turned** — cleared depth + uptrend + floor + bounce, **but the turn is not
  confirmed** (`state["turn"]["confirmed"] is False`): in its own band yet still falling or
  basing, no sign of a turn. This is the falling-knife gate — **never a buy now**. Report it
  separately as the watchlist with its **buy trigger** ("turns on a close above ₹X, or a lift
  to ₹Y") and re-screen next bar.
- **PATIENT BUY** — qualifies as a BUY but `recovery_class` is `slow`: the edge is real
  yet needs a long hold. Report it **separately** with its expected hold time; never mix it
  in with quick setups.
- **WATCH / already bounced** — qualified on Stage A but `now off high` ≤ 0 (price has
  recovered to/above the recent high) or the live low already bounced well off the band.
  Note them; they are not buys now.
- **SPECULATIVE** — qualifies but `n_events` thin (low-confidence), **or** `bounce@base`
  weak (< ~0.5), **or** *borrowed time* (`Δ ≥ 0.15` while `bounce@base < 0.5` — the rate
  exists only because the long horizon manufactured it), **or** the turn trigger is unlearnable (`confirmed is None` — `< 5`
  winning dips with an up-thrust; low-confidence). Size small.
- **CAUTION** — live low has dropped below the prior higher-low (near-term structure
  cracked, floor % < live-low %).
- **AVOID** — recent dip far beyond its own band (reversal risk, not a routine dip).

Do not dump every BUY-eligible name — rank by conviction and lead with the top handful;
state how many more cleared the bar (no silent truncation).

**Persist the report.** After presenting in chat, write the markdown file with Block A8
(`write_report(rows, buy_lines, disclosures, interval)`): `output/<YY-MM-DD-HHMM>-<interval>.md`
— the timestamp from the run clock, `interval` the user's timeframe. `rows` are the same
per-symbol dicts behind the chat table; `buy_lines` the same ranked one-liners shown for the
picks (no recomputation). Report the written path. **Write the file even when the shortlist is
empty** (heading + "no buyable dips today." + disclosures).

## Output style

**Ranked line (one per buy candidate):**

```
SYMBOL — <action> (<recovery class>): dipping X% vs its usual Y% dip;
bounces ~Z% @base / ~Z'% on its own ~D-day clock (Δ +d); turned via <path>;
buy zone ₹A–B, wrong below ₹C (−X% from price)
```

**Footer table, one row per analyzed stock, columns:**

```
Symbol | n dips | usual dip % | now off high % | live-low dip % |
bounce@base | bounce@learned (Δ) | H_stock (≈D days) | recovery class | turn |
vol-fade | live high ₹ (+%) | live low ₹ (−%) | floor ₹ (−%)
```

Mark a row ⚠ when the floor's % is smaller than the live low's % (live low below the
floor → near-term structure cracked). `dip %`, `now off high %`, and `live-low dip %` are
measured from the swing HIGH (depth); each `(−%)`/`(+%)` beside a ₹ level is measured from
the latest CLOSE (distance from price). `live high ₹` is the swing high the dip fell from —
the same high the depth %s use (depth-from-high vs distance-from-close: one high, two
reference points); its `(+%)` is the upside to reclaim it. `live low ₹` (−%) is the
near-term stop and `floor ₹` (−%) the structural floor — same low/floor, two reference
points. `vol-fade` shows the
dip/up-leg volume ratio (✓ if < 1 = volume fading = healthy). `bounce@base` is the
comparable rate at the fixed `H_base` yardstick; `bounce@learned` is the rate at the
stock's own `H_stock`; `Δ = learned − base` flags borrowed time when large.

`turn` shows the knife gate: `✓(path)` when confirmed (which of lift/reclaim fired), `— ₹X`
when not turned (the nearer buy-trigger price to reclaim), `n/a` when unlearnable. A BUY
always shows `✓`; a `—` row is WAIT, not a buy.

**Disclosures every run:** the W `mode` (stable/sensitive) + `overlap` + `W_used`;
computed `k` per stock; per stock `H_stock` (bars and ≈ trading days), its recovery class,
median & P75 recovery latency, and whether `H_stock` was clamped; the `H_base` yardstick
and the clamp range used; `bars_per_day` (derived from the data, not hardcoded); count
excluded for short history; survivorship bias (universe selected on today's uptrend); per
stock the learned rebound trigger (`learned_lift` in ATR, `learned_reclaim_ema`,
`learned_turn_lag`) and how many winning dips it was learned from (or "turn-unconfirmable");
EMAs/ATR computed on the fly.

**Markdown report file (every run):** table-first, written to
`output/<YY-MM-DD-HHMM>-<interval>.md` (Block A8). Layout: `# Pullback Screen — <date time>
(<interval>)`; a one-line tier count (`… — from N shortlisted, M analyzed`); the **full footer
table as a GitHub-flavored markdown table** (same columns and `⚠`/`[IDX]` markers as the chat
footer, each two-line box cell flattened to one line — e.g. `503.9 (+8.6%)`, `460.0 (−0.86%)`,
`0.733 (−0.067)`, `7≈1.0d`); a `## Buy lines` block reusing the ranked one-liners for the BUY/PATIENT/SPECULATIVE
picks; then a closing `_Disclosures: …_` line carrying the same disclosures above. **Chat
output is unchanged** — the file is an added durable copy, not a replacement.

**Empty shortlist → report plainly "no buyable dips today."** Never force picks, never
fall back to closest-to-band names.

Lead with the answer in plain words (translate the machinery — band → "usually dips
X–Y%", success_rate → "bounces N% of the time", `H_stock` → "usually recovers in ~D
trading days", anchor 'none' → "dips are structural"). The numbers live in the footer.
Structural evidence, not financial advice.

## The law — no frozen pattern constants

> Every **pattern** parameter (W, k, noise filter, depth bands, the recovery horizon
> `H_stock`, **and the rebound trigger — `learned_lift`, `learned_reclaim_ema`,
> `learned_turn_lag`**) is derived from or validated against the current data **at screen time** and
> disclosed in the output. None is a hardcoded constant trusted across runs, because the
> universe and each stock's behavior drift.
>
> The **3% hard stop is the only fixed risk knob** — it is the trader's loss tolerance, not
> a property of the stock. The **horizon is learned** (`H_stock`, Block A7), because how
> long a stock needs to resume is its own behavior, not the trader's preference.
>
> **Comparability clause (mandatory):** a learned horizon can only *add* wins (a longer
> window never removes a win), so it mechanically lifts bounce rates and breaks cross-stock
> comparability. Therefore every screen MUST report **both** `bounce@base` (a fixed
> `H_base` yardstick, identical for all stocks) **and** `bounce@learned` (`H_stock`), plus
> `H_stock` and its fast/slow class. A high `bounce@learned` resting on a large `H_stock`
> is *borrowed time* and must be labeled as such — never reported as a fast, comparable
> edge.

## Hard rules

- **The only file you may write into the repo is the final screen report** — one markdown
  file under `output/` (Stage C / Block A8). Write nothing else into the repo: no scratch
  `.py`, notebooks, or intermediate files. Run composed Polars by piping a heredoc to
  `.venv/bin/python` (`.venv/bin/python - <<'PY' ... PY`); if a throwaway script is genuinely
  unavoidable, put it under `/tmp/` only. The report markdown + the chat answer are the only
  artifacts.
- **Never delete or overwrite anything under `market-data/prices/`** — persistent data
  lake; only add (fetched intervals) to it.
- **Do not modify `pullback-finder`.** Compose its blocks by pasting them into the same
  heredoc; that skill stays the per-stock grammar.
- Every number computed in Polars, never eyeballed from a chart or invented.
- Read-only against `market-data/`. Disclose survivorship bias and on-demand EMA/ATR.

## Failure handling

| Situation | Behavior |
|---|---|
| No timeframe given | Ask; never default. |
| Requested interval not on disk | Fetch via pipeline (respect Yahoo caps); fail fast on a failed download. |
| Symbol file missing / empty | Quote the error, skip that symbol, disclose. |
| Shortlist empty | Report "no buyable dips today" in chat **and** still write the file (heading + that line + disclosures). No forced picks. |
| `output/` not writable | Fail fast; quote the OS error. No silent skip — the report is a required artifact. |
| Survivor with < 5 past dips | Label low-confidence; do not invent a signature. |
| < 5 events ever recover | Cannot learn `H_stock`; fall back to `H_base`, mark low-confidence. |
| `H_stock` hit the clamp | Disclose "clamped" — true recovery latency exceeds the cap (very slow grinder). |
| Borrowed time (`Δ ≥ 0.15` and `bounce@base < 0.5`) | Demote to SPECULATIVE; never lead BUY. |
| W-sensitive run (overlap < 0.85) | Use the union shortlist; disclose mode + overlap. |
| Turn trigger unlearnable (< 5 winning dips with an up-thrust) | `turn = unconfirmable`; demote to SPECULATIVE/low-confidence; never invent a lift or EMA. |
| Live dip still at a fresh low (no lift, no genuine reclaim) | `wait-not-turned` → WAIT tier, never BUY (the knife gate). |

This is structural evidence, not financial advice.
