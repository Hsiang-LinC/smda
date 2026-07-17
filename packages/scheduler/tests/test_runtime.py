import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fakes import FakeBacklogAdapter, FakeBacklogIssue

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.backlog import BacklogError, BacklogIssue
from smda_scheduler.git_integration import ConflictProbeResult
from smda_scheduler.candidate_routing import classify_candidate
from smda_scheduler.phase_ledger import BacklogEffect, PhaseLedger, StaleParentTransition
from smda_scheduler.role_contracts import RoleName
from smda_scheduler.role_attempts import AgentSelection, ChildTaskContext
from smda_scheduler.runtime import (
    _graph_payload_from_outcome,
    _write_parent_success,
    RoleExecutionAdapter,
    resolve_parent_base,
    run_roadmap_candidate_intake,
    run_roadmap_decomposition_tick,
    run_roadmap_completion_tick,
    run_roadmap_publication_tick,
    run_roadmap_workflow_tick,
    run_parent_child_publication_tick,
    run_parent_child_acceptance_tick,
    run_parent_remediation_planning_tick,
    run_landing_conflict_rebase_tick,
    run_parent_final_accept_tick,
    run_parent_workflow_tick,
    run_parent_candidate_intake,
    run_child_candidate_tick,
    run_child_workflow_tick,
)
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.scheduling import AttemptOutcome
from smda_scheduler.scheduling import ChildRunState, SchedulerState
from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    GraphError,
    ParentPhase,
    QaBounds,
    RoadmapPhase,
    RoleResult,
    WorkflowGraph,
)
from smda_scheduler.workflow_graph import WorkflowGraphArtifact
from smda_scheduler.workflow_engine import PARENT_DEFINITION, TASK_DEFINITION
from smda_scheduler.parent_acceptance import (
    ChildAcceptConflictError,
    ChildAcceptOperation,
    ParentLandOperation,
    ParentIntegration,
    child_accept_conflict_fingerprint,
)


class RecordingExecutionAdapter(RoleExecutionAdapter):
    def __init__(self, outcome: AttemptOutcome):
        self.outcome = outcome
        self.requests: list[RoleAttemptRequest] = []

    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome:
        self.requests.append(request)
        return self.outcome


class QueueExecutionAdapter(RoleExecutionAdapter):
    def __init__(self, outcomes: list[AttemptOutcome]):
        self.outcomes = list(outcomes)
        self.requests: list[RoleAttemptRequest] = []

    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome:
        self.requests.append(request)
        return self.outcomes.pop(0)


def _run_parent_role_workflow_tick(**kwargs):
    return run_parent_workflow_tick(backlog=FakeBacklogAdapter(), **kwargs)


class RecordingPublication(FakeBacklogAdapter):
    def __init__(self, *, issues: dict[str, FakeBacklogIssue] | None = None) -> None:
        super().__init__(issues=issues)
        self.states: list[tuple[str, str]] = []

    def set_coarse_state(self, issue_id: str, state: str) -> None:
        super().set_coarse_state(issue_id, state)
        self.states.append((issue_id, state))


def test_workflow_control_does_not_load_raw_attempt_rows():
    paths = [
        Path("packages/scheduler/src/smda_scheduler/runtime.py"),
        Path("packages/scheduler/src/smda_scheduler/child_dependency_gate.py"),
        Path("packages/scheduler/src/smda_scheduler/parent_acceptance.py"),
    ]
    assert all(".load_attempts()" not in path.read_text() for path in paths)


class RecordingParentIntegration(ParentIntegration):
    def __init__(
        self,
        *,
        conflicted_paths: tuple[str, ...] = (),
        child_accept_conflicted_paths: tuple[str, ...] = (),
    ) -> None:
        self.applied: list[ChildAcceptOperation] = []
        self.accepted_refs: set[str] = set()
        self.landed: list[ParentLandOperation] = []
        self.landed_refs: set[tuple[str, str]] = set()
        self.conflicted_paths = conflicted_paths
        self.child_accept_conflicted_paths = child_accept_conflicted_paths
        self.probes: list[tuple[str, str]] = []
        self.rebased: list[tuple[str, str]] = []
        self.ensured: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool:
        return operation.candidate_ref in self.accepted_refs

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None:
        self.applied.append(operation)
        if self.child_accept_conflicted_paths:
            raise ChildAcceptConflictError(
                "cherry-pick conflict",
                conflicted_paths=self.child_accept_conflicted_paths,
            )
        self.accepted_refs.add(operation.candidate_ref)

    def has_landed_parent_ref(self, operation: ParentLandOperation) -> bool:
        return (operation.parent_ref, operation.base_branch) in self.landed_refs

    def land_parent_to_base(self, operation: ParentLandOperation) -> None:
        self.landed.append(operation)
        self.landed_refs.add((operation.parent_ref, operation.base_branch))

    def probe_conflict(self, *, head: str, base: str) -> ConflictProbeResult:
        self.probes.append((head, base))
        if self.conflicted_paths:
            return ConflictProbeResult(
                clean=False, conflicted_paths=self.conflicted_paths
            )
        return ConflictProbeResult(clean=True)

    def rebase_onto_base(self, *, head: str, base: str) -> None:
        self.rebased.append((head, base))
        # A successful rebase clears the conflict so the next probe is clean.
        self.conflicted_paths = ()

    def ensure_branch(self, name: str, *, start_point: str) -> None:
        self.ensured.append((name, start_point))

    def branch_exists(self, name: str) -> bool:
        return name in {ensured[0] for ensured in self.ensured}

    def delete_branch(self, name: str) -> None:
        self.deleted.append(name)


def _prepare_approved_parent(tmp_path: Path) -> tuple[BacklogIssue, RepoContextPacket, PhaseLedger]:
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir(exist_ok=True)
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n",
        encoding="utf-8",
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    intake = run_parent_candidate_intake(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_root=tmp_path,
        ledger=ledger,
    )
    assert intake.target_state == "In Progress"
    return issue, repo_context, ledger


def _prepare_approved_roadmap(
    tmp_path: Path,
) -> tuple[BacklogIssue, RepoContextPacket, PhaseLedger]:
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "roadmap.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir(exist_ok=True)
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-16\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-100 approval\n"
        "---\n"
        "# Approved roadmap spec\n",
        encoding="utf-8",
    )
    issue = BacklogIssue(
        id="DANNY-100",
        title="Roadmap",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/roadmap.md\n"
            "Execution: smda-roadmap\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    intake = run_roadmap_candidate_intake(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_root=tmp_path,
        ledger=ledger,
    )
    assert intake.target_state == "In Progress"
    return issue, repo_context, ledger


def _roadmap_parent(**overrides: object) -> dict[str, object]:
    parent: dict[str, object] = {
        "node_id": "parent-001",
        "title": "Introduce member store",
        "body": "Persist roadmap member parent specs.",
        "risk_level": "medium",
        "dependencies": [],
    }
    parent.update(overrides)
    return parent


def _roadmap_edge(**overrides: object) -> dict[str, object]:
    edge: dict[str, object] = {
        "from": "parent-001",
        "to": "parent-002",
        "type": "code_dependency",
        "blocks_dispatch": True,
        "reason": "parent-002 reads parent-001 output.",
    }
    edge.update(overrides)
    return edge


def _complete_graph_child(**overrides: object) -> dict[str, object]:
    child: dict[str, object] = {
        "node_id": "child-001",
        "title": "Extract scheduler runtime",
        "body": "Move scheduler code into the SMDA product.",
        "in_scope": ["scheduler runtime"],
        "out_of_scope": ["consumer repo cleanup"],
        "touched_surfaces": {
            "files": ["packages/scheduler/src/smda_scheduler/runtime.py"],
            "modules": ["smda_scheduler.runtime"],
            "contracts": ["smda.graph-decomposer-result.v1"],
            "docs": ["docs/product-spec.md"],
            "tests": ["packages/scheduler/tests/test_runtime.py"],
        },
        "acceptance_criteria": ["scheduler tests pass"],
        "verification": {
            "required": ["uv run pytest packages/scheduler/tests/test_runtime.py -q"],
            "smoke": ["uv run pytest packages/scheduler/tests -q"],
        },
        "risk_level": "medium",
        "dependencies": [],
    }
    child.update(overrides)
    return child


def _record_graph(
    ledger: PhaseLedger,
    *,
    parent_id: str,
    graph_checksum: str,
    children: list[dict[str, object]],
    dependency_edges: list[dict[str, object]] | None = None,
) -> None:
    ledger.record_graph(
        WorkflowGraphArtifact.from_dict(
            {
                "parent_id": parent_id,
                "graph_checksum": graph_checksum,
                "children": children,
                "dependency_edges": dependency_edges or [],
            }
        )
    )


def _record_single_child_graph(
    ledger: PhaseLedger,
    *,
    parent_id: str = "DANNY-66",
    graph_checksum: str = "sha256:graph",
    node_id: str = "child-001",
) -> None:
    _record_graph(
        ledger,
        parent_id=parent_id,
        graph_checksum=graph_checksum,
        children=[_complete_graph_child(node_id=node_id)],
    )


def _record_quality_passed_child(
    ledger: PhaseLedger,
    *,
    child_id: str = "child-001",
    candidate_ref: str = "smda/danny-66/child-001/candidate",
    attempt_number: int = 4,
) -> None:
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                child_id: ChildRunState(
                    phase=ChildPhase.QUALITY_REVIEW_PASSED,
                    attempts=attempt_number,
                )
            }
        )
    )
    attempt_id = f"{child_id}-QUALITY_REVIEWING-{attempt_number}"
    ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="child",
        target_id=child_id,
        phase=ChildPhase.QUALITY_REVIEWING,
        idempotency_key=f"{child_id}:QUALITY_REVIEWING:{attempt_number}",
        request_json={"role": "child_quality_reviewer"},
    )
    ledger.record_attempt_result(
        attempt_id=attempt_id,
        status="succeeded",
        result_json={
            "verdict": "PASS",
            "required_next_action": "accept_candidate",
            "branch": candidate_ref,
        },
        error_message=None,
    )


def _graph_decomposition_outcome(
    children: list[dict[str, object]],
    *,
    dependency_edges: list[dict[str, object]] | None = None,
) -> AttemptOutcome:
    raw_result: dict[str, object] = {
        "verdict": "DONE",
        "required_next_action": "submit_for_graph_review",
        "children": children,
        "dependency_edges": dependency_edges or [],
    }
    return AttemptOutcome(
        status="succeeded",
        role_result=RoleResult(
            verdict="DONE",
            required_next_action="submit_for_graph_review",
        ),
        raw_result=raw_result,
    )


def test_graph_payload_rejects_child_ids_that_collide_after_parent_scoping():
    outcome = _graph_decomposition_outcome(
        [
            _complete_graph_child(node_id="child-001"),
            _complete_graph_child(node_id="DANNY-66-child-001"),
        ],
        dependency_edges=[],
    )

    with pytest.raises(GraphError, match="graph child IDs must be unique"):
        _graph_payload_from_outcome(outcome, parent_id="DANNY-66")


def test_graph_payload_rejects_legacy_edges_alias():
    outcome = _graph_decomposition_outcome(
        [_complete_graph_child()], dependency_edges=[]
    )
    assert outcome.raw_result is not None
    outcome.raw_result.pop("dependency_edges")
    outcome.raw_result["edges"] = []

    with pytest.raises(GraphError, match="dependency_edges"):
        _graph_payload_from_outcome(outcome, parent_id="DANNY-66")


