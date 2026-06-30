# Risk-Management Research — Handoff

**Date:** 2026-06-30 · **Resume:** new session, continue from "Next steps" below.
**Goal that emerged:** *What risk management gives **minimal drawdown yet profitable** for a single-name swing book?*

This started as a review of the user's standard order design (the `trade-style-amo-oco`
bundle: AMO entry + dual-OCO, 50/50, −3% stop, +3%/+15% targets) and turned into a
data-driven search for a better risk framework, backtested on the project's Parquet data.

---

## TL;DR

1. **The original design (−3% stop + 50%@+3% scalp) is ~breakeven** — slightly negative
   after costs. It's a capital-preservation structure, not a money-maker, in an up-tape.
2. **The −3% stop is the leak.** It sits *inside* these names' daily noise (~−3.4% to −4%
   mean MAE), so it harvests the entry edge into breakeven. Wider/ATR stops always did better.
3. **A pullback entry has a real but small edge** (lifts P(+3 before −3) from ~47% to ~54%;
   buy-and-hold edge ~+0.7pp). It helps; it doesn't rescue a tight-stop design.
4. **The winning recipe (capstone backtest):** volatility-based position sizing + an ATR
   chandelier trailing stop + diversification + let winners run. Net of costs, in a market
   where the median stock fell −33% (−44% DD), it returned **+30.8% CAGR at −9.4% max DD
   (Calmar 3.26)**.
5. **Surprise (corrected a prior hypothesis):** a market-regime filter was **not needed** and
   slightly *hurt* — the ATR trail already does per-position risk-off. (Holds only for a
   single-name book; a beta/correlated book would still want a regime overlay.)
6. **Caveat that gates everything:** survivorship bias + a single 19-month regime make the
   absolute numbers optimistic. **Validate out-of-sample before trusting it.**

---

## Data used

- Daily: `market-data/prices/1d/*.parquet` — 212 NSE names, 2014-12 → 2026-06 (~2,857 bars).
- Hourly: `market-data/prices/1h/*.parquet` — 211 names, 2024-12 → 2026-06 (~2,686 bars, 7/day).
- Indicators in `market-data/indicators/<iv>/` (atr_percent_14 used for one sweep).

---

## Findings in order (with numbers)

### 1. Daily random-entry base rates — `derisk_backtest.py`
89,337 random entries (every 5th bar), 60-day horizon, conservative fills.
- P(tag +3% before −3%) = **51.5%**, P(+6 before −3) = 36.9%, P(reach +15%) = **17.6%**.
- Mean MAE = **−4.03%** (avg trade dips below −4% → the −3% stop is inside the noise).
- Variants A/B/C/D (de-risk splits) all clustered **+0.5% to +1.0%** mean; **buy & hold = +7.40%**.

### 2. Stop-width sweep — `derisk_backtest.py` + `derisk_sweep.py`
Mean return rises monotonically as the stop widens: −3% → +0.96%, −8% → +1.93%, −10% → +2.34%,
**ATR×3 → +2.96% (first positive median)**. The −3% stop is the worst setting tested. For any
fixed stop ≤8%, the *median* trade is a dead-on stop-out.

### 3. Hourly pullback-gated vs random — `pullback_backtest.py`
Faithful **walk-forward** operationalization of the pullback-finder grammar's "buy-the-dip-turned"
(uptrend → dip into the stock's own depth band → confirmed turn: lift ≥ learned ATR-lift OR reclaim
of learned EMA). 2,626 entries vs an 18,334 random control.
- Pullback lifted P(+3 before −3) **47.2% → 54.1%**, P(+15%) 13.8% → 15.7%, buy&hold **+6.17% → +6.90%**.
- Managed −3%-stop variants still ~breakeven (+0.1 to +0.2%); buy&hold still dominates.

### 4. Structural stop vs flat −3% — `pullback_struct.py`
Same pullback entries, stop = live higher-low (dip low − 0.3%) instead of flat −3%.
- **Correction:** the structural stop is **tighter** than 3% (median **2.1%**, only 23% wider) —
  not wider as I'd assumed.
- Design A: win rate **26% → 39%**, mean +0.20% → +0.25%, R-multiple 0.06 → 0.11. Still breakeven.
- **Verdict on the user's design:** near-breakeven, slightly negative after costs. Safety, not growth.

### 5. Capstone portfolio system — `portfolio_system.py`
Event-driven **portfolio** backtest (drawdown is a portfolio property). Net of 0.1%/side cost,
drawdown measured per hourly bar. Window Dec 2024 → Jun 2026.

| Approach | CAGR | Max DD | Calmar | Trades | Win% | Expo |
|---|---:|---:|---:|---:|---:|---:|
| **System, no regime filter** | **+30.8%** | **−9.4%** | **3.26** | 888 | 39% | 89% |
| System + 50-day regime | +18.0% | −8.7% | 2.07 | 311 | 41% | 33% |
| System + 200-day regime | 0% | 0% | — | 0 | — | 0% |
| Equal-weight index buy & hold | **−22.5%** | **−44.0%** | −0.51 | — | — | 100% |

The 200-day breadth regime read **risk-off for 100% of the window** (median stock below its
200-DMA the whole time) → would have kept you in cash. The system's own controls handled the
drawdown without it.

---

## The recommended risk-management recipe

