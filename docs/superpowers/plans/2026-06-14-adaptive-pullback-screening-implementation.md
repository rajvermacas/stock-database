# Adaptive Pullback Screening and Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the maximum-recall learned prefilter, full-universe orchestration, ranking, reporting, CLI, and skill integration on top of the completed adaptive single-stock learner.

**Architecture:** Reuse the `stock_data.pullback` core built by `2026-06-14-adaptive-pullback-core-implementation.md`. Every valid stock learns a lightweight prefilter from its own raw profitable-opportunity labels; only survivors run the full learner. Independent results are ranked by uncertainty-adjusted probability-weighted expected raw return and exposed through a read-only CLI used by both pullback skills.

**Tech Stack:** Python 3.12, Polars, NumPy, SciPy, ruptures, Pydantic, Typer, pytest, Ruff.

**Prerequisite:** Complete every task in
`docs/superpowers/plans/2026-06-14-adaptive-pullback-core-implementation.md`.

**Invariant:** The fixed 3% stop from actual next-bar-open entry remains unchanged. The
prefilter and universe layer must not introduce any shared behavioral threshold.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/stock_data/pullback/prefilter.py` | Per-stock lexicographic maximum-recall prefilter |
| `src/stock_data/pullback/screen.py` | Shared universe gate, parallel workers, ranking |
| `src/stock_data/pullback/report.py` | JSON-safe records and Markdown reports |
| `src/stock_data/pullback/cli.py` | Required-argument `stock-pullback` CLI |

Keep every file below 800 lines and every function below 80 lines.

### Task 1: Maximum-Recall Per-Stock Prefilter

**Files:**
- Create: `src/stock_data/pullback/prefilter.py`
- Create: `tests/pullback/test_prefilter.py`

- [ ] **Step 1: Write lexicographic prefilter tests**

```python
def test_prefilter_selects_maximum_recall_before_pass_rate() -> None:
    selected = select_prefilter(rules)
    assert selected.recall == max(rule.recall for rule in rules)
    assert selected.pass_rate == min(
        rule.pass_rate for rule in rules if rule.recall == selected.recall
    )


def test_prefilter_uses_pass_all_when_it_alone_has_maximum_recall() -> None:
    selected = select_prefilter((pass_all_rule, lower_recall_rule))
    assert selected == pass_all_rule
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_prefilter.py -v`

Expected: FAIL because prefilter learning does not exist.

- [ ] **Step 3: Implement lightweight causal prefilter**

Train single-feature and Pareto-composed rules from the stock's raw profitable-opportunity
labels. Evaluate them walk-forward. Select lexicographically by:

1. maximum out-of-sample recall;
2. minimum pass rate;
3. minimum number of feature comparisons required at evaluation time.

Feature-comparison count is a deterministic latency proxy, not a behavioral threshold.
There is no minimum acceptable recall. If only pass-all attains maximum recall, use
pass-all for that stock.

- [ ] **Step 4: Log learned prefilter evidence**

Log symbol, candidate-rule count, selected feature bands, out-of-sample recall, pass rate,
and comparison count. Do not log or store a cross-stock fallback.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pullback/test_prefilter.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_data/pullback/prefilter.py tests/pullback/test_prefilter.py
git commit -m "feat(pullback): add learned maximum-recall prefilter"
```

### Task 2: Universe Screening, Ranking, and Parallelism

**Files:**
- Create: `src/stock_data/pullback/screen.py`
- Create: `tests/pullback/test_screen.py`

- [ ] **Step 1: Write universe flow tests**

Assert:

- invalid and stale symbols are excluded and disclosed;
- prefilter rejects do not invoke `learn_stock`;
- survivors invoke the full learner;
- eligible stocks rank by uncertainty-adjusted probability-weighted expected raw return;
- parallel and sequential results are identical;
- every run relearns each valid stock's prefilter.

```python
def test_prefilter_reject_does_not_run_full_learner(mocker, universe) -> None:
    learn = mocker.patch("stock_data.pullback.screen.learn_stock")
    result = screen_universe(universe)
    assert rejected_symbol not in {call.args[0] for call in learn.call_args_list}
    assert rejected_symbol in result.prefilter_rejections


def test_ranking_uses_adjusted_expected_return(screen_result) -> None:
    assert [row.symbol for row in screen_result.ranked] == ["HIGH.NS", "LOW.NS"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_screen.py -v`

Expected: FAIL because universe screening does not exist.