def test_run_child_workflow_tick_dispatches_typed_role_attempt(tmp_path: Path):
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
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )
    )
    ledger = PhaseLedger(tmp_path / ".smda" / "state" / "ledger.sqlite")

    state = run_child_workflow_tick(
        graph=WorkflowGraph(children={"child-001": ChildNode(id="child-001")}),
        child_tasks={
            "child-001": ChildTaskContext(
                child_id="child-001",
                title="Implement runtime wiring",
                body="Dispatch through Sandcastle.",
            )
        },
        parent_issue_id="DANNY-66",
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    assert state.children["child-001"].phase == ChildPhase.SPEC_REVIEWING
    assert len(execution.requests) == 1
    request = execution.requests[0]
    assert request.attempt_id == "child-001-IMPLEMENTING-1"
    assert request.role == "child_implementer"
    assert request.schema_id == "smda.child-implementer-result.v1"
    assert request.output_tag == "smda_child_implementer_result"
    assert request.context_packet["child_id"] == "child-001"
    assert ledger.load_attempts()[0]["status"] == "succeeded"


def test_run_child_workflow_tick_can_use_task_definition_to_skip_spec_review(
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

    state = run_child_workflow_tick(
        graph=WorkflowGraph(children={"child-001": ChildNode(id="child-001")}),
        child_tasks={
            "child-001": ChildTaskContext(
                child_id="child-001",
                title="Implement focused task",
                body="Use the task workflow definition.",
            )
        },
        parent_issue_id="DANNY-66",
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
        workflow_definition=TASK_DEFINITION,
    )

    assert state.children["child-001"].phase == ChildPhase.QUALITY_REVIEWING


def test_run_child_workflow_tick_fixer_carries_prior_review_findings(tmp_path: Path):
    bootloader = tmp_path / "AGENTS.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_spec_review"
            ),
        )
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.save_scheduler_state(
        SchedulerState(children={"child-001": ChildRunState(phase=ChildPhase.FIXING_SPEC)})
    )
    ledger.record_role_attempt_request(
        attempt_id="child-001-SPEC_REVIEWING-1",
        target_kind="child",
        target_id="child-001",
        phase="SPEC_REVIEWING",
        idempotency_key="child-001:SPEC_REVIEWING:1",
        request_json={},
    )
    ledger.record_attempt_result(
        attempt_id="child-001-SPEC_REVIEWING-1",
        status="succeeded",
        result_json={
            "verdict": "FAIL",
            "required_next_action": "fix_spec",
            "report": "Spec review: missing edge-case handling in parse().",
        },
        error_message=None,
    )

    run_child_workflow_tick(
        graph=WorkflowGraph(children={"child-001": ChildNode(id="child-001")}),
        child_tasks={
            "child-001": ChildTaskContext(
                child_id="child-001", title="t", body="b"
            )
        },
        parent_issue_id="DANNY-66",
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    assert len(execution.requests) == 1
    request = execution.requests[0]
    assert request.role == "child_fixer"
    assert "missing edge-case handling" in " ".join(
        request.context_packet["review_findings"]
    )


def test_run_child_candidate_tick_hydrates_static_context_from_graph(
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
        id="DANNY-66-C1",
        title="Stale title from tracker projection",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:graph",
                "Node id: child-001",
                "Source: docs/superpowers/specs/approved.md",
                "In scope: stale issue-body projection",
                "Touched files: stale.py",
                "Acceptance criteria: stale criteria",
                "Verification required: stale check",
                "Risk level: medium",
                "",
                "Stale issue body projection.",
            ]
        ),
    )
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
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(
                node_id="child-000",
                title="Accepted dependency",
                body="Accepted dependency body.",
            ),
            _complete_graph_child(
                node_id="child-001",
                title="Implement runtime wiring",
                body="Dispatch through Sandcastle.",
                touched_surfaces={
                    "files": ["packages/scheduler/src/smda_scheduler/runtime.py"],
                    "modules": ["smda_scheduler.runtime"],
                    "contracts": ["smda.child-role-context.v1"],
                    "docs": ["docs/product-spec.md"],
                    "tests": ["packages/scheduler/tests/test_runtime.py"],
                },
                dependencies=["child-000"],
            ),
        ],
        dependency_edges=[
            {
                "from": "child-000",
                "to": "child-001",
                "type": "code_dependency",
                "blocks_dispatch": False,
                "reason": "child-001 imports the accepted runtime API.",
                "required_artifacts": ["accepted_commit"],
            }
        ],
    )

    run_child_candidate_tick(
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

    packet = execution.requests[0].context_packet
    assert packet["child_title"] == "Implement runtime wiring"
    assert packet["child_body"] == "Dispatch through Sandcastle."
    assert packet["in_scope"] == ["scheduler runtime"]
    assert packet["out_of_scope"] == ["consumer repo cleanup"]
    assert packet["touched_surfaces"] == {
        "files": ["packages/scheduler/src/smda_scheduler/runtime.py"],
        "modules": ["smda_scheduler.runtime"],
        "contracts": ["smda.child-role-context.v1"],
        "docs": ["docs/product-spec.md"],
        "tests": ["packages/scheduler/tests/test_runtime.py"],
    }
    assert packet["verification"] == {
        "required": ["uv run pytest packages/scheduler/tests/test_runtime.py -q"],
        "smoke": ["uv run pytest packages/scheduler/tests -q"],
    }
    assert packet["dependencies"] == ["child-000"]
    assert packet["dependency_outputs"] == [
        {
            "dependency_id": "child-000",
            "required_artifacts": ["accepted_commit"],
            "reason": "child-001 imports the accepted runtime API.",
        }
    ]
    assert packet["candidate_ref"] is None
    assert packet["review_findings"] == []


def test_run_child_workflow_tick_requires_child_task_context(tmp_path: Path):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=(),
    )

    with pytest.raises(GraphError, match="Missing child task context"):
        run_child_workflow_tick(
            graph=WorkflowGraph(children={"child-001": ChildNode(id="child-001")}),
            child_tasks={},
            parent_issue_id="DANNY-66",
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
            execution=RecordingExecutionAdapter(AttemptOutcome(status="execution_failed")),
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            now=10.0,
            owner="daemon-1",
        )


def test_run_child_candidate_tick_hydrates_child_handle_and_dispatches(tmp_path: Path):
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
        title="Implement child packet",
        state="Todo",
        body=(
            "Parent issue: DANNY-66\n"
            "Graph checksum: sha256:abcdef\n"
            "Node id: child-001\n"
            "Execution: smda-child\n"
            "Acceptance criteria: validates routed child dispatch\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _record_single_child_graph(
        ledger,
        graph_checksum="sha256:abcdef",
        node_id="child-001",
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )
    )

    result = run_child_candidate_tick(
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
    state = result.state

    assert result.status == "dispatched"
    assert state.children["child-001"].phase == ChildPhase.SPEC_REVIEWING
    request = execution.requests[0]
    assert request.context_packet["parent_issue_id"] == "DANNY-66"
    assert request.context_packet["child_id"] == "child-001"
    assert request.context_packet["child_title"] == "Extract scheduler runtime"
    assert request.context_packet["acceptance_criteria"] == ["scheduler tests pass"]


def test_parent_scoped_child_ids_do_not_reuse_prior_parent_runtime_state(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _record_graph(
        ledger,
        parent_id="DANNY-70",
        graph_checksum="sha256:old",
        children=[_complete_graph_child(node_id="DANNY-70-child-001")],
    )
    _record_graph(
        ledger,
        parent_id="DANNY-79",
        graph_checksum="sha256:new",
        children=[_complete_graph_child(node_id="DANNY-79-child-001")],
    )
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "DANNY-70-child-001": ChildRunState(
                    phase=ChildPhase.QUALITY_REVIEW_PASSED,
                    attempts=4,
                )
            }
        )
    )
    issue = BacklogIssue(
        id="DANNY-81",
        title="Child",
        state="Todo",
        body=(
            "Execution: smda-child\n"
            "Parent issue: DANNY-79\n"
            "Graph checksum: sha256:new\n"
            "Node id: DANNY-79-child-001\n"
            "Acceptance criteria: works\n"
        ),
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
            raw_result={"verdict": "DONE"},
        )
    )

    result = run_child_candidate_tick(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_context=RepoContextPacket(
            bootloader_path=tmp_path / "AGENTS.md",
            bootloader_text="# Boot\n",
            spec_locations=(),
            adr_locations=(),
            quality_gates=("pytest",),
        ),
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=1.0,
        owner="daemon-1",
    )

    assert (
        result.state.children["DANNY-79-child-001"].phase
        == ChildPhase.SPEC_REVIEWING
    )
    assert (
        result.state.children["DANNY-70-child-001"].phase
        == ChildPhase.QUALITY_REVIEW_PASSED
    )
    assert execution.requests[0].context_packet["child_id"] == "DANNY-79-child-001"


def test_run_child_candidate_tick_rejects_child_id_owned_by_other_parent(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _record_graph(
        ledger,
        parent_id="DANNY-79",
        graph_checksum="sha256:new",
        children=[_complete_graph_child(node_id="child-001")],
    )
    ledger.record_role_attempt_request(
        attempt_id="child-001-QUALITY_REVIEWING-4",
        target_kind="child",
        target_id="child-001",
        phase=ChildPhase.QUALITY_REVIEWING,
        idempotency_key="child-001:QUALITY_REVIEWING:4",
        request_json={"context_packet": {"parent_issue_id": "DANNY-70"}},
    )
    issue = BacklogIssue(
        id="DANNY-81",
        title="Child",
        state="Todo",
        body=(
            "Execution: smda-child\n"
            "Parent issue: DANNY-79\n"
            "Graph checksum: sha256:new\n"
            "Node id: child-001\n"
            "Acceptance criteria: works\n"
        ),
    )

    with pytest.raises(GraphError, match="belongs to parent DANNY-70"):
        run_child_candidate_tick(
            issue=issue,
            decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
            repo_context=RepoContextPacket(
                bootloader_path=tmp_path / "AGENTS.md",
                bootloader_text="# Boot\n",
                spec_locations=(),
                adr_locations=(),
                quality_gates=("pytest",),
            ),
            repo_root=tmp_path,
            ledger=ledger,
            execution=RecordingExecutionAdapter(
                AttemptOutcome(status="execution_failed")
            ),
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            now=1.0,
            owner="daemon-1",
        )


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
    _record_graph(
        ledger,
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
    _record_graph(
        ledger,
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
            "branch": "smda/DANNY-66/child-001/candidate",
        },
        error_message=None,
    )
    ledger.record_parent_accept_operation(
        operation_id=(
            "accept:DANNY-66:child-001:"
            "smda/DANNY-66/child-001/candidate"
        ),
        idempotency_key=(
            "parent:DANNY-66:child-001:"
            "smda/DANNY-66/child-001/candidate"
        ),
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="smda/DANNY-66/child-001/candidate",
        integration_branch="smda/DANNY-66/integration",
    )
    ledger.mark_parent_accept_completed(
        "accept:DANNY-66:child-001:smda/DANNY-66/child-001/candidate"
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


def test_run_child_candidate_tick_rejects_unknown_graph_node(tmp_path: Path):
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
        id="DANNY-66-C9",
        title="Unknown child",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:graph",
                "Node id: child-999",
                "Acceptance criteria: should not dispatch",
            ]
        ),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_spec_review"
            ),
        )
    )

    with pytest.raises(GraphError, match="not present in current graph"):
        run_child_candidate_tick(
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
    assert execution.requests == []


def test_run_child_candidate_tick_rejects_non_child_route(tmp_path: Path):
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="Todo",
        body="Execution: smda\n",
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")

    with pytest.raises(GraphError, match="requires child route"):
        run_child_candidate_tick(
            issue=issue,
            decision=decision,
            repo_context=RepoContextPacket(
                bootloader_path=tmp_path / "AGENTS.md",
                bootloader_text="",
                spec_locations=(),
                adr_locations=(),
                quality_gates=(),
            ),
            repo_root=tmp_path,
            ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
            execution=RecordingExecutionAdapter(AttemptOutcome(status="execution_failed")),
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            now=10.0,
            owner="daemon-1",
        )


def test_run_parent_candidate_intake_blocks_missing_spec(tmp_path: Path):
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="Todo",
        body="Execution: smda\nAcceptance criteria: works\nVerification: pytest\n",
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    result = run_parent_candidate_intake(
        issue=issue,
        decision=decision,
        repo_root=tmp_path,
        ledger=ledger,
    )

    assert result.target_state == "Blocked"
    assert "No approved parent spec path" in result.comment
    assert ledger.load_parent_runs() == []


def test_run_parent_candidate_intake_routes_draft_spec_to_human_review(
    tmp_path: Path,
):
    spec = tmp_path / "docs" / "superpowers" / "specs" / "draft.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: draft\n"
        "approval_evidence: pending\n"
        "---\n"
        "# Draft\n",
        encoding="utf-8",
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="Todo",
        body=(
            "Source: docs/superpowers/specs/draft.md\n"
            "Execution: smda\n"
            "Acceptance criteria: works\n"
            "Verification: pytest\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    result = run_parent_candidate_intake(
        issue=issue,
        decision=decision,
        repo_root=tmp_path,
        ledger=ledger,
    )

    assert result.target_state == "Human Review"
    assert "spec approval is incomplete" in result.comment
    assert ledger.load_parent_run("DANNY-66") is None


def test_run_parent_candidate_intake_requires_complete_approval_frontmatter(
    tmp_path: Path,
):
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: approved\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved without approval actor or timestamp\n",
        encoding="utf-8",
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="Todo",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
            "Acceptance criteria: works\n"
            "Verification: pytest\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    result = run_parent_candidate_intake(
        issue=issue,
        decision=decision,
        repo_root=tmp_path,
        ledger=ledger,
    )

    assert result.target_state == "Human Review"
    assert "approved_at" in result.comment
    assert "approved_by" in result.comment
    assert ledger.load_parent_run("DANNY-66") is None


