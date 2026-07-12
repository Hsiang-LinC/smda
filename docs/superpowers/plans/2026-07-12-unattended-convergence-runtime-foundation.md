# Unattended Convergence Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the A-E Runtime foundation: one Parent Role residence, a complete typed Workflow Graph, semantic Attempt History, expected-phase Parent/Roadmap transitions, and atomic Backlog Projection enqueue.

**Architecture:** Keep the existing Python Workflow Engine and SQLite `PhaseLedger`, but deepen their existing interfaces instead of adding another runtime. Workflow Definitions own static Parent Role facts; `PhaseLedger` owns typed graph persistence, semantic Attempt History, and fenced Parent/Roadmap transactions. External publication sagas, Request Intake, the non-blocking Coordinator, and typed Escalation are separate follow-up plans built on this foundation.

**Tech Stack:** Python 3.12, SQLite, pytest, existing SMDA Workflow Engine and Adapter protocols.

---

## Program Position

This is plan 1 of the reviewed unattended-convergence program:

1. **This plan:** A-E Runtime foundation.
2. Runtime-led non-blocking Coordinator and bounded worker pool.
3. Request Admission, Amendments, and Git-backed Accepted Spec Artifacts.
4. Control Events, retry separation, and typed Escalation.
5. Child/Roadmap publication sagas and the AFK convergence suite.

The split is intentional. This plan must leave all current workflows green and
create the transaction and semantic interfaces consumed by later plans.

## File Structure

| File | Responsibility after this plan |
|---|---|
| `packages/scheduler/src/smda_scheduler/workflow_engine.py` | sole static Parent Stage/Role Contract/transition residence |
| `packages/scheduler/src/smda_scheduler/runtime.py` | stateful Parent hooks and heterogeneous Runtime Effects; no duplicate Parent Role facts or raw Attempt filtering |
| `packages/scheduler/src/smda_scheduler/workflow_graph.py` | complete typed Workflow Graph Artifact plus derived scheduling view |
| `packages/scheduler/src/smda_scheduler/workflow.py` | phases, results, and scheduling graph algorithms |
| `packages/scheduler/src/smda_scheduler/phase_ledger.py` | typed graph persistence, semantic Attempt History, Parent/Roadmap intake and fenced transactions, atomic outbox enqueue |
| `packages/scheduler/src/smda_scheduler/route_dispatch.py` | route dispatch only; no post-transition Parent lifecycle writes |
| `packages/scheduler/src/smda_scheduler/roadmap_publication.py` | current Roadmap publication behavior using fenced transitions; full intent/receipt saga remains plan 5 |
| `packages/scheduler/tests/test_workflow_graph.py` | complete graph Artifact validation and conversion |
| `packages/scheduler/tests/test_phase_ledger.py` | semantic history and transaction/failure-injection surface |
| `packages/scheduler/tests/test_workflow_engine.py` | static Parent Stage truth and dispatch |
| `packages/scheduler/tests/test_runtime.py` | production Parent workflow behavior through Workflow Definitions |
| `packages/scheduler/tests/test_reconciliation.py` | at-least-once outbox delivery remains compatible |

## Task 1: Make Workflow Definition The Parent Role Residence

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow_engine.py:39-320`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py:580-1298`
- Modify: `packages/scheduler/tests/test_workflow_engine.py:27-273`
- Modify: `packages/scheduler/tests/test_runtime.py:1-35,1320-2068,4139-4673`

- [ ] **Step 1: Write failing Workflow Definition ownership tests**

Add tests proving every Parent `ROLE_ATTEMPT` Stage carries its Role Contract and
the two gate-to-attempt differences are represented by
`dispatch_phase_overrides`:

