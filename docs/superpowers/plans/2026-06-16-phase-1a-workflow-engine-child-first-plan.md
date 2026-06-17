# Phase 1a — Workflow Engine (Child-First) Implementation Plan

> **REQUIRED SUB-SKILL:** Use `superpowers:executing-plans` (or
> `superpowers:subagent-driven-development`) + `tdd` to implement task-by-task.
> Every task is red → green → refactor. Steps use `- [ ]` checkboxes.

**Goal:** Introduce the data-driven workflow engine (`WorkflowDefinition` +
`WorkflowEngine` + Work Handler kinds) and express the **existing child SDD
workflow** as the first definition, routed through the engine, with **zero
behaviour change and full existing-test parity**. This is the load-bearing slice
from [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md): if the
engine re-expresses the current child workflow losslessly, all of target-C rests
on solid ground.

**Architecture:** The engine owns only the *decisions* — dispatch-phase mapping,
transition, terminal test, role selection, eligibility. `scheduling.run_once`
keeps owning the *orchestration loop* (claim/lease, durable recording, backoff,
fix-cycle escalation). We thread the engine through the existing decision
touchpoints rather than rewriting the scheduler, so parity is provable.

**Tech Stack:** Python scheduler package, pytest, existing `workflow.py`
(`TRANSITIONS`, `transition_child_phase`, `eligible_child_ids`,
`TERMINAL_CHILD_PHASES`), `scheduling.py` (`run_once`, `run_once_durable`,
`_dispatch_phase`), `role_contracts.py` (`child_role_contract_for_phase`,
`CHILD_ROLE_BY_PHASE`).

## Relationship To Other Plans

- Implements Phase 1 (step 1, child-first) of
  [target-c-implementation-path](2026-06-16-target-c-implementation-path.md).
- Spec: [target-C](../specs/2026-06-16-target-c-modular-parallel-engine.md),
  Required Behavior §1–§2, Acceptance §1.
- Builds on the salvaged `ExecutionMode`/`ModeTag` enums already on `target-c`
  (`execution_modes.py`) — used as the registry key in Task 4.

## Scope

In scope:
- New `workflow_engine.py`: `WorkHandlerKind`, `StageSpec`, `WorkflowDefinition`,
  `WorkflowEngine`.
- `CHILD_DEFINITION` assembled from the *existing* child data
  (`TRANSITIONS`, `CHILD_ROLE_BY_PHASE`, `TERMINAL_CHILD_PHASES`,
  `_dispatch_phase`).
- A definition `registry` mapping a Mode → `WorkflowDefinition`
  (`smda-child` → `CHILD_DEFINITION`).
- Refactor `scheduling.run_once` to consult the engine for dispatch-phase,
  transition, and terminal decisions.
- Parity tests proving engine decisions equal the legacy functions, plus the full
  existing suite green.

Out of scope (later plans):
- Parent workflow conversion + the `Effect` / `Aggregate` handlers actually
  driving work (Phase 1b / Phase 3). In 1a they are *defined but not
  interpreted* — interpreting one raises `NotImplementedError`, reserving the
  seam.
- Methodology-skill injection (Phase 2), schema codegen (Phase 0), roadmap tier
  (Phase 3), modes-as-definitions rewire of dispatch (Phase 5).

## File Structure

- Create `packages/scheduler/src/smda_scheduler/workflow_engine.py`
- Create `packages/scheduler/src/smda_scheduler/workflow_registry.py`
- Modify `packages/scheduler/src/smda_scheduler/scheduling.py`
- Modify `packages/scheduler/src/smda_scheduler/workflow.py`
  (make `transition_child_phase` / `_dispatch_phase` delegate, single-source)
- Tests:
  - Create `packages/scheduler/tests/test_workflow_engine.py`
  - Create `packages/scheduler/tests/test_workflow_registry.py`
  - `packages/scheduler/tests/test_scheduling.py` (parity, unchanged assertions)

---

## Task 1: Define `WorkflowDefinition` + Work Handler Kinds + `CHILD_DEFINITION`

**Files:** create `workflow_engine.py`; create `test_workflow_engine.py`.

- [ ] **Step 1: Write failing structural tests**

Create `packages/scheduler/tests/test_workflow_engine.py`:

