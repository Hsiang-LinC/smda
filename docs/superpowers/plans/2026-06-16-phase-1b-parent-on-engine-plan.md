# Phase 1b — Parent Workflow On The Engine Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time. Parity is the gate.

**Goal:** Put the **parent** workflow on the engine: replace the
`run_parent_workflow_tick` if-ladder (`runtime.py:178-274`) with engine-driven
stage dispatch, and first-class each parent stage's Work Handler **kind**
(`RoleAttempt` / `Effect` / `Aggregate`) as data — including the `Aggregate`
stage (`CHILDREN_PUBLISHED`) that Phase 3 will reuse for the roadmap tier. Zero
behaviour change, full parent-suite parity.

**Scope discipline — this is the *dispatch-unification* slice, deliberately
transitional.** In 1b each parent stage's work is the **existing handler
function, wrapped** as the stage's work. The stage *kind* becomes first-class
data and the if-ladder dies, but the handlers still own their own
transition/tracker/ledger side effects. Extracting the parent **transition
table** as authoritative data and decomposing handlers into the engine's
*generic* `RoleAttempt`/`Effect`/`Aggregate` interpretation is **Phase 1c** (see
Out Of Scope). The wrapped `work` callables here are scaffolding 1c removes — do
not mistake them for the deep end-state.

**Architecture:** Build a single `ParentTickContext` bundling every dispatch arg;
a parent stage registry maps `phase → StageSpec(kind, work)`; the engine
dispatches by lookup. `run_parent_workflow_tick` becomes: build context →
`engine.dispatch_parent_stage(phase, ctx)`. Side-effect ordering, the
`CHILDREN_PUBLISHED` "integration not configured → Blocked" guard, and the
idle-default branch are all preserved exactly.

**Tech Stack:** Python scheduler package, pytest. Builds on Phase 1a
(`workflow_engine.py`, `WorkflowDefinition`, `WorkHandlerKind`, `StageSpec`,
registry).

## Relationship To Other Plans

- Phase 1 (step 2) of
  [target-c-implementation-path](2026-06-16-target-c-implementation-path.md).
- Follows [Phase 1a](2026-06-16-phase-1a-workflow-engine-child-first-plan.md)
  (child on the engine, done).
- Spec: [target-C](../specs/2026-06-16-target-c-modular-parallel-engine.md) §1–§2,
  ADR-0001.

## Scope

In scope:
- `ParentTickContext` dataclass (bundles `issue`, `repo_context`, `repo_root`,
  `ledger`, `execution`, `backlog`, `sandbox_provider`, `agent`, `owner`,
  `child_labels`, `integration`, `integration_branch`, `qa_bounds`).
- Extend `StageSpec` with an optional `kind`-appropriate `work`
  (`Callable[[ParentTickContext], ParentIntakeResult] | None`). Child stages keep
  `work=None` (their work runs through `scheduling`).
- `PARENT_DEFINITION` (`WorkflowDefinition`) with parent phases + a stage per
  ledger phase carrying its `WorkHandlerKind` and wrapped handler.
- `WorkflowEngine.dispatch_parent_stage(phase, ctx)`.
- Replace the if-ladder in `run_parent_workflow_tick` with engine dispatch.
- Register `smda` → `PARENT_DEFINITION` in `workflow_registry`.

Out of scope → **Phase 1c**:
- Extract `PARENT_TRANSITIONS` (phase × verdict × action → phase) and make the
  table authoritative.
- Decompose handlers so the engine *generically* runs each kind (RoleAttempt =
  engine runs the role + applies the table transition + records tracker effects;
  Effect = engine runs a pure effect fn; Aggregate = engine runs a sub-scheduler
  over a node set), removing per-handler transition/tracker duplication and the
  opaque `work` callables introduced here.

## File Structure

- Modify `packages/scheduler/src/smda_scheduler/workflow_engine.py`
  (add `work` to `StageSpec`; add `dispatch_parent_stage`; add
  `ParentTickContext`; add `PARENT_DEFINITION` + parent stage registry).
- Modify `packages/scheduler/src/smda_scheduler/runtime.py`
  (replace the if-ladder body of `run_parent_workflow_tick`).
- Modify `packages/scheduler/src/smda_scheduler/workflow_registry.py`
  (register `smda`).
- Tests:
  - `packages/scheduler/tests/test_workflow_engine.py` (parent stage kinds,
    dispatch)
  - `packages/scheduler/tests/test_runtime.py` (parity — unchanged assertions)
  - `packages/scheduler/tests/test_workflow_registry.py` (smda registered)

---

## Task 1: `ParentTickContext` + `StageSpec.work`

**Files:** modify `workflow_engine.py`; modify `test_workflow_engine.py`.

