# Phase 5 — Modes As Definitions Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time.

> **Agent handoff (read first — hand-rolled RepoContextPacket):**
> - **Branch:** work on `target-c`. Do NOT branch from `master`/`main`.
> - **Read first:** [CONTEXT.md](../../CONTEXT.md) (Mode, Workflow Definition,
>   Stage), [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md)
>   (one engine, many definitions — this phase finishes it),
>   [target-C spec](../specs/2026-06-16-target-c-modular-parallel-engine.md) §7,
>   and the superseded [execution-modes spec](../specs/2026-06-16-execution-modes-and-workflow-options.md)
>   (the `WorkflowOptions` boolean bundle this phase removes).
> - **Mirror existing seams:** `CHILD_DEFINITION` + the child `TRANSITIONS`
>   (`workflow.py`), the `_REGISTRY` in `workflow_registry.py`, and
>   `run_child_candidate_tick` (`runtime.py`) — the SDD dispatch the task tier
>   reuses.
> - **Line numbers are indicative** — grep for symbols.
> - **Current reality (grep-verified):**
>   - `workflow_options` is set on every `CandidateRoutingDecision` but is
>     **consumed nowhere** — `require_spec_review` / `require_quality_review` /
>     `require_integration` / `risk_level` are dead threading.
>   - `CandidateRoute.TASK` is **unhandled** in `runtime_factory.py` — an
>     `Execution: smda-task` issue falls through to `TickResult(status="blocked")`.
>     So `smda-task` does not run today.
> - **Prereqs:** Phases 1–4 (engine, registry, methodology, roadmap, landing).
> - **Discipline:** TDD red→green. Parity = don't change a test's assertion to
>   hide a regression; updating assertions that describe *removed* surface
>   (the `WorkflowOptions` bundle) is the legitimate exception. All of
>   `uv run pytest packages/scheduler/tests/`, `npm run test:ts`,
>   `npx tsc --noEmit` green at every commit.

**Goal:** Finish ADR-0001 — every execution mode resolves to a
`WorkflowDefinition`, and `smda-task` runs as the child SDD definition **minus
the spec-review stage** (a different transition table, not a boolean flag). Drop
the `WorkflowOptions` boolean bundle and the `require_spec_review` threading.
After this phase, adding or shaping a mode is a registry/definition edit, not a
control-flow change (spec acceptance criterion 3).

**Scope split (one doc, green commit boundaries):**
- **5a — Remove the dead `WorkflowOptions` bundle.** Pure subtraction: drop
  `WorkflowOptions`, `resolve_workflow_options`, the `workflow_options` field on
  `CandidateRoutingDecision`, and the `require_*` threading. Keep the typed
  `ExecutionMode` / `ModeTag` enums, `parse_execution_mode`, `parse_mode_tags`
  (tag validation), and the catalog markdown.
- **5b — `TASK_DEFINITION`.** Child SDD transition table minus
  `SPEC_REVIEWING` / `FIXING_SPEC`; register `SMDA_TASK → TASK_DEFINITION`.
- **5c — Dispatch `smda-task` via the shared SDD path.** Wire `CandidateRoute.TASK`
  to run the SDD loop on a standalone task issue under `TASK_DEFINITION` — no
  net-new boolean-flagged task tick (see the design decision below).
- **5d — Full gate + end-to-end.** A task issue runs implement → quality → accepted
  with the spec-review stage never entered.

**Architecture:** `smda-task` is `CHILD_DEFINITION` with a transition table that
routes the implementer's `DONE / submit_for_spec_review` straight to
`QUALITY_REVIEWING` (skipping `SPEC_REVIEWING` / `FIXING_SPEC`). The implementer
`RoleContract` is **reused unchanged** — only the transition table differs, so the
"skip spec review" decision lives in data, per ADR-0001. The mode→definition
registry already exists; this phase adds the task entry and the dispatch wiring.

**Tech Stack:** Python scheduler, SQLite `PhaseLedger`, pytest. (Likely no TS
changes; confirm in 5d.)

## Open Design Decision — task dispatch wiring (resolve before 5c)

`run_child_candidate_tick` is **parent-coupled**: it loads the parent graph,
validates the graph checksum, and asserts child membership. A `smda-task` issue is
**standalone** (no parent, no graph; its acceptance criteria + verification live
inline in the body, per `_classify_task`). So the child tick cannot be reused
verbatim. Two ways to dispatch a task:

