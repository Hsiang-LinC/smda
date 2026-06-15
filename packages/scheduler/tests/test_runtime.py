from pathlib import Path

import pytest
from fakes import FakeBacklogAdapter, FakeBacklogIssue

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import classify_candidate
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.role_attempts import AgentSelection, ChildTaskContext
from smda_scheduler.runtime import (
    RoleExecutionAdapter,
    run_parent_graph_decomposition_tick,
    run_parent_graph_fixing_tick,
    run_parent_graph_execution_review_tick,
    run_parent_child_publication_tick,
    run_parent_child_acceptance_tick,
    run_parent_qa_review_tick,
    run_parent_remediation_planning_tick,
    run_parent_final_accept_tick,
    run_parent_graph_spec_review_tick,
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
    RoleResult,
    WorkflowGraph,
)
from smda_scheduler.parent_acceptance import ChildAcceptOperation, ParentIntegration


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


class RecordingParentIntegration(ParentIntegration):
    def __init__(self) -> None:
        self.applied: list[ChildAcceptOperation] = []
        self.accepted_refs: set[str] = set()

    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool:
        return operation.candidate_ref in self.accepted_refs

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None:
        self.applied.append(operation)
        self.accepted_refs.add(operation.candidate_ref)


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


def _graph_decomposition_outcome(
    children: list[dict[str, object]],
    *,
    dependency_edges: list[dict[str, object]] | None = None,
) -> AttemptOutcome:
    raw_result: dict[str, object] = {
        "verdict": "DONE",
        "required_next_action": "submit_for_graph_review",
        "children": children,
    }
    if dependency_edges is not None:
        raw_result["dependency_edges"] = dependency_edges
    return AttemptOutcome(
        status="succeeded",
        role_result=RoleResult(
            verdict="DONE",
            required_next_action="submit_for_graph_review",
        ),
        raw_result=raw_result,
    )


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