```python
@pytest.mark.parametrize(
    "gate_phase,attempt_phase,role",
    [
        ("SPEC_FINALIZED", ParentPhase.GRAPH_DECOMPOSING, "graph_decomposer"),
        (ParentPhase.GRAPH_FIXING.value, ParentPhase.GRAPH_FIXING, "graph_fixer"),
        (
            ParentPhase.GRAPH_SPEC_REVIEWING.value,
            ParentPhase.GRAPH_SPEC_REVIEWING,
            "graph_spec_reviewer",
        ),
        (
            ParentPhase.GRAPH_EXECUTION_REVIEWING.value,
            ParentPhase.GRAPH_EXECUTION_REVIEWING,
            "graph_execution_reviewer",
        ),
        (
            ParentPhase.PARENT_QA_READY.value,
            ParentPhase.PARENT_QA_REVIEWING,
            "parent_qa_reviewer",
        ),
        (
            ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING.value,
            ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING,
            "parent_integration_conflict_resolver",
        ),
    ],
)
def test_parent_definition_owns_role_contract_and_attempt_phase(
    gate_phase, attempt_phase, role
):
    stage = PARENT_DEFINITION.stage(gate_phase)
    assert stage.role_contract is not None
    assert stage.role_contract.role.value == role
    assert PARENT_DEFINITION.dispatch_phase_overrides.get(
        gate_phase, gate_phase
    ) == attempt_phase
```

- [ ] **Step 2: Run the tests and confirm the static facts are missing**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_workflow_engine.py::test_parent_definition_owns_role_contract_and_attempt_phase -q
```

Expected: FAIL because Parent `StageSpec.role_contract` is `None` and Parent
dispatch overrides do not yet carry `GRAPH_DECOMPOSING` / `PARENT_QA_REVIEWING`.

- [ ] **Step 3: Put Role Contracts and dispatch phases in `PARENT_DEFINITION`**

Import `parent_role_contract_for_phase` and replace `_parent_stage` with one
helper that accepts the gate phase, handler kind, and optional attempt phase:

```python
def _parent_role_stage(gate_phase, attempt_phase: ParentPhase) -> StageSpec:
    return StageSpec(
        phase=gate_phase,
        kind=WorkHandlerKind.ROLE_ATTEMPT,
        role_contract=parent_role_contract_for_phase(attempt_phase),
    )
```

Use it for all six Parent RoleAttempt stages. Add only these Parent overrides:

```python
dispatch_phase_overrides={
    _SPEC_FINALIZED: ParentPhase.GRAPH_DECOMPOSING,
    ParentPhase.PARENT_QA_READY.value: ParentPhase.PARENT_QA_REVIEWING,
}
```

Do not put Runtime callables, labels, or persistence hooks into `StageSpec`.

- [ ] **Step 4: Replace `ParentRoleStage` with stateful-only Runtime hooks**

In `runtime.py`, replace the duplicate static record with:

```python
@dataclass(frozen=True)
class ParentRoleHooks:
    gate_label: str
    build_request: Callable[..., RoleAttemptRequest]
    build_success: Callable[..., tuple[dict | None, str]]
    passing: Callable[[AttemptOutcome], bool] = lambda outcome: True
    on_failure: Callable[..., ParentIntakeResult] | None = None
```

Key the private hooks map by gate phase. Remove `gate_phase`, `attempt_phase`,
and `transition_phase` from Runtime-owned data. Change the generic runner to
receive `stage: StageSpec`, `attempt_phase`, and `hooks: ParentRoleHooks`; use:

```python
gate_phase = getattr(stage.phase, "value", stage.phase)
role_contract = stage.role_contract
if role_contract is None:
    raise GraphError(f"Parent RoleAttempt stage has no Role Contract: {gate_phase}")
```

`WorkflowEngine.dispatch_parent_stage()` passes its `StageSpec` and
`dispatch_phase(phase)` to `dispatch_role_attempt_stage`. Runtime hook lookup is
private implementation selection only.

- [ ] **Step 5: Delete the five pass-through Parent tick callers**

Delete:

```text
run_parent_graph_decomposition_tick
run_parent_graph_fixing_tick
run_parent_graph_spec_review_tick
run_parent_graph_execution_review_tick
run_parent_qa_review_tick
```

Update their tests to call `run_parent_workflow_tick()` or
`WorkflowEngine.dispatch_parent_stage()` through the production path. Keep
focused generic-runner tests only where they exercise concern follow-up or
stateful failure hooks.

- [ ] **Step 6: Run Parent dispatch and Runtime tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_workflow_engine.py \
  packages/scheduler/tests/test_runtime.py -q
```

Expected: PASS; existing Parent phase/result assertions remain unchanged.

- [ ] **Step 7: Verify deletion and commit**

Run:

```bash
rg "ParentRoleStage|_PARENT_ROLE_STAGES|def run_parent_graph_(decomposition|fixing|spec_review|execution_review)_tick|def run_parent_qa_review_tick" \
  packages/scheduler/src packages/scheduler/tests
```