def test_run_parent_candidate_intake_persists_spec_finalized(
    tmp_path: Path,
):
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved\n",
        encoding="utf-8",
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="Todo",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
            "Acceptance criteria: works\n"
            "Verification: pytest\n"
        ),
    )
    decision = classify_candidate(issue, issue_entry_policy="explicit-only")
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    result = run_parent_candidate_intake(
        issue=issue,
        decision=decision,
        repo_root=tmp_path,
        ledger=ledger,
    )

    parent_run = ledger.load_parent_runs()[0]
    assert result.target_state == "In Progress"
    assert "SPEC_FINALIZED" in result.comment
    assert parent_run["parent_id"] == "DANNY-66"
    assert parent_run["phase"] == "SPEC_FINALIZED"
    assert parent_run["spec_path"] == "docs/superpowers/specs/approved.md"
    assert parent_run["spec_checksum"].startswith("sha256:")
    assert parent_run["approval_evidence"] == "DANNY-66 approval"
    effects = ledger.load_pending_tracker_effects()
    comment_effect = next(
        effect for effect in effects if effect["payload"] == {"body": result.comment}
    )
    lifecycle_key = comment_effect["idempotency_key"].rsplit(":", 1)[1]
    assert any(
        effect["idempotency_key"] == f"lifecycle-state:DANNY-66:{lifecycle_key}"
        and effect["payload"] == {"state": result.target_state}
        for effect in effects
    )


def test_run_parent_graph_decomposition_tick_dispatches_from_spec_finalized(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    intake = run_parent_candidate_intake(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_root=tmp_path,
        ledger=ledger,
    )
    assert intake.target_state == "In Progress"
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_graph_review",
            ),
            raw_result={
                "verdict": "DONE",
                "required_next_action": "submit_for_graph_review",
                "dependency_edges": [],
                "children": [
                    _complete_graph_child(node_id="child-001"),
                    _complete_graph_child(
                        node_id="child-002",
                        title="Wire setup skill",
                        body="Make setup emit config only.",
                        acceptance_criteria=["setup emits config only"],
                        dependencies=["child-001"],
                    ),
                ],
            },
            branch="smda/danny-66/graph-decomposing",
            schema_id="smda.graph-decomposer-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "GRAPH_SPEC_REVIEWING" in result.comment
    assert len(execution.requests) == 1
    request = execution.requests[0]
    assert request.attempt_id == "DANNY-66-GRAPH_DECOMPOSING-1"
    assert request.role == "graph_decomposer"
    assert request.context_packet["spec_text"] == spec_text
    attempts = ledger.load_attempts()
    assert attempts[0]["target_kind"] == "parent"
    assert attempts[0]["target_id"] == "DANNY-66"
    assert attempts[0]["status"] == "succeeded"
    assert ledger.load_parent_runs()[0]["phase"] == "GRAPH_SPEC_REVIEWING"
    graph = ledger.load_graph("DANNY-66")
    assert graph.graph_checksum.startswith("sha256:")
    assert [child.to_dict() for child in graph.children] == [
        _complete_graph_child(node_id="DANNY-66-child-001"),
        _complete_graph_child(
            node_id="DANNY-66-child-002",
            title="Wire setup skill",
            body="Make setup emit config only.",
            acceptance_criteria=["setup emits config only"],
            dependencies=["DANNY-66-child-001"],
        ),
    ]
    effects = ledger.load_pending_tracker_effects()
    comment_effect = next(
        effect for effect in effects if effect["payload"] == {"body": result.comment}
    )
    lifecycle_key = comment_effect["idempotency_key"].rsplit(":", 1)[1]
    assert any(
        effect["idempotency_key"] == f"lifecycle-state:DANNY-66:{lifecycle_key}"
        and effect["payload"] == {"state": result.target_state}
        for effect in effects
    )


def test_parent_execution_failure_commits_evidence_and_lifecycle_in_same_phase(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="failed",
            role_result=None,
            error_message="worker exited 1",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "Blocked"
    assert ledger.load_parent_run(issue.id)["phase"] == "SPEC_FINALIZED"
    assert ledger.load_attempts()[0]["status"] == "failed"
    assert ledger.load_attempts()[0]["error_message"] == "worker exited 1"
    assert [
        (effect["effect_type"], effect["payload"])
        for effect in ledger.load_pending_tracker_effects()
        if effect["payload"] in ({"body": result.comment}, {"state": result.target_state})
    ] == [
        ("comment", {"body": result.comment}),
        ("set_state", {"state": result.target_state}),
    ]


def test_parent_completion_rejects_second_write_from_stale_snapshot(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="SPEC_FINALIZED",
        spec_path="docs/spec.md",
        spec_checksum="sha256:spec",
        approval_evidence="approved by user",
    )
    parent_run = ledger.load_parent_run("DANNY-66")
    assert parent_run is not None
    outcome = AttemptOutcome(
        status="succeeded",
        role_result=RoleResult(
            verdict="DONE",
            required_next_action="submit_for_graph_review",
        ),
    )
    graph_a = WorkflowGraphArtifact.from_dict(
        {
            "parent_id": "DANNY-66",
            "graph_checksum": "sha256:graph-a",
            "children": [_complete_graph_child(node_id="child-a")],
            "dependency_edges": [],
        }
    )
    graph_b = WorkflowGraphArtifact.from_dict(
        {
            "parent_id": "DANNY-66",
            "graph_checksum": "sha256:graph-b",
            "children": [_complete_graph_child(node_id="child-b")],
            "dependency_edges": [],
        }
    )
    for attempt_id in ("completion-1", "completion-2"):
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind="parent",
            target_id="DANNY-66",
            phase=ParentPhase.GRAPH_DECOMPOSING,
            idempotency_key=attempt_id,
            request_json={},
        )
    effect_a = BacklogEffect(
        effect_id="completion-1-effect",
        idempotency_key="completion-1-effect",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "completion 1"},
    )
    effect_b = BacklogEffect(
        effect_id="completion-2-effect",
        idempotency_key="completion-2-effect",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "completion 2"},
    )

    _write_parent_success(
        ledger=ledger,
        parent_id="DANNY-66",
        resolved_attempt_id="completion-1",
        outcome=outcome,
        next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
        parent_run=parent_run,
        extra=graph_a,
        effects=(effect_a,),
    )
    with pytest.raises(StaleParentTransition):
        _write_parent_success(
            ledger=ledger,
            parent_id="DANNY-66",
            resolved_attempt_id="completion-2",
            outcome=outcome,
            next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
            parent_run=parent_run,
            extra=graph_b,
            effects=(effect_b,),
        )

    attempts = {attempt["attempt_id"]: attempt for attempt in ledger.load_attempts()}
    assert attempts["completion-1"]["status"] == "succeeded"
    assert attempts["completion-2"]["status"] == "dispatched"
    assert ledger.load_graph("DANNY-66") == graph_a
    assert [effect["effect_id"] for effect in ledger.load_tracker_effects()] == [
        effect_a.effect_id
    ]
    assert ledger.load_parent_run("DANNY-66")["phase"] == (
        ParentPhase.GRAPH_SPEC_REVIEWING.value
    )


def test_parent_workflow_request_uses_definition_role_contract(
    tmp_path: Path, monkeypatch
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    stage = PARENT_DEFINITION.stage("SPEC_FINALIZED")
    assert stage.role_contract is not None
    contract = replace(
        stage.role_contract,
        role=RoleName.GRAPH_FIXER,
        schema_id="definition-owned-schema",
        output_tag="definition_owned_output",
        prompt_template="Definition-owned prompt for {parent_issue_id} ({schema_id}).",
    )
    monkeypatch.setitem(
        PARENT_DEFINITION.stages,
        "SPEC_FINALIZED",
        replace(stage, role_contract=contract),
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(status="execution_failed", error_message="test stop")
    )

    _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(
            provider="codex",
            model="default",
            role_overrides={
                "graph_fixer": AgentSelection(provider="codex", model="definition")
            },
        ),
        owner="daemon-1",
    )

    request = execution.requests[0]
    assert request.role == "graph_fixer"
    assert request.schema_id == "definition-owned-schema"
    assert request.output_tag == "definition_owned_output"
    assert "Definition-owned prompt" in request.prompt
    assert request.agent_model == "definition"


def test_run_parent_graph_decomposition_requires_child_acceptance_criteria(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    intake = run_parent_candidate_intake(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_root=tmp_path,
        ledger=ledger,
    )
    assert intake.target_state == "In Progress"
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_graph_review",
            ),
            raw_result={
                "verdict": "DONE",
                "required_next_action": "submit_for_graph_review",
                "dependency_edges": [],
                "children": [
                    _complete_graph_child(
                        node_id="child-001",
                        acceptance_criteria=[],
                    )
                ],
            },
        )
    )

    with pytest.raises(GraphError, match="acceptance_criteria"):
        _run_parent_role_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
        )