def test_run_child_candidate_tick_hydrates_static_context_from_issue_body(
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
        title="Implement runtime wiring",
        state="Todo",
        body="\n".join(
            [
                "Execution: smda-child",
                "Parent issue: DANNY-66",
                "Graph checksum: sha256:graph",
                "Node id: child-001",
                "Source: docs/superpowers/specs/approved.md",
                "In scope: scheduler runtime",
                "Out of scope: consumer repo cleanup",
                "Touched files: packages/scheduler/src/smda_scheduler/runtime.py",
                "Touched modules: smda_scheduler.runtime",
                "Touched contracts: smda.child-role-context.v1",
                "Touched docs: docs/product-spec.md",
                "Touched tests: packages/scheduler/tests/test_runtime.py",
                "Acceptance criteria: scheduler tests pass",
                "Verification required: uv run pytest packages/scheduler/tests/test_runtime.py -q",
                "Verification smoke: uv run pytest packages/scheduler/tests -q",
                "Risk level: medium",
                "Dependency reasons: child-000 -> child-001 (code_dependency, blocks_dispatch=True): child-001 imports the accepted runtime API.",
                "Required artifacts: accepted_commit",
                "",
                "Dispatch through Sandcastle.",
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

    run_child_candidate_tick(
        issue=issue,
        decision=classify_candidate(issue, issue_entry_policy="explicit-only"),
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    packet = execution.requests[0].context_packet
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
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )
    )

    state = run_child_candidate_tick(
        issue=issue,
        decision=decision,
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    assert state.children["child-001"].phase == ChildPhase.SPEC_REVIEWING
    request = execution.requests[0]
    assert request.context_packet["parent_issue_id"] == "DANNY-66"
    assert request.context_packet["child_id"] == "child-001"
    assert request.context_packet["child_title"] == "Implement child packet"
    assert request.context_packet["acceptance_criteria"] == [
        "validates routed child dispatch"
    ]


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
    assert ledger.load_parent_runs()[0]["phase"] == "SPEC_INTAKE"


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
    assert ledger.load_parent_runs()[0]["phase"] == "SPEC_INTAKE"


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

    result = run_parent_graph_decomposition_tick(
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
    assert graph["graph_checksum"].startswith("sha256:")
    assert graph["children"] == [
        _complete_graph_child(node_id="child-001"),
        _complete_graph_child(
            node_id="child-002",
            title="Wire setup skill",
            body="Make setup emit config only.",
            acceptance_criteria=["setup emits config only"],
            dependencies=["child-001"],
        ),
    ]


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
        run_parent_graph_decomposition_tick(
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
        run_parent_graph_decomposition_tick(
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
        run_parent_graph_decomposition_tick(
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
        run_parent_graph_decomposition_tick(
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
        run_parent_graph_decomposition_tick(
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
        run_parent_graph_decomposition_tick(
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
        run_parent_graph_decomposition_tick(
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

    result = run_parent_graph_decomposition_tick(
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
    assert graph["dependency_edges"] == [edge]
    assert graph["children"][1]["dependencies"] == ["child-001"]


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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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

    result = run_parent_graph_spec_review_tick(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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

    result = run_parent_graph_spec_review_tick(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="GRAPH_EXECUTION_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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

    result = run_parent_graph_execution_review_tick(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="CHILD_PUBLICATION_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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


def test_child_publication_body_contains_static_context_packet(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="CHILD_PUBLICATION_READY",
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
    ledger.record_graph(
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
        "child-001": "DANNY-66-C1",
        "child-002": "DANNY-66-C2",
    }
    assert backlog.fetch_issue("DANNY-66-C1").labels == frozenset({"agent"})
    assert backlog.query_blocked_by("DANNY-66-C2") == ["DANNY-66-C1"]


def test_run_parent_child_acceptance_tick_integrates_quality_passed_children(
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
            "branch": "smda/danny-66/child-001/quality-reviewing",
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
        integration_branch="smda/danny-66/integration",
    )

    assert result.target_state == "In Progress"
    assert "PARENT_QA_READY" in result.comment
    assert [operation.child_id for operation in integration.applied] == ["child-001"]
    operation = integration.applied[0]
    assert operation.parent_id == "DANNY-66"
    assert operation.candidate_ref == "smda/danny-66/child-001/quality-reviewing"
    assert operation.integration_branch == "smda/danny-66/integration"
    assert ledger.load_parent_accept_operations()[0]["status"] == "completed"
    assert ledger.load_parent_runs()[0]["phase"] == "PARENT_QA_READY"


def test_run_parent_workflow_tick_routes_children_published_to_acceptance(
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
            "branch": "smda/danny-66/child-001/quality-reviewing",
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="PARENT_QA_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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

    result = run_parent_qa_review_tick(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="PARENT_QA_READY",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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

    result = run_parent_qa_review_tick(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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
    backlog = FakeBacklogAdapter(
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
    assert graph["children"][1]["node_id"] == "remediation-001"
    assert graph["children"][1]["dependencies"] == ["child-001"]
    projections = ledger.load_child_issue_projections("DANNY-66")
    remediation_issue_id = projections["remediation-001"]
    remediation_issue = backlog.fetch_issue(remediation_issue_id)
    assert remediation_issue.parent_id == "DANNY-66"
    assert remediation_issue.labels == frozenset({"agent"})
    assert "Execution: smda-child" in remediation_issue.body
    assert "Node id: remediation-001" in remediation_issue.body
    assert "Parent QA found a missing acceptance criterion." in remediation_issue.body
    assert backlog.query_blocked_by(remediation_issue_id) == ["DANNY-66-C0"]
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.CHILDREN_PUBLISHED


def test_run_parent_remediation_planning_tick_human_reviews_when_bounds_exhausted(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="REMEDIATION_PLANNING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:spec",
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="FINAL_ACCEPT_READY",
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="GRAPH_FIXING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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
                "children": [_complete_graph_child(node_id="child-001")],
            },
            branch="smda/danny-66/graph-fixing",
            schema_id="smda.graph-decomposer-result.v1",
            schema_package_version="0.1.0",
        )
    )

    result = run_parent_graph_fixing_tick(
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
    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="GRAPH_SPEC_REVIEWING",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum=spec_checksum,
        approval_evidence="DANNY-66 approval",
    )
    ledger.record_graph(
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

    result = run_parent_graph_spec_review_tick(
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
    ledger.record_graph(
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