Expected: no matches.

Commit:

```bash
git add packages/scheduler/src/smda_scheduler/workflow_engine.py \
  packages/scheduler/src/smda_scheduler/runtime.py \
  packages/scheduler/tests/test_workflow_engine.py \
  packages/scheduler/tests/test_runtime.py
git commit -m "Deepen parent role dispatch"
```

## Task 2: Introduce The Complete Workflow Graph Artifact

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/workflow_graph.py`
- Create: `packages/scheduler/tests/test_workflow_graph.py`
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py:54-213`
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py:294-369,1155-1200,1406-1468`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py:759-830,2019-2105,2350-2610,3110-3225`
- Modify: `packages/scheduler/tests/test_phase_ledger.py:465-540`
- Modify: `packages/scheduler/tests/test_runtime.py:264-287,1320-1720,2071-2635`

- [ ] **Step 1: Write failing complete-graph round-trip tests**

Create `test_workflow_graph.py` with one complete Artifact:

```python
from smda_scheduler.workflow_graph import WorkflowGraphArtifact


def complete_graph_dict():
    return {
        "parent_id": "DANNY-66",
        "graph_checksum": "sha256:graph-v1",
        "children": [
            {
                "node_id": "child-001",
                "title": "Add durable transition",
                "body": "Move Parent transition truth into the Runtime Ledger.",
                "acceptance_criteria": ["stale transitions fail"],
                "dependencies": [],
                "in_scope": ["Parent persistence"],
                "out_of_scope": ["Request Intake"],
                "touched_surfaces": {
                    "files": ["packages/scheduler/src/smda_scheduler/phase_ledger.py"],
                    "modules": ["smda_scheduler.phase_ledger"],
                    "contracts": ["Parent Transition"],
                    "docs": ["docs/adr/0010-expected-phase-parent-transitions.md"],
                    "tests": ["packages/scheduler/tests/test_phase_ledger.py"],
                },
                "verification": {
                    "required": ["pytest test_phase_ledger.py"],
                    "smoke": [],
                },
                "risk_level": "medium",
            }
        ],
        "dependency_edges": [],
    }


def test_complete_workflow_graph_round_trips_without_losing_fields():
    graph = WorkflowGraphArtifact.from_dict(complete_graph_dict())
    assert graph.to_dict() == complete_graph_dict()
    assert graph.scheduling_view().children["child-001"].dependencies == frozenset()
```

Also test rejection of an unknown risk, an incomplete touched-surfaces object,
an incomplete verification object, an unknown dependency, and a dependency
edge without required artifacts.

- [ ] **Step 2: Run the new tests and confirm the Artifact is missing**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_workflow_graph.py -q
```

Expected: collection FAIL because `smda_scheduler.workflow_graph` does not
exist.

- [ ] **Step 3: Implement the typed Artifact and derived scheduling view**

Create immutable value types matching the existing Zod-derived graph schema:

```python
@dataclass(frozen=True)
class TouchedSurfaces:
    files: tuple[str, ...]
    modules: tuple[str, ...]
    contracts: tuple[str, ...]
    docs: tuple[str, ...]
    tests: tuple[str, ...]


@dataclass(frozen=True)
class Verification:
    required: tuple[str, ...]
    smoke: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowGraphChild:
    node_id: str
    title: str
    body: str
    acceptance_criteria: tuple[str, ...]
    dependencies: tuple[str, ...]
    in_scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    touched_surfaces: TouchedSurfaces
    verification: Verification
    risk_level: str


@dataclass(frozen=True)
class WorkflowGraphArtifact:
    parent_id: str
    graph_checksum: str
    children: tuple[WorkflowGraphChild, ...]
    dependency_edges: tuple[DependencyEdge, ...]