- **Option A (recommended): extract a shared SDD dispatch.** Factor the
  graph-independent core of `run_child_candidate_tick` (build `ChildTaskContext`
  from the issue body, run the role attempt, route via the engine) into a helper
  parameterized by `WorkflowDefinition`. The child route passes `CHILD_DEFINITION`
  + graph context; the task route passes `TASK_DEFINITION` + no graph. One SDD
  code path, definition selected by mode. Closest to acceptance criterion 3;
  larger diff.
- **Option B: a thin task tick.** A small `run_task_candidate_tick` that builds the
  context from the body and drives the SDD engine on `TASK_DEFINITION`, duplicating
  the graph-free portion. Smaller, but the spec explicitly says drop "any net-new
  `run_task_candidate_tick`" — so this is the discouraged path.

**Recommendation: Option A.** It satisfies the spec's "no net-new task tick" and
acceptance criterion 3. If Option A's refactor proves too large for one safe step,
split 5c into 5c-i (extract the shared dispatch, child route unchanged, parity-
green) and 5c-ii (task route uses it). Confirm this choice before starting 5c.

## Relationship To Other Plans

- Phase 5 of [target-c-implementation-path](2026-06-16-target-c-implementation-path.md);
  spec §7; ADR-0001. Supersedes the execution-modes / `WorkflowOptions` plan.
- Independent of Phase 4; can land in any order relative to it.
- **Out of scope / next:** optional Phase 1d (remove the parent stage-work
  wrappers once every stage is generic kind interpretation).

## Scope

In scope:
- Remove `WorkflowOptions`, `resolve_workflow_options`, the `workflow_options`
  decision field, and `require_*` threading.
- `TASK_DEFINITION` (child SDD minus spec-review) + `SMDA_TASK` registry entry.
- Dispatch `smda-task` through the shared SDD path on `TASK_DEFINITION`.

Out of scope:
- `manual` and `smda-review` stay **non-dispatching routing decisions** (manual =
  no auto-claim; smda-review = "not enabled in this slice"). They resolve via the
  typed `ExecutionMode` but get no `WorkflowDefinition` here — a full review
  definition is a later slice. (Deviation from a literal reading of spec §7's
  "become WorkflowDefinitions"; flagged deliberately because neither auto-runs.)
- Any change to the role schema / artifact, methodology bindings, or the
  landing/roadmap machinery.

## File Structure

- Modify `execution_modes.py` (drop `WorkflowOptions` + `resolve_workflow_options`;
  keep enums + parsers + catalog).
- Modify `candidate_routing.py` (drop the `workflow_options` field + its plumbing).
- Modify `workflow.py` (a `TASK_TRANSITIONS` table) and `workflow_engine.py`
  (`TASK_DEFINITION`), `workflow_registry.py` (`SMDA_TASK` entry).
- Modify `runtime.py` (shared SDD dispatch — Option A) and `runtime_factory.py`
  (wire `CandidateRoute.TASK`).
- Tests: `test_execution_modes.py`, `test_candidate_routing.py`,
  `test_workflow_engine.py`, `test_workflow_registry.py`, `test_runtime.py`,
  `test_runtime_factory.py`.

---

# 5a — Remove The Dead `WorkflowOptions` Bundle

## Task 1: Drop `WorkflowOptions` and its threading

**Files:** `execution_modes.py`, `candidate_routing.py`; `test_execution_modes.py`,
`test_candidate_routing.py`.

- [ ] **Step 1: Confirm it is dead.** `grep -rn "workflow_options\|require_spec_review"
  packages/scheduler/src` — verify no consumer reads the booleans (only the
  decision field + the resolver). This justifies removal as parity-preserving.

- [ ] **Step 2: Remove** `WorkflowOptions`, `resolve_workflow_options`, and the
  `workflow_options` field from `CandidateRoutingDecision` and every
  `_classify_*` return. Keep `ExecutionMode`, `ModeTag`, `parse_execution_mode`,
  `parse_mode_tags` (still validates and rejects unknown tags), and
  `SMDA_EXECUTION_MODE_CATALOG_MARKDOWN`. Update the two test files: delete the
  `WorkflowOptions`/`require_*` assertions; keep the mode-resolution and route
  assertions. These deletions remove coverage of removed surface, not of behaviour.

- [ ] **Step 3: Full suite green. Commit. 5a boundary.**

---

# 5b — `TASK_DEFINITION`

## Task 2: Task transition table + definition + registry

**Files:** `workflow.py`, `workflow_engine.py`, `workflow_registry.py`;
`test_workflow_engine.py`, `test_workflow_registry.py`.