def test_run_parent_graph_decomposition_requires_child_scope_fields(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    execution = RecordingExecutionAdapter(
        _graph_decomposition_outcome(
            [_complete_graph_child(in_scope=[], out_of_scope=[])]
        )
    )

    with pytest.raises(GraphError, match="in_scope"):
        _run_parent_role_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
        )


def test_run_parent_graph_decomposition_requires_touched_surfaces(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    execution = RecordingExecutionAdapter(
        _graph_decomposition_outcome(
            [_complete_graph_child(touched_surfaces={"files": []})]
        )
    )

    with pytest.raises(GraphError, match="touched_surfaces.files"):
        _run_parent_role_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
        )


def test_run_parent_graph_decomposition_requires_verification_commands(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    execution = RecordingExecutionAdapter(
        _graph_decomposition_outcome(
            [_complete_graph_child(verification={"required": []})]
        )
    )

    with pytest.raises(GraphError, match="verification.required"):
        _run_parent_role_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
        )


def test_run_parent_graph_decomposition_rejects_unknown_risk_level(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    execution = RecordingExecutionAdapter(
        _graph_decomposition_outcome(
            [_complete_graph_child(risk_level="catastrophic")]
        )
    )

    with pytest.raises(GraphError, match="risk_level"):
        _run_parent_role_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
        )


def test_graph_rejects_dependency_without_reason(tmp_path: Path):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    child_1 = _complete_graph_child(node_id="child-001")
    child_2 = _complete_graph_child(
        node_id="child-002",
        title="Wire setup skill",
        body="Make setup emit config only.",
        dependencies=["child-001"],
    )
    execution = RecordingExecutionAdapter(
        _graph_decomposition_outcome(
            [child_1, child_2],
            dependency_edges=[
                {
                    "from": "child-001",
                    "to": "child-002",
                    "type": "code_dependency",
                    "blocks_dispatch": True,
                    "reason": "",
                    "required_artifacts": ["accepted_commit"],
                }
            ],
        )
    )

    with pytest.raises(GraphError, match="dependency edge reason"):
        _run_parent_role_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
        )


def test_graph_rejects_dependency_without_required_artifacts(tmp_path: Path):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    child_1 = _complete_graph_child(node_id="child-001")
    child_2 = _complete_graph_child(
        node_id="child-002",
        title="Wire setup skill",
        body="Make setup emit config only.",
        dependencies=["child-001"],
    )
    execution = RecordingExecutionAdapter(
        _graph_decomposition_outcome(
            [child_1, child_2],
            dependency_edges=[
                {
                    "from": "child-001",
                    "to": "child-002",
                    "type": "code_dependency",
                    "blocks_dispatch": True,
                    "reason": "child-002 imports the new runtime API",
                    "required_artifacts": [],
                }
            ],
        )
    )

    with pytest.raises(GraphError, match="dependency edge required_artifacts"):
        _run_parent_role_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
        )


def test_graph_allows_sequencing_only_dependency_without_code_overlap(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    child_1 = _complete_graph_child(node_id="child-001")
    child_2 = _complete_graph_child(
        node_id="child-002",
        title="Wire setup skill",
        body="Make setup emit config only.",
        dependencies=["child-001"],
    )
    edge = {
        "from": "child-001",
        "to": "child-002",
        "type": "sequencing_only",
        "blocks_dispatch": True,
        "reason": "child-002 should start after child-001 defines the expected API.",
        "required_artifacts": ["accepted_commit"],
    }
    execution = RecordingExecutionAdapter(
        _graph_decomposition_outcome(
            [child_1, child_2],
            dependency_edges=[edge],
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    graph = ledger.load_graph("DANNY-66")
    assert graph.to_dict()["dependency_edges"] == [
        {
            **edge,
            "from": "DANNY-66-child-001",
            "to": "DANNY-66-child-002",
        }
    ]
    assert graph.children[1].dependencies == ("DANNY-66-child-001",)


def test_run_parent_graph_spec_review_tick_dispatches_from_graph_spec_reviewing(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="PASS",
                required_next_action="submit_for_graph_execution_review",
            ),
            raw_result={
                "verdict": "PASS",
                "required_next_action": "submit_for_graph_execution_review",
                "report": "graph matches spec",
            },
            branch="smda/danny-66/graph-spec-reviewing",
            schema_id="smda.review-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "GRAPH_EXECUTION_REVIEWING" in result.comment
    request = execution.requests[0]
    assert request.attempt_id == "DANNY-66-GRAPH_SPEC_REVIEWING-1"
    assert request.role == "graph_spec_reviewer"
    assert request.context_packet["graph_checksum"] == "sha256:graph"
    assert request.context_packet["children"][0]["node_id"] == "child-001"
    attempts = ledger.load_attempts()
    assert attempts[0]["phase"] == "GRAPH_SPEC_REVIEWING"
    assert attempts[0]["status"] == "succeeded"
    assert ledger.load_parent_runs()[0]["phase"] == "GRAPH_EXECUTION_REVIEWING"


def test_parent_workflow_dispatches_spec_review_through_generic_runner(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Source: docs/superpowers/specs/approved.md\nExecution: smda\n",
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="PASS",
                required_next_action="submit_for_graph_execution_review",
            ),
            raw_result={
                "verdict": "PASS",
                "required_next_action": "submit_for_graph_execution_review",
                "report": "graph matches spec",
            },
            branch="smda/danny-66/graph-spec-reviewing",
            schema_id="smda.review-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "GRAPH_EXECUTION_REVIEWING" in result.comment
    request = execution.requests[0]
    assert request.attempt_id == "DANNY-66-GRAPH_SPEC_REVIEWING-1"
    assert request.role == "graph_spec_reviewer"
    assert ledger.load_attempts()[0]["phase"] == "GRAPH_SPEC_REVIEWING"
    assert ledger.load_parent_runs()[0]["phase"] == "GRAPH_EXECUTION_REVIEWING"


def test_run_parent_graph_spec_review_tick_routes_fail_to_graph_fixing(tmp_path: Path):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\nstatus: approved\napproved_at: 2026-06-15\napproved_by: human\n"
        "approval_evidence: DANNY-66 approval\n---\n# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Source: docs/superpowers/specs/approved.md\nExecution: smda\n",
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="FAIL", required_next_action="request_human_review"
            ),
            raw_result={
                "verdict": "FAIL",
                "required_next_action": "request_human_review",
                "report": "graph omits requirement R3",
            },
            branch="smda/danny-66/graph-spec-reviewing",
            schema_id="smda.review-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "requirement R3" in result.comment
    assert ledger.load_parent_runs()[0]["phase"] == "GRAPH_FIXING"


def test_run_parent_graph_execution_review_tick_dispatches_from_graph_execution_reviewing(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_EXECUTION_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="PASS",
                required_next_action="publish_child_issues",
            ),
            raw_result={
                "verdict": "PASS",
                "required_next_action": "publish_child_issues",
                "report": "graph can execute safely",
            },
            branch="smda/danny-66/graph-execution-reviewing",
            schema_id="smda.review-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "CHILD_PUBLICATION_READY" in result.comment
    request = execution.requests[0]
    assert request.attempt_id == "DANNY-66-GRAPH_EXECUTION_REVIEWING-1"
    assert request.role == "graph_execution_reviewer"
    assert request.context_packet["graph_checksum"] == "sha256:graph"
    attempts = ledger.load_attempts()
    assert attempts[0]["phase"] == "GRAPH_EXECUTION_REVIEWING"
    assert attempts[0]["status"] == "succeeded"
    assert ledger.load_parent_runs()[0]["phase"] == "CHILD_PUBLICATION_READY"


def test_run_parent_child_publication_tick_creates_children_and_blockers(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILD_PUBLICATION_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001"),
            _complete_graph_child(
                node_id="child-002",
                title="Wire setup skill",
                body="Make setup emit config only.",
                acceptance_criteria=["setup emits config only"],
                dependencies=["child-001"],
            ),
        ],
    )
    backlog = FakeBacklogAdapter(
        issues={
            "DANNY-66": FakeBacklogIssue(
                id="DANNY-66",
                title="Parent",
                state="In Progress",
            )
        }
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Execution: smda\n",
    )

    result = run_parent_child_publication_tick(
        issue=issue,
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )

    projections = ledger.load_child_issue_projections("DANNY-66")
    assert result.target_state == "In Progress"
    assert "CHILDREN_PUBLISHED" in result.comment
    assert projections == {
        "child-001": "DANNY-66-C1",
        "child-002": "DANNY-66-C2",
    }
    child_1 = backlog.fetch_issue("DANNY-66-C1")
    child_2 = backlog.fetch_issue("DANNY-66-C2")
    assert child_1.parent_id == "DANNY-66"
    assert child_1.labels == frozenset({"agent"})
    assert child_1.title == "Extract scheduler runtime"
    assert "Execution: smda-child" in child_1.body
    assert "Parent issue: DANNY-66" in child_1.body
    assert "Graph checksum: sha256:graph" in child_1.body
    assert "Node id: child-001" in child_1.body
    assert "Acceptance criteria: scheduler tests pass" in child_1.body
    assert child_2.parent_id == "DANNY-66"
    assert backlog.query_blocked_by("DANNY-66-C2") == ["DANNY-66-C1"]
    assert ledger.load_parent_runs()[0]["phase"] == "CHILDREN_PUBLISHED"


def test_child_publication_sets_new_children_to_todo(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILD_PUBLICATION_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001"),
            _complete_graph_child(
                node_id="child-002",
                title="Wire setup skill",
                body="Make setup emit config only.",
                acceptance_criteria=["setup emits config only"],
                dependencies=["child-001"],
            ),
        ],
    )
    backlog = RecordingPublication(
        issues={
            "DANNY-66": FakeBacklogIssue(
                id="DANNY-66",
                title="Parent",
                state="In Progress",
            )
        }
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Execution: smda\n",
    )

    run_parent_child_publication_tick(
        issue=issue,
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )

    created_ids = list(ledger.load_child_issue_projections("DANNY-66").values())
    assert created_ids == ["DANNY-66-C1", "DANNY-66-C2"]
    for child_id in created_ids:
        assert (child_id, "Todo") in backlog.states


def test_run_roadmap_candidate_intake_records_decomposing_phase(tmp_path: Path):
    issue, _repo_context, ledger = _prepare_approved_roadmap(tmp_path)

    assert ledger.load_parent_runs() == [
        {
            "parent_id": issue.id,
            "phase": RoadmapPhase.ROADMAP_DECOMPOSING.value,
            "spec_path": "docs/superpowers/specs/roadmap.md",
            "spec_checksum": ledger.load_parent_runs()[0]["spec_checksum"],
            "approval_evidence": "DANNY-100 approval",
        }
    ]