```

`from_dict()` validates required non-empty strings/lists, the existing
`low|medium|high` risk vocabulary, unique Child IDs, dependency references,
typed edges, and cycles. `to_dict()` emits the current persisted/schema shape.
`scheduling_view()` returns the existing scheduling `WorkflowGraph` from
`workflow.py`; no caller builds a second graph by parsing dictionaries.

- [ ] **Step 4: Make `PhaseLedger` persist and load the Artifact**

Change the public signatures to `record_graph(self, graph:
WorkflowGraphArtifact) -> None` and `load_graph(self, parent_id: str) ->
WorkflowGraphArtifact`.

Keep the existing SQLite columns and migration behavior. Move SQL-to-value and
value-to-SQL conversion inside `PhaseLedger`; do not expose JSON-shaped rows.

Update the phase-ledger test to assert:

```python
loaded = ledger.load_graph("DANNY-66")
assert loaded == WorkflowGraphArtifact.from_dict(complete_graph_dict())
```

- [ ] **Step 5: Migrate Runtime graph consumers**

Replace dictionary normalization in these paths with Artifact methods/fields:

```text
_graph_payload_from_outcome
_child_task_context_from_graph
_graph_child
_graph_children_from_persisted_graph
_dependency_edges_from_persisted_graph
_graph_snapshot
run_parent_child_publication_tick
run_child_candidate_tick
```

Role output is converted once with `WorkflowGraphArtifact.from_dict()` before
persistence. Child task context and publication read the typed Artifact.
Scheduling receives only `graph.scheduling_view()`.

- [ ] **Step 6: Run graph, ledger, scheduling, and Runtime tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_workflow_graph.py \
  packages/scheduler/tests/test_workflow.py \
  packages/scheduler/tests/test_scheduling.py \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_runtime.py -q
```

Expected: PASS with complete graph fields preserved through decomposition,
persistence, scheduling, Child context, and publication.

- [ ] **Step 7: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/workflow_graph.py \
  packages/scheduler/src/smda_scheduler/workflow.py \
  packages/scheduler/src/smda_scheduler/phase_ledger.py \
  packages/scheduler/src/smda_scheduler/runtime.py \
  packages/scheduler/tests/test_workflow_graph.py \
  packages/scheduler/tests/test_workflow.py \
  packages/scheduler/tests/test_scheduling.py \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_runtime.py
git commit -m "Deepen workflow graph artifact"
```

## Task 3: Move Attempt Ordering And Evidence Selection Behind `PhaseLedger`

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py:66-292`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py:643-747,1930,2308-2348,2652-2725,3044-3120,3252-3330`
- Modify: `packages/scheduler/src/smda_scheduler/child_dependency_gate.py:19-118`
- Modify: `packages/scheduler/tests/test_phase_ledger.py:305-446`
- Modify: `packages/scheduler/tests/test_runtime.py:1320-2068,2897-3220,3308-3830`
- Modify: `packages/scheduler/tests/test_child_dependency_gate.py`

- [ ] **Step 1: Write failing semantic Attempt History tests**

Add phase-ledger tests for these methods:

```python
assert ledger.next_attempt_number(
    target_kind="parent",
    target_id="DANNY-66",
    phase=ParentPhase.GRAPH_SPEC_REVIEWING,
) == 3

assert ledger.latest_review_findings(
    target_kind="parent",
    target_id="DANNY-66",
    phases=(ParentPhase.GRAPH_SPEC_REVIEWING,),
) == "second review report"

assert ledger.latest_quality_candidate_ref("DANNY-66:child-001") == "commit-10"
assert ledger.parent_qa_results("DANNY-66")[-1]["verdict"] == "FAIL"
assert ledger.conflict_attempt_history("DANNY-66")[-1]["attempt_id"].endswith("-10")
```

Seed attempts out of lexicographic order (`attempt-2`, `attempt-10`) so the test proves
numeric Attempt ordering rather than insertion or string ordering.

- [ ] **Step 2: Run the tests and confirm the semantic methods are missing**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_phase_ledger.py -q
```

Expected: FAIL with missing `PhaseLedger` semantic methods.

- [ ] **Step 3: Add semantic SQL-backed methods**

Keep `load_attempts()` only for read-only status/tests. Add methods that query
by `target_kind`, `target_id`, and Phase inside `PhaseLedger`, parse result JSON,
and order by the numeric suffix used by current Attempt IDs/idempotency keys.

The minimum public surface is `next_attempt_number(target_kind, target_id,
phase)`, `latest_review_findings(target_kind, target_id, phases)`,
`latest_quality_candidate_ref(child_id)`, `parent_qa_results(parent_id)`, and
`conflict_attempt_history(parent_id)`, with the return types asserted by the
tests in Step 1.

Use one private ordered-attempt query implementation. Do not duplicate raw-row
filtering inside these methods.

- [ ] **Step 4: Migrate every workflow-control caller**

