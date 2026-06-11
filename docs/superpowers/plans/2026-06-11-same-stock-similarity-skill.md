# Same-Stock Similarity Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a repository skill that deterministically finds up to 200 non-overlapping historical 10-day setups similar to one stock's latest setup.

**Architecture:** Initialize a new repository skill with one importable/CLI Polars script. The script loads exact daily prices and indicators through `talk-to-stock-data`, creates rolling-window feature vectors, applies hard context gates, calculates auditable hierarchical distances, greedily removes overlapping matches, and reports future outcomes. A focused repository test module validates feature semantics, gates, distance, selection, outcomes, and fail-fast behavior.

**Tech Stack:** Python 3.12, Polars, pytest, existing `talk-to-stock-data` helper, Codex skill-creator scripts

---

## File Map

- Create: `.agents/skills/find-similar-stock-setups/SKILL.md`
  - Concise agent workflow, mandatory semantics, script invocation, and output rules.
- Create: `.agents/skills/find-similar-stock-setups/agents/openai.yaml`
  - Generated UI metadata.
- Create: `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`
  - CLI, validation, Polars feature/distance pipeline, non-overlap selection, JSON output.
- Create: `tests/test_find_similar_stock_setups.py`
  - Deterministic unit/integration tests for the skill script.
- Modify: `tests/test_documentation.py`
  - Verify new skill references existing data contract and raw-price caveat.

Keep script below 800 lines and every function below 80 lines.

## Task 1: Initialize Skill And Define Public Contract

**Files:**
- Create: `.agents/skills/find-similar-stock-setups/SKILL.md`
- Create: `.agents/skills/find-similar-stock-setups/agents/openai.yaml`
- Create: `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`
- Create: `tests/test_find_similar_stock_setups.py`

- [ ] **Step 1: Initialize skill skeleton**

Run:

```bash
python /root/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  find-similar-stock-setups \
  --path .agents/skills \
  --resources scripts \
  --interface 'display_name=Find Similar Stock Setups' \
  --interface 'short_description=Find same-stock historical chart analogs' \
  --interface 'default_prompt=Use $find-similar-stock-setups to find historical setups similar to the latest setup for CHENNPETRO.NS.'
```

Expected: skill directory, `SKILL.md`, `agents/openai.yaml`, and `scripts/` exist.

- [ ] **Step 2: Write failing public-contract tests**

Create `tests/test_find_similar_stock_setups.py` with dynamic import matching
`tests/test_talk_to_stock_data.py`, then add:

```python
SCRIPT = Path(
    ".agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py"
)


def test_constants_define_fixed_version_one_semantics() -> None:
    assert similarity.WINDOW == 10
    assert similarity.MAX_MATCHES == 200
    assert similarity.FUTURE_PERIODS == (5, 10, 20, 30)
    assert similarity.CORPORATE_ACTION_THRESHOLD == 0.40
    assert similarity.SUBGROUPS == (
        "chart_shape",
        "pace",
        "candle_volatility",
        "volume",
        "trend_context",
        "momentum",
    )


def test_invalid_symbol_fails_fast() -> None:
    with pytest.raises(similarity.SimilarityError, match="symbol"):
        similarity.validate_symbol("")
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -v
```

Expected: FAIL because script contract is absent.

- [ ] **Step 4: Add public constants, error, result types, and CLI shell**

In `find_similar_setups.py`, define:

```python
WINDOW = 10
MAX_MATCHES = 200
FUTURE_PERIODS = (5, 10, 20, 30)
CORPORATE_ACTION_THRESHOLD = 0.40
SUBGROUPS = (
    "chart_shape",
    "pace",
    "candle_volatility",
    "volume",
    "trend_context",
    "momentum",
)


class SimilarityError(ValueError):
    """Raised when a similarity query cannot be completed."""


def validate_symbol(symbol: str) -> None:
    if not symbol or "/" in symbol or "\\" in symbol:
        raise SimilarityError(f"Invalid symbol: {symbol!r}")
```

