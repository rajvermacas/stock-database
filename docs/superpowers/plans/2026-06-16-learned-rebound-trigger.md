# Learned Rebound Trigger Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to carry out this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-stock *learned* rebound trigger so a dip is only called BUY once it shows the stock's own historical sign of a turn — gating BUY against falling knives — across `pullback-finder` (owns the grammar) and `stock-screening` (consumes it).

**Approach:** Learn each stock's early-turn marker (lift off the low in its *own* ATR + the EMA its winners genuinely reclaim) from its winning past dips, then require the live dip to reproduce it. New blocks live in `pullback-finder/references/building-blocks.md`; `stock-screening` composes them (Stage B call + Stage C gate/tier + report column). No hardcoded thresholds — every turn parameter is learned and disclosed.

**Tools / Inputs:** Polars 1.41.2 (`.venv/bin/python`), read-only Parquet under `market-data/prices/1h/` (176 symbols), the approved spec `docs/superpowers/specs/2026-06-16-learned-rebound-trigger-design.md`. All code below is already validated against real 1h data (gate fires: e.g. AEROFLEX.NS→turned, STYLAMIND.NS→not-turned).

**Key facts the worker must respect (from the skills' hard rules):**
- NEVER write a scratch file into the repo. Run composed Polars via heredoc to `.venv/bin/python`; throwaway scripts go under `/tmp/` only. The sole repo write is the screener's `output/<…>.md` report.
- NEVER modify `pullback-finder` *from* `stock-screening` — screening pastes/composes its blocks.
- Every turn value is learned per stock and disclosed; `< 5` winning dips with an up-thrust → `turn-unconfirmable, low-confidence`, never a default.

---

## Task 1: Add Block 7b — `learn_turn_trigger` (learn the turn from winners)

**Inputs/Outputs:**
- Modify: `.claude/skills/pullback-finder/references/building-blocks.md` — insert a new section **after** Block 7 (`signature`, ends ~line 198) and **before** Block 8 (`## Block 8 — Current state`).
- Done-check: the new section is present; verified for real in Task 4.

- [ ] **Step 1: Insert the new Block 7b section**

Add this markdown block immediately after Block 7:

````markdown
## Block 7b — Learned turn trigger (the stock's own rebound signature)

What did a *real* turn look like for THIS stock? Learn it from its own winning dips —
never a hardcoded "1 ATR" or a fixed EMA. For each successful event, find the first
up-thrust after the low (first bar whose `close` > the prior bar's `high` — a structural
primitive, like the fractal-pivot definition), then measure how far price had lifted off
the low **in the stock's own ATR** and the **highest EMA it genuinely reclaimed** (low was
below it, thrust close above it). Aggregate: median lift, modal reclaim-EMA, median lag.
All observable at that historical bar — no look-ahead. `success_key` selects which outcome
flag marks a winner (`"success"` for a single-symbol run; screening passes `"success_base"`,
the comparable @base yardstick).

```python
from collections import Counter

def learn_turn_trigger(df, events, success_key="success", min_winners=5):
    emas = ["ema_10", "ema_20", "ema_50", "ema_100", "ema_200"]
    idx_of = df.with_row_index("i")
    lifts, reclaims, lags = [], [], []
    for ev in events:
        if not ev.get(success_key):
            continue                                   # learn only from winners
        i = idx_of.filter(pl.col("trade_timestamp") == ev["low_ts"]).select("i").item()
        low_row = df.row(i, named=True)
        atr_L = low_row["atr_14"]
        if atr_L is None or atr_L == 0:
            continue                                   # warm-up low; cannot scale
        fwd = df.slice(i + 1)
        if fwd.height < 2:
            continue
        prev_high = fwd["high"].shift(1)
        thrust_mask = (fwd["close"] > prev_high).fill_null(False)
        tpos = next((j for j, m in enumerate(thrust_mask) if m), None)
        if tpos is None:
            continue                                   # recovered without an up-thrust bar
        trow = fwd.row(tpos, named=True)
        lifts.append((trow["close"] - ev["low"]) / atr_L)     # lift in the stock's own ATR
        lags.append(tpos + 1)                          # 1-based bars: low -> first thrust
        rec = "none"
        for e in reversed(emas):                       # highest genuinely reclaimed EMA
            le, te = low_row.get(e), trow.get(e)
            if le is not None and te is not None and ev["low"] < le and trow["close"] > te:
                rec = e
                break
        reclaims.append(rec)
    if len(lifts) < min_winners:
        return {"turn_learnable": False, "winners_used": len(lifts),
                "reason": "too few winning dips with an up-thrust to learn a trigger"}
    return {
        "turn_learnable": True,
        "winners_used": len(lifts),
        "learned_lift": float(pl.Series(lifts).median()),          # ATR-multiple, learned
        "learned_reclaim_ema": Counter(reclaims).most_common(1)[0][0],
        "learned_turn_lag": float(pl.Series(lags).median()),
    }
```