Replace raw `load_attempts()` filtering in:

```text
run_child_candidate_tick
_next_attempt_number
_parent_qa_result_jsons
_latest_parent_qa_failure_report
_latest_parent_qa_pass_report
_latest_graph_review_findings
_review_findings_for_fixer
_latest_parent_qa_report
_parent_accept_conflict_history
_latest_child_candidate_ref
child_dependency_gate / latest_quality_candidate_ref
```

Change `child_dependency_gate()` to receive a semantic candidate-ref lookup or
the already resolved dependency candidate refs; it must not receive the complete
Attempt row list.

- [ ] **Step 5: Add a structural guard against raw workflow queries**

Add a test that scans production workflow modules:

```python
def test_workflow_control_does_not_load_raw_attempt_rows():
    paths = [
        Path("packages/scheduler/src/smda_scheduler/runtime.py"),
        Path("packages/scheduler/src/smda_scheduler/child_dependency_gate.py"),
        Path("packages/scheduler/src/smda_scheduler/parent_acceptance.py"),
    ]
    assert all(".load_attempts()" not in path.read_text() for path in paths)
```

Status/CLI code may continue to call `load_attempts()` for diagnostics.

- [ ] **Step 6: Run semantic history and dependent workflow tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_child_dependency_gate.py \
  packages/scheduler/tests/test_runtime.py -q
```

Expected: PASS; latest candidate, QA bounds, fixer findings, and conflict
history retain existing behavior.

- [ ] **Step 7: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/phase_ledger.py \
  packages/scheduler/src/smda_scheduler/runtime.py \
  packages/scheduler/src/smda_scheduler/child_dependency_gate.py \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_runtime.py \
  packages/scheduler/tests/test_child_dependency_gate.py
git commit -m "Deepen runtime attempt history"
```

## Task 4: Add Intake-Only Parent Facts And Expected-Phase Transitions

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py:179-255,852-901,1123-1129,1371-1404`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py:109-255,580-950,1301-1885,2820-2875`
- Modify: `packages/scheduler/src/smda_scheduler/roadmap_publication.py:36-101`
- Modify: `packages/scheduler/src/smda_scheduler/cli.py:588-650`
- Modify: `packages/scheduler/tests/test_phase_ledger.py:409-540`
- Modify: `packages/scheduler/tests/test_runtime.py:1173-1298,1320-2068,2071-2480,2701-4380`
- Modify: `packages/scheduler/tests/test_cli.py:336-412`

- [ ] **Step 1: Write failing Parent transition tests**

Add:

```python
def test_parent_transition_preserves_intake_facts_and_rejects_stale_phase(tmp_path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="SPEC_FINALIZED",
        spec_path="docs/spec.md",
        spec_checksum="sha256:spec",
        approval_evidence="approved by user",
    )

    ledger.transition_parent(
        parent_id="DANNY-66",
        expected_phase="SPEC_FINALIZED",
        next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
    )

    assert ledger.load_parent_run("DANNY-66") == {
        "parent_id": "DANNY-66",
        "phase": ParentPhase.GRAPH_SPEC_REVIEWING.value,
        "spec_path": "docs/spec.md",
        "spec_checksum": "sha256:spec",
        "approval_evidence": "approved by user",
    }
    with pytest.raises(StaleParentTransition):
        ledger.transition_parent(
            parent_id="DANNY-66",
            expected_phase="SPEC_FINALIZED",
            next_phase=ParentPhase.GRAPH_EXECUTION_REVIEWING.value,
        )
```

Also test duplicate intake rejection and direct `load_parent_run(parent_id)`.

- [ ] **Step 2: Run the tests and confirm current blind upsert behavior fails**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_phase_ledger.py -q
```

Expected: FAIL because `create_parent_run`, `load_parent_run`,
`transition_parent`, and `StaleParentTransition` do not exist.

- [ ] **Step 3: Implement the minimal Parent persistence interface**

Add:

```python
class ParentRunExists(RuntimeError):
    pass


class StaleParentTransition(RuntimeError):
    pass
