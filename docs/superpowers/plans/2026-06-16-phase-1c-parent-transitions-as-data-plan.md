# Phase 1c — Parent Transitions As Data Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time. Parity is the gate.

**Goal:** Make the parent workflow's **transitions data**. Populate
`PARENT_DEFINITION.transitions` (currently `{}`) and route every handler's
*success* next-phase decision through the engine instead of the hardcoded
`next_phase = ParentPhase.X.value` literals scattered across the handlers. This
lands the "transitions as data" half of ADR-0001 for the parent tier. Zero
behaviour change, full parent-suite parity.

**Honest scope correction (vs the Phase 1b note):** removing the opaque `work`
wrappers entirely — a *generic* RoleAttempt/Effect runner that subsumes each
handler body — is **NOT** this plan. The handler bodies do legitimately
role-specific work (per-role context building, per-role request builders, and
bounded *failure* routing such as `_route_failed_graph_review`). Genericizing
those is a larger, partially-bespoke effort deferred to **Phase 1d**. Phase 1c
extracts the *transition decisions* (the genuinely duplicated/scattered part);
the wrappers stay, but each handler stops hardcoding its next phase.

**Architecture:** Parent edges are two kinds:
- **Verdict-keyed** (RoleAttempt *success*): `(phase, verdict, action) → next_phase`,
  exactly like the child `TRANSITIONS` table. Handlers compute it today via
  `_is_passing_review(...)` + a literal.
- **Deterministic** (Effect / Aggregate *success*): a single next phase with no
  verdict (e.g. `FINAL_ACCEPT_READY → FINAL_ACCEPTED`,
  `CHILD_PUBLICATION_READY → CHILDREN_PUBLISHED`,
  `CHILDREN_PUBLISHED → PARENT_QA_READY`).

**Failure** routing (non-passing review → bounded `GRAPH_FIXING`/remediation →
escalate to `HUMAN_REVIEW_REQUIRED`) stays **dynamic in the handlers**, exactly
as the child's fix-cycle escalation stays in `scheduling`. The table holds only
the static success edges.

**Tech Stack:** Python scheduler package, pytest. Builds on Phase 1b
(`PARENT_DEFINITION`, `WorkflowEngine`, `ParentTickContext`, wrapped handlers).

## Relationship To Other Plans

- Phase 1 (step 3) of
  [target-c-implementation-path](2026-06-16-target-c-implementation-path.md).
- Follows [Phase 1b](2026-06-16-phase-1b-parent-on-engine-plan.md).
- Spec: [target-C](../specs/2026-06-16-target-c-modular-parallel-engine.md) §1,
  ADR-0001 ("transitions as data").

## Scope

In scope:
- `PARENT_TRANSITIONS` (verdict-keyed success edges) + a deterministic-edge
  representation for Effect/Aggregate stages (`StageSpec.next_phase_on_success`).
- Populate `PARENT_DEFINITION.transitions`.
- Route every handler's *success* transition through the engine
  (`_PARENT_ENGINE.next_phase(...)` for RoleAttempt; the stage's
  `next_phase_on_success` for Effect/Aggregate).
- Characterization + parity tests; full parent suite green unchanged.

Out of scope → **Phase 1d**:
- A generic RoleAttempt/Effect runner that removes the opaque `work` wrappers and
  the per-handler durable-record boilerplate. Per-role context/request building
  and bounded failure routing are genuinely role-specific; consolidating them is
  a separate, larger effort.

## File Structure

- Modify `workflow_engine.py` (`StageSpec.next_phase_on_success`;
  `PARENT_TRANSITIONS`; populate `PARENT_DEFINITION.transitions`; set
  deterministic edges on Effect/Aggregate stages).
- Modify `runtime.py` (route each handler's success next-phase through the
  engine; remove the hardcoded success literals).
- Tests:
  - `test_workflow_engine.py` (table shape + deterministic edges)
  - `test_runtime.py` (parity — unchanged assertions)

---

## Task 1: Characterize the current parent transitions (lock behaviour)

**Files:** `test_workflow_engine.py`.

Before changing any handler, write the golden table of what the parent currently
does, derived by reading each handler's success path. This is the snapshot the
extraction must reproduce.

- [ ] **Step 1: Enumerate edges by reading handlers.** Produce the expected
  success edges. Confirmed examples (verify the rest against the source):

```text
verdict-keyed (RoleAttempt success):
  (GRAPH_SPEC_REVIEWING,      PASS, submit_for_graph_execution_review) -> GRAPH_EXECUTION_REVIEWING
  (GRAPH_EXECUTION_REVIEWING, PASS, <action>)                          -> CHILD_PUBLICATION_READY
  (PARENT_QA_READY,           PASS, <action>)                          -> FINAL_ACCEPT_READY
  (SPEC_FINALIZED/decompose,  DONE, submit_for_graph_review)           -> GRAPH_SPEC_REVIEWING
  (GRAPH_FIXING,              DONE, <action>)                          -> GRAPH_SPEC_REVIEWING (re-review)

deterministic (Effect/Aggregate success):
  CHILD_PUBLICATION_READY -> CHILDREN_PUBLISHED
  CHILDREN_PUBLISHED      -> PARENT_QA_READY        (all children accepted)
  REMEDIATION_PLANNING    -> CHILDREN_PUBLISHED      (verify against handler)
  FINAL_ACCEPT_READY      -> FINAL_ACCEPTED
```