def test_run_roadmap_decomposition_tick_persists_members_edges_and_snapshot(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_roadmap(tmp_path)
    outcome = AttemptOutcome(
        status="succeeded",
        role_result=RoleResult(
            verdict="DONE",
            required_next_action="publish_roadmap_parents",
        ),
        raw_result={
            "verdict": "DONE",
            "required_next_action": "publish_roadmap_parents",
            "parents": [
                _roadmap_parent(node_id="parent-001"),
                _roadmap_parent(
                    node_id="parent-002",
                    title="Publish member parents",
                    body="Create parent issues from roadmap specs.",
                    risk_level="high",
                    dependencies=["parent-001"],
                ),
            ],
            "roadmap_edges": [_roadmap_edge()],
        },
    )
    execution = RecordingExecutionAdapter(outcome)
    backlog = FakeBacklogAdapter(
        issues={
            "DANNY-66": FakeBacklogIssue(
                id="DANNY-66",
                title="Existing parent",
                state="Todo",
                body="Execution: smda\nSource: docs/superpowers/specs/existing.md\n",
                labels=frozenset({"agent"}),
            )
        }
    )

    result = run_roadmap_decomposition_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        backlog=backlog,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "ROADMAP_PUBLICATION_READY" in result.comment
    assert [member["node_id"] for member in ledger.load_roadmap_members(issue.id)] == [
        "parent-001",
        "parent-002",
    ]
    assert ledger.load_roadmap_member_edges(issue.id) == [_roadmap_edge()]
    request = execution.requests[0]
    assert request.role == "roadmap_decomposer"
    assert request.schema_id == "smda.roadmap-decomposer-result.v1"
    assert request.context_packet["open_parent_snapshot"][0]["issue_id"] == "DANNY-66"
    assert "DANNY-66" in request.prompt
    assert ledger.load_parent_runs()[0]["phase"] == RoadmapPhase.ROADMAP_PUBLICATION_READY.value


def test_run_roadmap_publication_tick_creates_parent_members_and_edges_idempotently(
    tmp_path: Path,
):
    issue, _repo_context, ledger = _prepare_approved_roadmap(tmp_path)
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=RoadmapPhase.ROADMAP_DECOMPOSING.value,
        next_phase=RoadmapPhase.ROADMAP_PUBLICATION_READY.value,
    )
    ledger.record_roadmap_members(
        issue.id,
        [
            _roadmap_parent(node_id="parent-001"),
            _roadmap_parent(
                node_id="parent-002",
                title="Publish member parents",
                body="Create parent issues from roadmap specs.",
                risk_level="high",
                dependencies=["parent-001"],
            ),
        ],
        roadmap_edges=[_roadmap_edge()],
    )
    backlog = FakeBacklogAdapter(
        issues={
            issue.id: FakeBacklogIssue(
                id=issue.id,
                title=issue.title,
                state="In Progress",
                body=issue.body,
            )
        }
    )

    first = run_roadmap_publication_tick(
        issue=issue,
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )
    second = run_roadmap_publication_tick(
        issue=issue,
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )

    assert first.target_state == "In Progress"
    assert second.target_state == "In Progress"
    assert ledger.load_roadmap_member_projections(issue.id) == {
        "parent-001": "DANNY-100-C1",
        "parent-002": "DANNY-100-C2",
    }
    assert backlog.fetch_issue("DANNY-100-C1").body.startswith("Execution: smda")
    assert "Roadmap issue: DANNY-100" in backlog.fetch_issue("DANNY-100-C1").body
    assert backlog.fetch_issue("DANNY-100-C1").labels == frozenset({"agent"})
    assert backlog.query_blocked_by("DANNY-100-C2") == ["DANNY-100-C1"]
    assert ledger.load_roadmap_blockers("DANNY-100-C2") == ("DANNY-100-C1",)
    assert ledger.load_parent_runs()[0]["phase"] == RoadmapPhase.ROADMAP_PUBLISHED.value
    assert backlog.project_hierarchy(issue.id) == ["DANNY-100-C1", "DANNY-100-C2"]


def test_run_roadmap_publication_reconciles_edges_after_projection_reentry(
    tmp_path: Path,
):
    issue, _repo_context, ledger = _prepare_approved_roadmap(tmp_path)
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=RoadmapPhase.ROADMAP_DECOMPOSING.value,
        next_phase=RoadmapPhase.ROADMAP_PUBLICATION_READY.value,
    )
    ledger.record_roadmap_members(
        issue.id,
        [
            _roadmap_parent(node_id="parent-001"),
            _roadmap_parent(node_id="parent-002", dependencies=["parent-001"]),
        ],
        roadmap_edges=[_roadmap_edge()],
    )
    ledger.record_roadmap_member_projection(
        roadmap_id=issue.id,
        node_id="parent-001",
        issue_id="DANNY-100-C1",
    )
    ledger.record_roadmap_member_projection(
        roadmap_id=issue.id,
        node_id="parent-002",
        issue_id="DANNY-100-C2",
    )
    backlog = FakeBacklogAdapter(
        issues={
            issue.id: FakeBacklogIssue(id=issue.id, title=issue.title, state="In Progress"),
            "DANNY-100-C1": FakeBacklogIssue(
                id="DANNY-100-C1",
                title="Introduce member store",
                state="Todo",
                parent_id=issue.id,
            ),
            "DANNY-100-C2": FakeBacklogIssue(
                id="DANNY-100-C2",
                title="Publish member parents",
                state="Todo",
                parent_id=issue.id,
            ),
        }
    )

    run_roadmap_publication_tick(
        issue=issue,
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )

    assert backlog.project_hierarchy(issue.id) == ["DANNY-100-C1", "DANNY-100-C2"]
    assert ledger.load_roadmap_blockers("DANNY-100-C2") == ("DANNY-100-C1",)
    assert backlog.query_blocked_by("DANNY-100-C2") == ["DANNY-100-C1"]


class _LinkFailingBacklog(FakeBacklogAdapter):
    """Backlog that raises on the first link_blocking call to simulate a crash
    mid-publication, after member issues are created but before edges project."""

    def __init__(self, *, issues, fail_times: int = 1) -> None:
        super().__init__(issues=issues)
        self.link_failures_left = fail_times

    def link_blocking(self, *, blocker_id: str, blocked_id: str) -> None:
        if self.link_failures_left > 0:
            self.link_failures_left -= 1
            raise BacklogError("link_blocking boom")
        super().link_blocking(blocker_id=blocker_id, blocked_id=blocked_id)


def _dispatchable_member_ids(backlog, roadmap_id: str) -> set[str]:
    page = backlog.list_issues(
        state="Todo",
        label="agent",
        parent_id=roadmap_id,
        limit=50,
        cursor=None,
    )
    return {member.id for member in page.issues}


def test_run_roadmap_publication_holds_members_until_edges_recorded(tmp_path: Path):
    issue, _repo_context, ledger = _prepare_approved_roadmap(tmp_path)
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=RoadmapPhase.ROADMAP_DECOMPOSING.value,
        next_phase=RoadmapPhase.ROADMAP_PUBLICATION_READY.value,
    )
    ledger.record_roadmap_members(
        issue.id,
        [
            _roadmap_parent(node_id="parent-001"),
            _roadmap_parent(node_id="parent-002", dependencies=["parent-001"]),
        ],
        roadmap_edges=[_roadmap_edge()],
    )
    backlog = _LinkFailingBacklog(
        issues={
            issue.id: FakeBacklogIssue(
                id=issue.id, title=issue.title, state="In Progress", body=issue.body
            )
        }
    )

    # First tick crashes mid-publication (link_blocking raises).
    with pytest.raises(BacklogError):
        run_roadmap_publication_tick(
            issue=issue,
            ledger=ledger,
            backlog=backlog,
            child_labels=frozenset({"agent"}),
        )

    # Members were created but are NOT dispatchable: a Todo scan picks up none,
    # so the parent gate can never dispatch a downstream member out of order.
    assert _dispatchable_member_ids(backlog, issue.id) == set()
    assert (
        ledger.load_parent_runs()[0]["phase"]
        == RoadmapPhase.ROADMAP_PUBLICATION_READY.value
    )

    # Re-entry completes: members released only after edges + blocking projected.
    run_roadmap_publication_tick(
        issue=issue,
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )

    assert _dispatchable_member_ids(backlog, issue.id) == {
        "DANNY-100-C1",
        "DANNY-100-C2",
    }
    assert ledger.load_roadmap_blockers("DANNY-100-C2") == ("DANNY-100-C1",)
    assert backlog.query_blocked_by("DANNY-100-C2") == ["DANNY-100-C1"]
    assert ledger.load_parent_runs()[0]["phase"] == RoadmapPhase.ROADMAP_PUBLISHED.value


def test_parent_child_acceptance_records_child_done_tracker_effect(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
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
            "branch": "smda/DANNY-66/child-001/candidate",
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
    assert any("smda/DANNY-66/child-001/candidate" in body for body in comments)
    assert any("smda/DANNY-66/integration" in body for body in comments)


def test_parent_workflow_waits_for_children_before_requiring_integration(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "child-001": ChildRunState(
                    phase=ChildPhase.IMPLEMENTING,
                    attempts=1,
                )
            }
        )
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Execution: smda\n",
    )

    result = run_parent_workflow_tick(
        issue=issue,
        repo_context=RepoContextPacket(
            bootloader_path=tmp_path / "AGENTS.md",
            bootloader_text="# Boot\n",
            spec_locations=(tmp_path / "docs",),
            adr_locations=(),
            quality_gates=("pytest",),
        ),
        repo_root=tmp_path,
        ledger=ledger,
        execution=RecordingExecutionAdapter(
            AttemptOutcome(status="execution_failed", error_message="unused")
        ),
        backlog=RecordingPublication(),
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
        integration=None,
        integration_branch=None,
    )

    assert result.target_state == "In Progress"
    assert "waiting for quality-passed children" in result.comment
    assert ledger.load_parent_runs()[0]["phase"] == "CHILDREN_PUBLISHED"


def test_child_publication_body_contains_static_context_packet(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILD_PUBLICATION_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    dependency_edge = {
        "from": "child-001",
        "to": "child-002",
        "type": "code_dependency",
        "blocks_dispatch": True,
        "reason": "child-002 imports the new runtime API",
        "required_artifacts": ["accepted_commit"],
    }
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001"),
            _complete_graph_child(
                node_id="child-002",
                title="Wire setup skill",
                body="Make setup emit config only.",
                acceptance_criteria=["setup emits config only"],
                dependencies=["child-001"],
            ),
        ],
        dependency_edges=[dependency_edge],
    )
    backlog = FakeBacklogAdapter(
        issues={
            "DANNY-66": FakeBacklogIssue(
                id="DANNY-66",
                title="Parent",
                state="In Progress",
            )
        }
    )

    run_parent_child_publication_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )

    child_body = backlog.fetch_issue("DANNY-66-C2").body
    for section in (
        "Execution: smda-child",
        "Parent issue: DANNY-66",
        "Graph checksum: sha256:graph",
        "Node id: child-002",
        "Source: docs/superpowers/specs/approved.md",
        "In scope:",
        "Out of scope:",
        "Touched files:",
        "Touched modules:",
        "Touched contracts:",
        "Touched docs:",
        "Touched tests:",
        "Acceptance criteria:",
        "Verification required:",
        "Verification smoke:",
        "Risk level:",
        "Dependency reasons:",
    ):
        assert section in child_body
    assert "child-002 imports the new runtime API" in child_body
    assert "Required artifacts: accepted_commit" in child_body