**Risk is controlled by SIZE and a volatility-scaled trail — not by tight stops or a market filter.**

1. **Volatility-based position sizing (keystone):** risk a fixed **0.75% of equity** per trade.
   `shares = (0.75% × equity) ÷ (ATR_MULT × ATR)`. Decouples stop-width from account-risk.
2. **ATR chandelier trailing stop** (`ATR_MULT = 3`): initial = entry − 3×ATR; then ratchet
   `stop = max(stop, highest_close − 3×ATR)`. Room early, protect later, eject losers automatically.
   This *is* the "give it room then trail" intent — done with volatility, not a fixed +15% trigger.
3. **Let winners run** — no +3% scalp, no fixed target. The return lives in the right tail.
4. **Diversify** — ≤ 20 small concurrent names (`MAX_POS_PCT = 12%`).
5. **Keep the pullback entry** as the selective trigger.
6. **No macro regime filter** for a single-name book — the ATR trail already does risk-off per position.

Current tuned params (NOT optimized, just sensible defaults): `RISK_PCT=0.0075`, `ATR_MULT=3.0`,
`MAX_POS=20`, `MAX_POS_PCT=0.12`, `MAX_HOLD=420` hourly bars, `COST=0.0010`/side.

---

## Caveats (read before trusting any number)

- **Survivorship bias** — the 208 names exist *today*; the system trades their pullbacks/recoveries.
  A delisting-inclusive universe would lower the absolute CAGR. (The benchmark uses the same
  survivors and still did −22%, so the *relative* edge is partly protected — but treat +31% as
  optimistic.)
- **One regime, 19 months, in-sample.** No multi-period walk-forward yet. Params were *not* fitted
  (good) but are unvalidated out-of-sample.
- **Signal is an operationalization** of the grammar (fixed `k=5`, ATR-at-low for lift), not the
  exact bespoke per-stock engine.
- **Slippage** on midcap stop-exits in fast markets can exceed the modeled 0.1%/side.
- Hourly drawdown is bar-level; true intraday troughs could be marginally deeper.

---

## Locked decisions (from the user, this session)

- **Objective:** best risk-adjusted return (Calmar/Sharpe), smooth equity.
- **Automation:** daily automated rules (script/cron) — wanted.
- **Core mix:** all individual stock swings (no index core).

---

## Next steps (ranked — recommendation: do (B) before (A))

**(B) Validate out-of-sample FIRST — highest priority.**
- Adapt `portfolio_system.py` to **daily** data (2014–2024) → longer history, multiple regimes
  (2014-19 bull, 2020 COVID crash, 2021 bull, 2022 bear, 2023-24 bull). Does Calmar hold across all?
- Use rolling/walk-forward windows (train signature on prior years, test on next) — not one in-sample pass.
- **Parameter sensitivity:** `RISK_PCT ∈ {0.5, 0.75, 1.0}%`, `ATR_MULT ∈ {2.5, 3, 4}`,
  `MAX_POS ∈ {10, 20, 30}`. If results swing wildly, it's overfit.
- Add a **survivorship sanity check** (or at minimum quantify how many traded names later underperformed).
- Re-run the entry with the **true pullback-finder engine** (per-stock `k`, full Block 7b turn) to
  confirm the k=5 approximation didn't flatter the signal.

**(A) THEN build the daily automation (what the user wants).**
- Morning job: pull holdings/positions + regime-free pullback signals from Kite MCP + Parquet →
  output, per fired signal, the **vol-sized share count** and the **ATR-trail GTT levels**
  (initial 3×ATR stop). For open positions, output the **ratcheted trail stop** to modify GTTs to.
- Wire to the existing `scripts/kite/` order plumbing + `kite-amo-oco-bundle` skill conventions.
  NOTE: per memory `kite-order-no-guardrails`, kite order scripts fire immediately — keep that.
- Until (B) passes, run it in **paper/report-only** mode (print orders, don't place).

**Open questions for tomorrow**
- Confirm starting params (0.75% risk / 3×ATR / 20 names) after the sensitivity run.
- Decide trade timeframe for execution: signals are hourly; is a once-daily check acceptable
  (it was assumed) or do you want intraday checks?
- Position-sizing reality: a wider ATR stop ⇒ smaller share count; confirm that fits the
  ~₹10k-per-ticket habit (it will mean variable rupee size per name).

---

## Scripts (preserved in this folder — run from the repo root with `.venv/bin/python`)

| Script | What it does |
|---|---|
| `derisk_backtest.py` | Daily random-entry base rates + A/B/C/D variant comparison + buy&hold anchor. |
| `derisk_sweep.py` | Daily stop-width sweep (fixed 3–10% and ATR×2/×3). |
| `pullback_backtest.py` | Hourly **walk-forward pullback signal** detector + pullback-vs-random comparison + stop sweep. (Imported by the two below.) |
| `pullback_struct.py` | Structural-stop vs flat-3% head-to-head on the same pullback entries. |
| `portfolio_system.py` | **Capstone**: event-driven portfolio backtest of the recommended system (vol-sizing + ATR trail + diversification + optional regime). This is the file to evolve for step (B). |

Run example: `cd /workspaces/stock-database && .venv/bin/python output/risk-research/portfolio_system.py`

All are read-only against `market-data/`. No look-ahead in the signal (signature learned only
from each stock's prior dips); regime uses prior-day close.