```

`create_parent_run()` performs a plain `INSERT` and raises `ParentRunExists` on
duplicate identity. `load_parent_run()` performs a direct primary-key lookup.
`transition_parent()` runs:

```sql
UPDATE parent_run_state
SET phase = ?
WHERE parent_id = ? AND phase = ?
```

and raises `StaleParentTransition` unless exactly one row changes. It accepts no
spec path/checksum/approval parameters. Add `force_parent_phase()` for the
audited CLI repair path; normal Runtime code must not call it.

- [ ] **Step 4: Migrate intake and direct lookup callers**

Use `create_parent_run()` only in:

```text
run_parent_candidate_intake
run_roadmap_candidate_intake
```

Use `load_parent_run()` in `_parent_run_for`, RouteDispatcher parent existence,
Roadmap publication lookup, and CLI status/repair paths. Remove the existing
whole-table parent-existence comprehension.

- [ ] **Step 5: Migrate every Parent/Roadmap phase write**

Replace production `record_parent_run()` calls in:

```text
_write_parent_success
_route_failed_graph_review
_child_accept_conflict_on_failure
run_roadmap_decomposition_tick
run_roadmap_completion_tick
run_parent_child_publication_tick
run_parent_child_acceptance_tick
_route_child_accept_conflict
run_parent_remediation_planning_tick
run_parent_final_accept_tick
run_landing_conflict_rebase_tick
publish_roadmap_members
```

Each call supplies the phase it already checked as `expected_phase`; no caller
passes immutable spec facts. CLI `force-phase` alone uses
`force_parent_phase()`.

- [ ] **Step 6: Prove stale workflow work cannot overwrite a newer phase**

Add a Runtime test that executes two completions built from the same
`SPEC_FINALIZED` snapshot. Commit the first; assert the second raises
`StaleParentTransition` and leaves the first next phase intact.

- [ ] **Step 7: Run ledger, Runtime, RouteDispatcher, Roadmap, and CLI tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_runtime.py \
  packages/scheduler/tests/test_workspace_tick.py \
  packages/scheduler/tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 8: Verify no production blind upsert remains and commit**

Run:

```bash
rg "record_parent_run\(" packages/scheduler/src/smda_scheduler
```

Expected: no production matches. Then commit:

```bash
git add packages/scheduler/src/smda_scheduler/phase_ledger.py \
  packages/scheduler/src/smda_scheduler/runtime.py \
  packages/scheduler/src/smda_scheduler/roadmap_publication.py \
  packages/scheduler/src/smda_scheduler/route_dispatch.py \
  packages/scheduler/src/smda_scheduler/cli.py \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_runtime.py \
  packages/scheduler/tests/test_workspace_tick.py \
  packages/scheduler/tests/test_cli.py
git commit -m "Fence parent runtime transitions"
```

## Task 5: Atomically Commit Parent Outcomes And Backlog Projections

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py:130-255,455-555,852-901,1352-1468`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py:580-950,1301-1885,2750-3040`
- Modify: `packages/scheduler/src/smda_scheduler/route_dispatch.py:87-171`
- Modify: `packages/scheduler/src/smda_scheduler/reconciliation.py:30-73`
- Modify: `packages/scheduler/tests/test_phase_ledger.py:409-650`
- Modify: `packages/scheduler/tests/test_runtime.py:1320-2068,2481-4380,4503-4673`
- Modify: `packages/scheduler/tests/test_workspace_tick.py:323-760`
- Modify: `packages/scheduler/tests/test_reconciliation.py`

- [ ] **Step 1: Write failure-injection tests for transition plus outbox**

Define an immutable effect value in `phase_ledger.py`:

```python
@dataclass(frozen=True)
class AttemptResultUpdate:
    attempt_id: str
    status: str
    result_json: dict[str, Any] | None
    error_message: str | None


@dataclass(frozen=True)
class BacklogEffect:
    effect_id: str
    idempotency_key: str
    effect_type: str
    target_id: str
    payload: dict[str, Any]
```

Write tests proving `transition_parent()` can atomically include an Attempt
result, optional Workflow Graph Artifact, and effects. Construct the update
explicitly:

```python
attempt_result = AttemptResultUpdate(
    attempt_id="DANNY-66-GRAPH_DECOMPOSING-1",
    status="succeeded",
    result_json={"verdict": "DONE", "required_next_action": "submit_for_graph_review"},
    error_message=None,
)
ledger.transition_parent(
    parent_id="DANNY-66",
    expected_phase="SPEC_FINALIZED",
    next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
    attempt_result=attempt_result,
    graph=graph,
    effects=(comment_effect, state_effect),
)
```

Seed a tracker effect whose idempotency key conflicts with one supplied effect,
then assert the resulting SQLite integrity error rolls back the phase, Attempt
result, graph, and all new effects. Execute again with a fresh idempotency key
and assert all four facts appear together.

- [ ] **Step 2: Run the tests and confirm transaction composition is missing**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_phase_ledger.py -q
```

