---
name: brainstorming
description: "You MUST use this before any creative work - creating features, building components, building workflows, designing processes, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation or execution."
---

# Brainstorming Ideas Into Designs or Workflows

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the current project context, then ask questions one at a time to refine the idea. Once you understand what you're building, present the design and get user approval.

<HARD-GATE>
Do NOT invoke any implementation skill, produce any deliverable, scaffold any project, or take any implementation/execution action until you have presented a design and the user has approved it. This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

## Anti-Pattern: "This Is Too Simple To Need A Design"

Every project goes through this process. A todo list, a single-function utility, a one-off workflow, a config change — all of them. "Simple" projects are where unexamined assumptions cause the most wasted work. The design can be short (a few sentences for truly simple projects), but you MUST present it and get approval.

## Checklist

You MUST create a task for each of these items and complete them in order:

1. **Explore project context** — check existing files, docs, prior work, recent commits, or current state
2. **Identify work type** — software (feature/component/system) or general workflow (process, plan, research, content, ops). This determines which design and plan machinery applies later.
3. **Ask clarifying questions** — one at a time, understand purpose/constraints/success criteria
4. **Propose 2-3 approaches** — with trade-offs and your recommendation
5. **Present design** — in sections scaled to their complexity, get user approval after each section
6. **Write design doc** — save to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and commit
7. **Spec self-review** — quick inline check for placeholders, contradictions, ambiguity, scope (see below)
8. **User reviews written spec** — ask user to review the spec file before proceeding
9. **Transition to implementation** — invoke writing-plans skill to create implementation/execution plan

## The Process

**Understanding the idea:**

- Check out the current project state first (files, docs, recent commits, or whatever artifacts already exist)
- Early on, settle the **work type**: is this software (a feature, component, or system) or a general workflow (a process, plan, research effort, content piece, or operational runbook)? You don't need a separate question for this if it's obvious from the request — just note it, since it scales the rest of the design.
- Before asking detailed questions, assess scope: if the request describes multiple independent subsystems or workstreams (e.g., "build a platform with chat, file storage, billing, and analytics" or "run our whole quarterly launch"), flag this immediately. Don't spend questions refining details of a project that needs to be decomposed first.
- If the project is too large for a single spec, help the user decompose into sub-projects: what are the independent pieces, how do they relate, what order should they be built or run? Then brainstorm the first sub-project through the normal design flow. Each sub-project gets its own spec → plan → implementation/execution cycle.
- For appropriately-scoped projects, ask questions one at a time to refine the idea
- Prefer multiple choice questions when possible, but open-ended is fine too
- Only one question per message - if a topic needs more exploration, break it into multiple questions
- Focus on understanding: purpose, constraints, success criteria

**Exploring approaches:**

- Propose 2-3 different approaches with trade-offs
- Present options conversationally with your recommendation and reasoning
- Lead with your recommended option and explain why

**Presenting the design:**

- Once you believe you understand what you're building, present the design
- Scale each section to its complexity: a few sentences if straightforward, up to 200-300 words if nuanced
- Ask after each section whether it looks right so far
- Cover: structure, components/steps, flow, failure handling, and how success is verified
- Be ready to go back and clarify if something doesn't make sense

**Design for isolation and clarity:**

- Break the work into smaller parts that each have one clear purpose, communicate through well-defined interfaces (inputs and outputs), and can be understood and verified independently
- For each part, you should be able to answer: what does it do, how do you use it, and what does it depend on?
- Can someone understand what a part does without reading its internals? Can you change the internals without breaking what depends on it? If not, the boundaries need work.
- Smaller, well-bounded parts are also easier for you to work with - you reason better about work you can hold in context at once, and your edits are more reliable when units are focused. When a part grows large, that's often a signal that it's doing too much.

**Working with existing material or systems:**

- Explore the current structure before proposing changes. Follow existing patterns and conventions.
- Where existing material has problems that affect the work (e.g., a file that's grown too large, an unclear process, tangled responsibilities), include targeted improvements as part of the design - the way a good practitioner improves what they're working in.
- Don't propose unrelated rework. Stay focused on what serves the current goal.

## After the Design

**Documentation:**

- Write the validated design (spec) to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
  - (User preferences for spec location override this default)
- Use elements-of-style:writing-clearly-and-concisely skill if available
- Commit the design document to git

**Spec Self-Review:**
After writing the spec document, look at it with fresh eyes:

1. **Placeholder scan:** Any "TBD", "TODO", incomplete sections, or vague requirements? Fix them.
2. **Internal consistency:** Do any sections contradict each other? Does the structure match the feature/step descriptions?
3. **Scope check:** Is this focused enough for a single implementation/execution plan, or does it need decomposition?
4. **Ambiguity check:** Could any requirement be interpreted two different ways? If so, pick one and make it explicit.

Fix any issues inline. No need to re-review — just fix and move on.

**User Review Gate:**
After the spec review loop passes, ask the user to review the written spec before proceeding:

> "Spec written and committed to `<path>`. Please review it and let me know if you want to make any changes before we start writing out the implementation/execution plan."

Wait for the user's response. If they request changes, make them and re-run the spec review loop. Only proceed once the user approves.

**Implementation:**

- Invoke the writing-plans skill to create a detailed implementation/execution plan
- Do NOT invoke any other skill. writing-plans is the next step.

## Key Principles

- **One question at a time** - Don't overwhelm with multiple questions
- **Multiple choice preferred** - Easier to answer than open-ended when possible
- **YAGNI, KISS, DRY ruthlessly** - Remove unnecessary features from all designs
- **Explore alternatives** - Always propose 2-3 approaches before settling
- **Incremental validation** - Present design, get approval before moving on
- **Be flexible** - Go back and clarify when something doesn't make sense