def test_run_parent_workflow_tick_advances_parent_state_machine_happy_path(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n",
        encoding="utf-8",
    )
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    run_parent_candidate_intake(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_root=tmp_path,
        ledger=ledger,
    )
    execution = QueueExecutionAdapter(
        [
            AttemptOutcome(
                status="succeeded",
                role_result=RoleResult(
                    verdict="DONE",
                    required_next_action="submit_for_graph_review",
                ),
                raw_result={
                    "verdict": "DONE",
                    "required_next_action": "submit_for_graph_review",
                    "dependency_edges": [],
                    "children": [
                        _complete_graph_child(node_id="child-001"),
                        _complete_graph_child(
                            node_id="child-002",
                            title="Wire setup skill",
                            body="Make setup emit config only.",
                            acceptance_criteria=["setup emits config only"],
                            dependencies=["child-001"],
                        ),
                    ],
                },
            ),
            AttemptOutcome(
                status="succeeded",
                role_result=RoleResult(
                    verdict="PASS",
                    required_next_action="submit_for_graph_execution_review",
                ),
            ),
            AttemptOutcome(
                status="succeeded",
                role_result=RoleResult(
                    verdict="PASS",
                    required_next_action="publish_child_issues",
                ),
            ),
        ]
    )
    backlog = FakeBacklogAdapter(
        issues={
            "DANNY-66": FakeBacklogIssue(
                id="DANNY-66",
                title="Parent",
                state="In Progress",
            )
        }
    )

    for _ in range(4):
        run_parent_workflow_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=ledger,
            execution=execution,
            backlog=backlog,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            owner="daemon-1",
            child_labels=frozenset({"agent"}),
        )

    assert [request.role for request in execution.requests] == [
        "graph_decomposer",
        "graph_spec_reviewer",
        "graph_execution_reviewer",
    ]
    assert ledger.load_parent_runs()[0]["phase"] == "CHILDREN_PUBLISHED"
    assert ledger.load_child_issue_projections("DANNY-66") == {
        "DANNY-66-child-001": "DANNY-66-C1",
        "DANNY-66-child-002": "DANNY-66-C2",
    }
    assert backlog.fetch_issue("DANNY-66-C1").labels == frozenset({"agent"})
    assert backlog.query_blocked_by("DANNY-66-C2") == ["DANNY-66-C1"]


def test_run_parent_child_acceptance_tick_integrates_quality_passed_children(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    ledger.record_child_issue_projection(
        parent_id="DANNY-66",
        node_id="child-001",
        issue_id="DANNY-101",
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
            "branch": "smda/danny-66/child-001/candidate",
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
        integration_branch=None,
    )

    assert result.target_state == "In Progress"
    assert "PARENT_QA_READY" in result.comment
    assert [operation.child_id for operation in integration.applied] == ["child-001"]
    operation = integration.applied[0]
    assert operation.parent_id == "DANNY-66"
    assert operation.candidate_ref == "smda/danny-66/child-001/candidate"
    assert operation.integration_branch == "smda/danny-66/integration"
    assert ledger.load_parent_accept_operations()[0]["status"] == "completed"
    assert ledger.load_parent_runs()[0]["phase"] == "PARENT_QA_READY"


def test_parent_child_acceptance_routes_conflict_to_resolver(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_single_child_graph(ledger)
    _record_quality_passed_child(ledger)
    integration = RecordingParentIntegration(
        child_accept_conflicted_paths=("shared.txt",)
    )

    result = run_parent_child_acceptance_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        integration=integration,
        integration_branch=None,
    )

    assert result.target_state == "In Progress"
    assert "CHILD_ACCEPT_CONFLICT_RESOLVING" in result.comment
    operation = ledger.load_parent_accept_operations()[0]
    assert operation["status"] == "pending"
    assert operation["conflicted_paths"] == ("shared.txt",)
    assert operation["conflict_fingerprint"]
    assert operation["resolver_attempts"] == 0
    assert ledger.load_parent_runs()[0]["phase"] == (
        ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING
    )


def test_parent_accept_conflict_resolver_retries_with_visible_history(
    tmp_path: Path,
):
    issue, repo_context, ledger = _prepare_approved_parent(tmp_path)
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase="SPEC_FINALIZED",
        next_phase=ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING.value,
    )
    _record_single_child_graph(ledger, parent_id=issue.id)
    operation_id = ledger.record_parent_accept_operation(
        operation_id="accept:DANNY-66:child-001:candidate-1",
        idempotency_key="parent:DANNY-66:child-001:candidate-1",
        parent_id=issue.id,
        child_id="child-001",
        candidate_ref="candidate-1",
        integration_branch="smda/danny-66/integration",
    )
    ledger.mark_parent_accept_failed(
        operation_id,
        "cherry-pick conflict",
        conflicted_paths=("shared.txt",),
        conflict_fingerprint="fp-1",
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="retry_child_acceptance",
            ),
            raw_result={
                "verdict": "DONE",
                "required_next_action": "retry_child_acceptance",
                "report": "Resolved shared.txt conflict.",
            },
        )
    )

    result = run_parent_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        backlog=FakeBacklogAdapter(
            issues={
                issue.id: FakeBacklogIssue(
                    id=issue.id,
                    title=issue.title,
                    state="In Progress",
                )
            }
        ),
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "CHILDREN_PUBLISHED" in result.comment
    request = execution.requests[0]
    assert request.role == "parent_integration_conflict_resolver"
    history = request.context_packet["conflict_history"]
    assert history["operation_id"] == operation_id
    assert history["conflicted_paths"] == ["shared.txt"]
    assert history["last_error"] == "cherry-pick conflict"
    operation = ledger.load_parent_accept_operations()[0]
    assert operation["resolver_attempts"] == 1
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.CHILDREN_PUBLISHED


def test_parent_child_acceptance_escalates_repeated_conflict_to_human_review(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_single_child_graph(ledger)
    _record_quality_passed_child(ledger)
    operation_id = ledger.record_parent_accept_operation(
        operation_id="accept:DANNY-66:child-001:smda/danny-66/child-001/candidate",
        idempotency_key="parent:DANNY-66:child-001:smda/danny-66/child-001/candidate",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="smda/danny-66/child-001/candidate",
        integration_branch="smda/danny-66/integration",
    )
    operation = ChildAcceptOperation(
        operation_id=operation_id,
        idempotency_key="parent:DANNY-66:child-001:smda/danny-66/child-001/candidate",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="smda/danny-66/child-001/candidate",
        integration_branch="smda/danny-66/integration",
    )
    fingerprint = child_accept_conflict_fingerprint(
        operation,
        conflicted_paths=("shared.txt",),
        error_message="cherry-pick conflict",
    )
    ledger.mark_parent_accept_failed(
        operation_id,
        "cherry-pick conflict",
        conflicted_paths=("shared.txt",),
        conflict_fingerprint=fingerprint,
    )
    ledger.increment_parent_accept_resolver_attempts(operation_id)
    ledger.increment_parent_accept_resolver_attempts(operation_id)

    result = run_parent_child_acceptance_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        integration=RecordingParentIntegration(
            child_accept_conflicted_paths=("shared.txt",)
        ),
        integration_branch=None,
    )

    assert result.target_state == "Human Review"
    assert "attempts exhausted" in result.comment
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.HUMAN_REVIEW_REQUIRED


def test_parent_child_acceptance_uses_latest_quality_candidate_by_attempt_number(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
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


def test_parent_child_acceptance_accepts_new_latest_ref_after_old_ref_completed(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
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
    ledger.record_parent_accept_operation(
        operation_id="accept:DANNY-66:child-001:branch-9",
        idempotency_key="parent:DANNY-66:child-001:branch-9",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="branch-9",
        integration_branch="smda/DANNY-66/integration",
    )
    ledger.mark_parent_accept_completed("accept:DANNY-66:child-001:branch-9")
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
    assert [operation.candidate_ref for operation in integration.applied] == [
        "branch-10"
    ]
    operations = ledger.load_parent_accept_operations()
    completed_refs = [
        operation["candidate_ref"]
        for operation in operations
        if operation["status"] == "completed"
    ]
    assert set(completed_refs) == {"branch-9", "branch-10"}


def test_run_parent_workflow_tick_routes_children_published_to_acceptance(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="CHILDREN_PUBLISHED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
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
            "branch": "smda/danny-66/child-001/candidate",
        },
        error_message=None,
    )
    integration = RecordingParentIntegration()

    result = run_parent_workflow_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        repo_context=RepoContextPacket(
            bootloader_path=tmp_path / "AGENTS.md",
            bootloader_text="",
            spec_locations=(),
            adr_locations=(),
            quality_gates=(),
        ),
        repo_root=tmp_path,
        ledger=ledger,
        execution=QueueExecutionAdapter([]),
        backlog=FakeBacklogAdapter(
            issues={
                "DANNY-66": FakeBacklogIssue(
                    id="DANNY-66",
                    title="Parent",
                    state="In Progress",
                )
            }
        ),
        integration=integration,
        integration_branch="smda/danny-66/integration",
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert "PARENT_QA_READY" in result.comment
    assert [operation.child_id for operation in integration.applied] == ["child-001"]


def test_run_parent_qa_review_tick_dispatches_from_parent_qa_ready(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="PARENT_QA_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="PASS",
                required_next_action="accept_parent",
            ),
            raw_result={
                "verdict": "PASS",
                "required_next_action": "accept_parent",
                "report": "Parent integration satisfies the approved spec.",
            },
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "FINAL_ACCEPT_READY" in result.comment
    request = execution.requests[0]
    assert request.attempt_id == "DANNY-66-PARENT_QA_REVIEWING-1"
    assert request.role == "parent_qa_reviewer"
    assert request.context_packet["graph_checksum"] == "sha256:graph"
    attempts = ledger.load_attempts()
    assert attempts[0]["target_kind"] == "parent"
    assert attempts[0]["target_id"] == "DANNY-66"
    assert attempts[0]["phase"] == "PARENT_QA_REVIEWING"
    assert attempts[0]["status"] == "succeeded"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.FINAL_ACCEPT_READY


def test_run_parent_qa_review_tick_routes_fail_to_remediation_planning(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
        ),
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="PARENT_QA_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="FAIL",
                required_next_action="plan_remediation",
            ),
            raw_result={
                "verdict": "FAIL",
                "required_next_action": "plan_remediation",
                "report": "Parent integration misses one acceptance criterion.",
            },
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert "REMEDIATION_PLANNING" in result.comment
    assert ledger.load_attempts()[0]["status"] == "succeeded"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.REMEDIATION_PLANNING


def test_run_parent_remediation_planning_tick_creates_remediation_child(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    ledger.record_child_issue_projection(
        parent_id="DANNY-66",
        node_id="child-001",
        issue_id="DANNY-66-C0",
    )
    ledger.record_role_attempt_request(
        attempt_id="DANNY-66-PARENT_QA_REVIEWING-1",
        target_kind="parent",
        target_id="DANNY-66",
        phase=ParentPhase.PARENT_QA_REVIEWING,
        idempotency_key="parent:DANNY-66:PARENT_QA_REVIEWING:1",
        request_json={"role": "parent_qa_reviewer"},
    )
    ledger.record_attempt_result(
        attempt_id="DANNY-66-PARENT_QA_REVIEWING-1",
        status="succeeded",
        result_json={
            "verdict": "FAIL",
            "required_next_action": "plan_remediation",
            "report": "Parent QA found a missing acceptance criterion.",
        },
        error_message=None,
    )
    backlog = RecordingPublication(
        issues={
            "DANNY-66": FakeBacklogIssue(
                id="DANNY-66",
                title="Parent",
                state="In Progress",
            ),
            "DANNY-66-C0": FakeBacklogIssue(
                id="DANNY-66-C0",
                title="Original child",
                state="Done",
                parent_id="DANNY-66",
            ),
        }
    )

    result = run_parent_remediation_planning_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )

    assert result.target_state == "In Progress"
    assert "CHILDREN_PUBLISHED" in result.comment
    graph = ledger.load_graph("DANNY-66")
    remediation = next(
        child
        for child in graph.children
        if child.node_id == "DANNY-66-remediation-001"
    )
    assert remediation.dependencies == ("child-001",)
    projections = ledger.load_child_issue_projections("DANNY-66")
    remediation_issue_id = projections["DANNY-66-remediation-001"]
    remediation_issue = backlog.fetch_issue(remediation_issue_id)
    assert (remediation_issue_id, "Todo") in backlog.states
    assert remediation_issue.parent_id == "DANNY-66"
    assert remediation_issue.labels == frozenset({"agent"})
    assert "Execution: smda-child" in remediation_issue.body
    assert "Node id: DANNY-66-remediation-001" in remediation_issue.body
    assert "Parent QA found a missing acceptance criterion." in remediation_issue.body
    assert backlog.query_blocked_by(remediation_issue_id) == ["DANNY-66-C0"]
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.CHILDREN_PUBLISHED