`learned_lift` is the stock's typical ATR-lift by its first up-thrust (median; tunable +
disclosed). `learned_reclaim_ema` is the EMA its rebounds genuinely reclaim (`none` is a
valid structural answer, like `dominant_anchor`). `< min_winners` usable winners →
`turn_learnable=False`; the caller must treat that as low-confidence, never invent a value.
````

- [ ] **Step 2: Verify it's done**

Run: `grep -n "def learn_turn_trigger" .claude/skills/pullback-finder/references/building-blocks.md`
Expected: one match, located between Block 7 and Block 8.

---

## Task 2: Add Block 8c — `live_turn` (is the live dip reproducing the trigger?)

**Inputs/Outputs:**
- Modify: `.claude/skills/pullback-finder/references/building-blocks.md` — insert a new section **after** Block 8b (`live_pullback_low`, ends ~line 268, just before Block 9).
- Done-check: section present; verified in Task 4.

- [ ] **Step 1: Insert the new Block 8c section**

Add this markdown block immediately after Block 8b and before `## Block 9`:

````markdown
## Block 8c — Live turn check (the falling-knife gate)

Is the LIVE dip reproducing the stock's learned turn marker? **Union:** confirmed if the
live lift off the low has reached `learned_lift` (in the stock's own ATR) **OR** the dip
genuinely reclaimed `learned_reclaim_ema` (the live low broke below that EMA and close is
now back above it — a bare "close above EMA" on a shallow dip that never lost it is NOT a
reclaim). Returns the unmet-path trigger PRICE(s) so a not-yet name shows exactly what to
reclaim to flip to BUY. `confirmed is None` = cannot judge (trigger unlearnable / ATR
warm-up / no live dip) → low-confidence, never a buy.

```python
def live_turn(df, zz, trigger):
    if not trigger.get("turn_learnable"):
        return {"turn_learnable": False, "confirmed": None,
                "why": trigger.get("reason", "trigger not learnable")}
    live = live_pullback_low(df, zz)               # Block 8b — the forming low
    if live["live_low"] is None:
        return {"turn_learnable": True, "confirmed": None,
                "why": "no live dip (last high is the last bar)"}
    last = df.row(df.height - 1, named=True)
    atr_now = last["atr_14"]
    if atr_now is None or atr_now == 0:
        return {"turn_learnable": True, "confirmed": None,
                "why": "ATR warm-up — cannot scale live lift"}
    close, low = last["close"], live["live_low"]
    cur_lift = (close - low) / atr_now                            # lift in own ATR
    lift_ok = cur_lift >= trigger["learned_lift"]
    ema = trigger["learned_reclaim_ema"]
    ema_now = last.get(ema) if ema != "none" else None
    ema_at_low = None                                            # genuine reclaim needs the
    if ema != "none":                                            # dip to have BROKEN the EMA
        low_row = df.filter(pl.col("trade_timestamp") == live["live_low_ts"]).row(0, named=True)
        ema_at_low = low_row.get(ema)
    reclaim_ok = (ema_now is not None and ema_at_low is not None
                  and low < ema_at_low and close > ema_now)
    path = []
    if lift_ok: path.append("lift")
    if reclaim_ok: path.append("reclaim")
    return {
        "turn_learnable": True,
        "confirmed": bool(lift_ok or reclaim_ok),
        "path": path,                                            # which path(s) fired
        "cur_lift": cur_lift,
        "learned_lift": trigger["learned_lift"],
        "trigger_lift_price": low + trigger["learned_lift"] * atr_now,   # reclaim for lift path
        "reclaim_ema": ema,
        "trigger_ema_price": ema_now,                            # reclaim for ema path (None if 'none')
        "broke_ema": (ema_at_low is not None and low < ema_at_low),
        "live_low": low,
        "live_low_ts": live["live_low_ts"],
    }
```

A fresh-low last bar gives `cur_lift ≈ 0` and no reclaim → `confirmed=False` (the knife,
correctly held back). "Already bounced far past the trigger" is NOT decided here — it stays
with the existing now-off-high ≤ 0 / WATCH handling (Block 8 / Stage C).
````

- [ ] **Step 2: Verify it's done**

Run: `grep -n "def live_turn" .claude/skills/pullback-finder/references/building-blocks.md`
Expected: one match, located after `live_pullback_low` and before Block 9.

---

## Task 3: Wire the turn into Block 8 `current_state`

**Inputs/Outputs:**
- Modify: `.claude/skills/pullback-finder/references/building-blocks.md` — replace the `current_state` function in Block 8 (~lines 206-232).
- Done-check: backward-compatible (no `trigger` ⇒ original behavior); verified in Task 4.

- [ ] **Step 1: Replace `current_state` with the trigger-aware version**

Replace the existing `def current_state(df, zz, sig):` … `return out` block with exactly:

```python
def current_state(df, zz, sig, trigger=None):
    last = df.row(df.height - 1, named=True)
    last_high = next((p for p in reversed(zz) if p[1] == "H"), None)
    if last_high is None:
        return {"label": "no-match", "why": "no confirmed swing high"}
    live = live_pullback_low(df, zz)               # Block 8b — recover edge-zone low
    hi_idx = max(i for i, p in enumerate(zz) if p[1] == "H")
    structural_floor = next((zz[j][2] for j in range(hi_idx - 1, -1, -1)
                             if zz[j][1] == "L"), None)   # prior confirmed HL = deep floor
    near_term = live["live_low"] if live["live_low"] is not None else structural_floor
    cur_depth = (last_high[2] - last["close"]) / last_high[2] * 100
    lo, hi = sig["depth_iqr"]
    uptrend = last["close"] > last["ema_50"] and last["ema_50"] > df["ema_50"][-20]
    out = {"cur_depth": cur_depth, "band": sig["depth_iqr"],
           "live_low": live["live_low"],
           "live_low_depth": live.get("depth_from_high_pct"),
           "near_term_invalidation": near_term,    # QUOTE THIS as the stop, not the floor
           "structural_floor": structural_floor,   # deeper break = full trend reversal
           "success_rate": sig["success_rate"], "uptrend": uptrend}
    if uptrend and lo <= cur_depth <= hi:
        out["label"] = "buyable-dip-now"
    elif uptrend and cur_depth < lo:
        out["label"] = "pullback-coming/wait"
        out["why"] = "near high, shallower than typical pullback band"
    else:
        out["label"] = "no-match"
    # turn gate: only an in-band live dip can be a buy — require the learned turn
    if trigger is not None and out["label"] == "buyable-dip-now":
        tr = live_turn(df, zz, trigger)            # Block 8c
        out["turn"] = tr
        if tr["turn_learnable"] is False or tr["confirmed"] is None:
            out["label"] = "buyable-dip-now/turn-unconfirmable"
        elif tr["confirmed"]:
            out["label"] = "buy-the-dip-turned"
        else:
            out["label"] = "wait-not-turned"
    return out
```

- [ ] **Step 2: Update the Block 8 prose to document the new labels**

In Block 8, after the existing paragraph that begins "`cur_depth` is measured off the latest
close.", append this sentence:

```markdown
When a `trigger` (Block 7b) is passed, the `buyable-dip-now` state is split by the live turn
(Block 8c): `buy-the-dip-turned` (the dip reproduced the stock's learned trigger — a buy),
`wait-not-turned` (in band but no turn yet — the falling-knife hold, quote the buy trigger),
or `buyable-dip-now/turn-unconfirmable` (trigger unlearnable / warm-up — low-confidence).
Without a `trigger` the original `buyable-dip-now` label is unchanged (backward compatible).
```

- [ ] **Step 3: Verify it's done**

Run: `grep -n "trigger=None\|buy-the-dip-turned\|wait-not-turned" .claude/skills/pullback-finder/references/building-blocks.md`
Expected: at least 3 matches (signature + both new labels).

---

## Task 4: Verify the three new/changed blocks on real data, then commit

**Inputs/Outputs:**
- Input: edited `building-blocks.md`, `market-data/prices/1h/`.
- Done-check: `/tmp/verify_blocks.py` runs clean, the turn gate fires, prints `OK turn blocks validated`.
- Checkpoint: commit `building-blocks.md`.

- [ ] **Step 1: Build and run the verification script**

Create `/tmp/verify_blocks.py` by concatenating, in order: **all Python code blocks** from
`.claude/skills/pullback-finder/references/building-blocks.md` (the `load`, `add_indicators`,
`fractal_flags`, `zigzag`, `pullback_events`, `anchor_for_low`, `outcome`, `signature`,
`learn_turn_trigger`, `current_state`, `live_pullback_low`, `live_turn` functions and their
`import polars as pl` / `from collections import Counter` lines), then append this driver:

```python
def _run(sym, interval="1h", k=6):
    df = add_indicators(load(sym, interval))
    zz = zigzag(fractal_flags(df, k))
    events = pullback_events(zz)
    for ev in events:
        try: ev.update(anchor_for_low(df, ev["low_ts"]))
        except ValueError: ev["anchor"] = "none"
        ev.update(outcome(df, ev))
    sig = signature(events)
    assert sig.get("confidence") == "ok", f"{sym}: need >=5 events, got {sig.get('n_events')}"
    trig = learn_turn_trigger(df, events)
    assert trig["turn_learnable"], f"{sym}: trigger not learnable"
    assert trig["learned_lift"] > 0, f"{sym}: learned_lift must be positive"
    st = current_state(df, zz, sig, trigger=trig)
    print(f"{sym:16} {st['label']:34} lift={trig['learned_lift']:.2f} "
          f"ema={trig['learned_reclaim_ema']} path={ (st.get('turn') or {}).get('path') }")
    return st["label"]

labels = [_run(s) for s in ["AEROFLEX.NS", "STYLAMIND.NS", "INOXWIND.NS", "SUZLON.NS", "KEI.NS"]]
gate = {"buy-the-dip-turned", "wait-not-turned", "buyable-dip-now/turn-unconfirmable"}
assert any(l in gate for l in labels), f"turn gate never fired across sample: {labels}"
# backward-compat: no trigger => original label vocabulary, no 'turn' key
df = add_indicators(load("AEROFLEX.NS", "1h")); zz = zigzag(fractal_flags(df, 6))
evs = pullback_events(zz)
for ev in evs:
    try: ev.update(anchor_for_low(df, ev["low_ts"]))
    except ValueError: ev["anchor"] = "none"
    ev.update(outcome(df, ev))
st0 = current_state(df, zz, signature(evs))
assert "turn" not in st0 and st0["label"] in {"buyable-dip-now","pullback-coming/wait","no-match"}, \
    "backward-compat broken: no-trigger call changed"
print("OK turn blocks validated")
```

Run: `.venv/bin/python /tmp/verify_blocks.py`

- [ ] **Step 2: Verify the output**

Expected: five `SYMBOL  <label> …` lines (labels are data-dependent; at least one is a
turn-gated label), then `OK turn blocks validated`. No traceback.
*(If a named symbol has drifted to `< 5` events or out of band and an assert trips on it,
swap it for any symbol from `ls market-data/prices/1h/` with enough history — the test is
that the gate fires across the sample and backward-compat holds, not specific per-symbol
labels.)*

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pullback-finder/references/building-blocks.md
git commit -m "feat(pullback-finder): learned rebound trigger blocks (7b, 8c) + turn-gated current_state

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Update `pullback-finder/SKILL.md` (workflow, output, hard rules)

**Inputs/Outputs:**
- Modify: `.claude/skills/pullback-finder/SKILL.md`.
- Done-check: the four edits below are present; grep confirms.
- Checkpoint: commit `SKILL.md`.

- [ ] **Step 1: Add the trigger to the single-symbol workflow**

In `## Workflow — single symbol`, replace step 5 and step 6 with:

```markdown
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
```

- [ ] **Step 2: Make BUY require the turn in the output shape**

In `## Output style`, replace the verdict header line of the Required shape (the
`**<SYMBOL> — <timeframe> → <BUY THE DIP | WAIT | AVOID>. …**` line) and add a turn line, so
the template reads:

```markdown
**<SYMBOL> — <timeframe> → <BUY THE DIP | WAIT (not turned) | AVOID>. <one-line reason>.**

<1–3 plain sentences: where price is vs its recent high, whether a dip is actually happening,
and — the key addition — whether the dip has shown this stock's own sign of a turn yet.>
```

Then, in the same section, after the "**What to watch for / what to do:**" paragraph, insert:

```markdown
**Turn check (the knife gate):** only call BUY THE DIP when the dip has reproduced this
stock's learned turn — lifted to about its usual ATR-bounce off the low, or genuinely
reclaimed the EMA its rebounds reclaim. If it has not turned yet, say **WAIT (not turned)**
and quote the **buy trigger** in ₹ ("turns on a close above ₹<trigger_ema_price>, or a lift
to ₹<trigger_lift_price>"). A dip still making fresh lows is a falling knife — never a buy.
```

- [ ] **Step 3: Add the hard rule**

In `## Hard rules`, add this bullet after the `n_events < 5` bullet:

```markdown
- **The turn is learned, never assumed.** Learn the rebound trigger per stock from its own
  winning dips (Block 7b) and confirm it live (Block 8c); a dip is BUY only once it
  reproduces that trigger (lift in the stock's own ATR **or** a genuine reclaim of its learned
  EMA — union). A live dip still printing fresh lows (no lift, no genuine reclaim) is
  `wait-not-turned`, the falling-knife hold, never a buy. `< 5` winning dips with an up-thrust
  → `turn-unconfirmable, low-confidence`; never invent a lift or an EMA.
```

- [ ] **Step 4: Verify + commit**

Run: `grep -n "learn_turn_trigger\|wait-not-turned\|knife gate\|turn-unconfirmable" .claude/skills/pullback-finder/SKILL.md`
Expected: ≥4 matches across the workflow, output, and hard-rules sections.

```bash
git add .claude/skills/pullback-finder/SKILL.md
git commit -m "docs(pullback-finder): document learned turn gate in workflow/output/rules

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Update `stock-screening/references/screening-blocks.md` (A6 recipe + A8 column)

**Inputs/Outputs:**
- Modify: `.claude/skills/stock-screening/references/screening-blocks.md`.
- Done-check: `/tmp/verify_render.py` writes a report to `/tmp/turn_test_out/` whose table has a `turn` column.
- Checkpoint: commit `screening-blocks.md`.

- [ ] **Step 1: Add the trigger to the Block A6 recipe**

In `## Block A6 — Stage-B recipe`, replace recipe item 7 (`sig = signature(events)` …) with:

```markdown
7. `sig = signature(events)` (Block 7). Learn the turn: `trigger = learn_turn_trigger(df,
   events, success_key="success_base")` (Block 7b — learn from the comparable @base winners
   tagged in step 6). Then `state = current_state(df, zz, sig, trigger=trigger)` (Block 8 —
   runs `live_turn`, Block 8c, internally). Read `state["turn"]`: `confirmed` (True/False/
   None), `path`, `cur_lift`, `learned_lift`, `reclaim_ema`, `trigger_lift_price`,
   `trigger_ema_price`. **The knife gate:** a BUY requires `state["turn"]["confirmed"] is
   True`; `False` → the WAIT/not-turned tier; `None` (unlearnable/warm-up/no live dip) →
   low-confidence (SPECULATIVE). For a not-turned name, the **buy-trigger price** to quote =
   the nearer reachable level: `min(p for p in [trigger_lift_price, trigger_ema_price] if p
   is not None)`.
```

- [ ] **Step 2: Add the `turn` column to the Block A8 renderer**

In Block A8, replace the `COLS = [...]` list with (adds `"turn"` after `"class"`):

```python
COLS = ["Symbol", "tier", "n", "usual dip%", "now off hi%", "live-lo dip%", "b@base",
        "b@learn (Δ)", "H≈days", "class", "turn", "vol-fade", "live high ₹ (+%)",
        "live low ₹ (−%)", "floor ₹ (−%)"]
```

Add this helper next to the other `_cell_*` helpers (e.g. after `_cell_vol`):

```python
def _cell_turn(r):
    if r["turn_confirmed"] is None:
        return "n/a"                                    # unlearnable / warm-up / no live dip
    if r["turn_confirmed"]:
        return "✓(" + ",".join(r["turn_path"]) + ")"    # which path(s) fired
    return f"— ₹{r['buy_trigger_price']}" if r["buy_trigger_price"] is not None else "—"
```

In `_md_row`, replace the `f"{r['recovery_class']}",` cell with the class **and** turn cells:

```python
        f"{r['recovery_class']}", _cell_turn(r),
```

In `_count_line`, add the new `WAIT` tier token to the `order` list so WAIT rows are counted
(place it before `WATCH`):

```python
    order = ["BUY", "PATIENT", "SPEC", "WAIT", "WATCH", "CAUTION", "AVOID"]
```

In the Block A8 prose listing the `row` dict keys, append these three keys to the documented
list: `turn_confirmed, turn_path, buy_trigger_price` (with a one-line note: "`turn_confirmed`
True/False/None from `state["turn"]`; `turn_path` the fired path list; `buy_trigger_price` the
nearer trigger ₹ for not-turned names, else `None`"). The WAIT/not-turned tier sets
`tier="WAIT"` (the short token used in `_count_line` and the `tier` column).

- [ ] **Step 3: Verify the renderer accepts the new column**

Create `/tmp/verify_render.py` by concatenating **all Python from Block A8** then appending:

```python
row = {"symbol":"TEST.NS","tier":"BUY","n":30,"band_lo":2.6,"band_hi":4.5,"now_off_high":3.9,
       "live_low_dip":3.9,"bounce_base":0.6,"bounce_learned":0.7,"delta":0.1,"H_stock":7,
       "trading_days":1.0,"clamped":False,"h_base":15,"recovery_class":"medium",
       "vol_fade_ratio":0.9,"fading":True,"live_low_price":100.0,"live_low_pct":-1.0,
       "floor_price":95.0,"floor_pct":-5.0,"live_high_price":110.0,"live_high_pct":8.6,
       "is_index":False,"caution":False,
       "turn_confirmed":True,"turn_path":["reclaim"],"buy_trigger_price":None}
wait = dict(row); wait.update(symbol="WAIT.NS", tier="WAIT", turn_confirmed=False,
            turn_path=[], buy_trigger_price=102.5)
disc = {"mode":"stable","overlap":0.9,"W_used":120,"bars_per_day":7,"h_base":15,
        "clamp_days":"0.5–10","excluded_short_history":3,"n_shortlisted":2}
p = write_report([row, wait], ["TEST.NS — BUY (medium): turned via reclaim …"], disc, "1h",
                 outdir="/tmp/turn_test_out")
txt = p.read_text()
assert "| turn |" in txt, "turn column header missing"
assert "✓(reclaim)" in txt and "— ₹102.5" in txt, "turn cells not rendered"
print("OK renderer validated:", p)
```

Run: `.venv/bin/python /tmp/verify_render.py`
Expected: `OK renderer validated: /tmp/turn_test_out/<…>-1h.md`. No traceback.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/stock-screening/references/screening-blocks.md
git commit -m "feat(stock-screening): compose learned turn in Stage B recipe + report turn column

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Update `stock-screening/SKILL.md` (Stage B/C, output, law, failures)

**Inputs/Outputs:**
- Modify: `.claude/skills/stock-screening/SKILL.md`.
- Done-check: the five edits below are present; grep confirms.
- Checkpoint: commit `SKILL.md`.

- [ ] **Step 1: Mention the turn in the Stage B workflow + Stage B section**

In `## Workflow — the two-stage funnel` step 2, after "the per-stock learned horizon
(`learn_horizon`, Block A7)." append:

```markdown
 Also learn the per-stock rebound trigger (`learn_turn_trigger`, Block 7b) and confirm it on
 the live dip (`live_turn`, Block 8c) — the falling-knife gate.
```

In `## Stage B — bespoke confirm (composes pullback-finder)`, append to the end of the
paragraph:

```markdown
 Stage B also learns each survivor's **rebound trigger** from its own winning dips (lift in
 its ATR + the EMA its rebounds reclaim) and checks whether the live dip has reproduced it —
 `turn confirmed` True/False/None. A BUY requires `True`.
```

- [ ] **Step 2: Add the turn gate to BUY and a new WAIT tier in Stage C**

In `## Stage C — tier + report`, in the **BUY THE DIP** bullet, change its condition line to
add the turn (insert "**turn confirmed**" into the requirements):

```markdown
- **BUY THE DIP** — price is *still in the dip now* (`now off high` is positive and inside
  the stock's own band), uptrend intact, live low above floor, `bounce@base` fair or better
  (≈ 0.5+), **and the turn is confirmed** (`state["turn"]["confirmed"] is True` — the live dip
  lifted to its learned ATR-bounce or genuinely reclaimed its learned EMA). Rank by
  `bounce@base` first, then prefer `fast`/`medium` recovery and a small `Δ`; a fading-volume
  dip and deepest-in-band break ties. Lead with the few highest-conviction names. Quote each
  pick's recovery class, expected hold, and **which turn path fired** (lift / reclaim).
```

Immediately after the BUY THE DIP bullet, insert a new tier bullet:

```markdown
- **WAIT / not-turned** — cleared depth + uptrend + floor + bounce, **but the turn is not
  confirmed** (`state["turn"]["confirmed"] is False`): in its own band yet still falling or
  basing, no sign of a turn. This is the falling-knife gate — **never a buy now**. Report it
  separately as the watchlist with its **buy trigger** ("turns on a close above ₹X, or a lift
  to ₹Y") and re-screen next bar.
```

In the **SPECULATIVE** bullet, append to its condition list:

```markdown
 , **or** the turn trigger is unlearnable (`confirmed is None` — `< 5` winning dips with an
  up-thrust; low-confidence).
```

- [ ] **Step 3: Add the `turn` column + ranked-line turn to Output style**

In `## Output style`, in the "**Footer table … columns:**" code block, replace the column
list so it includes `turn` after `recovery class`:

```
Symbol | n dips | usual dip % | now off high % | live-low dip % |
bounce@base | bounce@learned (Δ) | H_stock (≈D days) | recovery class | turn |
vol-fade | live high ₹ (+%) | live low ₹ (−%) | floor ₹ (−%)
```

Then, after the paragraph explaining `vol-fade`, add:

```markdown
`turn` shows the knife gate: `✓(path)` when confirmed (which of lift/reclaim fired), `— ₹X`
when not turned (the nearer buy-trigger price to reclaim), `n/a` when unlearnable. A BUY
always shows `✓`; a `—` row is WAIT, not a buy.
```

In the "**Ranked line (one per buy candidate):**" template, append a turn clause to the line:

```
SYMBOL — <action> (<recovery class>): dipping X% vs its usual Y% dip;
bounces ~Z% @base / ~Z'% on its own ~D-day clock (Δ +d); turned via <path>;
buy zone ₹A–B, wrong below ₹C (−X% from price)
```

- [ ] **Step 4: Add the trigger to "The law" learned-params list**

In `## The law — no frozen pattern constants`, in the first blockquote sentence, change the
parenthetical list of learned params to include the trigger:

```markdown
> Every **pattern** parameter (W, k, noise filter, depth bands, the recovery horizon
> `H_stock`, **and the rebound trigger — `learned_lift`, `learned_reclaim_ema`,
> `learned_turn_lag`**) is derived from or validated against the current data **at screen
> time** and disclosed in the output. None is a hardcoded constant trusted across runs,
> because the universe and each stock's behavior drift.
```

- [ ] **Step 5: Add failure-handling rows + disclosure**

In `## Failure handling`, add these two rows to the table:

```markdown
| Turn trigger unlearnable (< 5 winning dips with an up-thrust) | `turn = unconfirmable`; demote to SPECULATIVE/low-confidence; never invent a lift or EMA. |
| Live dip still at a fresh low (no lift, no genuine reclaim) | `wait-not-turned` → WAIT tier, never BUY (the knife gate). |
```

In `**Disclosures every run:**` (Output style), append to the list:

```markdown
; per stock the learned rebound trigger (`learned_lift` in ATR, `learned_reclaim_ema`,
`learned_turn_lag`) and how many winning dips it was learned from (or "turn-unconfirmable")
```

- [ ] **Step 6: Verify + commit**

Run: `grep -n "WAIT / not-turned\|turn is confirmed\|learned_reclaim_ema\|knife gate" .claude/skills/stock-screening/SKILL.md`
Expected: ≥4 matches across Stage C, output, law, and failures.

```bash
git add .claude/skills/stock-screening/SKILL.md
git commit -m "docs(stock-screening): turn-gate BUY, add WAIT tier, report column + law/failures

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: End-to-end screener verification on the 1h universe

**Inputs/Outputs:**
- Input: all edits committed; `market-data/prices/1h/`.
- Done-check: `/tmp/verify_e2e.py` runs the composed Stage A→B pipeline and confirms the gate splits in-band dips into turned vs not-turned with learned (non-constant) triggers.
- Checkpoint: none (read-only verification); report findings to the user.

- [ ] **Step 1: Build the end-to-end driver**

Create `/tmp/verify_e2e.py` by concatenating, in order: **all Python from**
`pullback-finder/references/building-blocks.md`, then **all Python from**
`stock-screening/references/screening-blocks.md` (Blocks A1–A8), then this driver:

```python
cal = calibrate_W("1h")
print("Stage A:", cal["mode"], "overlap", round(cal["overlap"],3),
      "W", cal["W_used"], "shortlist", len(cal["shortlist"]))
turned, not_turned, unconf, lifts = [], [], [], set()
for sym in cal["shortlist"]:
    try:
        df = add_indicators(load(sym, "1h"))
        k = choppiness_k(df.select("high","low","close"))["k"]
        zz = zigzag(fractal_flags(df, k))
        events = pullback_events(zz)   # up-leg guard is exercised in the real screen; not needed here
        for ev in events:
            try: ev.update(anchor_for_low(df, ev["low_ts"]))
            except ValueError: ev["anchor"] = "none"
            ev.update(outcome(df, ev, stop_pct=0.03, horizon=15))
            ev["success_base"] = ev.get("success")
        sig = signature(events)
        if sig.get("confidence") != "ok":
            continue
        trig = learn_turn_trigger(df, events, success_key="success_base")
        st = current_state(df, zz, sig, trigger=trig)
        lbl = st["label"]
        if lbl == "buy-the-dip-turned": turned.append(sym)
        elif lbl == "wait-not-turned": not_turned.append(sym)
        elif lbl == "buyable-dip-now/turn-unconfirmable": unconf.append(sym)
        if trig.get("turn_learnable"): lifts.add(round(trig["learned_lift"], 2))
    except Exception as e:
        print("skip", sym, type(e).__name__, e)
print("turned (BUY):", len(turned), turned[:8])
print("not-turned (WAIT):", len(not_turned), not_turned[:8])
print("turn-unconfirmable:", len(unconf), unconf[:8])
print("distinct learned_lift values (proof: per-stock, not a constant):", sorted(lifts)[:12])
assert len(lifts) >= 3, "learned_lift looks constant — trigger not per-stock"
print("OK e2e: turn gate live on the screener")
```

Run: `.venv/bin/python /tmp/verify_e2e.py`

- [ ] **Step 2: Verify the output**

Expected:
- A `Stage A:` line with a non-empty shortlist.
- Non-zero counts for **both** `turned (BUY)` and `not-turned (WAIT)` (the gate splits
  in-band dips both ways — this is the falling-knife filter working).
- `distinct learned_lift values …` shows **several different** numbers (e.g. `[1.72, 1.83,
  1.99, 2.03, …]`) — proof the trigger is learned per stock, never a constant.
- Final `OK e2e: turn gate live on the screener`. No traceback.

- [ ] **Step 3: Report to the user**

Summarize: shortlist size, how many BUY (turned) vs WAIT (not-turned), a couple of example
not-turned names with their buy-trigger, and the spread of `learned_lift` values proving
per-stock learning. Note that a full screen run (per `stock-screening` SKILL.md) will also
write the `output/<…>-1h.md` report with the new `turn` column.

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Spec §1 learned signature → Task 1 (`learn_turn_trigger`). ✓
- Spec §2 live test → Task 2 (`live_turn`), incl. genuine-reclaim fix found in validation. ✓
- Spec §3 verdict changes (pullback-finder) → Task 3 + Task 5. ✓
- Spec §3 verdict changes (stock-screening: BUY gate, WAIT tier, footer column) → Tasks 6 & 7. ✓
- Spec §4 scope/layout (block in pullback-finder, composed by screening) → Tasks 1-3 vs 6-7. ✓
- Spec §5 fixed-vs-learned ledger → enforced (only learned trigger added; 3% stop & H_base untouched). ✓
- Spec failure handling (unlearnable, fresh-low, warm-up) → Task 2 returns + Task 5/7 rules + Task 7 table. ✓
- Spec success criteria (knife→WAIT, lifted→BUY, thin→low-conf, screener drop, disclosed values) → Tasks 4 & 8 done-checks. ✓

**Placeholder scan:** none — all code is the validated implementation; no TBD/TODO.

**Naming/output consistency:** function names (`learn_turn_trigger`, `live_turn`,
`current_state(…, trigger=…)`), labels (`buy-the-dip-turned`, `wait-not-turned`,
`buyable-dip-now/turn-unconfirmable`), row keys (`turn_confirmed`, `turn_path`,
`buy_trigger_price`), and `success_key="success_base"` are identical across Tasks 1-8. ✓