- [ ] **Step 3: Implement shared scan and per-stock workers**

Use the quality module's shared lazy scan, then load each valid symbol once. Derive worker
count from available CPUs with `os.process_cpu_count()`; this is a resource decision, not
a behavioral parameter. Use `ProcessPoolExecutor` only after the shared gate. Preserve
stable symbol ordering before ranking.

Screen flow:

```python
quality = validate_universe(prices_root, interval)
prefiltered = run_prefilters(quality.valid_symbols)
decisions = run_full_learners(prefiltered.survivors)
return rank_decisions(quality, prefiltered, decisions)
```

- [ ] **Step 4: Implement ranking**

Rank only non-abstaining eligible decisions by their independently learned
uncertainty-adjusted probability-weighted expected raw return. Preserve all excluded,
rejected, avoided, and abstained stocks in the audit result.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pullback/test_screen.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_data/pullback/screen.py tests/pullback/test_screen.py
git commit -m "feat(pullback): screen and rank the stock universe"
```

### Task 3: Reporting and Required-Argument CLI

**Files:**
- Create: `src/stock_data/pullback/report.py`
- Create: `src/stock_data/pullback/cli.py`
- Create: `tests/pullback/test_report.py`
- Create: `tests/pullback/test_cli.py`
- Modify: `pyproject.toml`
- Modify: `COMMANDS.md`
- Modify: `README.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Write report and CLI tests**

Test that Markdown and JSON disclose:

- selected stock-specific parameters;
- detection timestamp and next-open entry status;
- actual entry and fixed 3% stop when available;
- learned target and horizon;
- current/similar regime evidence;
- uncertainty-adjusted expected raw return;
- prior-high recovery probability;
- exclusions, prefilter counts, abstentions, and as-of timestamp.

```python
def test_markdown_discloses_fixed_stop_and_learned_parameters(screen_result) -> None:
    text = render_markdown(screen_result)
    assert "3% stop" in text
    assert "learned horizon" in text
    assert "abstained" in text


def test_json_is_round_trip_safe(screen_result) -> None:
    assert json.loads(render_json(screen_result))["as_of"] == screen_result.as_of.isoformat()
```

CLI commands must require every argument:

```text
stock-pullback screen --prices-root PATH --interval 1h --output markdown
stock-pullback analyze --prices-root PATH --interval 1h --symbol BALAMINES.NS --output json
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pullback/test_report.py tests/pullback/test_cli.py -v`

Expected: FAIL because reporting and CLI do not exist.

- [ ] **Step 3: Implement reports and CLI**

Add:

```toml
stock-pullback = "stock_data.pullback.cli:app"
```

Reject unsupported output types, missing intervals, missing roots, and missing symbols.
Configure detailed logging through the existing logging module. CLI analysis remains
read-only against prices.

- [ ] **Step 4: Update user documentation**

Document that all behavioral parameters are relearned per stock per run; the fixed 3%
stop is the sole trading invariant.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pullback/test_report.py tests/pullback/test_cli.py tests/test_documentation.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml COMMANDS.md README.md src/stock_data/pullback tests/pullback tests/test_documentation.py
git commit -m "feat(pullback): add adaptive screening reports and CLI"
```

### Task 4: Replace Grammar Skills with Engine Workflows

**Files:**
- Modify: `.agents/skills/stock-screening/SKILL.md`
- Modify: `.agents/skills/stock-screening/references/screening-blocks.md`
- Modify: `.agents/skills/pullback-finder/SKILL.md`
- Modify: `.agents/skills/pullback-finder/references/building-blocks.md`
- Modify: `.agents/skills/pullback-finder/references/worked-example.md`
- Modify: `.agents/skills/pullback-finder/references/data.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Write skill-contract documentation tests**

Require both skills to document:

- invocation through `stock-pullback`;
- per-run per-stock relearning;
- no shared behavioral thresholds;
- next-bar-open entry;
- fixed 3% stop;
- learned horizon and target;
- causal walk-forward;
- maximum-recall learned prefilter;
- abstention.

```python
def test_pullback_skills_use_adaptive_engine() -> None:
    text = Path(".agents/skills/stock-screening/SKILL.md").read_text()
    assert "stock-pullback screen" in text
    assert "next-bar-open" in text
    assert "fixed 3% stop" in text
    assert "W={60,120,240}" not in text
```

- [ ] **Step 2: Run documentation test and verify failure**

Run: `pytest tests/test_documentation.py -v`

Expected: FAIL because the skills still prescribe the old grammar.