Add `argparse` CLI requiring `--symbol`, `--prices-root`, and `--indicators-root`.
Do not provide fallback values. Configure detailed stderr logging and reserve stdout for
JSON output.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -v
python /root/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/find-similar-stock-setups
git add .agents/skills/find-similar-stock-setups tests/test_find_similar_stock_setups.py
git commit -m "feat: initialize similar stock setup skill"
```

Expected: tests and skill validation pass.

## Task 2: Build Window Features And Context Regimes

**Files:**
- Modify: `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`
- Modify: `tests/test_find_similar_stock_setups.py`

- [ ] **Step 1: Add deterministic fixture builder and failing feature tests**

Add a fixture producing at least 450 daily joined OHLCV/indicator rows. Include variants
for steady rise, late breakout, early spike, fall, and sideways paths. Add tests:

```python
def test_chart_features_preserve_direction_and_pace() -> None:
    features = similarity.build_window_features(pattern_frame())
    rows = features.select("pattern", "direction_regime", "pace_slope").collect()
    assert row(rows, "steady_rise")["direction_regime"] == "rising"
    assert row(rows, "fall")["direction_regime"] == "falling"
    assert row(rows, "sideways")["direction_regime"] == "sideways"
    assert row(rows, "early_spike")["pace_slope"] != row(rows, "late_breakout")[
        "pace_slope"
    ]


def test_extreme_move_window_is_flagged() -> None:
    result = similarity.build_window_features(extreme_move_frame()).collect()
    assert result["has_corporate_action_jump"].any()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -k "features or extreme" -v
```

Expected: FAIL because feature pipeline does not exist.

- [ ] **Step 3: Implement rolling feature pipeline**

Implement focused helpers named `add_base_expressions`, `add_path_features`,
`add_scalar_features`, `add_context_regimes`, and `build_window_features`. Every helper
accepts and returns `pl.LazyFrame`; `build_window_features` composes the other four.

Use Polars rolling/window expressions only. Build fixed-length list/vector columns for
each subgroup. Preserve signed normalized OHLC paths, returns, slope, acceleration,
candle features, volume features, all approved indicator paths, and hard-gate regime
columns. Define:

```text
sideways: abs(10-day close return) < 0.02
rising: 10-day close return >= 0.02
falling: 10-day close return <= -0.02
```

Calculate ATR terciles from candidate history. Reject incomplete windows and flag any
window whose absolute daily close return exceeds `0.40`.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -k "features or extreme" -v
ruff check .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git add .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git commit -m "feat: build stock setup feature vectors"
```

Expected: focused tests and Ruff pass.

## Task 3: Implement Hierarchical Distance And Hard Gates

**Files:**
- Modify: `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`
- Modify: `tests/test_find_similar_stock_setups.py`

- [ ] **Step 1: Write failing gate and distance tests**

Add:

```python
def test_hard_gates_reject_context_mismatch() -> None:
    candidates = similarity.apply_context_gates(context_fixture()).collect()
    assert candidates["candidate_id"].to_list() == ["matching"]


def test_signed_direction_differences_cannot_cancel() -> None:
    result = similarity.calculate_distances(distance_fixture()).collect()
    assert score(result, "same_direction") < score(result, "opposite_direction")


def test_each_subgroup_remains_visible() -> None:
    result = similarity.calculate_distances(distance_fixture()).collect()
    assert {f"{name}_distance" for name in similarity.SUBGROUPS}.issubset(
        result.columns
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -k "gates or distance or subgroup" -v
```

Expected: FAIL because gating/distance functions do not exist.

- [ ] **Step 3: Implement hard gates and distance**

Implement `split_latest_and_candidates`, returning latest and candidate lazy frames;
`apply_context_gates`, returning only exact regime matches; `standardize_components`,
returning standardized component columns; and `calculate_distances`, returning subgroup
and combined distance columns.

Gate exact matches for direction, EMA-50/EMA-200 sides, ATR tercile, and yearly-position
third. Standardize each feature component from candidate-history means/population
standard deviations. Raise `SimilarityError` for nonfinite or zero-variance required
components. Calculate subgroup MSEs, scale each by surviving-candidate median, and set:

```python
combined_distance = pl.mean_horizontal(
    [pl.col(f"{group}_distance") for group in SUBGROUPS]
)
```