def test_run_parent_remediation_planning_tick_human_reviews_when_bounds_exhausted(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001"),
            _complete_graph_child(
                node_id="remediation-001",
                title="Remediate parent QA failure",
                body="Fix parent QA feedback.",
                acceptance_criteria=["parent QA feedback is resolved"],
                dependencies=["child-001"],
            ),
        ],
    )
    backlog = FakeBacklogAdapter(
        issues={
            "DANNY-66": FakeBacklogIssue(
                id="DANNY-66",
                title="Parent",
                state="In Progress",
            )
        }
    )

    result = run_parent_remediation_planning_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        backlog=backlog,
        qa_bounds=QaBounds(
            max_same_feedback_fingerprint=10,
            max_total_remediation_children=1,
            max_parent_qa_cycles=10,
        ),
    )

    assert result.target_state == "Human Review"
    assert "remediation bounds exhausted" in result.comment
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.HUMAN_REVIEW_REQUIRED


def test_run_parent_workflow_tick_threads_qa_bounds_to_remediation(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(
                node_id="remediation-001",
                title="Remediate parent QA failure",
                body="Fix parent QA feedback.",
                acceptance_criteria=["parent QA feedback is resolved"],
            )
        ],
    )

    result = run_parent_workflow_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        repo_context=RepoContextPacket(
            bootloader_path=tmp_path / "AGENTS.md",
            bootloader_text="",
            spec_locations=(),
            adr_locations=(),
            quality_gates=(),
        ),
        repo_root=tmp_path,
        ledger=ledger,
        execution=QueueExecutionAdapter([]),
        backlog=FakeBacklogAdapter(
            issues={
                "DANNY-66": FakeBacklogIssue(
                    id="DANNY-66",
                    title="Parent",
                    state="In Progress",
                )
            }
        ),
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
        qa_bounds=QaBounds(
            max_same_feedback_fingerprint=10,
            max_total_remediation_children=1,
            max_parent_qa_cycles=10,
        ),
    )

    assert result.target_state == "Human Review"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.HUMAN_REVIEW_REQUIRED


def test_run_parent_remediation_planning_tick_human_reviews_repeated_feedback(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    for attempt_number in (1, 2):
        attempt_id = f"DANNY-66-PARENT_QA_REVIEWING-{attempt_number}"
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind="parent",
            target_id="DANNY-66",
            phase=ParentPhase.PARENT_QA_REVIEWING,
            idempotency_key=f"parent:DANNY-66:PARENT_QA_REVIEWING:{attempt_number}",
            request_json={"role": "parent_qa_reviewer"},
        )
        ledger.record_attempt_result(
            attempt_id=attempt_id,
            status="succeeded",
            result_json={
                "verdict": "FAIL",
                "required_next_action": "plan_remediation",
                "report": "Same parent QA failure.",
            },
            error_message=None,
        )

    result = run_parent_remediation_planning_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        backlog=FakeBacklogAdapter(
            issues={
                "DANNY-66": FakeBacklogIssue(
                    id="DANNY-66",
                    title="Parent",
                    state="In Progress",
                )
            }
        ),
        qa_bounds=QaBounds(
            max_same_feedback_fingerprint=1,
            max_total_remediation_children=10,
            max_parent_qa_cycles=10,
        ),
    )

    assert result.target_state == "Human Review"
    assert "remediation bounds exhausted" in result.comment
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.HUMAN_REVIEW_REQUIRED


def test_run_parent_remediation_planning_tick_human_reviews_qa_cycle_limit(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[
            _complete_graph_child(node_id="child-001")
        ],
    )
    for attempt_number in (1, 2):
        attempt_id = f"DANNY-66-PARENT_QA_REVIEWING-{attempt_number}"
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind="parent",
            target_id="DANNY-66",
            phase=ParentPhase.PARENT_QA_REVIEWING,
            idempotency_key=f"parent:DANNY-66:PARENT_QA_REVIEWING:{attempt_number}",
            request_json={"role": "parent_qa_reviewer"},
        )
        ledger.record_attempt_result(
            attempt_id=attempt_id,
            status="succeeded",
            result_json={
                "verdict": "FAIL",
                "required_next_action": "plan_remediation",
                "report": f"Parent QA failure {attempt_number}.",
            },
            error_message=None,
        )

    result = run_parent_remediation_planning_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        backlog=FakeBacklogAdapter(
            issues={
                "DANNY-66": FakeBacklogIssue(
                    id="DANNY-66",
                    title="Parent",
                    state="In Progress",
                )
            }
        ),
        qa_bounds=QaBounds(
            max_same_feedback_fingerprint=10,
            max_total_remediation_children=10,
            max_parent_qa_cycles=1,
        ),
    )

    assert result.target_state == "Human Review"
    assert "remediation bounds exhausted" in result.comment
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.HUMAN_REVIEW_REQUIRED


def test_run_parent_final_accept_tick_records_tracker_effects(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="FINAL_ACCEPT_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_role_attempt_request(
        attempt_id="DANNY-66-PARENT_QA_REVIEWING-1",
        target_kind="parent",
        target_id="DANNY-66",
        phase=ParentPhase.PARENT_QA_REVIEWING,
        idempotency_key="parent:DANNY-66:PARENT_QA_REVIEWING:1",
        request_json={"role": "parent_qa_reviewer"},
    )
    ledger.record_attempt_result(
        attempt_id="DANNY-66-PARENT_QA_REVIEWING-1",
        status="succeeded",
        result_json={
            "verdict": "PASS",
            "required_next_action": "accept_parent",
            "report": "Parent QA passed all checks.",
        },
        error_message=None,
    )

    result = run_parent_final_accept_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
    )

    assert result.target_state == "Done"
    assert "FINAL_ACCEPTED" in result.comment
    effects = ledger.load_pending_tracker_effects()
    assert [(effect["effect_type"], effect["target_id"]) for effect in effects] == [
        ("comment", "DANNY-66"),
        ("set_state", "DANNY-66"),
    ]
    assert "Parent QA passed all checks." in effects[0]["payload"]["body"]
    assert effects[1]["payload"] == {"state": "Done"}
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.FINAL_ACCEPTED


def test_final_accept_rolls_back_phase_and_both_effects_on_effect_conflict(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="FINAL_ACCEPT_READY",
        spec_path="docs/spec.md",
        spec_checksum="sha256:spec",
        approval_evidence="approved",
    )
    ledger.record_tracker_effect(
        effect_id="existing-final-state",
        idempotency_key="final-accept-state:DANNY-66",
        effect_type="set_state",
        target_id="DANNY-66",
        payload={"state": "In Progress"},
    )

    with pytest.raises(sqlite3.IntegrityError):
        run_parent_final_accept_tick(
            issue=BacklogIssue(
                id="DANNY-66",
                title="Parent",
                state="In Progress",
                body="Execution: smda\n",
            ),
            ledger=ledger,
        )

    assert ledger.load_parent_run("DANNY-66")["phase"] == "FINAL_ACCEPT_READY"
    assert [effect["effect_id"] for effect in ledger.load_tracker_effects()] == [
        "existing-final-state"
    ]


