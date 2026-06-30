---
name: kite-amo-oco-bundle
description: Place the user's standard swing-trade order bundle through the Kite MCP — an AMO market entry plus two GTT protective exits that split the position 50/50: one OCO (−3% stop / +3% target) and one single-leg stop-only (−3%), 0.5% limit buffer. Use when the user asks to buy/enter one or more stocks, "set up <SYMBOL>", "place my usual order for X", or wants the full entry+exit bracket on a name.
---

# Kite AMO + OCO/Stop Bundle

Place the user's default swing-trade structure for one or more stocks via the Kite
MCP tools: a **delivery AMO market buy**, protected by **two GTT sell orders** that
split the position 50/50 — one **OCO (two-leg)** with a −3% stop and a +3% target,
and one **single-leg** −3% stop-only (no target). All GTT legs are LIMIT orders with
a 0.5% buffer past the trigger to fill like a market order (Kite has no market GTT).

This encodes the user's saved trade style. Never invent or estimate a number — every
price comes from a live LTP and the fixed percentage rules below.

## Fixed rules (the user's defaults)

| Parameter        | Value |
|------------------|-------|
| Entry            | variety `amo`, `MARKET`, `BUY`, product `CNC`, exchange **NSE** |
| Order tag        | `amo_oco` (on the AMO; `place_gtt_order` has no tag field) |
| Position size    | ~₹10,000 notional, rounded to an **even** share count |
| Level basis      | current **LTP** (the AMO market fill price isn't known yet) |
| Stop loss        | −3% of basis (both GTTs) |
| Target           | +3% on the **OCO** GTT only; the second GTT is **stop-only** (no target) |
| Quantity split   | 50 / 50 of the bought qty across the two GTTs |
| Limit buffer     | each GTT leg's limit = 0.5% **below** its trigger (SELL) |
| Tick rounding    | round every price to the instrument tick (₹0.05 for equities) |

The user always wants a **review table first, then an explicit `confirm`** before
anything is placed. Do not place on the same turn you show the table.

## Workflow

1. **Login if needed.** If any Kite tool returns a session/login error, call
   `mcp__kite__login`, show the user the returned link with the AI-risk warning,
   and wait for them to finish before continuing.

2. **Resolve each symbol.** Accept one symbol or a list (batch). For each:
   - `mcp__kite__search_instruments` (query = symbol) to confirm it exists.
   - Default to the **NSE** listing. Use BSE only if the user explicitly says so,
     or if the symbol is not listed on NSE. If it can't be resolved, stop and
     report — never guess the token/exchange.

3. **Get the entry basis.** `mcp__kite__get_ltp` for `NSE:<SYMBOL>` (all symbols
   in one call). This LTP is the basis for sizing and all levels.

4. **Size the position** (only if the user didn't give a quantity):
   - `qty = round(10000 / ltp)`, then adjust to the nearest **even** integer
     (so it splits 50/50). Minimum 2.
   - If the user *did* give a quantity, use it. If it's odd, tell them you'll put
     the extra share on the +3% (first) GTT leg, or ask — don't silently drop it.

5. **Compute levels** from the LTP basis, then round each to the ₹0.05 tick:
   - Stop trigger  = basis × 0.97  (used by **both** GTTs)
   - Target A trig = basis × 1.03  (OCO GTT only)
   - Each leg's **limit** = its trigger × 0.995 (0.5% below), re-rounded to tick.
   - Sanity check: the stop trigger must be **below** the LTP and the +3% target
     trigger **above** it, or the GTT is invalid at placement. If the LTP has
     moved so this fails, flag it and ask before proceeding.

6. **Show the review table** — one combined table when batching — listing for each
   symbol: exchange, qty, LTP basis, the AMO line, and both GTTs (the OCO's stop +
   +3% target with buffered limits and qty per leg, and the stop-only GTT's trigger +
   buffered limit + qty). State that levels are LTP estimates and the real −3/+3 shift
   slightly if the AMO fills at a different price. Then wait for `confirm`.

7. **On confirm, place in order** per symbol:
   - **AMO entry** — `mcp__kite__place_order`:
     `variety=amo, exchange=NSE, tradingsymbol=<SYM>, transaction_type=BUY,
      quantity=<qty>, product=CNC, order_type=MARKET, tag=amo_oco`.
   - **GTT A (OCO, +3%)** — `mcp__kite__place_gtt_order`:
     `exchange=NSE, tradingsymbol=<SYM>, last_price=<ltp>, transaction_type=SELL,
      product=CNC, trigger_type=two-leg,
      lower_trigger_value=<stop>, lower_limit_price=<stop×0.995>, lower_quantity=<qty/2>,
      upper_trigger_value=<t3>, upper_limit_price=<t3×0.995>, upper_quantity=<qty/2>`.
   - **GTT B (stop-only)** — `mcp__kite__place_gtt_order`:
     `exchange=NSE, tradingsymbol=<SYM>, last_price=<ltp>, transaction_type=SELL,
      product=CNC, trigger_type=single,
      trigger_value=<stop>, limit_price=<stop×0.995>, quantity=<qty/2>`.

8. **Report** the AMO `order_id` and both GTT `trigger_id`s in a table. Note the
   GTT levels are based on the LTP estimate; treat the bundle as **complete** —
   do not leave a standing "re-base after fill" task for a future session.

## Worked example (TIMEX, basis ₹507.50, qty 20)

| Order | Detail |
|-------|--------|
| AMO BUY | 20 × MARKET · CNC · tag `amo_oco` |
| GTT A — OCO (10) | stop 492.30→489.85 · target +3% 522.75→520.15 |
| GTT B — stop-only (10) | stop 492.30→489.85 · no target |

## Notes & guardrails

- These are real, irreversible orders. Always review-then-confirm; never skip step 6.
- The two GTTs are **separate** orders on the same instrument — one OCO (two-leg),
  one single-leg stop — Kite allows this.
- Only the AMO carries the `amo_oco` tag; GTTs can't be tagged via the API.
- The review-then-confirm step (step 6) is this skill's only safety gate — do not
  place without it.