- [ ] **Step 3: Rewrite skills as thin workflows**

Remove instructions to paste bespoke heredocs or use fixed `W`, `k`, event-count,
horizon, or tier thresholds. Keep mandatory timeframe input and read-only market-data
rules. The stock-screening skill invokes `stock-pullback screen`; pullback-finder invokes
`stock-pullback analyze`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_documentation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .agents/skills tests/test_documentation.py
git commit -m "docs(skills): use adaptive pullback learning engine"
```

### Task 5: Adversarial, Real-Data, Performance, and Final Verification

**Files:**
- Create: `tests/pullback/test_adversarial.py`
- Create: `tests/pullback/test_real_data_smoke.py`
- Create: `tests/pullback/test_performance.py`

- [ ] **Step 1: Add adversarial tests**

Cover flat prices, tied extrema, gaps, sparse/zero volume, missing bars, duplicate bars,
short histories, stale symbols, regime transitions, incomplete outcomes, same-bar
stop/target, parameter ties, and histories with no profitable stable setup.

```python
@pytest.mark.parametrize("case", adversarial_price_cases())
def test_adversarial_history_never_forces_a_buy(case) -> None:
    result = learn_stock(case.prices)
    assert result.decision in case.allowed_decisions
```

- [ ] **Step 2: Add real-data smoke tests**

Use a small checked-in-independent subset from existing `market-data/prices/1h` when
available. Assert:

- BALAMINES and TMB may learn different parameter sets;
- every non-pending entry equals an observed next-bar open;
- every stop equals entry multiplied by `0.97`;
- repeated runs over identical data return identical auditable results;
- no stock receives another stock's parameter set by construction.

Skip only when market-data is absent; do not fabricate a passing result.

```python
def test_real_entries_and_stops_are_observed() -> None:
    result = analyze_real_symbol("BALAMINES.NS", "1h")
    for trade in result.audit_trades:
        assert trade.entry_price == trade.prices["open"][trade.entry_index]
        assert trade.stop_price == pytest.approx(trade.entry_price * 0.97)
```

- [ ] **Step 3: Add performance regression test**

Benchmark a representative subset and assert the prefilter reduces full-learner calls
whenever its learned maximum-recall rule can do so. Assert shared universe validation
uses one lazy collection. Do not enforce a fixed wall-clock threshold.

```python
def test_prefilter_reduces_full_learner_calls_when_possible(instrumented_screen) -> None:
    result = instrumented_screen.run()
    assert result.full_learner_calls == len(result.prefilter_survivors)
    assert result.full_learner_calls <= result.valid_symbol_count
```

- [ ] **Step 4: Run the complete verification suite**

Run:

```bash
pytest -v
ruff check src tests
ruff format --check src tests
find src/stock_data/pullback tests/pullback -type f -name '*.py' -print0 | xargs -0 wc -l
```

Expected: all tests and lint pass; every file is below 800 lines.

- [ ] **Step 5: Audit function lengths**

Run:

```bash
.venv/bin/python - <<'PY'
import ast
from pathlib import Path

bad = []
for path in [*Path("src/stock_data/pullback").glob("*.py"), *Path("tests/pullback").glob("*.py")]:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > 80:
                bad.append((str(path), node.name, length))
if bad:
    raise SystemExit(bad)
PY
```

Expected: exit code `0`.

- [ ] **Step 6: Run live read-only CLI smoke**

Run:

```bash
stock-pullback analyze --prices-root market-data/prices --interval 1h --symbol BALAMINES.NS --output json
stock-pullback screen --prices-root market-data/prices --interval 1h --output markdown
```

Expected: both commands complete read-only, disclose as-of/data exclusions, and either
select one stock-specific parameter set or explicitly abstain.

- [ ] **Step 7: Commit**

```bash
git add tests/pullback
git commit -m "test(pullback): verify causal adaptive learner end to end"
```

---

## Spec Coverage Audit

| Approved requirement | Implemented by |
|---|---|
| High-recall learned prefilter against raw profitable opportunities | Task 1 |
| Structural quality exclusions before prefilter | Task 2 plus core quality module |
| Full learner only for prefilter survivors | Task 2 |
| Universe ranking by uncertainty-adjusted expected raw return | Task 2 |
| Read-only JSON and Markdown reporting | Task 3 |
| Skills invoke production engine instead of fixed grammar | Task 4 |
| Causal, adversarial, real-data, and performance verification | Task 5 |