```python
from smda_scheduler.workflow import (
    ChildPhase,
    TERMINAL_CHILD_PHASES,
    TRANSITIONS,
)
from smda_scheduler.workflow_engine import (
    CHILD_DEFINITION,
    WorkHandlerKind,
)


def test_child_definition_phases_cover_child_phase_enum():
    assert CHILD_DEFINITION.phases == frozenset(ChildPhase)


def test_child_definition_terminal_matches_legacy():
    assert CHILD_DEFINITION.terminal_phases == TERMINAL_CHILD_PHASES


def test_child_definition_transition_table_matches_legacy():
    assert CHILD_DEFINITION.transitions == TRANSITIONS


def test_child_definition_every_active_phase_is_role_attempt():
    for phase in ChildPhase:
        if phase in TERMINAL_CHILD_PHASES:
            continue
        assert CHILD_DEFINITION.stage(phase).kind is WorkHandlerKind.ROLE_ATTEMPT


def test_child_definition_role_for_implementing_is_child_implementer():
    contract = CHILD_DEFINITION.stage(ChildPhase.IMPLEMENTING).role_contract
    assert contract is not None
    assert contract.role.value == "child_implementer"
```

- [ ] **Step 2: Run, verify failure** — `ModuleNotFoundError: workflow_engine`.

```bash
uv run pytest packages/scheduler/tests/test_workflow_engine.py -q
```

- [ ] **Step 3: Implement the data structures**

Create `packages/scheduler/src/smda_scheduler/workflow_engine.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto

from smda_scheduler.role_contracts import RoleContract, child_role_contract_for_phase
from smda_scheduler.workflow import (
    ChildPhase,
    TERMINAL_CHILD_PHASES,
    TRANSITIONS,
)


class WorkHandlerKind(StrEnum):
    ROLE_ATTEMPT = auto()
    EFFECT = auto()
    AGGREGATE = auto()


@dataclass(frozen=True)
class StageSpec:
    phase: object
    kind: WorkHandlerKind
    role_contract: RoleContract | None = None


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    phases: frozenset
    transitions: dict
    terminal_phases: frozenset
    stages: dict
    dispatch_phase_overrides: dict  # phase -> dispatched phase (e.g. READY->IMPLEMENTING)

    def stage(self, phase) -> StageSpec:
        return self.stages[phase]


def _child_stages() -> dict[ChildPhase, StageSpec]:
    stages: dict[ChildPhase, StageSpec] = {}
    for phase in ChildPhase:
        if phase in TERMINAL_CHILD_PHASES:
            stages[phase] = StageSpec(phase=phase, kind=WorkHandlerKind.ROLE_ATTEMPT)
            continue
        # Every active child phase is a single agent role attempt.
        contract = _safe_child_contract(phase)
        stages[phase] = StageSpec(
            phase=phase,
            kind=WorkHandlerKind.ROLE_ATTEMPT,
            role_contract=contract,
        )
    return stages


def _safe_child_contract(phase: ChildPhase) -> RoleContract | None:
    try:
        return child_role_contract_for_phase(phase)
    except KeyError:
        # READY has no role; it dispatches as IMPLEMENTING (see overrides).
        return None


CHILD_DEFINITION = WorkflowDefinition(
    name="smda-child",
    phases=frozenset(ChildPhase),
    transitions=dict(TRANSITIONS),
    terminal_phases=TERMINAL_CHILD_PHASES,
    stages=_child_stages(),
    dispatch_phase_overrides={ChildPhase.READY: ChildPhase.IMPLEMENTING},
)
```

- [ ] **Step 4: Run tests** — expect PASS. Adjust `role.value`/`RoleName`
  attribute names to the real `RoleContract` shape if the assertion fails on
  attribute access (inspect `role_contracts.py`).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/workflow_engine.py packages/scheduler/tests/test_workflow_engine.py
git commit -m "Add workflow definition + child definition (data only)"
```

---

## Task 2: `WorkflowEngine` decision methods + parity with legacy

**Files:** modify `workflow_engine.py`; modify `test_workflow_engine.py`.

- [ ] **Step 1: Write failing parity tests**

Append to `test_workflow_engine.py`:

```python
import pytest

from smda_scheduler.workflow import (
    GraphError,
    RoleResult,
    WorkflowGraph,
    ChildNode,
    eligible_child_ids,
    transition_child_phase,
)
from smda_scheduler.workflow_engine import WorkflowEngine


ENGINE = WorkflowEngine(CHILD_DEFINITION)


@pytest.mark.parametrize("key", list(TRANSITIONS.keys()))
def test_engine_next_phase_matches_legacy_for_every_transition(key):
    phase, verdict, action = key
    result = RoleResult(verdict=verdict, required_next_action=action)
    assert ENGINE.next_phase(phase, result) == transition_child_phase(phase, result)


def test_engine_next_phase_unknown_raises_graph_error():
    with pytest.raises(GraphError):
        ENGINE.next_phase(
            ChildPhase.IMPLEMENTING,
            RoleResult(verdict="NOPE", required_next_action="nope"),
        )


def test_engine_dispatch_phase_maps_ready_to_implementing_else_identity():
    assert ENGINE.dispatch_phase(ChildPhase.READY) == ChildPhase.IMPLEMENTING
    assert ENGINE.dispatch_phase(ChildPhase.SPEC_REVIEWING) == ChildPhase.SPEC_REVIEWING