def test_resolve_parent_base_uses_roadmap_branch_for_members(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_roadmap_member_projection(
        roadmap_id="DANNY-100",
        node_id="parent-001",
        issue_id="DANNY-101",
    )

    assert (
        resolve_parent_base(ledger, "DANNY-101", standalone_base="main")
        == "smda/DANNY-100/integration"
    )
    assert resolve_parent_base(ledger, "DANNY-66", standalone_base="main") == "main"


def test_run_parent_final_accept_tick_lands_parent_to_resolved_base(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="FINAL_ACCEPT_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    integration = RecordingParentIntegration()

    result = run_parent_final_accept_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        integration=integration,
        integration_branch=None,
        standalone_base="main",
    )

    assert result.target_state == "Done"
    assert [(op.parent_ref, op.base_branch) for op in integration.landed] == [
        ("smda/danny-66/integration", "main")
    ]
    assert ledger.load_parent_land_operations()[0]["status"] == "completed"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.FINAL_ACCEPTED


def test_run_parent_final_accept_tick_routes_conflict_to_rebasing(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="FINAL_ACCEPT_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    integration = RecordingParentIntegration(conflicted_paths=("shared.txt",))

    result = run_parent_final_accept_tick(
        issue=BacklogIssue(
            id="DANNY-66",
            title="Parent",
            state="In Progress",
            body="Execution: smda\n",
        ),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-66/integration",
        standalone_base="main",
    )

    # Probe ran, no land happened, parent routed to the rebase phase.
    assert integration.probes == [("smda/DANNY-66/integration", "main")]
    assert integration.landed == []
    assert ledger.load_parent_land_operations() == []
    assert (
        ledger.load_parent_runs()[0]["phase"]
        == ParentPhase.LANDING_CONFLICT_REBASING.value
    )
    assert result.target_state == "In Progress"


def _seed_rebasing_parent(ledger: PhaseLedger, *, qa_fail_attempts: int = 0) -> None:
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="LANDING_CONFLICT_REBASING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    for index in range(qa_fail_attempts):
        attempt_id = f"DANNY-66-PARENT_QA_REVIEWING-{index}"
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind="parent",
            target_id="DANNY-66",
            phase=ParentPhase.PARENT_QA_REVIEWING.value,
            idempotency_key=f"parent:DANNY-66:PARENT_QA_REVIEWING:{index}",
            request_json={},
        )
        ledger.record_attempt_result(
            attempt_id=attempt_id,
            status="succeeded",
            result_json={"verdict": "PASS", "required_next_action": "accept_parent"},
            error_message=None,
        )


def _rebasing_issue() -> BacklogIssue:
    return BacklogIssue(
        id="DANNY-66", title="Parent", state="In Progress", body="Execution: smda\n"
    )


def test_run_landing_conflict_rebase_tick_rebases_and_requeues_qa(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _seed_rebasing_parent(ledger, qa_fail_attempts=1)
    integration = RecordingParentIntegration(conflicted_paths=("shared.txt",))

    result = run_landing_conflict_rebase_tick(
        issue=_rebasing_issue(),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-66/integration",
        standalone_base="main",
        qa_bounds=QaBounds(
            max_same_feedback_fingerprint=3,
            max_total_remediation_children=3,
            max_parent_qa_cycles=3,
        ),
    )

    assert integration.rebased == [("smda/DANNY-66/integration", "main")]
    assert (
        ledger.load_parent_runs()[0]["phase"] == ParentPhase.PARENT_QA_READY.value
    )
    assert result.target_state == "In Progress"


def test_run_landing_conflict_rebase_tick_escalates_after_cap(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    # Already past the cap (max_parent_qa_cycles=2, 3 QA attempts recorded).
    _seed_rebasing_parent(ledger, qa_fail_attempts=3)
    integration = RecordingParentIntegration(conflicted_paths=("shared.txt",))

    run_landing_conflict_rebase_tick(
        issue=_rebasing_issue(),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-66/integration",
        standalone_base="main",
        qa_bounds=QaBounds(
            max_same_feedback_fingerprint=3,
            max_total_remediation_children=3,
            max_parent_qa_cycles=2,
        ),
    )

    assert integration.rebased == []
    assert (
        ledger.load_parent_runs()[0]["phase"]
        == ParentPhase.HUMAN_REVIEW_REQUIRED.value
    )


def _phase_of(ledger: PhaseLedger, parent_id: str) -> str:
    return next(
        run["phase"]
        for run in ledger.load_parent_runs()
        if run["parent_id"] == parent_id
    )


def _seed_published_roadmap(ledger: PhaseLedger, *, accepted_members: int) -> None:
    ledger.create_parent_run(
        parent_id="DANNY-100",
        initial_phase="ROADMAP_PUBLISHED",
        spec_path="docs/superpowers/specs/roadmap.md",
        spec_checksum="sha256:roadmap",
        approval_evidence="DANNY-100 approval",
    )
    members = [("parent-001", "DANNY-100-C1"), ("parent-002", "DANNY-100-C2")]
    for node_id, issue_id in members:
        ledger.record_roadmap_member_projection(
            roadmap_id="DANNY-100", node_id=node_id, issue_id=issue_id
        )
    for _, issue_id in members[:accepted_members]:
        ledger.create_parent_run(
            parent_id=issue_id,
            initial_phase="FINAL_ACCEPTED",
            spec_path="docs/spec.md",
            spec_checksum="sha256:m",
            approval_evidence="member approval",
        )


def _roadmap_issue() -> BacklogIssue:
    return BacklogIssue(
        id="DANNY-100", title="Roadmap", state="In Progress", body="Execution: smda-roadmap\n"
    )


def test_run_roadmap_completion_tick_waits_until_all_members_accepted(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _seed_published_roadmap(ledger, accepted_members=1)
    integration = RecordingParentIntegration()

    result = run_roadmap_completion_tick(
        issue=_roadmap_issue(),
        ledger=ledger,
        integration=integration,
        standalone_base="main",
    )

    assert integration.landed == []
    assert (
        _phase_of(ledger, "DANNY-100")
        == RoadmapPhase.ROADMAP_PUBLISHED.value
    )
    assert result.target_state == "In Progress"


def test_run_roadmap_completion_tick_lands_roadmap_to_main_once(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _seed_published_roadmap(ledger, accepted_members=2)
    integration = RecordingParentIntegration()

    first = run_roadmap_completion_tick(
        issue=_roadmap_issue(),
        ledger=ledger,
        integration=integration,
        standalone_base="main",
    )
    second = run_roadmap_completion_tick(
        issue=_roadmap_issue(),
        ledger=ledger,
        integration=integration,
        standalone_base="main",
    )

    assert [(op.parent_ref, op.base_branch) for op in integration.landed] == [
        ("smda/DANNY-100/integration", "main")
    ]
    assert integration.deleted == ["smda/DANNY-100/integration"]
    assert (
        _phase_of(ledger, "DANNY-100")
        == RoadmapPhase.ROADMAP_COMPLETED.value
    )
    assert first.target_state == "Done"
    assert second.target_state in {"Done", "In Progress"}


def test_run_parent_graph_fixing_tick_revises_graph_and_re_reviews(tmp_path: Path):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\nstatus: approved\napproved_at: 2026-06-15\napproved_by: human\n"
        "approval_evidence: DANNY-66 approval\n---\n# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Source: docs/superpowers/specs/approved.md\nExecution: smda\n",
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_FIXING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:old-graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    # Prior graph spec review failure provides the findings the fixer must act on.
    ledger.record_role_attempt_request(
        attempt_id="DANNY-66-GRAPH_SPEC_REVIEWING-1",
        target_kind="parent",
        target_id="DANNY-66",
        phase="GRAPH_SPEC_REVIEWING",
        idempotency_key="parent:DANNY-66:GRAPH_SPEC_REVIEWING:1",
        request_json={},
    )
    ledger.record_attempt_result(
        attempt_id="DANNY-66-GRAPH_SPEC_REVIEWING-1",
        status="succeeded",
        result_json={
            "verdict": "FAIL",
            "required_next_action": "request_human_review",
            "report": "child-001 omits requirement R3",
        },
        error_message=None,
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_graph_review"
            ),
            raw_result={
                "verdict": "DONE",
                "required_next_action": "submit_for_graph_review",
                "dependency_edges": [],
                "children": [_complete_graph_child(node_id="child-001")],
            },
            branch="smda/danny-66/graph-fixing",
            schema_id="smda.graph-decomposer-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "In Progress"
    assert ledger.load_parent_runs()[0]["phase"] == "GRAPH_SPEC_REVIEWING"
    request = execution.requests[0]
    assert request.role == "graph_fixer"
    assert "omits requirement R3" in request.context_packet["review_findings"]


def test_graph_review_fail_escalates_to_human_after_fix_budget(tmp_path: Path):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\nstatus: approved\napproved_at: 2026-06-15\napproved_by: human\n"
        "approval_evidence: DANNY-66 approval\n---\n# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Source: docs/superpowers/specs/approved.md\nExecution: smda\n",
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    # Two prior graph fix cycles already spent.
    for n in (1, 2):
        ledger.record_role_attempt_request(
            attempt_id=f"DANNY-66-GRAPH_FIXING-{n}",
            target_kind="parent",
            target_id="DANNY-66",
            phase="GRAPH_FIXING",
            idempotency_key=f"parent:DANNY-66:GRAPH_FIXING:{n}",
            request_json={},
        )
        ledger.record_attempt_result(
            attempt_id=f"DANNY-66-GRAPH_FIXING-{n}",
            status="succeeded",
            result_json={"verdict": "DONE", "required_next_action": "submit_for_graph_review"},
            error_message=None,
        )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="FAIL", required_next_action="request_human_review"
            ),
            raw_result={
                "verdict": "FAIL",
                "required_next_action": "request_human_review",
                "report": "still failing",
            },
            branch="smda/danny-66/graph-spec-reviewing",
            schema_id="smda.review-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert result.target_state == "Human Review"
    assert ledger.load_parent_runs()[0]["phase"] == "HUMAN_REVIEW_REQUIRED"


def test_run_child_candidate_tick_records_child_tracker_lifecycle(tmp_path: Path):
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
        id="DANNY-66-C1",
        title="Implement runtime wiring",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:graph",
                "Node id: child-001",
                "Acceptance criteria: scheduler tests pass",
                "Dispatch through Sandcastle.",
            ]
        ),
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_spec_review"
            ),
        )
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _record_single_child_graph(ledger)

    run_child_candidate_tick(
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

    effects = ledger.load_pending_tracker_effects()
    states = [
        (e["target_id"], e["payload"]["state"])
        for e in effects
        if e["effect_type"] == "set_state"
    ]
    # implementer DONE -> SPEC_REVIEWING -> active -> In Progress
    assert ("DANNY-66-C1", "In Progress") in states


def test_run_child_candidate_tick_rejects_stale_graph_checksum(tmp_path: Path):
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
        id="DANNY-66-C1",
        title="Implement",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:stale",
                "Node id: child-001",
                "Acceptance criteria: scheduler tests pass",
            ]
        ),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:current",
        children=[_complete_graph_child(node_id="child-001")],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_spec_review"
            ),
        )
    )

    with pytest.raises(GraphError, match="checksum"):
        run_child_candidate_tick(
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


def test_child_lifecycle_comment_includes_latest_report(tmp_path: Path):
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
        id="DANNY-66-C1",
        title="Implement",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:graph",
                "Node id: child-001",
                "Acceptance criteria: scheduler tests pass",
            ]
        ),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _record_single_child_graph(ledger)
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE", required_next_action="submit_for_spec_review"
            ),
            raw_result={
                "verdict": "DONE",
                "required_next_action": "submit_for_spec_review",
                "report": "Implemented the parser with edge-case handling.",
            },
        )
    )

    run_child_candidate_tick(
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

    comments = [
        e["payload"]["body"]
        for e in ledger.load_pending_tracker_effects()
        if e["effect_type"] == "comment"
    ]
    assert any("edge-case handling" in body for body in comments)


def test_graph_spec_review_done_with_concerns_proceeds_and_surfaces_report(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\nstatus: approved\napproved_at: 2026-06-15\napproved_by: human\n"
        "approval_evidence: DANNY-66 approval\n---\n# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Source: docs/superpowers/specs/approved.md\nExecution: smda\n",
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE_WITH_CONCERNS",
                required_next_action="submit_for_graph_execution_review",
            ),
            raw_result={
                "verdict": "DONE_WITH_CONCERNS",
                "required_next_action": "submit_for_graph_execution_review",
                "report": "child-002 naming is slightly off; minor, not blocking.",
            },
            branch="smda/danny-66/graph-spec-reviewing",
            schema_id="smda.review-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
    )

    assert ledger.load_parent_runs()[0]["phase"] == "GRAPH_EXECUTION_REVIEWING"
    assert "passed with concerns" in result.comment
    assert "child-002 naming" in result.comment
    assert not any(
        effect["effect_type"] == "create_child"
        for effect in ledger.load_pending_tracker_effects()
    )


def test_graph_spec_review_done_with_concerns_records_follow_up_when_enabled(
    tmp_path: Path,
):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    spec.parent.mkdir(parents=True)
    spec_text = (
        "---\nstatus: approved\napproved_at: 2026-06-15\napproved_by: human\n"
        "approval_evidence: DANNY-66 approval\n---\n# Approved parent spec\n"
    )
    spec.write_text(spec_text, encoding="utf-8")
    spec_checksum = "sha256:" + __import__("hashlib").sha256(
        spec_text.encode("utf-8")
    ).hexdigest()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="In Progress",
        body="Source: docs/superpowers/specs/approved.md\nExecution: smda\n",
    )
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    _record_graph(
        ledger,
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[_complete_graph_child(node_id="child-001")],
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE_WITH_CONCERNS",
                required_next_action="submit_for_graph_execution_review",
            ),
            raw_result={
                "verdict": "DONE_WITH_CONCERNS",
                "required_next_action": "submit_for_graph_execution_review",
                "report": "child-002 naming is slightly off; minor, not blocking.",
            },
            branch="smda/danny-66/graph-spec-reviewing",
            schema_id="smda.review-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = _run_parent_role_workflow_tick(
        issue=issue,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        owner="daemon-1",
        create_follow_up_issues_for_concerns=True,
        concern_followup_labels=frozenset({"smda-follow-up"}),
    )

    effects = [
        effect
        for effect in ledger.load_pending_tracker_effects()
        if effect["effect_type"] == "create_child"
    ]
    assert result.target_state == "In Progress"
    assert len(effects) == 1
    assert effects[0]["target_id"] == "DANNY-66"
    assert effects[0]["payload"]["parent_id"] == "DANNY-66"
    assert effects[0]["payload"]["title"] == (
        "Follow up: graph spec review concern for DANNY-66"
    )
    assert effects[0]["payload"]["labels"] == ["smda-follow-up"]
    assert "Execution: manual" in effects[0]["payload"]["body"]
    assert "child-002 naming" in effects[0]["payload"]["body"]