Expected: FAIL because `transition_parent()` does not accept the atomic fact
bundle.

- [ ] **Step 3: Deepen `transition_parent()`**

Inside one `BEGIN IMMEDIATE` transaction:

1. update phase with expected-phase comparison;
2. update the supplied Attempt result, if any;
3. store the supplied Workflow Graph Artifact, if any;
4. insert every `BacklogEffect` with the existing unique idempotency rule;
5. commit once.

Extract private `_record_tracker_effect(connection, effect)` so both
`transition_parent()` and the diagnostic/non-transition effect writer reuse the
same SQL. Do not call one public transaction method from another.

- [ ] **Step 4: Generate lifecycle effects before Parent transition commit**

Add one pure helper in `runtime.py`:

```python
def _parent_lifecycle_effects(
    *, issue_id: str, target_state: str, comment: str
) -> tuple[BacklogEffect, BacklogEffect]:
    key = hashlib.sha256(comment.encode("utf-8")).hexdigest()[:16]
    return (
        BacklogEffect(
            effect_id=f"lifecycle-comment:{issue_id}:{key}",
            idempotency_key=f"lifecycle-comment:{issue_id}:{key}",
            effect_type="comment",
            target_id=issue_id,
            payload={"body": comment},
        ),
        BacklogEffect(
            effect_id=f"lifecycle-state:{issue_id}:{key}",
            idempotency_key=f"lifecycle-state:{issue_id}:{key}",
            effect_type="set_state",
            target_id=issue_id,
            payload={"state": target_state},
        ),
    )
```

Parent role success/failure handlers build the comment before committing and
pass these effects into `transition_parent()`. Extend `create_parent_run` with
an `effects: tuple[BacklogEffect, ...] = ()` parameter so intake can persist its
initial lifecycle projections in the same transaction.

For an execution failure that records evidence but remains in the same Phase,
call `transition_parent()` with `next_phase` equal to `expected_phase`; the
Attempt result and lifecycle effects still commit atomically.

- [ ] **Step 5: Remove RouteDispatcher post-transition lifecycle writes**

Delete `_record_parent_lifecycle_effects()` and its calls in Parent/Roadmap
dispatch. RouteDispatcher only returns the already committed Runtime result.
Update workspace tests to assert pending effects exist immediately after the
Runtime transition, not because RouteDispatcher added them later.

- [ ] **Step 6: Make final acceptance one transaction**

Replace the current separate final comment, Done state, and Parent phase writes
with one `transition_parent()` call containing both effects. Keep Git landing
outside SQLite, represented by its existing idempotent Parent land operation;
only transition after that operation is durably completed.

Add a failure-injection test proving `FINAL_ACCEPTED` cannot commit without both
pending final effects.

- [ ] **Step 7: Keep reconciliation behavior unchanged**

Run existing reconciliation tests. Add one duplicate-delivery test that inserts
the same semantic effect twice through two transition attempts and proves only
one pending effect exists because the stable idempotency key is unique.

Full Child/Roadmap create-issue intent and receipt sagas remain plan 5; this
task must not fake distributed transactions around Adapter calls.

- [ ] **Step 8: Run targeted Runtime/outbox tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_runtime.py \
  packages/scheduler/tests/test_workspace_tick.py \
  packages/scheduler/tests/test_reconciliation.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/phase_ledger.py \
  packages/scheduler/src/smda_scheduler/runtime.py \
  packages/scheduler/src/smda_scheduler/route_dispatch.py \
  packages/scheduler/src/smda_scheduler/reconciliation.py \
  packages/scheduler/tests/test_phase_ledger.py \
  packages/scheduler/tests/test_runtime.py \
  packages/scheduler/tests/test_workspace_tick.py \
  packages/scheduler/tests/test_reconciliation.py
git commit -m "Commit parent projections atomically"
```

## Task 6: Migrate All Parent/Roadmap Transition Combinations To The Deep Interface

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/src/smda_scheduler/roadmap_publication.py`
- Modify: `packages/scheduler/src/smda_scheduler/route_dispatch.py`
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Modify: `packages/scheduler/tests/test_runtime.py`
- Modify: `packages/scheduler/tests/test_phase_ledger.py`
- Modify: `packages/scheduler/tests/test_workspace_tick.py`