def test_engine_is_terminal_matches_legacy():
    for phase in ChildPhase:
        assert ENGINE.is_terminal(phase) == (phase in TERMINAL_CHILD_PHASES)


def test_engine_eligible_matches_legacy_eligible_child_ids():
    graph = WorkflowGraph(
        children={
            "a": ChildNode(id="a"),
            "b": ChildNode(id="b", dependencies=frozenset({"a"})),
        }
    )
    completed = frozenset({"a"})
    assert ENGINE.eligible(graph, completed_child_ids=completed) == eligible_child_ids(
        graph, completed_child_ids=completed
    )
```

- [ ] **Step 2: Run, verify failure** (`WorkflowEngine` undefined).

- [ ] **Step 3: Implement `WorkflowEngine`**

Append to `workflow_engine.py`:

```python
from smda_scheduler.workflow import (
    GraphError,
    RoleResult,
    WorkflowGraph,
    eligible_child_ids,
)


class WorkflowEngine:
    def __init__(self, definition: WorkflowDefinition) -> None:
        self._definition = definition

    @property
    def definition(self) -> WorkflowDefinition:
        return self._definition

    def dispatch_phase(self, phase):
        return self._definition.dispatch_phase_overrides.get(phase, phase)

    def next_phase(self, phase, result: RoleResult):
        key = (phase, result.verdict, result.required_next_action)
        try:
            return self._definition.transitions[key]
        except KeyError as error:
            raise GraphError(
                "No transition for "
                f"phase={phase} verdict={result.verdict} "
                f"required_next_action={result.required_next_action}"
            ) from error

    def is_terminal(self, phase) -> bool:
        return phase in self._definition.terminal_phases

    def role_contract(self, phase):
        return self._definition.stage(phase).role_contract

    def eligible(self, graph: WorkflowGraph, *, completed_child_ids):
        # Child-tier eligibility is the existing graph-completion computation.
        return eligible_child_ids(graph, completed_child_ids=completed_child_ids)
```

- [ ] **Step 4: Run tests** — expect PASS (parametrized parity over all
  transitions).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/workflow_engine.py packages/scheduler/tests/test_workflow_engine.py
git commit -m "Add WorkflowEngine decision methods with legacy parity"
```

---

## Task 3: Route `scheduling.run_once` through the engine (behaviour-preserving)

**Files:** modify `scheduling.py`; `test_scheduling.py` (must stay green
unchanged).

- [ ] **Step 1: Add a regression test pinning engine usage**

Append to `packages/scheduler/tests/test_scheduling.py`:

```python
from smda_scheduler.workflow_engine import CHILD_DEFINITION, WorkflowEngine


def test_run_once_uses_engine_transition_for_unknown_action_raises(tmp_path):
    graph = WorkflowGraph(children={"c": ChildNode(id="c")})

    def executor(dispatch):
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(verdict="DONE", required_next_action="bogus"),
        )

    with pytest.raises(GraphError):
        run_once(graph, SchedulerState(), executor=executor, now=0.0, owner="d")
```

(This proves the engine's transition lookup — not a stale table — drives
`run_once`. If `run_once` already raised `GraphError` via the legacy helper,
keep the test; after refactor it must still raise via the engine.)

- [ ] **Step 2: Run full `test_scheduling.py`, confirm current green baseline**

```bash
uv run pytest packages/scheduler/tests/test_scheduling.py -q
```

- [ ] **Step 3: Thread the engine through `run_once`**

In `scheduling.py`, construct the engine once and replace the three decision
touchpoints. Keep claim/lease/durable/backoff/escalation EXACTLY as-is.

```python
from smda_scheduler.workflow_engine import CHILD_DEFINITION, WorkflowEngine

_CHILD_ENGINE = WorkflowEngine(CHILD_DEFINITION)
```

- Replace `_dispatch_phase(child.phase)` (line ~123) with
  `_CHILD_ENGINE.dispatch_phase(child.phase)`.
- Replace `transition_child_phase(dispatch_phase, outcome.role_result)`
  (line ~147) with
  `_CHILD_ENGINE.next_phase(dispatch_phase, outcome.role_result)`.
- Where the loop tests completion / terminal, route through
  `_CHILD_ENGINE.is_terminal(...)` and keep `_CHILD_ENGINE.eligible(...)` in
  place of the direct `eligible_child_ids` call (identical result).

Do NOT change the `_FIXING_PHASES` escalation, claim creation, or
`run_once_durable` recording.

- [ ] **Step 4: Run the FULL parity gate**

```bash
uv run pytest packages/scheduler/tests/test_scheduling.py packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_workflow.py -q
```

