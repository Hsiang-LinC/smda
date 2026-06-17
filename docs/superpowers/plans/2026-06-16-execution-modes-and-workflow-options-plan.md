# Execution Modes And Workflow Options Implementation Plan

> **SUPERSEDED by [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md) (2026-06-16).**
> Do NOT execute as written. Salvage only: the typed `ExecutionMode` / `ModeTag`
> enums and `candidate_routing` resolving `Execution:` → a Mode. Discard the
> `WorkflowOptions` boolean bundle, the `require_spec_review` threading through
> `run_once` / `transition_child_phase`, and the net-new `run_task_candidate_tick`
> branch — those encode the shallow per-mode path the ADR replaces. `smda-task`,
> `manual`, and `smda-review` become Workflow Definitions on the one engine.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic SMDA execution modes for small task automation while preserving the dependency-gate safety invariant from the child dependency dispatch gate work.

**Architecture:** Keep `Execution: smda` and `Execution: smda-child` behavior intact, add typed mode/tag resolution in a focused module, and route `Execution: smda-task` through a reused child workflow segment with task-specific options. Fix the parent-accept/latest-candidate-ref consistency bug first so task and child gating share one definition of the latest accepted quality candidate.

**Tech Stack:** Python scheduler package, SQLite-backed `PhaseLedger`, pytest, existing child role contracts and Sandcastle role attempt adapter.

---

## Relationship To Existing Plans

This is Plan B for `docs/superpowers/specs/2026-06-16-execution-modes-and-workflow-options.md`.

It depends on the completed Plan A dependency gate behavior:

- `run_child_candidate_tick` loads the persisted parent graph and gates child dispatch.
- `run_workspace_tick` skips dependency-waiting candidates instead of starving the queue.
- Parent acceptance records child completion tracker effects.
- `child_dependency_gate.latest_quality_candidate_ref()` uses numeric attempt ordering.

This plan must not re-run or reinterpret `docs/superpowers/plans/2026-06-15-smda-product-slices.md`. That plan predates the later loophole findings. Treat it as historical product-slice scaffolding, not as the authority for execution mode behavior.

## Scope

In scope:

- Fix the latest quality candidate ref inconsistency between dependency gate and parent child acceptance.
- Add typed execution mode and mode tag resolution.
- Add `Execution: smda-task` as an independent single-task workflow.
- Add `Execution: manual` as an explicit no-automation mode.
- Change `implicit-one-child` freeform entry to route to `smda-task`.
- Persist resolved task options in the task role attempt context.
- Surface the execution mode catalog in product/harness-facing docs.

Out of scope for this first implementation:

- Running `Execution: smda-review` as a live review-only workflow.
- Per-role model selection.
- Tracker label shortcuts for mode tags.
- Project-specific custom modes.

`Execution: smda-review` should be documented as cataloged but not enabled. Candidate routing should return a clear block reason until a separate review-only runtime slice exists.

## File Structure

- Create `packages/scheduler/src/smda_scheduler/execution_modes.py`
  - Owns `ExecutionMode`, `ModeTag`, `WorkflowOptions`, parsing, validation, and catalog markdown.
- Modify `packages/scheduler/src/smda_scheduler/candidate_routing.py`
  - Classifies `smda-task`, `manual`, and disabled `smda-review`.
  - Carries resolved `WorkflowOptions` in `CandidateRoutingDecision`.
  - Routes `implicit-one-child` to task mode.
- Modify `packages/scheduler/src/smda_scheduler/runtime.py`
  - Adds `run_task_candidate_tick`.
  - Makes parent child acceptance use the same latest quality ref helper as dependency gate.
  - Records task lifecycle tracker effects.
- Modify `packages/scheduler/src/smda_scheduler/runtime_factory.py`
  - Dispatches `CandidateRoute.TASK`.
- Modify `packages/scheduler/src/smda_scheduler/role_attempts.py`
  - Adds resolved workflow options to child/task context packets.
- Modify `packages/scheduler/src/smda_scheduler/workflow.py`
  - Adds option-aware child phase transition helper for task mode.
- Modify docs:
  - `docs/product-spec.md`
  - `docs/known-gaps.md`
  - `docs/adapter-boundaries.md`
- Tests:
  - `packages/scheduler/tests/test_execution_modes.py`
  - `packages/scheduler/tests/test_candidate_routing.py`
  - `packages/scheduler/tests/test_runtime.py`
  - `packages/scheduler/tests/test_runtime_factory.py`
  - `packages/scheduler/tests/test_role_attempts.py`
  - `packages/scheduler/tests/test_workflow.py`

---

