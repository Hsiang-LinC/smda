# Child Dependency Dispatch Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent downstream child issues from dispatching until every blocking upstream dependency has quality-passed and been accepted into the parent integration branch.

**Architecture:** Add a small pure dependency-gate module that evaluates persisted parent graph edges against scheduler state, child attempt refs, and parent accept operations. `run_child_candidate_tick` becomes the child route hard gate: it validates graph/node/checksum, records dependency-wait evidence, and only calls the child workflow when eligible. `run_workspace_tick` then iterates over scanned candidates so a dependency-waiting child cannot starve other eligible issues.

**Tech Stack:** Python 3.11+, SQLite-backed `PhaseLedger`, pytest, existing SMDA scheduler/runtime modules.

---

## File Structure

- Create `packages/scheduler/src/smda_scheduler/child_dependency_gate.py`
  - Owns `ChildDependencyGateResult` and pure helper functions for dependency eligibility.
  - Does not import backlog adapters or execution adapters.
- Create `packages/scheduler/tests/test_child_dependency_gate.py`
  - Unit tests for dependency gate edge cases.
- Modify `packages/scheduler/src/smda_scheduler/runtime.py`
  - Load persisted parent graph in `run_child_candidate_tick`.
  - Verify node id exists.
  - Evaluate dependency gate before dispatch.
  - Return a typed child candidate tick result with `dispatched` or `waiting`.
  - Record idempotent dependency-wait tracker comments.
  - Record child completion tracker effects after parent acceptance completes.
- Modify `packages/scheduler/src/smda_scheduler/runtime_factory.py`
  - Convert child candidate tick result into `TickResult`.
- Modify `packages/scheduler/src/smda_scheduler/workspace_tick.py`
  - Iterate candidates in the scanned page.
  - Continue past `skipped` dependency-wait results.
  - Preserve routing-block and GraphError behavior.
- Modify tests:
  - `packages/scheduler/tests/test_runtime.py`
  - `packages/scheduler/tests/test_workspace_tick.py`
  - `packages/scheduler/tests/test_runtime_factory.py` if result shape changes affect configured tick tests.
- Modify docs:
  - `docs/known-gaps.md`
  - `docs/product-spec.md`

---

### Task 1: Add Pure Child Dependency Gate Tests

**Files:**
- Create: `packages/scheduler/tests/test_child_dependency_gate.py`
- Planned create in Task 2: `packages/scheduler/src/smda_scheduler/child_dependency_gate.py`

- [x] **Step 1: Write failing unit tests for dependency eligibility**

Create `packages/scheduler/tests/test_child_dependency_gate.py` with this complete content:

```python
from smda_scheduler.child_dependency_gate import child_dependency_gate
from smda_scheduler.scheduling import ChildRunState, SchedulerState
from smda_scheduler.workflow import ChildPhase


def graph_with_edge(*, blocks_dispatch: bool = True) -> dict:
    return {
        "parent_id": "DANNY-66",
        "graph_checksum": "sha256:graph",
        "children": [
            {"node_id": "child-001", "dependencies": []},
            {"node_id": "child-002", "dependencies": ["child-001"]},
        ],
        "dependency_edges": [
            {
                "from": "child-001",
                "to": "child-002",
                "type": "code_dependency",
                "blocks_dispatch": blocks_dispatch,
                "reason": "child-002 imports the accepted API.",
                "required_artifacts": ["accepted_commit"],
            }
        ],
    }


def quality_attempt(*, child_id: str = "child-001", candidate_ref: str = "branch-1") -> dict:
    return {
        "target_kind": "child",
        "target_id": child_id,
        "phase": "QUALITY_REVIEWING",
        "status": "succeeded",
        "result_json": {
            "verdict": "PASS",
            "required_next_action": "accept_candidate",
            "branch": candidate_ref,
        },
    }


def accept_operation(
    *,
    parent_id: str = "DANNY-66",
    child_id: str = "child-001",
    candidate_ref: str = "branch-1",
    status: str = "completed",
) -> dict:
    return {
        "operation_id": f"accept:{parent_id}:{child_id}:{candidate_ref}",
        "idempotency_key": f"parent:{parent_id}:{child_id}:{candidate_ref}",
        "parent_id": parent_id,
        "child_id": child_id,
        "candidate_ref": candidate_ref,
        "integration_branch": "smda/DANNY-66/integration",
        "status": status,
        "last_error": None,
    }


def test_child_dependency_gate_allows_child_without_blocking_dependencies():
    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-001",
        graph=graph_with_edge(),
        scheduler_state=SchedulerState(),
        attempts=[],
        parent_accept_operations=[],
    )

    assert result.eligible is True
    assert result.blocked_by == ()
    assert result.missing_artifacts == ()


def test_child_dependency_gate_blocks_when_upstream_has_no_scheduler_state():
    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=SchedulerState(),
        attempts=[],
        parent_accept_operations=[],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:quality_review_passed",)
    assert "child-001" in result.reason


def test_child_dependency_gate_blocks_when_upstream_not_quality_passed():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEWING)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        attempts=[],
        parent_accept_operations=[],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:quality_review_passed",)


def test_child_dependency_gate_blocks_when_upstream_has_no_candidate_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        attempts=[],
        parent_accept_operations=[],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:candidate_ref",)


def test_child_dependency_gate_blocks_when_accept_operation_not_completed():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        attempts=[quality_attempt()],
        parent_accept_operations=[accept_operation(status="pending")],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:accepted_commit",)


def test_child_dependency_gate_allows_when_accept_completed_for_same_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        attempts=[quality_attempt(candidate_ref="branch-1")],
        parent_accept_operations=[accept_operation(candidate_ref="branch-1")],
    )

    assert result.eligible is True
    assert result.blocked_by == ()
    assert result.missing_artifacts == ()


def test_child_dependency_gate_blocks_when_accept_completed_for_different_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        attempts=[quality_attempt(candidate_ref="branch-new")],
        parent_accept_operations=[accept_operation(candidate_ref="branch-old")],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:accepted_commit",)


def test_child_dependency_gate_ignores_non_blocking_edges():
    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(blocks_dispatch=False),
        scheduler_state=SchedulerState(),
        attempts=[],
        parent_accept_operations=[],
    )

    assert result.eligible is True
    assert result.blocked_by == ()
    assert result.missing_artifacts == ()
```

- [x] **Step 2: Run tests to verify they fail because the module does not exist**

Run:

```bash
uv run pytest packages/scheduler/tests/test_child_dependency_gate.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'smda_scheduler.child_dependency_gate'`.

- [x] **Step 3: Commit is not required yet**

Do not commit after the red test. Continue to Task 2.

---

### Task 2: Implement The Pure Child Dependency Gate

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/child_dependency_gate.py`
- Test: `packages/scheduler/tests/test_child_dependency_gate.py`

- [x] **Step 1: Add the dependency gate module**

Create `packages/scheduler/src/smda_scheduler/child_dependency_gate.py` with this content:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smda_scheduler.scheduling import SchedulerState
from smda_scheduler.workflow import ChildPhase


@dataclass(frozen=True)
class ChildDependencyGateResult:
    eligible: bool
    blocked_by: tuple[str, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    reason: str = ""


def child_dependency_gate(
    *,
    parent_id: str,
    child_id: str,
    graph: dict,
    scheduler_state: SchedulerState,
    attempts: list[dict],
    parent_accept_operations: list[dict],
) -> ChildDependencyGateResult:
    blocked_by: list[str] = []
    missing_artifacts: list[str] = []

    for edge in _incoming_blocking_edges(graph, child_id):
        upstream_id = str(edge["from"])
        upstream_state = scheduler_state.children.get(upstream_id)
        if upstream_state is None or upstream_state.phase != ChildPhase.QUALITY_REVIEW_PASSED:
            blocked_by.append(upstream_id)
            missing_artifacts.append(f"{upstream_id}:quality_review_passed")
            continue

        candidate_ref = latest_quality_candidate_ref(attempts, upstream_id)
        if candidate_ref is None:
            blocked_by.append(upstream_id)
            missing_artifacts.append(f"{upstream_id}:candidate_ref")
            continue

        if not _has_completed_accept(
            parent_accept_operations,
            parent_id=parent_id,
            child_id=upstream_id,
            candidate_ref=candidate_ref,
        ):
            blocked_by.append(upstream_id)
            missing_artifacts.append(f"{upstream_id}:accepted_commit")

    unique_blocked_by = tuple(dict.fromkeys(blocked_by))
    unique_missing = tuple(dict.fromkeys(missing_artifacts))
    if not unique_blocked_by:
        return ChildDependencyGateResult(eligible=True)

    return ChildDependencyGateResult(
        eligible=False,
        blocked_by=unique_blocked_by,
        missing_artifacts=unique_missing,
        reason=_reason(unique_blocked_by, unique_missing),
    )


def latest_quality_candidate_ref(attempts: list[dict], child_id: str) -> str | None:
    for attempt in reversed(attempts):
        if (
            attempt.get("target_kind") == "child"
            and attempt.get("target_id") == child_id
            and attempt.get("phase") == ChildPhase.QUALITY_REVIEWING.value
            and attempt.get("status") == "succeeded"
        ):
            result = attempt.get("result_json") or {}
            if not isinstance(result, dict):
                continue
            branch = result.get("branch")
            if isinstance(branch, str) and branch:
                return branch
            commits = result.get("commits")
            if isinstance(commits, list) and commits and isinstance(commits[-1], str):
                return commits[-1]
    return None


def _incoming_blocking_edges(graph: dict, child_id: str) -> list[dict[str, Any]]:
    edges = graph.get("dependency_edges") or []
    return [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and str(edge.get("to")) == child_id
        and bool(edge.get("blocks_dispatch")) is True
        and edge.get("from") is not None
    ]


def _has_completed_accept(
    parent_accept_operations: list[dict],
    *,
    parent_id: str,
    child_id: str,
    candidate_ref: str,
) -> bool:
    for operation in parent_accept_operations:
        if (
            operation.get("parent_id") == parent_id
            and operation.get("child_id") == child_id
            and operation.get("candidate_ref") == candidate_ref
            and operation.get("status") == "completed"
        ):
            return True
    return False


def _reason(blocked_by: tuple[str, ...], missing_artifacts: tuple[str, ...]) -> str:
    blocked = ", ".join(blocked_by)
    missing = ", ".join(missing_artifacts)
    return f"Waiting for accepted upstream dependencies: {blocked}. Missing: {missing}"
```