- [ ] **Step 1: Failing test** — assert `ParentTickContext` carries the dispatch
  args and `StageSpec` accepts a `work` callable defaulting to `None`.

```python
def test_stage_spec_accepts_work_callable_defaulting_none():
    spec = StageSpec(phase=ChildPhase.IMPLEMENTING, kind=WorkHandlerKind.ROLE_ATTEMPT)
    assert spec.work is None
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement** — add `work: Callable[..., object] | None = None` to
  `StageSpec`; add `ParentTickContext` (frozen dataclass) importing the parent
  arg types (`BacklogIssue`, `RepoContextPacket`, `PhaseLedger`,
  `RoleExecutionAdapter`, `BacklogPublicationAdapter`, `AgentSelection`,
  `ParentIntegration`, `QaBounds`). Beware import cycles — import these lazily or
  use `TYPE_CHECKING` + string annotations if `runtime.py` would re-import the
  engine.

- [ ] **Step 4: Run, green. Commit.**

```bash
git commit -m "Add ParentTickContext and StageSpec.work"
```

---

## Task 2: `PARENT_DEFINITION` + parent stage registry (handlers wrapped)

**Files:** modify `workflow_engine.py`; modify `test_workflow_engine.py`.

The wrapped handlers must be imported lazily inside each `work` (a module-load
`workflow_engine → runtime → ... → workflow_engine` cycle is otherwise certain).

- [ ] **Step 1: Failing tests** — assert each parent ledger phase maps to a stage
  with the correct kind:

```python
import pytest
from smda_scheduler.workflow import ParentPhase
from smda_scheduler.workflow_engine import PARENT_DEFINITION, WorkHandlerKind

@pytest.mark.parametrize("phase,kind", [
    ("SPEC_FINALIZED", WorkHandlerKind.ROLE_ATTEMPT),
    (ParentPhase.GRAPH_FIXING.value, WorkHandlerKind.ROLE_ATTEMPT),
    (ParentPhase.GRAPH_SPEC_REVIEWING.value, WorkHandlerKind.ROLE_ATTEMPT),
    (ParentPhase.GRAPH_EXECUTION_REVIEWING.value, WorkHandlerKind.ROLE_ATTEMPT),
    (ParentPhase.CHILD_PUBLICATION_READY.value, WorkHandlerKind.EFFECT),
    (ParentPhase.CHILDREN_PUBLISHED.value, WorkHandlerKind.AGGREGATE),
    (ParentPhase.PARENT_QA_READY.value, WorkHandlerKind.ROLE_ATTEMPT),
    (ParentPhase.REMEDIATION_PLANNING.value, WorkHandlerKind.EFFECT),
    (ParentPhase.FINAL_ACCEPT_READY.value, WorkHandlerKind.EFFECT),
])
def test_parent_stage_kinds(phase, kind):
    assert PARENT_DEFINITION.stage(phase).kind is kind
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement** the parent stages. Key the registry on the ledger
  phase strings (note `"SPEC_FINALIZED"` is a string marker, not a `ParentPhase`
  member — preserve it). Each `work` wraps the existing handler with a lazy
  import and pulls its args from `ParentTickContext`:

```python
def _spec_finalized_work(ctx):
    from smda_scheduler.runtime import run_parent_graph_decomposition_tick
    return run_parent_graph_decomposition_tick(
        issue=ctx.issue, repo_context=ctx.repo_context, repo_root=ctx.repo_root,
        ledger=ctx.ledger, execution=ctx.execution,
        sandbox_provider=ctx.sandbox_provider, agent=ctx.agent, owner=ctx.owner,
    )
# ... one per handler; CHILD_PUBLICATION_READY uses (issue, ledger, backlog,
# child_labels); CHILDREN_PUBLISHED uses (issue, ledger, integration,
# integration_branch); REMEDIATION_PLANNING adds qa_bounds; FINAL_ACCEPT_READY
# uses (issue, ledger).

PARENT_DEFINITION = WorkflowDefinition(
    name="smda",
    phases=frozenset(ParentPhase),
    transitions={},  # authority stays in handlers until Phase 1c
    terminal_phases=frozenset(
        {ParentPhase.FINAL_ACCEPTED, ParentPhase.HUMAN_REVIEW_REQUIRED}
    ),
    stages={...},  # phase string -> StageSpec(kind=..., work=...)
    dispatch_phase_overrides={},
)
```

- [ ] **Step 4: Run, green. Commit.**

```bash
git commit -m "Model parent stages as workflow definition (handlers wrapped)"
```

---

## Task 3: Engine parent dispatch + replace the if-ladder

**Files:** modify `workflow_engine.py`, `runtime.py`; `test_runtime.py` stays
green unchanged.

