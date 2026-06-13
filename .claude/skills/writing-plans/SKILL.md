---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before starting implementation or execution
---

# Writing Plans

## Overview

Write comprehensive plans assuming the worker has zero context for this work and questionable taste. Document everything they need to know: which files or artifacts to touch for each task, the actual content, how to verify each step is done, any docs they might need to check. Give them the whole plan as bite-sized tasks. DRY. YAGNI. KISS. Frequent checkpoints.

Assume they are skilled, but know almost nothing about our toolset or problem domain.

**Announce at start:** "I'm using the writing-plans skill to create the plan."

**Save plans to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
- (User preferences for plan location override this default)

This plan markdown is the **source of truth** for execution — whether that's building a feature or running a workflow.

## Scope Check

If the spec covers multiple independent subsystems or workstreams, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest breaking this into separate plans — one per subsystem/workstream. Each plan should produce a working, verifiable result on its own.

## Structure / Decomposition

Before defining tasks, map out the pieces and what each one is responsible for. This is where decomposition decisions get locked in.

- For **software**: which files will be created or modified and what each is responsible for.
- For a **general workflow**: which phases, steps, or artifacts exist and what each produces.
- Design units with clear boundaries and well-defined interfaces. Each unit should have one clear responsibility.
- You reason best about work you can hold in context at once, and your edits are more reliable when units are focused. Prefer smaller, focused units over large ones that do too much.
- Things that change together should live together. Split by responsibility, not by technical layer.
- In existing material, follow established patterns. If the existing structure uses large units, don't unilaterally restructure - but if a unit you're touching has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

## Bite-Sized Task Granularity

**Each task follows the same shape, regardless of work type:**
- **Do the action** - write the code, draft the section, send the request, configure the setting - one concrete action (2-5 minutes)
- **Verify it's done** - confirm the action produced the intended result
- **Checkpoint** - commit, save, or record completion

A step is one of these actions. Keep steps small and concrete.

**Verification scales to the work:**
- Default to a lightweight **done-check**: a concrete, observable signal that the step is complete (a command's output, a file exists, a value matches, a reviewer signs off, a link resolves).
- Add **automated tests only when** the user requests TDD, or when correctness is non-obvious and a test is the cheapest reliable check. Don't make "write a failing test" the default spine of every task.

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Project Name] Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to carry out this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this produces]

**Approach:** [2-3 sentences about the approach]

**Tools / Inputs:** [Key technologies, libraries, sources, or resources]

---
```

## Task Structure

Each task declares its inputs and outputs, then walks through do → verify → checkpoint. Show the actual content for each step — code for software, concrete instructions/content for a workflow.

**Software example:**

````markdown
### Task N: [Component Name]

**Inputs/Outputs:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Done-check: `tests/exact/path/to/test.py` (or a command whose output confirms success)

- [ ] **Step 1: Write the implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 2: Verify it's done**

Run: `pytest tests/path/test.py::test_name -v` (or another concrete done-check)
Expected: PASS
*(Add a failing-test-first cycle here only if the user asked for TDD or correctness is non-obvious.)*

- [ ] **Step 3: Commit**

```bash
git add src/path/file.py
git commit -m "feat: add specific feature"
```
````

**General workflow example:**

````markdown
### Task N: [Step Name]

**Inputs/Outputs:**
- Input: `docs/research/sources.md`
- Output: `docs/draft/section-2.md`
- Done-check: section covers all 3 required points, links resolve

- [ ] **Step 1: Do the action**

Draft section 2 covering: [point A], [point B], [point C].
Use [source X] for the figures; keep it under 400 words.

- [ ] **Step 2: Verify it's done**

Confirm: all three points present, every link resolves, word count under 400.

- [ ] **Step 3: Checkpoint**

Save `docs/draft/section-2.md` and commit:
```bash
git add docs/draft/section-2.md
git commit -m "draft: section 2"
```
````

## No Placeholders

Every step must contain the actual content the worker needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Verify the above" (without saying what the concrete done-check is)
- "Similar to Task N" (repeat the content — the worker may be reading tasks out of order)
- Steps that describe what to do without showing how (concrete content required — code for code steps, explicit instructions for workflow steps)
- References to types, functions, artifacts, or outputs not defined in any task

## Remember
- Exact paths and names always
- Complete content in every step — if a step changes something, show what it changes
- Concrete done-checks with expected results
- DRY, YAGNI, KISS frequent checkpoints

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and check the plan against it. This is a checklist you run yourself — not a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the patterns from the "No Placeholders" section above. Fix them.

**3. Naming/output consistency:** Do the names, signatures, artifacts, and outputs you used in later tasks match what you defined in earlier tasks? A unit called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 — or an output `section-2.md` in one task and `sec2.md` in another — is a bug.

If you find issues, fix them inline. No need to re-review — just fix and move on. If you find a spec requirement with no task, add the task.

## Execution Handoff

After saving the plan, offer the execution choice based on work type:

**"Plan complete and saved to `docs/superpowers/plans/<filename>.md`. This plan is the source of truth for the next step.**

- **Feature/software:** hand off to implementation via executing-plans.
- **General workflow:** hand off to executing-plans to carry out the steps.

**Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.**