- [ ] **Step 1: Add a production-call structural test**

Add a packaging/architecture test that permits only these public write methods
for Parent/Roadmap state:

```text
create_parent_run
transition_parent
force_parent_phase   # CLI break-glass caller only
```

The test fails if Runtime or Roadmap publication contains
`record_parent_run(`, `record_attempt_result_and_parent_run(`, or
`record_attempt_result_parent_run_and_graph(`.

- [ ] **Step 2: Run the structural test and confirm legacy callers remain**

Run the new test directly. Expected: FAIL and list the remaining legacy call
sites.

- [ ] **Step 3: Migrate every result combination**

Use the one deep interface for:

- RoleAttempt success with Attempt result only;
- graph decomposition/fixing success with Attempt result plus graph;
- graph review failure with bounded next phase;
- conflict resolver success/failure;
- remediation and landing Effect transitions;
- Roadmap decomposition/completion transitions;
- concern/follow-up lifecycle effects that are required by the transition.

Do not generalize heterogeneous Git or Backlog Adapter calls into opaque
callables. They remain explicit Runtime Effects and commit only their durable
operation result and transition facts.

- [ ] **Step 4: Delete superseded public compound write methods**

After all callers migrate, delete:

```text
record_parent_run
record_attempt_result_and_parent_run
record_attempt_result_parent_run_and_graph
```

Keep `record_attempt_result()` for execution failures that do not transition a
Parent because they belong to Child or diagnostic paths outside this Parent
transaction. Keep raw load methods only for read-only status.

- [ ] **Step 5: Run all Python scheduler tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q
```

Expected: all tests pass; live tests may retain their documented opt-in skips.

- [ ] **Step 6: Commit**

```bash
git add packages/scheduler/src/smda_scheduler \
  packages/scheduler/tests
git commit -m "Finish runtime ledger foundation migration"
```

## Task 7: Verify The Foundation And Update Durable Gap Status

**Files:**
- Modify: `docs/known-gaps.md`
- Modify: `docs/work-ledger/active.md`
- Modify: `docs/work-ledger/completed.md`

- [ ] **Step 1: Run the architecture guards**

Run:

```bash
rg "ParentRoleStage|_PARENT_ROLE_STAGES|record_parent_run\(|record_attempt_result_and_parent_run|record_attempt_result_parent_run_and_graph" \
  packages/scheduler/src/smda_scheduler
rg "\.load_attempts\(\)" \
  packages/scheduler/src/smda_scheduler/runtime.py \
  packages/scheduler/src/smda_scheduler/child_dependency_gate.py \
  packages/scheduler/src/smda_scheduler/parent_acceptance.py
```

Expected: no matches.

- [ ] **Step 2: Run product gates**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q
npm run test:ts
npm run typecheck
npm run schema:export
git diff --check
```

Expected: all commands pass; live smoke tests may retain documented opt-in
skips.

- [ ] **Step 3: Update known gaps precisely**

Mark the atomic lifecycle-projection and expected-phase Parent transition gaps
complete only if their failure-injection and structural guards pass. Leave a
smaller explicit follow-up for Child/Roadmap external create-issue
intent/receipt sagas; do not claim publication is complete in this plan.

- [ ] **Step 4: Update the tracker and commit**

Move the implementation work item to `completed.md` only after human acceptance
under the repo tracker policy. Record the exact gate outputs and the publication
saga follow-up.

```bash
git add docs/known-gaps.md docs/work-ledger/active.md docs/work-ledger/completed.md
git commit -m "Verify runtime convergence foundation"
```

## Plan Self-Review Checklist

- A maps to Task 1.
- B maps to Task 2.
- C maps to Task 3.
- E is introduced in Task 4 and completed in Task 6.
- D is introduced in Task 5 and completed for lifecycle projections in Task 6;
  external create-issue intent/receipt sagas remain explicitly assigned to
  program plan 5.
- No Task introduces Request Intake, Control/Escalation records, a non-blocking
  Coordinator, remote workers, a broker, or event sourcing.
- Every production change begins with a failing test and ends with targeted or
  full verification plus a focused commit.