- [ ] **Step 1: Failing test** — `dispatch_parent_stage` runs the stage work for
  a phase and returns its result; unknown/idle phase returns the idle default.
  Add a focused engine test with a fake `ParentTickContext` whose stage work is
  monkeypatched, OR rely on the existing `test_runtime` parent tests as the
  oracle (preferred — they already assert real transitions).

- [ ] **Step 2: Implement `dispatch_parent_stage`**

```python
def dispatch_parent_stage(self, phase, ctx):
    stage = self._definition.stages.get(phase)
    if stage is None or stage.work is None:
        return None  # caller applies the idle/blocked default
    return stage.work(ctx)
```

- [ ] **Step 3: Replace the if-ladder** in `run_parent_workflow_tick`
  (`runtime.py:178-274`). Build a `ParentTickContext` from the kwargs, then:

```python
    parent_run = _parent_run_for(ledger, issue.id)
    phase = parent_run["phase"]
    # Preserve the CHILDREN_PUBLISHED precondition exactly.
    if phase == ParentPhase.CHILDREN_PUBLISHED.value and (
        integration is None or integration_branch is None
    ):
        return ParentIntakeResult(
            target_state="Blocked",
            comment=f"SMDA child acceptance is not configured for {issue.id}.",
        )
    ctx = ParentTickContext(issue=issue, ...)
    result = _PARENT_ENGINE.dispatch_parent_stage(phase, ctx)
    if result is not None:
        return result
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA parent workflow idle for {issue.id}.\n\n"
            f"Current parent phase: `{phase}`"
        ),
    )
```

- [ ] **Step 4: The PARITY GATE** — run the full parent suite, unchanged:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_runtime_factory.py packages/scheduler/tests/test_workspace_tick.py -q
```

Expected: all green, **no parent test modified**. This is the zero-behaviour-
change proof for the parent tier.

- [ ] **Step 5: Commit**

```bash
git commit -m "Dispatch parent workflow through the engine (kills if-ladder)"
```

---

## Task 4: Register `smda` → `PARENT_DEFINITION`

**Files:** modify `workflow_registry.py`, `test_workflow_registry.py`.

- [ ] **Step 1: Update the unknown-mode test** — `smda` now resolves to
  `PARENT_DEFINITION`; pick a still-unregistered mode (`smda-task`) for the
  raises-case.
- [ ] **Step 2: Register** `ExecutionMode.SMDA: PARENT_DEFINITION` in `_REGISTRY`.
- [ ] **Step 3: Run registry tests, green. Commit.**

```bash
git commit -m "Register smda parent definition"
```

---

## Task 5: Full-suite gate + refactor

- [ ] **Step 1: Whole Python suite + TS + tsc**

```bash
uv run pytest packages/scheduler/tests/ -q
npm run test:ts
npx tsc --noEmit
```

Expected: all green (TS unaffected). Record counts.

- [ ] **Step 2: Refactor** — collapse the per-handler `work` wrappers to a tight,
  uniform shape (e.g. a small table of `(phase → (handler, arg-selector))`) so
  Task 2 is not nine near-identical functions. Do not change behaviour. Confirm
  the if-ladder is fully gone from `runtime.py`.

- [ ] **Step 3: Commit**

```bash
git commit -m "Tidy parent stage wrappers; parent fully engine-dispatched"
```

---

## Acceptance Criteria

1. Every parent ledger phase maps to a `PARENT_DEFINITION` stage with the correct
   `WorkHandlerKind` (including `CHILDREN_PUBLISHED` = `AGGREGATE`).
2. `run_parent_workflow_tick` dispatches through `WorkflowEngine`; the if-ladder
   is removed; the `CHILDREN_PUBLISHED` guard and idle default are preserved.
3. The full `test_runtime` / `test_runtime_factory` / `test_workspace_tick`
   suites pass **unchanged** (zero behaviour change).
4. `workflow_registry` resolves `smda` → `PARENT_DEFINITION`.
5. Entire Python suite + TS build green.

## Done Definition

- All Acceptance Criteria met; parent suite behaviour byte-for-byte equivalent.
- Parent tier is engine-dispatched with first-class stage kinds; the `Aggregate`
  stage is modeled and ready for Phase 3 to reuse.
- Branch ready for **Phase 1c** (parent transition table authority + generic
  handler decomposition that removes the wrapped `work` callables).

## Out Of Scope — Next Plan (Phase 1c)

Extract `PARENT_TRANSITIONS`; make the table authoritative; decompose each
handler so the engine generically interprets `RoleAttempt` (run role → apply
table transition → record tracker effects), `Effect` (pure effect fn), and
`Aggregate` (sub-scheduler over a node set). This removes the transition/tracker
duplication and the opaque `work` callables, landing the deep end-state of
ADR-0001 for the parent tier.