Expected: **all green, no test changed** (besides the one added in Step 1). This
is the zero-behaviour-change proof.

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/scheduling.py packages/scheduler/tests/test_scheduling.py
git commit -m "Route child scheduling decisions through the workflow engine"
```

---

## Task 4: Definition registry (Mode → Definition)

**Files:** create `workflow_registry.py`; create `test_workflow_registry.py`.

- [ ] **Step 1: Write failing tests**

Create `packages/scheduler/tests/test_workflow_registry.py`:

```python
import pytest

from smda_scheduler.execution_modes import ExecutionMode
from smda_scheduler.workflow_engine import CHILD_DEFINITION
from smda_scheduler.workflow_registry import (
    WorkflowRegistryError,
    definition_for_mode,
)


def test_registry_resolves_smda_child_to_child_definition():
    assert definition_for_mode(ExecutionMode.SMDA_CHILD) is CHILD_DEFINITION


def test_registry_unknown_mode_raises():
    with pytest.raises(WorkflowRegistryError):
        definition_for_mode(ExecutionMode.SMDA)  # not yet registered in Phase 1a
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement the registry**

Create `packages/scheduler/src/smda_scheduler/workflow_registry.py`:

```python
from __future__ import annotations

from smda_scheduler.execution_modes import ExecutionMode
from smda_scheduler.workflow_engine import CHILD_DEFINITION, WorkflowDefinition


class WorkflowRegistryError(KeyError):
    """Raised when no workflow definition is registered for a mode."""


_REGISTRY: dict[ExecutionMode, WorkflowDefinition] = {
    ExecutionMode.SMDA_CHILD: CHILD_DEFINITION,
}


def definition_for_mode(mode: ExecutionMode) -> WorkflowDefinition:
    try:
        return _REGISTRY[mode]
    except KeyError as error:
        raise WorkflowRegistryError(
            f"No workflow definition registered for mode: {mode}"
        ) from error
```

- [ ] **Step 4: Run tests** — expect PASS. (Parent/task/review register in later
  phases; the unknown-mode test documents that boundary.)

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/workflow_registry.py packages/scheduler/tests/test_workflow_registry.py
git commit -m "Add workflow definition registry (smda-child registered)"
```

---

## Task 5: Single-source the legacy helpers + full-suite parity gate

**Files:** modify `workflow.py`; full suite.

- [ ] **Step 1: Make legacy helpers delegate (no behaviour change)**

To remove duplication, have `transition_child_phase` and `_dispatch_phase`
delegate to `CHILD_DEFINITION` / the engine so there is one source of truth.
Keep their public signatures (other call sites + tests depend on them).

```python
# workflow.py
def transition_child_phase(phase: ChildPhase, result: RoleResult) -> ChildPhase:
    from smda_scheduler.workflow_engine import _CHILD_ENGINE_SINGLETON
    return _CHILD_ENGINE_SINGLETON.next_phase(phase, result)
```

If this creates an import cycle (`workflow_engine` imports from `workflow`),
keep `transition_child_phase`'s body as the table lookup and instead assert
equality in a test (the parity tests in Task 2 already guarantee it). Prefer the
no-cycle option; do not introduce a circular import to chase DRY.

- [ ] **Step 2: Run the ENTIRE Python suite + TS build**

```bash
uv run pytest packages/scheduler/tests/ -q
npm run test:ts
npx tsc --noEmit
```

Expected: all green (TS unaffected). Record the counts.

- [ ] **Step 3: Refactor pass**

`code-simplifier` over the new modules. Confirm no `transition_child_phase` /
`_dispatch_phase` logic is duplicated between `workflow.py` and
`workflow_engine.py`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Single-source child transition via engine; full parity green"
```

---

## Acceptance Criteria

1. `CHILD_DEFINITION` reproduces the legacy child transition table, terminal set,
   dispatch-phase mapping, and role map exactly (Task 1–2 parity tests).
2. `scheduling.run_once` drives child dispatch through `WorkflowEngine`; the full
   `test_scheduling` / `test_runtime` / `test_workflow` suites pass **unchanged**
   (zero behaviour change).
3. A registry resolves `smda-child` → `CHILD_DEFINITION`; unknown modes raise.
4. Entire Python suite + TS build green.
5. No duplicated transition logic between `workflow.py` and `workflow_engine.py`.

## Done Definition

- All Acceptance Criteria met; the existing child test suite is byte-for-byte
  equivalent in behaviour (only additive tests).
- `Effect` / `Aggregate` kinds exist but are not interpreted (seam reserved).
- The branch is ready for Phase 1b (parent definition + `Effect`/`Aggregate`
  interpretation) to build on the engine.

## Out Of Scope — Next Plan (Phase 1b)

- Convert the parent if-ladder (`runtime.py:190-263`) to a parent
  `WorkflowDefinition`; implement the `Effect` (publish-children, final-accept)
  and `Aggregate` (children-published) handlers; register `smda` → parent
  definition. That plan reuses this engine and the same parity discipline.