- [ ] **Step 1: Failing tests**
  - `definition_for_mode(ExecutionMode.SMDA_TASK)` returns `TASK_DEFINITION`.
  - `TASK_DEFINITION` has **no** `SPEC_REVIEWING` / `FIXING_SPEC` transitions; its
    `IMPLEMENTING / DONE / submit_for_spec_review` edge targets `QUALITY_REVIEWING`
    (spec review skipped); the quality loop + terminal phases match the child.
  - `dispatch_phase_overrides` still maps `READY → IMPLEMENTING`.

- [ ] **Step 2: Implement** a `TASK_TRANSITIONS` table = the child `TRANSITIONS`
  with the two spec-review entries removed and the implementer edge rerouted to
  `QUALITY_REVIEWING`. Build `TASK_DEFINITION` (`name="smda-task"`, reuse the child
  stages for the phases it keeps; `SPEC_REVIEWING`/`FIXING_SPEC` carry no contract
  and are unreachable). Register `ExecutionMode.SMDA_TASK → TASK_DEFINITION`.

- [ ] **Step 3: Run, green. Commit.**

---

# 5c — Dispatch `smda-task`

## Task 3: Shared SDD dispatch (Option A) — child route, parity-green

**Files:** `runtime.py`; `test_runtime.py`.

- [ ] **Step 1:** Extract the graph-independent core of `run_child_candidate_tick`
  (build `ChildTaskContext` from the issue body → role attempt → engine routing)
  into a shared helper that takes a `WorkflowDefinition`. The child route calls it
  with `CHILD_DEFINITION` + the graph-validation preamble unchanged.

- [ ] **Step 2: Parity gate** — the entire existing child suite passes **with its
  assertions unchanged** (this step is a pure refactor; no behaviour change).

- [ ] **Step 3: Commit.**

## Task 4: Wire `CandidateRoute.TASK`

**Files:** `runtime.py`, `runtime_factory.py`; `test_runtime.py`,
`test_runtime_factory.py`.

- [ ] **Step 1: Failing tests** — a standalone `Execution: smda-task` issue (with
  `Acceptance criteria` + `Verification` in the body) dispatches through the shared
  SDD path on `TASK_DEFINITION`: it runs `IMPLEMENTING`, and on the implementer's
  `DONE / submit_for_spec_review` advances to `QUALITY_REVIEWING` (NOT
  `SPEC_REVIEWING`). No parent graph is required.

- [ ] **Step 2: Implement** the task branch in `runtime_factory` (route
  `CandidateRoute.TASK` to the shared dispatch with `TASK_DEFINITION` and no graph
  context) — replacing the current blocked fall-through.

- [ ] **Step 3: Run, green. Commit. 5c boundary.**

---

# 5d — Full Gate + End-To-End

## Task 5: Full gate + task e2e

- [ ] `uv run pytest packages/scheduler/tests/ -q`; `npm run test:ts`;
  `npx tsc --noEmit`. All green.
- [ ] End-to-end: an `Execution: smda-task` issue runs implement → quality review →
  `QUALITY_REVIEW_PASSED`, with `SPEC_REVIEWING` never entered (assert the phase
  trace skips it). A quality FAIL still loops through `FIXING_QUALITY`.
- [ ] Confirm: `smda` / `smda-child` / `smda-roadmap` behaviour unchanged.
- [ ] Commit.

## Acceptance Criteria

1. `WorkflowOptions`, `resolve_workflow_options`, and the `workflow_options`
   decision field are gone; the typed `ExecutionMode` / `ModeTag` enums, parsers,
   and catalog remain; nothing reads removed booleans.
2. `SMDA_TASK` resolves to `TASK_DEFINITION` via the registry; the definition is
   the child SDD minus the spec-review stage (transition table, not a flag).
3. A standalone `smda-task` issue dispatches through the shared SDD path and never
   enters `SPEC_REVIEWING`; the quality loop and acceptance behave like a child.
4. Adding/altering this mode was a registry + definition + thin route edit, with no
   per-mode dispatch logic beyond route selection (spec criterion 3).
5. Existing `smda` / `smda-child` / `smda-roadmap` suites are green and unchanged.
6. Full suite + TS + tsc green.

## Done Definition

- Every running mode resolves to a `WorkflowDefinition`; `smda-task` runs the
  spec-review-free SDD loop selected purely by data. The `WorkflowOptions` boolean
  bundle and `require_spec_review` threading are removed. ADR-0001 is fully
  realized for the modes that dispatch.

## Out Of Scope — Next Plans

- **Phase 1d (optional):** remove the parent stage-work wrappers in
  `workflow_engine.py` once every stage is generic `WorkHandlerKind` interpretation
  (the last "shallow" seam from Phase 1b).
- A first-class `smda-review` workflow definition, if/when that mode is enabled.