- [ ] **Step 2: Write a failing test** asserting `PARENT_TRANSITIONS` and the
  stages' `next_phase_on_success` equal the enumerated golden edges.

- [ ] **Step 3: Run, verify failure** (`PARENT_TRANSITIONS` undefined).

---

## Task 2: Define the tables + populate the definition

**Files:** `workflow_engine.py`.

- [ ] **Step 1: Add `next_phase_on_success` to `StageSpec`** (default `None`).
- [ ] **Step 2: Define `PARENT_TRANSITIONS`** (verdict-keyed dict) from Task 1.
- [ ] **Step 3: Populate** `PARENT_DEFINITION.transitions = PARENT_TRANSITIONS`
  and set `next_phase_on_success` on the Effect/Aggregate stages.
- [ ] **Step 4: Run Task-1 tests** — expect PASS. `engine.next_phase` already
  reads `definition.transitions`, so it now works for the parent verdict edges.

- [ ] **Step 5: Commit**

```bash
git commit -m "Add parent transition tables as data"
```

---

## Task 3: Route handler success transitions through the engine

**Files:** `runtime.py`; `test_runtime.py` stays green unchanged.

For each RoleAttempt handler, replace the hardcoded success literal with an engine
lookup. Example (`run_parent_graph_spec_review_tick`):

```python
# was: next_phase = ParentPhase.GRAPH_EXECUTION_REVIEWING.value
next_phase = _PARENT_ENGINE.next_phase(phase, outcome.role_result)
```

Leave the failure branch (`_route_failed_graph_review`) and all durable recording
EXACTLY as-is. For Effect/Aggregate handlers, replace the deterministic literal
with the stage's `next_phase_on_success`:

```python
# was: next_phase = ParentPhase.FINAL_ACCEPTED.value
next_phase = PARENT_DEFINITION.stage(ParentPhase.FINAL_ACCEPT_READY.value).next_phase_on_success
```

- [ ] **Step 1: One handler at a time** — convert, run that handler's tests,
  repeat. Do NOT batch all handlers before testing.
- [ ] **Step 2: The PARITY GATE** — after each handler and at the end:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_runtime_factory.py -q
```

Expected: green, **no parent test modified**.

- [ ] **Step 3: Commit** (may be one commit per handler or one for the batch).

```bash
git commit -m "Route parent success transitions through the engine table"
```

---

## Task 4: Full gate + refactor

- [ ] **Step 1: Whole suite + TS + tsc**

```bash
uv run pytest packages/scheduler/tests/ -q
npm run test:ts
npx tsc --noEmit
```

- [ ] **Step 2: Confirm no scattered success literals remain.** There should be
  no `next_phase = ParentPhase.<X>.value` on a success path in `runtime.py`
  (failure/escalation literals like `HUMAN_REVIEW_REQUIRED` may remain — they are
  dynamic routing, not static transitions):

```bash
grep -n "next_phase = ParentPhase" packages/scheduler/src/smda_scheduler/runtime.py
```

- [ ] **Step 3: Commit**

```bash
git commit -m "Parent transitions fully table-driven on success paths"
```

---

## Acceptance Criteria

1. `PARENT_DEFINITION.transitions` is populated and reproduces every parent
   success transition (Task 1 characterization).
2. RoleAttempt handlers derive their success next-phase from
   `_PARENT_ENGINE.next_phase`; Effect/Aggregate handlers from the stage's
   `next_phase_on_success`. No hardcoded success-phase literals remain.
3. Failure routing (bounded fixer / remediation / human-review escalation) is
   unchanged and still dynamic.
4. Full `test_runtime` / `test_runtime_factory` suites pass **unchanged**.
5. Entire Python suite + TS build green.

## Done Definition

- Parent transitions are data; the table is authoritative for success edges.
- Behaviour byte-for-byte equivalent (only additive tests).
- Branch ready for **Phase 1d** (generic work-handler runner that removes the
  opaque wrappers) — or for jumping to Phase 0 / Phase 2 / Phase 3, since the
  engine's "transitions as data" foundation is now complete for both tiers.

## Out Of Scope — Next Plan (Phase 1d, optional)

Introduce a generic RoleAttempt runner (build request from a per-stage builder →
record → run → `engine.next_phase` → record) and an Effect runner, collapsing the
handler bodies and removing the `work` wrappers. Bounded failure routing becomes a
shared engine concern. This is the final deepening; it is optional for unblocking
Phases 2-4, which only need transitions-as-data (done here) and the stage-kind
model (done in 1b).