Raise clear errors for zero subgroup median or no surviving candidates.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -k "gates or distance or subgroup" -v
ruff check .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git add .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git commit -m "feat: calculate hierarchical setup distance"
```

Expected: focused tests and Ruff pass.

## Task 4: Select Non-Overlapping Matches And Calculate Outcomes

**Files:**
- Modify: `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`
- Modify: `tests/test_find_similar_stock_setups.py`

- [ ] **Step 1: Write failing selection and outcome tests**

Add:

```python
def test_select_matches_removes_overlaps_and_returns_available_count() -> None:
    selected = similarity.select_non_overlapping(ranked_fixture(), limit=200)
    assert selected.height == 3
    assert no_windows_overlap(selected)


def test_future_outcomes_match_hand_calculation() -> None:
    result = similarity.attach_future_outcomes(outcome_fixture()).collect()
    match = result.row(0, named=True)
    assert match["return_5"] == pytest.approx(0.05)
    assert match["mfe_30"] == pytest.approx(0.12)
    assert match["mae_30"] == pytest.approx(-0.04)
    assert match["max_close_drawdown_30"] == pytest.approx(-0.06)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -k "overlap or outcomes" -v
```

Expected: FAIL because selection/outcome functions do not exist.

- [ ] **Step 3: Implement future outcomes and final selection**

Implement Polars `attach_future_outcomes()` for close returns, MFE, MAE, and close
drawdown. Exclude candidates without 30 future sessions before matching.

Implement `select_non_overlapping()` as the only row loop:

```python
def select_non_overlapping(ranked: pl.DataFrame, limit: int) -> pl.DataFrame:
    selected: list[dict[str, object]] = []
    occupied: list[tuple[int, int]] = []
    for row in ranked.iter_rows(named=True):
        interval = (row["window_start_index"], row["window_end_index"])
        if any(interval[0] <= end and start <= interval[1] for start, end in occupied):
            continue
        selected.append(row)
        occupied.append(interval)
        if len(selected) == limit:
            break
    if not selected:
        raise SimilarityError("No non-overlapping historical matches survived")
    return pl.DataFrame(selected, schema=ranked.schema)
```

Keep candidates sorted by combined distance then end date before selection.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -k "overlap or outcomes" -v
ruff check .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git add .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git commit -m "feat: select matches and report future outcomes"
```

Expected: focused tests and Ruff pass.

## Task 5: Complete End-To-End Query And JSON Output

**Files:**
- Modify: `.agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py`
- Modify: `tests/test_find_similar_stock_setups.py`

- [ ] **Step 1: Write failing end-to-end and fail-fast tests**

Add temporary Parquet integration fixtures and tests:

```python
def test_find_similar_setups_returns_auditable_result(tmp_path: Path) -> None:
    prices_root, indicators_root = write_similarity_data(tmp_path)
    result = similarity.find_similar_setups(
        "TCS.NS", prices_root, indicators_root
    )
    assert result["metadata"]["source_interval"] == "1d"
    assert result["metadata"]["match_count"] <= 200
    assert result["matches"]
    assert all("combined_distance" in row for row in result["matches"])
    assert all("chart_shape_distance" in row for row in result["matches"])


@pytest.mark.parametrize("case", ["missing_symbol", "short_history", "latest_jump"])
def test_find_similar_setups_fails_clearly(tmp_path: Path, case: str) -> None:
    prices_root, indicators_root = write_invalid_case(tmp_path, case)
    with pytest.raises(similarity.SimilarityError):
        similarity.find_similar_setups("TCS.NS", prices_root, indicators_root)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -k "auditable or fails_clearly" -v
```

Expected: FAIL because orchestration is incomplete.

- [ ] **Step 3: Implement orchestration and serialization**

Implement `load_symbol_frame` to return one-symbol exact-daily joined lazy data,
`summarize_matches` to return aggregate outcome dictionaries, `find_similar_setups` to
return the complete serializable result dictionary, and `main` to parse required CLI
arguments and print JSON.

Import `load_prices_with_indicators()` from `talk-to-stock-data`. Select one symbol and
exact `1d`. Log input counts, exclusion counts, gate counts, and selected count. Collect
the ranked candidate result once, perform deterministic non-overlap selection, then emit
JSON containing metadata, rejection counts, matches, subgroup scores, and aggregate
outcomes. Serialize timestamps as ISO-8601 strings.