### Task 1: Align Parent Acceptance With Latest Quality Candidate Ref

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/src/smda_scheduler/child_dependency_gate.py`
- Test: `packages/scheduler/tests/test_runtime.py`
- Test: `packages/scheduler/tests/test_child_dependency_gate.py`

- [ ] **Step 1: Add a regression test for attempt 9/10 parent acceptance ordering**

Append this test near the existing parent child acceptance tests in `packages/scheduler/tests/test_runtime.py`:

```python
def test_parent_child_acceptance_uses_latest_quality_candidate_by_attempt_number(
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
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "child-001": ChildRunState(
                    phase=ChildPhase.QUALITY_REVIEW_PASSED,
                    attempts=10,
                )
            }
        )
    )
    for attempt_number, branch in ((9, "branch-9"), (10, "branch-10")):
        attempt_id = f"child-001-QUALITY_REVIEWING-{attempt_number}"
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind="child",
            target_id="child-001",
            phase=ChildPhase.QUALITY_REVIEWING,
            idempotency_key=f"child-001:QUALITY_REVIEWING:{attempt_number}",
            request_json={"role": "child_quality_reviewer"},
        )
        ledger.record_attempt_result(
            attempt_id=attempt_id,
            status="succeeded",
            result_json={
                "verdict": "PASS",
                "required_next_action": "accept_candidate",
                "branch": branch,
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
    assert integration.accepted_refs == {"branch-10"}
    operations = ledger.load_parent_accept_operations()
    assert [operation["candidate_ref"] for operation in operations] == ["branch-10"]
```

- [ ] **Step 2: Run the regression test and verify it fails**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_parent_child_acceptance_uses_latest_quality_candidate_by_attempt_number -q
```

Expected: FAIL because `_latest_child_candidate_ref()` in `runtime.py` uses reversed lexicographic attempt ordering and may choose `branch-9`.

- [ ] **Step 3: Reuse the dependency gate helper in parent acceptance**

In `packages/scheduler/src/smda_scheduler/runtime.py`, extend the existing import:

```python
from smda_scheduler.child_dependency_gate import (
    ChildDependencyGateResult,
    child_dependency_gate,
    latest_quality_candidate_ref,
)
```

Replace `_latest_child_candidate_ref()` with:

```python
def _latest_child_candidate_ref(ledger: PhaseLedger, child_id: str) -> str:
    candidate_ref = latest_quality_candidate_ref(ledger.load_attempts(), child_id)
    if candidate_ref is None:
        raise GraphError(f"Accepted child has no candidate ref: {child_id}")
    return candidate_ref
```

- [ ] **Step 4: Add a dependency-gate test that proves old accepts do not unblock latest refs**

Append this test to `packages/scheduler/tests/test_child_dependency_gate.py`:

```python
def test_child_dependency_gate_requires_accept_for_latest_quality_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        attempts=[
            quality_attempt(candidate_ref="branch-9", attempt_number=9),
            quality_attempt(candidate_ref="branch-10", attempt_number=10),
        ],
        parent_accept_operations=[accept_operation(candidate_ref="branch-9")],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:accepted_commit",)
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_parent_child_acceptance_uses_latest_quality_candidate_by_attempt_number packages/scheduler/tests/test_child_dependency_gate.py::test_child_dependency_gate_requires_accept_for_latest_quality_ref -q
```

Expected: PASS.

- [ ] **Step 6: Run related acceptance/gate tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_child_dependency_gate.py packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_dispatches_after_dependency_accept_completed packages/scheduler/tests/test_runtime.py::test_parent_child_acceptance_records_child_done_tracker_effect packages/scheduler/tests/test_parent_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/runtime.py packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_child_dependency_gate.py
git commit -m "Use latest quality candidate for parent acceptance"
```

---

### Task 2: Add Typed Execution Modes And Workflow Options

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/execution_modes.py`
- Test: `packages/scheduler/tests/test_execution_modes.py`

- [ ] **Step 1: Write failing tests for mode and tag resolution**

Create `packages/scheduler/tests/test_execution_modes.py`:

```python
import pytest

from smda_scheduler.execution_modes import (
    ExecutionMode,
    ModeTag,
    WorkflowOptions,
    WorkflowOptionsError,
    parse_mode_tags,
    resolve_workflow_options,
)


def test_parse_mode_tags_accepts_comma_separated_values():
    assert parse_mode_tags("full_review, high_risk") == frozenset(
        {ModeTag.FULL_REVIEW, ModeTag.HIGH_RISK}
    )


def test_parse_mode_tags_rejects_unknown_tag():
    with pytest.raises(WorkflowOptionsError, match="Unsupported Mode tags: custom"):
        parse_mode_tags("full_review, custom")


def test_resolve_smda_task_defaults_to_quality_review_only():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset(),
    )

    assert options == WorkflowOptions(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset(),
        require_spec_review=False,
        require_quality_review=True,
        require_human_approval=False,
        require_integration=False,
        risk_level="normal",
    )


def test_full_review_requires_spec_and_quality_review():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset({ModeTag.FULL_REVIEW}),
    )

    assert options.require_spec_review is True
    assert options.require_quality_review is True


def test_quality_only_high_risk_is_invalid():
    with pytest.raises(
        WorkflowOptionsError,
        match="quality_only cannot be combined with high_risk",
    ):
        resolve_workflow_options(
            mode=ExecutionMode.SMDA_TASK,
            tags=frozenset({ModeTag.QUALITY_ONLY, ModeTag.HIGH_RISK}),
        )


def test_high_risk_requires_full_review():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset({ModeTag.HIGH_RISK}),
    )

    assert options.risk_level == "high"
    assert options.require_spec_review is True
    assert options.require_quality_review is True


def test_manual_mode_disables_all_automation_gates():
    options = resolve_workflow_options(
        mode=ExecutionMode.MANUAL,
        tags=frozenset(),
    )

    assert options.require_spec_review is False
    assert options.require_quality_review is False
    assert options.require_human_approval is True


def test_smda_child_tags_cannot_weaken_dependency_gate():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_CHILD,
        tags=frozenset({ModeTag.QUALITY_ONLY, ModeTag.LOW_RISK}),
    )

    assert options.mode == ExecutionMode.SMDA_CHILD
    assert options.require_spec_review is True
    assert options.require_quality_review is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest packages/scheduler/tests/test_execution_modes.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'smda_scheduler.execution_modes'`.

- [ ] **Step 3: Implement `execution_modes.py`**

Create `packages/scheduler/src/smda_scheduler/execution_modes.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkflowOptionsError(ValueError):
    """Raised when execution mode or mode tag options are invalid."""


class ExecutionMode(StrEnum):
    SMDA = "smda"
    SMDA_CHILD = "smda-child"
    SMDA_TASK = "smda-task"
    SMDA_REVIEW = "smda-review"
    MANUAL = "manual"


class ModeTag(StrEnum):
    FULL_REVIEW = "full_review"
    QUALITY_ONLY = "quality_only"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    REQUIRES_INTEGRATION = "requires_integration"
    HIGH_RISK = "high_risk"
    LOW_RISK = "low_risk"


@dataclass(frozen=True)
class WorkflowOptions:
    mode: ExecutionMode
    tags: frozenset[ModeTag]
    require_spec_review: bool
    require_quality_review: bool
    require_human_approval: bool
    require_integration: bool
    risk_level: str

    def to_context_packet(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "tags": sorted(tag.value for tag in self.tags),
            "require_spec_review": self.require_spec_review,
            "require_quality_review": self.require_quality_review,
            "require_human_approval": self.require_human_approval,
            "require_integration": self.require_integration,
            "risk_level": self.risk_level,
        }


SUPPORTED_MODE_TAGS: frozenset[ModeTag] = frozenset(ModeTag)


SMDA_EXECUTION_MODE_CATALOG_MARKDOWN = """## SMDA Execution Modes

- Use `Execution: smda` for complex spec-driven work that may need decomposition.
- Use `Execution: smda-task` for small scoped bugs and single-task fixes.
- Use `Execution: smda-child` only for scheduler-created child issues.
- Use `Execution: smda-review` for review-only automation, if enabled.
- Use `Execution: manual` to prevent automatic claim.

Optional `Mode tags:` values: full_review, quality_only,
human_approval_required, requires_integration, high_risk, low_risk.

Mode chooses the primary state machine. Tags only modify predefined gates.
"""


def parse_execution_mode(value: str) -> ExecutionMode:
    normalized = value.strip().lower()
    try:
        return ExecutionMode(normalized)
    except ValueError as error:
        raise WorkflowOptionsError(f"Unsupported Execution mode: {value}") from error


def parse_mode_tags(value: str | None) -> frozenset[ModeTag]:
    if value is None or not value.strip():
        return frozenset()
    raw_tags = [tag.strip().lower() for tag in value.split(",") if tag.strip()]
    parsed: set[ModeTag] = set()
    unsupported: list[str] = []
    for raw_tag in raw_tags:
        try:
            parsed.add(ModeTag(raw_tag))
        except ValueError:
            unsupported.append(raw_tag)
    if unsupported:
        raise WorkflowOptionsError(
            "Unsupported Mode tags: " + ", ".join(sorted(unsupported))
        )
    return frozenset(parsed)


def resolve_workflow_options(
    *,
    mode: ExecutionMode,
    tags: frozenset[ModeTag],
) -> WorkflowOptions:
    _validate_tag_combination(mode=mode, tags=tags)
    risk_level = _risk_level(tags)
    require_human_approval = ModeTag.HUMAN_APPROVAL_REQUIRED in tags
    require_integration = ModeTag.REQUIRES_INTEGRATION in tags

    if mode == ExecutionMode.MANUAL:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=False,
            require_quality_review=False,
            require_human_approval=True,
            require_integration=False,
            risk_level=risk_level,
        )

    if mode in {ExecutionMode.SMDA, ExecutionMode.SMDA_CHILD}:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=True,
            require_quality_review=True,
            require_human_approval=require_human_approval,
            require_integration=require_integration,
            risk_level=risk_level,
        )

    if mode == ExecutionMode.SMDA_TASK:
        require_spec_review = (
            ModeTag.FULL_REVIEW in tags or ModeTag.HIGH_RISK in tags
        )
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=require_spec_review,
            require_quality_review=True,
            require_human_approval=require_human_approval,
            require_integration=require_integration,
            risk_level=risk_level,
        )

    if mode == ExecutionMode.SMDA_REVIEW:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=ModeTag.FULL_REVIEW in tags,
            require_quality_review=True,
            require_human_approval=require_human_approval,
            require_integration=False,
            risk_level=risk_level,
        )

    raise WorkflowOptionsError(f"Unsupported Execution mode: {mode}")


def _validate_tag_combination(
    *,
    mode: ExecutionMode,
    tags: frozenset[ModeTag],
) -> None:
    if ModeTag.QUALITY_ONLY in tags and ModeTag.HIGH_RISK in tags:
        raise WorkflowOptionsError("quality_only cannot be combined with high_risk")
    if ModeTag.FULL_REVIEW in tags and ModeTag.QUALITY_ONLY in tags:
        raise WorkflowOptionsError("full_review cannot be combined with quality_only")
    if mode != ExecutionMode.SMDA_TASK and ModeTag.QUALITY_ONLY in tags:
        return


def _risk_level(tags: frozenset[ModeTag]) -> str:
    if ModeTag.HIGH_RISK in tags:
        return "high"
    if ModeTag.LOW_RISK in tags:
        return "low"
    return "normal"
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_execution_modes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/execution_modes.py packages/scheduler/tests/test_execution_modes.py
git commit -m "Add typed execution mode options"
```

---

### Task 3: Extend Candidate Routing For Modes And Tags

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/candidate_routing.py`
- Modify: `packages/scheduler/tests/test_candidate_routing.py`

- [ ] **Step 1: Add routing tests for task, manual, tags, invalid tags, and implicit task entry**

Append these tests to `packages/scheduler/tests/test_candidate_routing.py`:

```python
def test_classifies_smda_task_with_workflow_options():
    decision = classify_candidate(
        issue(
            "Execution: smda-task\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest packages/scheduler/tests -q\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.TASK
    assert decision.workflow_options is not None
    assert decision.workflow_options.mode.value == "smda-task"
    assert decision.workflow_options.require_quality_review is True
    assert decision.workflow_options.require_spec_review is False


def test_classifies_smda_task_with_full_review_tag():
    decision = classify_candidate(
        issue(
            "Execution: smda-task\n"
            "Mode tags: full_review\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.TASK
    assert decision.workflow_options is not None
    assert decision.workflow_options.require_spec_review is True


def test_blocks_smda_task_with_invalid_tag_combination():
    decision = classify_candidate(
        issue(
            "Execution: smda-task\n"
            "Mode tags: quality_only, high_risk\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "quality_only cannot be combined with high_risk" in decision.reason


def test_blocks_smda_task_without_minimum_context():
    decision = classify_candidate(
        issue("Execution: smda-task\nAcceptance criteria: bug fixed\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "Verification" in decision.reason


def test_manual_execution_never_dispatches():
    decision = classify_candidate(
        issue("Execution: manual\nAcceptance criteria: human only\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "manual" in decision.reason


def test_smda_review_is_cataloged_but_not_enabled():
    decision = classify_candidate(
        issue(
            "Execution: smda-review\n"
            "Candidate ref: feature/ref\n"
            "Acceptance criteria: review it\n"
            "Verification: pytest\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "smda-review is not enabled" in decision.reason


def test_normalizes_unmodeled_issue_under_implicit_one_child_policy_to_task():
    decision = classify_candidate(
        issue("Source: bug report\nAcceptance criteria: works\nVerification: pytest\n"),
        issue_entry_policy="implicit-one-child",
    )

    assert decision.route == CandidateRoute.TASK
    assert decision.reason == "implicit-one-child policy -> smda-task"
    assert decision.workflow_options is not None
    assert decision.workflow_options.mode.value == "smda-task"
```

Update the existing `test_normalizes_unmodeled_issue_under_implicit_one_child_policy` so it expects `CandidateRoute.TASK` instead of `CandidateRoute.IMPLICIT_PARENT`.

- [ ] **Step 2: Run routing tests and verify failure**

Run:

```bash
uv run pytest packages/scheduler/tests/test_candidate_routing.py -q
```

Expected: FAIL because `CandidateRoute.TASK` and `workflow_options` do not exist.

- [ ] **Step 3: Update candidate routing data structures**

In `packages/scheduler/src/smda_scheduler/candidate_routing.py`, import execution mode helpers:

```python
from smda_scheduler.execution_modes import (
    ExecutionMode,
    WorkflowOptions,
    WorkflowOptionsError,
    parse_execution_mode,
    parse_mode_tags,
    resolve_workflow_options,
)
```

Update `CandidateRoute`:

```python
class CandidateRoute(StrEnum):
    PARENT = "parent"
    IMPLICIT_PARENT = "implicit_parent"
    CHILD = "child"
    TASK = "task"
    BLOCK = "block"
```

Update `CandidateRoutingDecision`:

```python
@dataclass(frozen=True)
class CandidateRoutingDecision:
    route: CandidateRoute
    reason: str
    parent_issue_id: str | None = None
    node_id: str | None = None
    graph_checksum: str | None = None
    workflow_options: WorkflowOptions | None = None
```

- [ ] **Step 4: Resolve mode and tags before route-specific validation**

Replace the `execution_mode` branch in `classify_candidate()` with this structure:

```python
    try:
        mode = parse_execution_mode(execution_mode)
        tags = parse_mode_tags(_field(body, "Mode tags"))
        workflow_options = resolve_workflow_options(mode=mode, tags=tags)
    except WorkflowOptionsError as error:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason=str(error),
        )

    if mode == ExecutionMode.SMDA:
        return CandidateRoutingDecision(
            route=CandidateRoute.PARENT,
            reason="Execution: smda",
            workflow_options=workflow_options,
        )
    if mode == ExecutionMode.SMDA_CHILD:
        return _classify_child(issue, workflow_options=workflow_options)
    if mode == ExecutionMode.SMDA_TASK:
        return _classify_task(issue, workflow_options=workflow_options)
    if mode == ExecutionMode.MANUAL:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Execution: manual prevents automatic claim",
            workflow_options=workflow_options,
        )
    if mode == ExecutionMode.SMDA_REVIEW:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Execution: smda-review is not enabled in this implementation slice",
            workflow_options=workflow_options,
        )
```

Keep the existing obsolete `orchestrator` message by checking it before `parse_execution_mode()`:

```python
    if execution_mode.lower() == "orchestrator":
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Execution: orchestrator is obsolete; use Execution: smda, Execution: smda-child, or Execution: smda-task",
        )
```

- [ ] **Step 5: Add task classification helpers**

Add:

```python
def _classify_child(
    issue: BacklogIssue,
    *,
    workflow_options: WorkflowOptions,
) -> CandidateRoutingDecision:
    parent_issue_id = _field(issue.body, "Parent issue")
    graph_checksum = _field(issue.body, "Graph checksum")
    node_id = _field(issue.body, "Node id")
    acceptance_criteria = _field(issue.body, "Acceptance criteria")
    missing = [
        label
        for label, value in (
            ("Parent issue", parent_issue_id),
            ("Graph checksum", graph_checksum),
            ("Node id", node_id),
            ("Acceptance criteria", acceptance_criteria),
        )
        if value is None
    ]
    if missing:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason=f"Missing smda-child context: {', '.join(missing)}",
            workflow_options=workflow_options,
        )

    return CandidateRoutingDecision(
        route=CandidateRoute.CHILD,
        reason="Execution: smda-child",
        parent_issue_id=parent_issue_id,
        node_id=node_id,
        graph_checksum=graph_checksum,
        workflow_options=workflow_options,
    )
```

Add:

```python
def _classify_task(
    issue: BacklogIssue,
    *,
    workflow_options: WorkflowOptions,
) -> CandidateRoutingDecision:
    acceptance_criteria = _field(issue.body, "Acceptance criteria")
    verification = _field(issue.body, "Verification")
    missing = [
        label
        for label, value in (
            ("Acceptance criteria", acceptance_criteria),
            ("Verification", verification),
        )
        if value is None
    ]
    if missing:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason=f"Missing smda-task context: {', '.join(missing)}",
            workflow_options=workflow_options,
        )
    return CandidateRoutingDecision(
        route=CandidateRoute.TASK,
        reason="Execution: smda-task",
        workflow_options=workflow_options,
    )
```

Update `_classify_unmodeled_issue()` so `implicit-one-child` returns task options:

```python
    if issue_entry_policy == "implicit-one-child" and _has_minimal_context(body):
        workflow_options = resolve_workflow_options(
            mode=ExecutionMode.SMDA_TASK,
            tags=frozenset(),
        )
        return CandidateRoutingDecision(
            route=CandidateRoute.TASK,
            reason="implicit-one-child policy -> smda-task",
            workflow_options=workflow_options,
        )
```

- [ ] **Step 6: Run routing tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_candidate_routing.py packages/scheduler/tests/test_execution_modes.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/candidate_routing.py packages/scheduler/tests/test_candidate_routing.py
git commit -m "Route task execution modes"
```

---

### Task 4: Add Option-Aware Child Transitions For Task Mode

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Test: `packages/scheduler/tests/test_workflow.py`
- Test: `packages/scheduler/tests/test_scheduling.py`

- [ ] **Step 1: Add workflow tests for quality-only task transitions**

Append these tests to `packages/scheduler/tests/test_workflow.py`:

```python
def test_transition_child_phase_skips_spec_review_when_spec_review_not_required():
    result = RoleResult(verdict="DONE", required_next_action="submit_for_spec_review")

    assert (
        transition_child_phase(
            ChildPhase.IMPLEMENTING,
            result,
            require_spec_review=False,
        )
        == ChildPhase.QUALITY_REVIEWING
    )


def test_transition_child_phase_keeps_full_review_when_spec_review_required():
    result = RoleResult(verdict="DONE", required_next_action="submit_for_spec_review")

    assert (
        transition_child_phase(
            ChildPhase.IMPLEMENTING,
            result,
            require_spec_review=True,
        )
        == ChildPhase.SPEC_REVIEWING
    )
```

- [ ] **Step 2: Add scheduling test for option propagation**

Append this test to `packages/scheduler/tests/test_scheduling.py`:

```python
def test_run_once_can_skip_spec_review_for_task_options():
    graph = WorkflowGraph(children={"task-DANNY-66": ChildNode(id="task-DANNY-66")})
    dispatches: list[AttemptDispatch] = []

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        dispatches.append(dispatch)
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )

    result = run_once(
        graph,
        SchedulerState(),
        executor=executor,
        now=0,
        owner="daemon",
        require_spec_review=False,
    )

    assert dispatches[0].phase == ChildPhase.IMPLEMENTING
    assert result.children["task-DANNY-66"].phase == ChildPhase.QUALITY_REVIEWING
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run pytest packages/scheduler/tests/test_workflow.py::test_transition_child_phase_skips_spec_review_when_spec_review_not_required packages/scheduler/tests/test_scheduling.py::test_run_once_can_skip_spec_review_for_task_options -q
```

Expected: FAIL because `transition_child_phase()` and `run_once()` do not accept `require_spec_review`.

- [ ] **Step 4: Add option-aware transition parameter**

In `packages/scheduler/src/smda_scheduler/workflow.py`, change the function signature:

```python
def transition_child_phase(
    phase: ChildPhase,
    result: RoleResult,
    *,
    require_spec_review: bool = True,
) -> ChildPhase:
```

Add this special case before the transition table lookup:

```python
    if (
        phase == ChildPhase.IMPLEMENTING
        and result.verdict == "DONE"
        and result.required_next_action == "submit_for_spec_review"
        and not require_spec_review
    ):
        return ChildPhase.QUALITY_REVIEWING
```

- [ ] **Step 5: Thread the option through scheduling**

In `packages/scheduler/src/smda_scheduler/scheduling.py`, add `require_spec_review: bool = True` to `run_once()` and `run_once_durable()` signatures.

In `run_once()`, change:

```python
next_phase = transition_child_phase(dispatch_phase, outcome.role_result)
```

to:

```python
next_phase = transition_child_phase(
    dispatch_phase,
    outcome.role_result,
    require_spec_review=require_spec_review,
)
```

In `run_once_durable()`, pass the option into `run_once()`:

```python
        require_spec_review=require_spec_review,
```

- [ ] **Step 6: Run workflow and scheduling tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_workflow.py packages/scheduler/tests/test_scheduling.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/workflow.py packages/scheduler/src/smda_scheduler/scheduling.py packages/scheduler/tests/test_workflow.py packages/scheduler/tests/test_scheduling.py
git commit -m "Support option-aware task transitions"
```

---

### Task 5: Carry Workflow Options In Role Attempt Context

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/role_attempts.py`
- Test: `packages/scheduler/tests/test_role_attempts.py`

- [ ] **Step 1: Add role attempt context test**

Append this test to `packages/scheduler/tests/test_role_attempts.py`:

```python
from smda_scheduler.execution_modes import ExecutionMode, ModeTag, WorkflowOptions
```

Add this import next to the existing project imports in `packages/scheduler/tests/test_role_attempts.py`.

Append:

```python
def test_build_child_role_attempt_request_carries_workflow_options(tmp_path: Path):
    bootloader_path = tmp_path / "AGENTS.md"
    bootloader_path.write_text("# Boot\nUse pytest.\n", encoding="utf-8")
    repo_context = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\nUse pytest.\n",
        spec_locations=(),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    options = WorkflowOptions(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset({ModeTag.FULL_REVIEW}),
        require_spec_review=True,
        require_quality_review=True,
        require_human_approval=False,
        require_integration=False,
        risk_level="normal",
    )

    request = build_child_role_attempt_request(
        attempt_id="task-DANNY-66-IMPLEMENTING-1",
        parent_issue_id="DANNY-66",
        child=ChildTaskContext(
            child_id="task-DANNY-66",
            title="Fix small bug",
            body="Execution: smda-task",
            acceptance_criteria=("bug fixed",),
            verification={"required": ["pytest"]},
            workflow_options=options,
        ),
        phase=ChildPhase.IMPLEMENTING,
        repo_context=repo_context,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.context_packet["workflow_options"] == {
        "mode": "smda-task",
        "tags": ["full_review"],
        "require_spec_review": True,
        "require_quality_review": True,
        "require_human_approval": False,
        "require_integration": False,
        "risk_level": "normal",
    }
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest packages/scheduler/tests/test_role_attempts.py::test_build_child_role_attempt_request_carries_workflow_options -q
```

Expected: FAIL because `ChildTaskContext` has no `workflow_options` field.

- [ ] **Step 3: Add workflow options to child context**

In `packages/scheduler/src/smda_scheduler/role_attempts.py`, import `WorkflowOptions`:

```python
from smda_scheduler.execution_modes import WorkflowOptions
```

Add this field to `ChildTaskContext`:

```python
    workflow_options: WorkflowOptions | None = None
```

In `_context_packet()`, add:

```python
        "workflow_options": (
            child.workflow_options.to_context_packet()
            if child.workflow_options is not None
            else None
        ),
```

Keep the key present with `None` for existing `smda-child` calls unless local tests require omitting it. The task runtime will always pass a concrete value.

- [ ] **Step 4: Run role attempt tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_role_attempts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/role_attempts.py packages/scheduler/tests/test_role_attempts.py
git commit -m "Carry workflow options in role context"
```

---

### Task 6: Implement `smda-task` Runtime Tick

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [ ] **Step 1: Add runtime tests for default task mode**

Append this test near child candidate tick tests in `packages/scheduler/tests/test_runtime.py`:

```python
def test_run_task_candidate_tick_dispatches_quality_only_task(tmp_path: Path):
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
        id="DANNY-99",
        title="Fix small bug",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest packages/scheduler/tests -q\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
            raw_result={
                "verdict": "DONE",
                "required_next_action": "submit_for_spec_review",
                "report": "implementation complete",
            },
            branch="smda/danny-99/task-danny-99/implementing",
            schema_id="smda.child-implementer-result.v1",
            schema_package_version="0.1.0",
        )
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    result = run_task_candidate_tick(
        issue=issue,
        decision=decision,
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
    task_id = "task-DANNY-99"
    assert result.state.children[task_id].phase == ChildPhase.QUALITY_REVIEWING
    assert execution.requests[0].context_packet["workflow_options"]["mode"] == "smda-task"
    assert execution.requests[0].context_packet["workflow_options"]["require_spec_review"] is False
```

- [ ] **Step 2: Add runtime test for full review tag**

Append:

```python
def test_run_task_candidate_tick_full_review_enters_spec_review(tmp_path: Path):
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
        id="DANNY-100",
        title="Fix risky bug",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Mode tags: full_review\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    result = run_task_candidate_tick(
        issue=issue,
        decision=decision,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    assert result.state.children["task-DANNY-100"].phase == ChildPhase.SPEC_REVIEWING
```

- [ ] **Step 3: Add runtime test for task Done tracker effect**

Append:

```python
def test_run_task_candidate_tick_records_done_effect_after_quality_pass(
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
        id="DANNY-101",
        title="Fix small bug",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    task_id = "task-DANNY-101"
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.save_scheduler_state(
        SchedulerState(children={task_id: ChildRunState(phase=ChildPhase.QUALITY_REVIEWING)})
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="PASS",
                required_next_action="accept_candidate",
            ),
            raw_result={
                "verdict": "PASS",
                "required_next_action": "accept_candidate",
                "report": "quality passed",
            },
            branch="smda/danny-101/task-danny-101/quality-reviewing",
            schema_id="smda.child-quality-reviewer-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = run_task_candidate_tick(
        issue=issue,
        decision=decision,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=20.0,
        owner="daemon-1",
    )

    assert result.state.children[task_id].phase == ChildPhase.QUALITY_REVIEW_PASSED
    effects = ledger.load_pending_tracker_effects()
    states = [
        effect["payload"]["state"]
        for effect in effects
        if effect["effect_type"] == "set_state" and effect["target_id"] == "DANNY-101"
    ]
    comments = [
        effect["payload"]["body"]
        for effect in effects
        if effect["effect_type"] == "comment" and effect["target_id"] == "DANNY-101"
    ]
    assert "Done" in states
    assert any("quality passed" in body for body in comments)
```

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_run_task_candidate_tick_dispatches_quality_only_task packages/scheduler/tests/test_runtime.py::test_run_task_candidate_tick_full_review_enters_spec_review packages/scheduler/tests/test_runtime.py::test_run_task_candidate_tick_records_done_effect_after_quality_pass -q
```

Expected: FAIL because `run_task_candidate_tick` does not exist.

- [ ] **Step 5: Implement task context hydration and task tick**

In `packages/scheduler/src/smda_scheduler/runtime.py`, add `run_task_candidate_tick()` next to `run_child_candidate_tick()`:

```python
def run_task_candidate_tick(
    *,
    issue: BacklogIssue,
    decision: CandidateRoutingDecision,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    now: float,
    owner: str,
) -> ChildCandidateTickResult:
    if decision.route != CandidateRoute.TASK:
        raise GraphError(f"run_task_candidate_tick requires task route: {decision.route}")
    if decision.workflow_options is None:
        raise GraphError("Task route is missing workflow options")

    task_id = _task_child_id(issue.id)
    child = ChildTaskContext(
        child_id=task_id,
        title=issue.title,
        body=issue.body,
        in_scope=_field_values(issue.body, "In scope"),
        out_of_scope=_field_values(issue.body, "Out of scope"),
        touched_surfaces={
            "files": list(_field_values(issue.body, "Touched files")),
            "modules": list(_field_values(issue.body, "Touched modules")),
            "contracts": list(_field_values(issue.body, "Touched contracts")),
            "docs": list(_field_values(issue.body, "Touched docs")),
            "tests": list(_field_values(issue.body, "Touched tests")),
        },
        acceptance_criteria=_field_values(issue.body, "Acceptance criteria"),
        verification={
            "required": list(_field_values(issue.body, "Verification")),
            "smoke": list(_field_values(issue.body, "Verification smoke")),
        },
        workflow_options=decision.workflow_options,
    )
    state = run_child_workflow_tick(
        graph=WorkflowGraph(children={task_id: ChildNode(id=task_id)}),
        child_tasks={task_id: child},
        parent_issue_id=issue.id,
        repo_context=repo_context,
        repo_root=repo_root,
        ledger=ledger,
        execution=execution,
        sandbox_provider=sandbox_provider,
        agent=agent,
        now=now,
        owner=owner,
        require_spec_review=decision.workflow_options.require_spec_review,
    )
    _record_task_lifecycle_effect(ledger, issue.id, task_id, state)
    return ChildCandidateTickResult(
        status="dispatched",
        detail=f"{issue.id}:{state.children[task_id].phase}",
        state=state,
    )
```

Add helpers near lifecycle helpers:

```python
def _task_child_id(issue_id: str) -> str:
    return f"task-{issue_id}"


def _record_task_lifecycle_effect(
    ledger: PhaseLedger,
    issue_id: str,
    task_id: str,
    state: SchedulerState,
) -> None:
    child = state.children.get(task_id)
    if child is None:
        return
    tracker_state = _CHILD_PHASE_TRACKER_STATE.get(child.phase, "In Progress")
    if child.phase == ChildPhase.QUALITY_REVIEW_PASSED:
        tracker_state = "Done"
    key = child.phase.value
    body = f"SMDA task {issue_id} reached `{key}`."
    report = _latest_child_report(ledger, task_id)
    if report:
        body += f"\n\nLatest report:\n{report}"
    ledger.record_tracker_effect(
        effect_id=f"task-lifecycle-state:{issue_id}:{key}",
        idempotency_key=f"task-lifecycle-state:{issue_id}:{key}",
        effect_type="set_state",
        target_id=issue_id,
        payload={"state": tracker_state},
    )
    ledger.record_tracker_effect(
        effect_id=f"task-lifecycle-comment:{issue_id}:{key}",
        idempotency_key=f"task-lifecycle-comment:{issue_id}:{key}:{body}",
        effect_type="comment",
        target_id=issue_id,
        payload={"body": body},
    )
```

- [ ] **Step 6: Add `require_spec_review` to `run_child_workflow_tick()`**

Change `run_child_workflow_tick()` signature:

```python
    require_spec_review: bool = True,
) -> SchedulerState:
```

Pass it through to `run_once_durable()`:

```python
        require_spec_review=require_spec_review,
```

Existing `run_child_candidate_tick()` calls do not need to pass it; the default preserves `smda-child` full review behavior.

- [ ] **Step 7: Run task runtime tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_run_task_candidate_tick_dispatches_quality_only_task packages/scheduler/tests/test_runtime.py::test_run_task_candidate_tick_full_review_enters_spec_review packages/scheduler/tests/test_runtime.py::test_run_task_candidate_tick_records_done_effect_after_quality_pass -q
```

Expected: PASS.

- [ ] **Step 8: Run child runtime regression tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_hydrates_child_handle_and_dispatches packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_dispatches_after_dependency_accept_completed packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_records_child_tracker_lifecycle -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/runtime.py packages/scheduler/tests/test_runtime.py
git commit -m "Run smda task candidates through child workflow"
```

---

### Task 7: Wire Task Mode Into Workspace Runtime

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime_factory.py`
- Modify: `packages/scheduler/tests/test_runtime_factory.py`
- Modify: `packages/scheduler/tests/test_workspace_tick.py`

- [ ] **Step 1: Add configured runtime test for `smda-task`**

Append this test to `packages/scheduler/tests/test_runtime_factory.py`:

```python
def test_configured_workspace_tick_dispatches_smda_task(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# Boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    issue = BacklogIssue(
        id="DANNY-120",
        title="Fix small bug",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
        labels=frozenset({"agent"}),
    )
    backlog = RecordingBacklog(issue)
    execution = RecordingExecution(
        [
            AttemptOutcome(
                status="succeeded",
                role_result=RoleResult(
                    verdict="DONE",
                    required_next_action="submit_for_spec_review",
                ),
            )
        ]
    )

    tick = build_configured_workspace_tick(
        config_path=config_path,
        repo_root=tmp_path,
        backlog=backlog,
        execution=execution,
        scan_state="Todo",
        scan_label="agent",
        owner="daemon-1",
    )
    result = tick()

    assert result.status == "dispatched"
    assert execution.requests[0].context_packet["workflow_options"]["mode"] == "smda-task"
```

- [ ] **Step 2: Add workspace test that task dispatch uses routed path**

Append this test to `packages/scheduler/tests/test_workspace_tick.py`:

```python
def test_workspace_tick_dispatches_task_route(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    task = BacklogIssue(
        id="DANNY-121",
        title="Task",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
        labels=frozenset({"agent"}),
    )
    backlog = RecordingBacklog(BacklogPage(issues=(task,)))
    routed: list[str] = []

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        state="Todo",
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: routed.append(decision.route)
        or TickResult(status="dispatched", detail=issue.id),
    )

    assert result.status == "dispatched"
    assert routed == [CandidateRoute.TASK]
```

Add `CandidateRoute` to the import from `smda_scheduler.candidate_routing` in `packages/scheduler/tests/test_workspace_tick.py`.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime_factory.py::test_configured_workspace_tick_dispatches_smda_task packages/scheduler/tests/test_workspace_tick.py::test_workspace_tick_dispatches_task_route -q
```

Expected: FAIL because `runtime_factory` does not dispatch `CandidateRoute.TASK`.

- [ ] **Step 4: Dispatch task route in `runtime_factory.py`**

In `packages/scheduler/src/smda_scheduler/runtime_factory.py`, import `run_task_candidate_tick` from `smda_scheduler.runtime`.

In `dispatch_routed_candidate()`, add this branch after the child branch:

```python
        if decision.route == CandidateRoute.TASK:
            result = run_task_candidate_tick(
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

- [ ] **Step 5: Run runtime factory and workspace tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime_factory.py packages/scheduler/tests/test_workspace_tick.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/runtime_factory.py packages/scheduler/tests/test_runtime_factory.py packages/scheduler/tests/test_workspace_tick.py
git commit -m "Wire task route into workspace runtime"
```

---

### Task 8: Handle Human Approval And Integration Tags Conservatively

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [ ] **Step 1: Add human approval tag test**

Append to `packages/scheduler/tests/test_runtime.py`:

```python
def test_smda_task_human_approval_tag_parks_after_quality_pass(tmp_path: Path):
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
        id="DANNY-130",
        title="Human checked task",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Mode tags: human_approval_required\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    task_id = "task-DANNY-130"
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.save_scheduler_state(
        SchedulerState(children={task_id: ChildRunState(phase=ChildPhase.QUALITY_REVIEWING)})
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(verdict="PASS", required_next_action="accept_candidate"),
        )
    )

    result = run_task_candidate_tick(
        issue=issue,
        decision=decision,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=20.0,
        owner="daemon-1",
    )

    assert result.state.children[task_id].phase == ChildPhase.QUALITY_REVIEW_PASSED
    effects = ledger.load_pending_tracker_effects()
    assert any(
        effect["effect_type"] == "set_state"
        and effect["target_id"] == "DANNY-130"
        and effect["payload"] == {"state": "Human Review"}
        for effect in effects
    )
```

- [ ] **Step 2: Add integration tag block test**

Append:

```python
def test_smda_task_requires_integration_blocks_until_integration_runtime_exists(
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
        id="DANNY-131",
        title="Integrated task",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Mode tags: requires_integration\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    task_id = "task-DANNY-131"
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.save_scheduler_state(
        SchedulerState(children={task_id: ChildRunState(phase=ChildPhase.QUALITY_REVIEWING)})
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(verdict="PASS", required_next_action="accept_candidate"),
        )
    )

    result = run_task_candidate_tick(
        issue=issue,
        decision=decision,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=20.0,
        owner="daemon-1",
    )

    assert result.state.children[task_id].phase == ChildPhase.QUALITY_REVIEW_PASSED
    effects = ledger.load_pending_tracker_effects()
    assert any(
        effect["effect_type"] == "set_state"
        and effect["target_id"] == "DANNY-131"
        and effect["payload"] == {"state": "Blocked"}
        for effect in effects
    )
    assert any(
        "requires_integration is not configured for smda-task"
        in effect["payload"].get("body", "")
        for effect in effects
        if effect["effect_type"] == "comment"
    )
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_smda_task_human_approval_tag_parks_after_quality_pass packages/scheduler/tests/test_runtime.py::test_smda_task_requires_integration_blocks_until_integration_runtime_exists -q
```

Expected: FAIL because task lifecycle currently maps `QUALITY_REVIEW_PASSED` to Done unconditionally.

- [ ] **Step 4: Update task lifecycle state mapping**

In `_record_task_lifecycle_effect()`, replace the terminal state calculation with:

```python
    latest_request = _latest_child_request_json(ledger, task_id)
    context_packet = latest_request.get("context_packet") if latest_request else None
    workflow_options = (
        context_packet.get("workflow_options")
        if isinstance(context_packet, dict)
        else None
    )

    if child.phase == ChildPhase.QUALITY_REVIEW_PASSED:
        if isinstance(workflow_options, dict) and workflow_options.get(
            "require_integration"
        ):
            tracker_state = "Blocked"
            body += (
                "\n\nSMDA task requires_integration is not configured for "
                "smda-task in this implementation slice."
            )
        elif isinstance(workflow_options, dict) and workflow_options.get(
            "require_human_approval"
        ):
            tracker_state = "Human Review"
        else:
            tracker_state = "Done"
```

Add helper near `_latest_child_report()`:

```python
def _latest_child_request_json(ledger: PhaseLedger, child_id: str) -> dict | None:
    for attempt in reversed(ledger.load_attempts()):
        if attempt["target_kind"] == "child" and attempt["target_id"] == child_id:
            request_json = attempt["request_json"]
            if isinstance(request_json, dict):
                return request_json
    return None
```

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest packages/scheduler/tests/test_runtime.py::test_run_task_candidate_tick_records_done_effect_after_quality_pass packages/scheduler/tests/test_runtime.py::test_smda_task_human_approval_tag_parks_after_quality_pass packages/scheduler/tests/test_runtime.py::test_smda_task_requires_integration_blocks_until_integration_runtime_exists -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/runtime.py packages/scheduler/tests/test_runtime.py
git commit -m "Apply task terminal mode tags"
```

---

### Task 9: Document Mode Catalog In Product And Harness Surface

**Files:**
- Modify: `docs/product-spec.md`
- Modify: `docs/known-gaps.md`
- Modify: `docs/adapter-boundaries.md`
- Test: `packages/scheduler/tests/test_execution_modes.py`

- [ ] **Step 1: Add catalog markdown test**

Append this test to `packages/scheduler/tests/test_execution_modes.py`:

```python
from smda_scheduler.execution_modes import SMDA_EXECUTION_MODE_CATALOG_MARKDOWN
```

Add the name to the existing import from `smda_scheduler.execution_modes`.

Append:

```python
def test_execution_mode_catalog_markdown_surfaces_supported_modes():
    catalog = SMDA_EXECUTION_MODE_CATALOG_MARKDOWN

    assert "Execution: smda" in catalog
    assert "Execution: smda-task" in catalog
    assert "Execution: smda-child" in catalog
    assert "Execution: smda-review" in catalog
    assert "Execution: manual" in catalog
    assert "Mode tags:" in catalog
    assert "full_review" in catalog
    assert "quality_only" in catalog
    assert "human_approval_required" in catalog
    assert "requires_integration" in catalog
```

- [ ] **Step 2: Run catalog test**

Run:

```bash
uv run pytest packages/scheduler/tests/test_execution_modes.py::test_execution_mode_catalog_markdown_surfaces_supported_modes -q
```

Expected: PASS.

- [ ] **Step 3: Update product spec**

In `docs/product-spec.md`, add or update a section named `Execution Modes` with this content:

```md
## Execution Modes

SMDA supports multiple deterministic execution modes. The mode chooses the
primary state machine; mode tags only modify predefined gates.

- `Execution: smda` runs the full parent-driven workflow: approved spec intake,
  graph decomposition, graph reviews, child publication, child SDD loops,
  parent integration, parent QA, and final accept.
- `Execution: smda-child` is reserved for scheduler-created child handles from
  a persisted parent graph. Dependency truth remains in SMDA graph and ledger
  state, not tracker blocking labels.
- `Execution: smda-task` runs a single issue through the reusable child SDD
  segment without graph decomposition or parent QA. The default is implement
  plus quality review; `full_review` or `high_risk` adds spec review.
- `Execution: smda-review` is cataloged for review-only automation but is not
  enabled in the first task-mode implementation slice.
- `Execution: manual` prevents automatic claim.

Supported issue-body `Mode tags:` values are `full_review`, `quality_only`,
`human_approval_required`, `requires_integration`, `high_risk`, and `low_risk`.
Unsupported tags and invalid tag combinations block before role execution.
Tags cannot weaken stale graph checksum checks or dependency dispatch gates.
```

- [ ] **Step 4: Update known gaps**

In `docs/known-gaps.md`, add an entry under the relevant completed/future section:

```md
- **Execution modes** (task-mode slice): `smda-task` supports independent
  single-issue automation with typed `Mode tags:` resolution. `smda-review`,
  per-role model policy, tracker label shortcuts, and task integration-branch
  acceptance remain future slices.
```

- [ ] **Step 5: Update adapter boundaries**

In `docs/adapter-boundaries.md`, add this setup/config boundary statement:

```md
Setup and harness docs may surface the built-in SMDA execution mode catalog, but
they must not invent project-specific custom modes. New modes require product
runtime support in `smda_scheduler.execution_modes` and scheduler tests.
```

- [ ] **Step 6: Run docs sanity checks**

Run:

```bash
git diff --check
uv run pytest packages/scheduler/tests/test_execution_modes.py -q
```

Expected: no whitespace errors and PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/product-spec.md docs/known-gaps.md docs/adapter-boundaries.md packages/scheduler/tests/test_execution_modes.py
git commit -m "Document SMDA execution modes"
```

---

### Task 10: Full Verification

**Files:**
- Verify: full scheduler test suite
- Verify: git diff
- Modify: `docs/superpowers/plans/2026-06-16-execution-modes-and-workflow-options-plan.md`

- [ ] **Step 1: Run full scheduler tests**

Run:

```bash
uv run pytest packages/scheduler/tests -q
```

Expected: PASS.

- [ ] **Step 2: Run diff sanity check**

Run:

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 3: Inspect changed files**

Run:

```bash
git status --short
git diff --stat HEAD~9..HEAD
```

Expected: only execution-mode, task-runtime, latest-ref, docs, and tests changed. `.DS_Store`, caches, and local environment files must not appear.

- [ ] **Step 4: Mark this plan complete**

In this file, update completed checkboxes for all tasks that were executed and add a short verification note under this task:

```md
Verification:
- `uv run pytest packages/scheduler/tests -q`
- `git diff --check`
```

- [ ] **Step 5: Commit plan completion**

```bash
git add docs/superpowers/plans/2026-06-16-execution-modes-and-workflow-options-plan.md
git commit -m "Mark execution modes plan complete"
```

---

## Self-Review

Spec coverage:

- Product docs define supported modes and tags: Task 9.
- Setup/harness surface has mode catalog: Task 2 catalog constant and Task 9 docs boundary.
- `Execution: smda-task` runs a small bug through reusable child SDD: Tasks 3, 4, 5, 6, 7.
- `implicit-one-child` routes to `smda-task`: Task 3.
- Tags resolve into typed `WorkflowOptions`: Task 2.
- Invalid tags and invalid tag combinations block before role execution: Tasks 2 and 3.
- Tags cannot override dependency gating or stale graph checksum checks: preserved by leaving `smda-child` graph gate untouched and documenting tag limits in Task 9.
- Existing `smda` and `smda-child` behavior remains compatible: Tasks 4, 6, 7 include regression test runs.
- Latest parent acceptance candidate edge case is covered: Task 1.

Placeholder scan:

- No task uses open-ended implementation instructions without concrete code or commands.
- `smda-review` is explicitly out of scope for runtime and blocks with a clear reason.
- `requires_integration` for `smda-task` is conservative: it blocks terminal Done until a future integration runtime exists.

Type consistency:

- `CandidateRoutingDecision.workflow_options` is created in Task 3 and consumed in Tasks 6 and 7.
- `WorkflowOptions.to_context_packet()` is created in Task 2 and consumed in Task 5.
- `require_spec_review` is added to workflow and scheduler in Task 4 and passed by task runtime in Task 6.
- Parent acceptance and dependency gate both use `latest_quality_candidate_ref()` after Task 1.