- [x] **Step 2: Run gate unit tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_child_dependency_gate.py -q
```

Expected: PASS, `8 passed`.

- [x] **Step 3: Commit the pure gate**

Run:

```bash
git add packages/scheduler/src/smda_scheduler/child_dependency_gate.py packages/scheduler/tests/test_child_dependency_gate.py
git commit -m "Add child dependency dispatch gate"
```

Expected: commit succeeds.

---

### Task 3: Add Runtime Tests For Child Candidate Dependency Gating

**Files:**
- Modify: `packages/scheduler/tests/test_runtime.py`
- Planned modify in Task 4: `packages/scheduler/src/smda_scheduler/runtime.py`

- [x] **Step 1: Add runtime tests for blocked and eligible child dispatch**

Append these tests near the existing `run_child_candidate_tick` tests in `packages/scheduler/tests/test_runtime.py`:

```python
def test_run_child_candidate_tick_waits_for_unaccepted_graph_dependency(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    issue = BacklogIssue(
        id="DANNY-66-C2",
        title="Use accepted API",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:graph",
                "Node id: child-002",
                "Acceptance criteria: downstream uses accepted API",
            ]
        ),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_graph(
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001"),
            _complete_graph_child(
                node_id="child-002",
                dependencies=["child-001"],
            ),
        ],
        dependency_edges=[
            {
                "from": "child-001",
                "to": "child-002",
                "type": "code_dependency",
                "blocks_dispatch": True,
                "reason": "child-002 imports child-001 output.",
                "required_artifacts": ["accepted_commit"],
            }
        ],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_spec_review"
            ),
        )
    )

    result = run_child_candidate_tick(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    assert result.status == "skipped"
    assert "child-001" in result.detail
    assert execution.requests == []
    assert ledger.load_attempts() == []
    comments = [
        effect["payload"]["body"]
        for effect in ledger.load_pending_tracker_effects()
        if effect["effect_type"] == "comment"
    ]
    assert any("waiting to dispatch" in body for body in comments)


def test_run_child_candidate_tick_dispatches_after_dependency_accept_completed(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    issue = BacklogIssue(
        id="DANNY-66-C2",
        title="Use accepted API",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:graph",
                "Node id: child-002",
                "Acceptance criteria: downstream uses accepted API",
            ]
        ),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_graph(
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001"),
            _complete_graph_child(
                node_id="child-002",
                dependencies=["child-001"],
            ),
        ],
        dependency_edges=[
            {
                "from": "child-001",
                "to": "child-002",
                "type": "code_dependency",
                "blocks_dispatch": True,
                "reason": "child-002 imports child-001 output.",
                "required_artifacts": ["accepted_commit"],
            }
        ],
    )
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "child-001": ChildRunState(
                    phase=ChildPhase.QUALITY_REVIEW_PASSED,
                    attempts=4,
                )
            }
        )
    )
    ledger.record_role_attempt_request(
        attempt_id="child-001-QUALITY_REVIEWING-4",
        target_kind="child",
        target_id="child-001",
        phase=ChildPhase.QUALITY_REVIEWING,
        idempotency_key="child-001:QUALITY_REVIEWING:4",
        request_json={"role": "child_quality_reviewer"},
    )
    ledger.record_attempt_result(
        attempt_id="child-001-QUALITY_REVIEWING-4",
        status="succeeded",
        result_json={
            "verdict": "PASS",
            "required_next_action": "accept_candidate",
            "branch": "smda/DANNY-66/child-001/quality-reviewing",
        },
        error_message=None,
    )
    ledger.record_parent_accept_operation(
        operation_id="accept:DANNY-66:child-001:smda/DANNY-66/child-001/quality-reviewing",
        idempotency_key="parent:DANNY-66:child-001:smda/DANNY-66/child-001/quality-reviewing",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="smda/DANNY-66/child-001/quality-reviewing",
        integration_branch="smda/DANNY-66/integration",
    )
    ledger.mark_parent_accept_completed(
        "accept:DANNY-66:child-001:smda/DANNY-66/child-001/quality-reviewing"
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_spec_review"
            ),
        )
    )

    result = run_child_candidate_tick(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    assert result.status == "dispatched"
    assert result.state.children["child-002"].phase == ChildPhase.SPEC_REVIEWING
    assert execution.requests[0].context_packet["child_id"] == "child-002"
```

Also ensure these imports exist at the top of `test_runtime.py`:

```python
from smda_scheduler.scheduling import AttemptOutcome, ChildRunState, SchedulerState
```

If `AttemptOutcome` is already imported from the same module, extend the existing import rather than duplicating it.

- [x] **Step 2: Run the new runtime tests and confirm they fail**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_waits_for_unaccepted_graph_dependency packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_dispatches_after_dependency_accept_completed -q
```

Expected: FAIL because `run_child_candidate_tick` still returns `SchedulerState` and dispatches the blocked child.

---

### Task 4: Gate `run_child_candidate_tick`

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Add a typed child candidate result**

In `packages/scheduler/src/smda_scheduler/runtime.py`, add this dataclass near `ParentIntakeResult`:

```python
@dataclass(frozen=True)
class ChildCandidateTickResult:
    status: str
    detail: str
    state: SchedulerState
```

Add this import with the other runtime imports:

```python
from smda_scheduler.child_dependency_gate import (
    ChildDependencyGateResult,
    child_dependency_gate,
)
```

- [x] **Step 2: Add helper functions for child graph validation and wait evidence**

In `runtime.py`, add these helpers near `_record_child_lifecycle_effect`:

```python
def _assert_graph_contains_child(graph: dict, *, parent_id: str, child_id: str) -> None:
    child_ids = {
        str(child["node_id"])
        for child in graph.get("children", [])
        if isinstance(child, dict) and "node_id" in child
    }
    if child_id not in child_ids:
        raise GraphError(
            f"Child node {child_id} is not present in current graph for {parent_id}"
        )


def _record_child_dependency_wait_effect(
    ledger: PhaseLedger,
    *,
    issue_id: str,
    parent_id: str,
    child_id: str,
    graph_checksum: str,
    gate: ChildDependencyGateResult,
) -> None:
    blocked_key = ",".join(gate.blocked_by)
    missing_key = ",".join(gate.missing_artifacts)
    key = hashlib.sha256(
        f"{parent_id}:{child_id}:{graph_checksum}:{blocked_key}:{missing_key}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    body = (
        f"SMDA is waiting to dispatch {issue_id} until dependencies are accepted.\n\n"
        f"Child node: `{child_id}`\n"
        f"Blocked by: {', '.join(gate.blocked_by)}\n"
        f"Missing artifacts: {', '.join(gate.missing_artifacts)}"
    )
    ledger.record_tracker_effect(
        effect_id=f"child-dependency-wait:{issue_id}:{key}",
        idempotency_key=f"child-dependency-wait:{issue_id}:{key}",
        effect_type="comment",
        target_id=issue_id,
        payload={"body": body},
    )
```

- [x] **Step 3: Change `run_child_candidate_tick` to return `ChildCandidateTickResult`**

Update the signature:

```python
) -> ChildCandidateTickResult:
```

Replace the current graph-load block in `run_child_candidate_tick` with this:

```python
    try:
        persisted_graph = ledger.load_graph(decision.parent_issue_id)
    except KeyError as error:
        raise GraphError(
            f"SMDA graph not found for child parent: {decision.parent_issue_id}"
        ) from error
    if (
        decision.graph_checksum is not None
        and str(persisted_graph["graph_checksum"]) != decision.graph_checksum
    ):
        raise GraphError(
            f"Stale child handle for {issue.id}: graph checksum "
            f"{decision.graph_checksum} != current "
            f"{persisted_graph['graph_checksum']}"
        )
    _assert_graph_contains_child(
        persisted_graph,
        parent_id=decision.parent_issue_id,
        child_id=decision.node_id,
    )
```

After building the `ChildTaskContext` object and before `run_child_workflow_tick`, add:

```python
    gate = child_dependency_gate(
        parent_id=decision.parent_issue_id,
        child_id=decision.node_id,
        graph=persisted_graph,
        scheduler_state=ledger.load_scheduler_state(),
        attempts=ledger.load_attempts(),
        parent_accept_operations=ledger.load_parent_accept_operations(),
    )
    if not gate.eligible:
        _record_child_dependency_wait_effect(
            ledger,
            issue_id=issue.id,
            parent_id=decision.parent_issue_id,
            child_id=decision.node_id,
            graph_checksum=str(persisted_graph["graph_checksum"]),
            gate=gate,
        )
        return ChildCandidateTickResult(
            status="skipped",
            detail=gate.reason,
            state=ledger.load_scheduler_state(),
        )
```

Replace the final return:

```python
    _record_child_lifecycle_effect(ledger, issue.id, decision.node_id, state)
    return ChildCandidateTickResult(
        status="dispatched",
        detail=f"{issue.id}:{state.children[decision.node_id].phase}",
        state=state,
    )
```

- [x] **Step 4: Update existing runtime tests for the new result shape**

In `packages/scheduler/tests/test_runtime.py`, update existing calls that expect `SchedulerState` directly. For example, change:

```python
state = run_child_candidate_tick(
```

to:

```python
result = run_child_candidate_tick(
state = result.state
```

For calls that ignore the returned state, no change is required. For tests that assert direct state, assert `result.status == "dispatched"` before reading `result.state`.

- [x] **Step 5: Run targeted runtime tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_hydrates_child_handle_and_dispatches packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_records_child_tracker_lifecycle packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_rejects_stale_graph_checksum packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_waits_for_unaccepted_graph_dependency packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_dispatches_after_dependency_accept_completed -q
```

Expected: PASS.

- [x] **Step 6: Commit runtime gating**

Run:

```bash
git add packages/scheduler/src/smda_scheduler/runtime.py packages/scheduler/tests/test_runtime.py
git commit -m "Gate child dispatch on accepted dependencies"
```

Expected: commit succeeds.

---

### Task 5: Make Workspace Tick Skip Dependency-Wait Candidates

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workspace_tick.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime_factory.py`
- Modify: `packages/scheduler/tests/test_workspace_tick.py`
- Modify: `packages/scheduler/tests/test_runtime_factory.py` if configured tick tests assume child detail format.

- [ ] **Step 1: Add workspace tick tests for skip-and-continue behavior**

Append these tests to `packages/scheduler/tests/test_workspace_tick.py`:

```python
def test_workspace_tick_skips_dependency_wait_candidate_and_dispatches_next(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    blocked = BacklogIssue(
        id="DANNY-66-C2",
        title="Blocked child",
        state="Todo",
        body=(
            "Parent issue: DANNY-66\n"
            "Graph checksum: sha256:graph\n"
            "Node id: child-002\n"
            "Execution: smda-child\n"
            "Acceptance criteria: waits\n"
        ),
        labels=frozenset({"agent"}),
    )
    ready = BacklogIssue(
        id="DANNY-66-C1",
        title="Ready child",
        state="Todo",
        body=(
            "Parent issue: DANNY-66\n"
            "Graph checksum: sha256:graph\n"
            "Node id: child-001\n"
            "Execution: smda-child\n"
            "Acceptance criteria: runs\n"
        ),
        labels=frozenset({"agent"}),
    )
    backlog = RecordingBacklog(BacklogPage(issues=(blocked, ready)))
    dispatched: list[str] = []

    def dispatch(issue: BacklogIssue, decision) -> TickResult:
        if issue.id == "DANNY-66-C2":
            return TickResult(status="skipped", detail="waiting for child-001")
        dispatched.append(issue.id)
        return TickResult(status="dispatched", detail=f"child:{issue.id}")

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        state="Todo",
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=dispatch,
    )

    assert result.status == "dispatched"
    assert "child:DANNY-66-C1" in (result.detail or "")
    assert "skipped=1" in (result.detail or "")
    assert dispatched == ["DANNY-66-C1"]


def test_workspace_tick_reports_idle_when_all_candidates_dependency_wait(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    child = BacklogIssue(
        id="DANNY-66-C2",
        title="Blocked child",
        state="Todo",
        body=(
            "Parent issue: DANNY-66\n"
            "Graph checksum: sha256:graph\n"
            "Node id: child-002\n"
            "Execution: smda-child\n"
            "Acceptance criteria: waits\n"
        ),
        labels=frozenset({"agent"}),
    )
    backlog = RecordingBacklog(BacklogPage(issues=(child,)))

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        state="Todo",
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: TickResult(
            status="skipped",
            detail="waiting for child-001",
        ),
    )

    assert result.status == "idle"
    assert result.detail == "skipped=1; reconciled=0; failed=0"
```

- [ ] **Step 2: Run the new workspace tests and confirm they fail**

Run:

```bash
uv run pytest packages/scheduler/tests/test_workspace_tick.py::test_workspace_tick_skips_dependency_wait_candidate_and_dispatches_next packages/scheduler/tests/test_workspace_tick.py::test_workspace_tick_reports_idle_when_all_candidates_dependency_wait -q
```

Expected: FAIL because `run_workspace_tick` only inspects `candidates.issues[0]`.

- [ ] **Step 3: Update `run_workspace_tick` to loop over candidates**

In `packages/scheduler/src/smda_scheduler/workspace_tick.py`, replace the single-candidate block beginning with:

```python
    candidate = candidates.issues[0]
```

with this loop:

```python
    skipped_count = 0
    for candidate in candidates.issues:
        if issue_entry_policy is not None:
            decision = classify_candidate(
                candidate,
                issue_entry_policy=issue_entry_policy,
            )
            if decision.route == CandidateRoute.BLOCK:
                _record_block_effects(
                    ledger,
                    issue=candidate,
                    reason=decision.reason,
                )
                return TickResult(
                    status="blocked",
                    detail=f"{candidate.id}: {decision.reason}; skipped={skipped_count}; {detail_suffix}",
                )
            paused_parent_id = _paused_parent_id(candidate, decision)
            if paused_parent_id is not None and ledger.is_parent_paused(paused_parent_id):
                skipped_count += 1
                continue
            if dispatch_routed_candidate is not None:
                try:
                    result = dispatch_routed_candidate(candidate, decision)
                except GraphError as error:
                    _record_block_effects(
                        ledger,
                        issue=candidate,
                        reason=f"SMDA workflow error: {error}",
                    )
                    return TickResult(
                        status="blocked",
                        detail=f"{candidate.id}: {error}; skipped={skipped_count}; {detail_suffix}",
                    )
                if result.status == "skipped":
                    skipped_count += 1
                    continue
                detail = result.detail or candidate.id
                return TickResult(
                    status=result.status,
                    detail=f"{detail}; skipped={skipped_count}; {detail_suffix}",
                )

        result = dispatch_candidate(candidate)
        detail = result.detail or candidate.id
        return TickResult(
            status=result.status,
            detail=f"{detail}; skipped={skipped_count}; {detail_suffix}",
        )

    return TickResult(
        status="idle",
        detail=f"skipped={skipped_count}; {detail_suffix}",
    )
```

After this replacement, remove the old trailing single-candidate dispatch block so the function has only one dispatch path.

- [ ] **Step 4: Update runtime factory child dispatch to propagate skipped results**

In `packages/scheduler/src/smda_scheduler/runtime_factory.py`, replace the child branch with:

```python
        if decision.route == CandidateRoute.CHILD:
            result = run_child_candidate_tick(
                issue=issue,
                decision=decision,
                repo_context=repo_context,
                repo_root=config.repo_root,
                ledger=ledger,
                execution=execution,
                sandbox_provider=config.adapters.execution.provider,
                agent=agent,
                now=0.0,
                owner=owner,
            )
            return TickResult(status=result.status, detail=result.detail)
```

- [ ] **Step 5: Update workspace test expectations affected by `skipped=0`**

Existing `run_workspace_tick` tests that assert exact detail strings will now include `skipped=0`. Update expected details. For example:

```python
detail="DANNY-101:SPEC_REVIEWING; reconciled=0; failed=0"
```

becomes:

```python
detail="DANNY-101:SPEC_REVIEWING; skipped=0; reconciled=0; failed=0"
```

Apply the same exact-string adjustment to other workspace tick tests that dispatch or block one candidate.

- [ ] **Step 6: Run workspace and runtime factory tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_workspace_tick.py packages/scheduler/tests/test_runtime_factory.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit workspace skip behavior**

Run:

```bash
git add packages/scheduler/src/smda_scheduler/workspace_tick.py packages/scheduler/src/smda_scheduler/runtime_factory.py packages/scheduler/tests/test_workspace_tick.py packages/scheduler/tests/test_runtime_factory.py
git commit -m "Skip dependency-waiting child candidates"
```

Expected: commit succeeds.

---

### Task 6: Record Child Completion Tracker Effects From Parent Acceptance

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [ ] **Step 1: Add a parent acceptance tracker-effect test**

Append this test near existing parent child acceptance tests in `packages/scheduler/tests/test_runtime.py`:

```python
def test_parent_child_acceptance_records_child_done_tracker_effect(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    ledger.record_child_issue_projection(
        parent_id="DANNY-66",
        node_id="child-001",
        issue_id="DANNY-66-C1",
    )
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "child-001": ChildRunState(
                    phase=ChildPhase.QUALITY_REVIEW_PASSED,
                    attempts=4,
                )
            }
        )
    )
    ledger.record_role_attempt_request(
        attempt_id="child-001-QUALITY_REVIEWING-4",
        target_kind="child",
        target_id="child-001",
        phase=ChildPhase.QUALITY_REVIEWING,
        idempotency_key="child-001:QUALITY_REVIEWING:4",
        request_json={"role": "child_quality_reviewer"},
    )
    ledger.record_attempt_result(
        attempt_id="child-001-QUALITY_REVIEWING-4",
        status="succeeded",
        result_json={
            "verdict": "PASS",
            "required_next_action": "accept_candidate",
            "branch": "smda/DANNY-66/child-001/quality-reviewing",
        },
        error_message=None,
    )
    integration = RecordingParentIntegration()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Execution: smda\n",
    )

    result = run_parent_child_acceptance_tick(
        issue=issue,
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-66/integration",
    )

    assert result.target_state == "In Progress"
    effects = ledger.load_pending_tracker_effects()
    states = [
        (effect["target_id"], effect["payload"]["state"])
        for effect in effects
        if effect["effect_type"] == "set_state"
    ]
    comments = [
        effect["payload"]["body"]
        for effect in effects
        if effect["effect_type"] == "comment"
    ]
    assert ("DANNY-66-C1", "Done") in states
    assert any("smda/DANNY-66/child-001/quality-reviewing" in body for body in comments)
    assert any("smda/DANNY-66/integration" in body for body in comments)
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_parent_child_acceptance_records_child_done_tracker_effect -q
```

Expected: FAIL because parent acceptance does not yet record a child Done tracker effect.

- [ ] **Step 3: Add helper to record accepted child tracker effects**

In `packages/scheduler/src/smda_scheduler/runtime.py`, add this helper near `_record_child_lifecycle_effect`:

```python
def _record_child_accepted_tracker_effect(
    ledger: PhaseLedger,
    *,
    parent_id: str,
    child_id: str,
    issue_id: str,
    candidate_ref: str,
    integration_branch: str,
) -> None:
    key = hashlib.sha256(
        f"{parent_id}:{child_id}:{candidate_ref}:{integration_branch}".encode("utf-8")
    ).hexdigest()[:16]
    body = (
        f"SMDA child {issue_id} accepted into parent integration branch.\n\n"
        f"Parent: `{parent_id}`\n"
        f"Child node: `{child_id}`\n"
        f"Candidate ref: `{candidate_ref}`\n"
        f"Integration branch: `{integration_branch}`"
    )
    ledger.record_tracker_effect(
        effect_id=f"child-accepted-state:{issue_id}:{key}",
        idempotency_key=f"child-accepted-state:{issue_id}:{key}",
        effect_type="set_state",
        target_id=issue_id,
        payload={"state": "Done"},
    )
    ledger.record_tracker_effect(
        effect_id=f"child-accepted-comment:{issue_id}:{key}",
        idempotency_key=f"child-accepted-comment:{issue_id}:{key}",
        effect_type="comment",
        target_id=issue_id,
        payload={"body": body},
    )
```

- [ ] **Step 4: Call the helper after successful child acceptance**

In `run_parent_child_acceptance_tick`, load projections before the loop if not already available:

```python
    projections = ledger.load_child_issue_projections(issue.id)
```

After `accepted_child_ids.add(child_id)`, add:

```python
        issue_id = projections.get(child_id)
        if issue_id is not None:
            _record_child_accepted_tracker_effect(
                ledger,
                parent_id=issue.id,
                child_id=child_id,
                issue_id=issue_id,
                candidate_ref=candidate_ref,
                integration_branch=integration_branch,
            )
```

- [ ] **Step 5: Run parent acceptance tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_parent_child_acceptance_records_child_done_tracker_effect packages/scheduler/tests/test_runtime.py::test_run_parent_child_acceptance_tick_integrates_quality_passed_children packages/scheduler/tests/test_parent_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit tracker projection**

Run:

```bash
git add packages/scheduler/src/smda_scheduler/runtime.py packages/scheduler/tests/test_runtime.py
git commit -m "Record accepted child tracker completion"
```

Expected: commit succeeds.

---

### Task 7: Documentation And Known Gaps Update

**Files:**
- Modify: `docs/known-gaps.md`
- Modify: `docs/product-spec.md`
- Test: no code tests required for docs-only changes.

- [ ] **Step 1: Update `docs/known-gaps.md`**

Add a short entry near the prior scheduler-routing follow-ups:

```markdown
- **Child dependency dispatch gate** (done): live child dispatch now validates
  persisted parent graph dependencies against scheduler state, latest quality
  candidate refs, and completed parent accept operations before invoking role
  execution. Dependency-waiting children are skipped during workspace scans so
  they do not starve eligible candidates.
```

- [ ] **Step 2: Update `docs/product-spec.md`**

In the workflow semantics section around dependency gating, add:

```markdown
For live child issue dispatch, backlog blocking relations are projection only.
The scheduler gates dispatch from SMDA-owned state: persisted graph edges,
child scheduler phases, latest quality-pass candidate refs, and completed
parent accept operations. A dependency-waiting child is skipped rather than
manually blocked so it can become eligible automatically after upstream accept
recovery completes.
```

- [ ] **Step 3: Run docs diff check**

Run:

```bash
git diff -- docs/known-gaps.md docs/product-spec.md
```

Expected: diff only describes the dependency dispatch gate behavior.

- [ ] **Step 4: Commit docs**

Run:

```bash
git add docs/known-gaps.md docs/product-spec.md
git commit -m "Document child dependency dispatch gate"
```

Expected: commit succeeds.

---

### Task 8: Full Verification

**Files:**
- No new files.
- Verify all modified scheduler tests.

- [ ] **Step 1: Run targeted scheduler tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_child_dependency_gate.py packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_workspace_tick.py packages/scheduler/tests/test_runtime_factory.py packages/scheduler/tests/test_parent_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full scheduler test suite**

Run:

```bash
uv run pytest packages/scheduler/tests -q
```

Expected: PASS.

- [ ] **Step 3: Run git diff check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 4: Inspect final status**

Run:

```bash
git status --short
```

Expected: clean working tree, or only intentional uncommitted files if the implementer was instructed not to commit.

---

## Self-Review

### Spec Coverage

- Dispatch eligibility from SMDA-owned state: Task 1 and Task 2.
- `run_child_candidate_tick` graph hydration, node validation, and pre-dispatch gate: Task 3 and Task 4.
- Workspace scan skipping dependency-wait candidates: Task 5.
- Parent acceptance child completion tracker projection: Task 6.
- Backlog blocking relation remains projection only: Task 5 and Task 7.
- Missing/stale graph and unknown node hard stops: Task 4 preserves stale checksum and adds node validation.
- Merge conflicts do not unblock downstream children: Task 2 requires completed accept operation, so failed/pending accept operations block.
- Docs updated after behavior change: Task 7.

### Placeholder Scan

The plan contains no `TBD`, `TODO`, or intentionally incomplete code snippets. The remaining ellipsis matches are Python `tuple[str, ...]` type syntax in concrete code.

### Type Consistency

- `ChildDependencyGateResult` is defined in Task 2 and consumed in Task 4.
- `ChildCandidateTickResult` is defined in Task 4 and consumed by `runtime_factory.py` in Task 5.
- `TickResult(status="skipped")` is introduced in Task 5 and handled only as a workspace scan control status.