- [ ] **Step 4: Run end-to-end tests and commit**

Run:

```bash
pytest tests/test_find_similar_stock_setups.py -v
ruff check .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git add .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
git commit -m "feat: run same-stock similarity queries"
```

Expected: all similarity tests and Ruff pass.

## Task 6: Write Skill Instructions And Documentation Checks

**Files:**
- Modify: `.agents/skills/find-similar-stock-setups/SKILL.md`
- Modify: `.agents/skills/find-similar-stock-setups/agents/openai.yaml`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Write failing documentation assertions**

Add:

```python
def test_similarity_skill_documents_required_contract() -> None:
    text = Path(".agents/skills/find-similar-stock-setups/SKILL.md").read_text()
    for required in [
        "same stock",
        "10-day",
        "non-overlapping",
        "raw, unadjusted",
        "combined distance",
        "subgroup",
        "not a probability",
        "find_similar_setups.py",
    ]:
        assert required in text
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_documentation.py::test_similarity_skill_documents_required_contract -v
```

Expected: FAIL until generated placeholder `SKILL.md` is replaced.

- [ ] **Step 3: Write concise skill workflow**

Replace `SKILL.md` frontmatter with:

```yaml
---
name: find-similar-stock-setups
description: Find same-stock historical daily setups similar to a symbol's latest 10-day chart using hierarchical chart, pace, candle, volume, trend-context, and momentum distances. Use when asked for historical analogs, similar chart setups, matching past scenarios, or subsequent outcomes for one stock.
---
```

Body must instruct agent to:

1. Invoke `talk-to-stock-data` conventions.
2. Run bundled script with explicit roots and symbol.
3. Present metadata, rejection counts, closest matches, subgroup distances, and outcome
   summary.
4. State similarity is not probability and prices are raw/unadjusted.
5. Never silently relax gates, overlap windows, or invent missing data.

Regenerate metadata:

```bash
python /root/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py \
  .agents/skills/find-similar-stock-setups \
  --interface 'display_name=Find Similar Stock Setups' \
  --interface 'short_description=Find same-stock historical chart analogs' \
  --interface 'default_prompt=Use $find-similar-stock-setups to find historical setups similar to the latest setup for CHENNPETRO.NS.'
```

- [ ] **Step 4: Validate skill and commit**

Run:

```bash
pytest tests/test_documentation.py::test_similarity_skill_documents_required_contract -v
python /root/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/find-similar-stock-setups
git add .agents/skills/find-similar-stock-setups tests/test_documentation.py
git commit -m "docs: teach same-stock similarity workflow"
```

Expected: documentation test and skill validation pass.

## Task 7: Full Verification And Forward Test

**Files:**
- Modify no files unless verification exposes a defect.

- [ ] **Step 1: Verify line and function limits**

Run:

```bash
wc -l .agents/skills/find-similar-stock-setups/SKILL.md \
  .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py
ruff check .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  tests/test_find_similar_stock_setups.py tests/test_documentation.py
```

Expected: each file below 800 lines; Ruff passes. Inspect function lengths and split any
function exceeding 80 lines.

- [ ] **Step 2: Run full repository tests**

Run:

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 3: Run real-symbol forward tests**

Run:

```bash
python .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  --symbol CHENNPETRO.NS \
  --prices-root market-data/prices \
  --indicators-root market-data/indicators > /tmp/chennpetro-similar.json

python .agents/skills/find-similar-stock-setups/scripts/find_similar_setups.py \
  --symbol POWERINDIA.NS \
  --prices-root market-data/prices \
  --indicators-root market-data/indicators > /tmp/powerindia-similar.json
```

Expected: both commands exit `0`; JSON reports non-overlapping matches, six subgroup
distances, outcomes, exact daily provenance, and raw-price warning.

- [ ] **Step 4: Validate skill and inspect repository state**

Run:

```bash
python /root/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/find-similar-stock-setups
git status --short
git log --oneline -7
```

Expected: skill validation passes; only intentional changes remain.
