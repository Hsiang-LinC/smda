from pathlib import Path

from helpers import write_minimal_config

from smda_scheduler.backlog import BacklogIssue, BacklogPage
from smda_scheduler.config import derive_workspace_paths, load_config
from smda_scheduler.git_integration import ConflictProbeResult
from smda_scheduler.parent_acceptance import (
    ChildAcceptOperation,
    ParentLandOperation,
    ParentIntegration,
)
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.runtime_factory import build_configured_workspace_tick
from smda_scheduler.scheduling import AttemptOutcome, ChildRunState, SchedulerState
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.workflow import ChildPhase, ParentPhase, RoadmapPhase, RoleResult


class RecordingBacklog:
    def __init__(self, issue: BacklogIssue) -> None:
        self.issue = issue
        self.created_children: list[BacklogIssue] = []
        self.blocking_links: list[tuple[str, str]] = []
        self.list_calls: list[dict] = []
        self.comments: list[tuple[str, str]] = []
        self.states: list[tuple[str, str]] = []

    def list_issues(
        self,
        *,
        state: str,
        label: str,
        parent_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> BacklogPage:
        self.list_calls.append(
            {
                "state": state,
                "label": label,
                "parent_id": parent_id,
                "limit": limit,
                "cursor": cursor,
            }
        )
        return BacklogPage(issues=(self.issue,))

    def comment(self, issue_id: str, body: str) -> None:
        self.comments.append((issue_id, body))

    def set_coarse_state(self, issue_id: str, state: str) -> None:
        self.states.append((issue_id, state))

    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ) -> BacklogIssue:
        issue = BacklogIssue(
            id=f"{parent_id}-C{len(self.created_children) + 1}",
            title=title,
            state="Todo",
            body=body,
            parent_id=parent_id,
            labels=frozenset(labels or ()),
        )
        self.created_children.append(issue)
        return issue

    def link_blocking(self, *, blocker_id: str, blocked_id: str) -> None:
        self.blocking_links.append((blocker_id, blocked_id))


class RecordingExecution:
    def __init__(self, outcomes: list[AttemptOutcome] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.requests: list[RoleAttemptRequest] = []

    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome:
        self.requests.append(request)
        if not self.outcomes:
            raise AssertionError(
                f"unexpected execution attempt for role {request.role}"
            )
        return self.outcomes.pop(0)


class RecordingParentIntegration(ParentIntegration):
    def __init__(self) -> None:
        self.applied: list[ChildAcceptOperation] = []
        self.landed: list[ParentLandOperation] = []

    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool:
        return False

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None:
        self.applied.append(operation)

    def has_landed_parent_ref(self, operation: ParentLandOperation) -> bool:
        return False

    def land_parent_to_base(self, operation: ParentLandOperation) -> None:
        self.landed.append(operation)

    def probe_conflict(self, *, head: str, base: str) -> ConflictProbeResult:
        return ConflictProbeResult(clean=True)

    def rebase_onto_base(self, *, head: str, base: str) -> None:
        return None

    def ensure_branch(self, name: str, *, start_point: str) -> None:
        return None

    def branch_exists(self, name: str) -> bool:
        return False

    def delete_branch(self, name: str) -> None:
        return None


def _complete_graph_child(**overrides: object) -> dict[str, object]:
    child: dict[str, object] = {
        "node_id": "child-001",
        "title": "Migrate trading-advisor consumer wiring",
        "body": "Verify trading-advisor can run through the external SMDA product.",
        "in_scope": ["trading-advisor SMDA consumer wiring"],
        "out_of_scope": ["live Linear writes"],
        "touched_surfaces": {
            "files": ["smda.config.json"],
            "modules": ["smda_scheduler.runtime_factory"],
            "contracts": ["smda.graph-decomposer-result.v1"],
            "docs": ["docs/harness/operating-process.md"],
            "tests": ["packages/scheduler/tests/test_runtime_factory.py"],
        },
        "acceptance_criteria": ["consumer dry-run reaches final accept"],
        "verification": {
            "required": [
                "uv run pytest packages/scheduler/tests/test_runtime_factory.py -q"
            ],
            "smoke": ["uv run pytest packages/scheduler/tests -q"],
        },
        "risk_level": "medium",
        "dependencies": [],
    }
    child.update(overrides)
    return child


def _approved_spec(repo_root: Path) -> None:
    (repo_root / "AGENTS.md").write_text("# Trading Advisor Boot\n", encoding="utf-8")
    (repo_root / "docs" / "roadmap").mkdir(parents=True)
    (repo_root / "docs" / "adr").mkdir(parents=True)
    spec = repo_root / "docs" / "superpowers" / "specs" / "approved.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-15\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-66 approval\n"
        "---\n"
        "# Approved trading-advisor SMDA migration spec\n",
        encoding="utf-8",
    )


def test_build_configured_workspace_tick_routes_parent_intake_from_config(
    tmp_path: Path,
):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# Boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
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
        labels=frozenset({"agent"}),
    )
    backlog = RecordingBacklog(issue)

    tick = build_configured_workspace_tick(
        config_path=config_path,
        repo_root=tmp_path,
        backlog=backlog,
        execution=RecordingExecution(),
        scan_state="Todo",
        scan_label="agent",
        owner="daemon-1",
    )

    result = tick()

    assert result.status == "dispatched"
    assert backlog.list_calls == [
        {
            "state": "Todo",
            "label": "agent",
            "parent_id": None,
            "limit": 50,
            "cursor": None,
        }
    ]
    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    ledger = PhaseLedger(workspace.ledger_path)
    parent_run = ledger.load_parent_runs()[0]
    assert parent_run["parent_id"] == "DANNY-66"
    assert parent_run["phase"] == "SPEC_FINALIZED"


def test_build_configured_workspace_tick_routes_roadmap_to_publish_members(
    tmp_path: Path,
):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# Boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    spec = tmp_path / "docs" / "superpowers" / "specs" / "roadmap.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: approved\n"
        "approved_at: 2026-06-16\n"
        "approved_by: human\n"
        "approval_evidence: DANNY-100 approval\n"
        "---\n"
        "# Approved roadmap\n",
        encoding="utf-8",
    )
    issue = BacklogIssue(
        id="DANNY-100",
        title="Roadmap",
        state="Todo",
        body=(
            "Source: docs/superpowers/specs/roadmap.md\n"
            "Execution: smda-roadmap\n"
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
                    required_next_action="publish_roadmap_parents",
                ),
                raw_result={
                    "verdict": "DONE",
                    "required_next_action": "publish_roadmap_parents",
                    "parents": [
                        {
                            "node_id": "parent-001",
                            "title": "Introduce member store",
                            "body": "Persist roadmap member parent specs.",
                            "risk_level": "medium",
                            "dependencies": [],
                        },
                        {
                            "node_id": "parent-002",
                            "title": "Publish member parents",
                            "body": "Create parent issues from roadmap specs.",
                            "risk_level": "high",
                            "dependencies": ["parent-001"],
                        },
                    ],
                    "roadmap_edges": [
                        {
                            "from": "parent-001",
                            "to": "parent-002",
                            "type": "code_dependency",
                            "blocks_dispatch": True,
                            "reason": "parent-002 reads parent-001 output.",
                        }
                    ],
                },
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

    assert tick().status == "dispatched"
    assert tick().status == "dispatched"
    assert tick().status == "dispatched"

    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    ledger = PhaseLedger(workspace.ledger_path)
    assert ledger.load_parent_runs()[0]["phase"] == RoadmapPhase.ROADMAP_PUBLISHED
    assert [request.role for request in execution.requests] == ["roadmap_decomposer"]
    assert [issue.title for issue in backlog.created_children] == [
        "Introduce member store",
        "Publish member parents",
    ]
    assert "Execution: smda" in backlog.created_children[0].body
    assert backlog.blocking_links == [("DANNY-100-C1", "DANNY-100-C2")]
    assert ledger.load_roadmap_blockers("DANNY-100-C2") == ("DANNY-100-C1",)


def test_build_configured_workspace_tick_routes_smda_task_without_parent_graph(
    tmp_path: Path,
):
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
        id="DANNY-201",
        title="Fix focused bug",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Acceptance criteria: focused bug is fixed\n"
            "Verification: uv run pytest packages/scheduler/tests/test_runtime_factory.py -q\n"
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
    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    ledger = PhaseLedger(workspace.ledger_path)
    state = ledger.load_scheduler_state()
    assert state.children["DANNY-201"].phase == ChildPhase.QUALITY_REVIEWING
    assert [request.role for request in execution.requests] == ["child_implementer"]
    assert execution.requests[0].context_packet["child_id"] == "DANNY-201"
    assert execution.requests[0].context_packet["parent_issue_id"] == "DANNY-201"
    assert execution.requests[0].context_packet["acceptance_criteria"] == [
        "focused bug is fixed"
    ]
    assert execution.requests[0].context_packet["verification"]["required"] == [
        "uv run pytest packages/scheduler/tests/test_runtime_factory.py -q"
    ]


def test_configured_workspace_tick_threads_qa_policy_to_parent_workflow(
    tmp_path: Path,
):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
        max_total_remediation_children=1,
    )
    (tmp_path / "AGENTS.md").write_text("# Boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    issue = BacklogIssue(
        id="DANNY-66",
        title="Parent",
        state="Todo",
        body="Execution: smda\n",
        labels=frozenset({"agent"}),
    )
    backlog = RecordingBacklog(issue)
    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    ledger = PhaseLedger(workspace.ledger_path)
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
            {
                "node_id": "remediation-001",
                "title": "Remediate parent QA failure",
                "body": "Fix parent QA feedback.",
                "in_scope": ["parent QA remediation"],
                "out_of_scope": ["unrelated parent graph changes"],
                "touched_surfaces": {
                    "files": ["<to-be-determined-by-remediation-worker>"],
                    "modules": ["<to-be-determined-by-remediation-worker>"],
                    "contracts": ["smda.parent-qa-remediation.v1"],
                    "docs": ["<to-be-determined-by-remediation-worker>"],
                    "tests": ["<to-be-determined-by-remediation-worker>"],
                },
                "acceptance_criteria": ["parent QA feedback is resolved"],
                "verification": {
                    "required": ["configured quality gates pass"],
                    "smoke": [],
                },
                "risk_level": "medium",
                "dependencies": [],
            }
        ],
    )

    tick = build_configured_workspace_tick(
        config_path=config_path,
        repo_root=tmp_path,
        backlog=backlog,
        execution=RecordingExecution(),
        scan_state="Todo",
        scan_label="agent",
        owner="daemon-1",
    )

    result = tick()

    assert result.status == "dispatched"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.HUMAN_REVIEW_REQUIRED


def test_trading_advisor_config_runs_parent_dry_run_with_fake_adapters(
    tmp_path: Path,
):
    config_path = Path("/Users/danny/Desktop/GitHub/trading-advisor/smda.config.json")
    _approved_spec(tmp_path)
    issue = BacklogIssue(
        id="DANNY-66",
        title="Trading Advisor SMDA migration",
        state="Todo",
        body=(
            "Source: docs/superpowers/specs/approved.md\n"
            "Execution: smda\n"
            "Acceptance criteria: consumer dry-run reaches final accept\n"
            "Verification: product and harness gates pass\n"
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
                    required_next_action="submit_for_graph_review",
                ),
                raw_result={
                    "verdict": "DONE",
                    "required_next_action": "submit_for_graph_review",
                    "children": [_complete_graph_child()],
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
            AttemptOutcome(
                status="succeeded",
                role_result=RoleResult(
                    verdict="PASS",
                    required_next_action="accept_parent",
                ),
                raw_result={
                    "verdict": "PASS",
                    "required_next_action": "accept_parent",
                    "report": "Trading-advisor consumer dry-run passed.",
                },
            ),
        ]
    )
    integration = RecordingParentIntegration()
    tick = build_configured_workspace_tick(
        config_path=config_path,
        repo_root=tmp_path,
        backlog=backlog,
        execution=execution,
        scan_state="Todo",
        scan_label="agent",
        owner="daemon-1",
        integration=integration,
        integration_branch="smda/danny-66/integration",
    )

    for _ in range(5):
        result = tick()
        assert result.status == "dispatched"

    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    ledger = PhaseLedger(workspace.ledger_path)
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.CHILDREN_PUBLISHED
    assert [request.role for request in execution.requests] == [
        "graph_decomposer",
        "graph_spec_reviewer",
        "graph_execution_reviewer",
    ]
    assert len(backlog.created_children) == 1
    assert backlog.created_children[0].labels == frozenset({"agent"})
    assert "Execution: smda-child" in backlog.created_children[0].body

    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "child-001": ChildRunState(
                    phase=ChildPhase.QUALITY_REVIEW_PASSED,
                    attempts=1,
                )
            }
        )
    )
    ledger.record_role_attempt_request(
        attempt_id="child-001-QUALITY_REVIEWING-1",
        target_kind="child",
        target_id="child-001",
        phase=ChildPhase.QUALITY_REVIEWING,
        idempotency_key="child-001:QUALITY_REVIEWING:1",
        request_json={"role": "child_quality_reviewer"},
    )
    ledger.record_attempt_result(
        attempt_id="child-001-QUALITY_REVIEWING-1",
        status="succeeded",
        result_json={
            "verdict": "PASS",
            "required_next_action": "accept_candidate",
            "branch": "smda/danny-66/child-001/quality-reviewing",
        },
        error_message=None,
    )

    assert tick().status == "dispatched"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.PARENT_QA_READY
    assert [operation.child_id for operation in integration.applied] == ["child-001"]

    assert tick().status == "dispatched"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.FINAL_ACCEPT_READY

    assert tick().status == "dispatched"
    assert ledger.load_parent_runs()[0]["phase"] == ParentPhase.FINAL_ACCEPTED
    assert [(op.parent_ref, op.base_branch) for op in integration.landed] == [
        ("smda/danny-66/integration", "main")
    ]

    assert tick().status in {"dispatched", "idle"}
    assert backlog.comments
    assert backlog.states[-1] == ("DANNY-66", "Done")


def test_configured_workspace_tick_records_parent_lifecycle_tracker_effects(
    tmp_path: Path,
):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# Boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    spec = tmp_path / "docs" / "superpowers" / "specs" / "approved.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\nstatus: approved\napproved_at: 2026-06-15\napproved_by: human\n"
        "approval_evidence: DANNY-66 approval\n---\n# Approved\n",
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
        labels=frozenset({"agent"}),
    )
    backlog = RecordingBacklog(issue)

    tick = build_configured_workspace_tick(
        config_path=config_path,
        repo_root=tmp_path,
        backlog=backlog,
        execution=RecordingExecution(),
        scan_state="Todo",
        scan_label="agent",
        owner="daemon-1",
    )
    tick()

    ledger = PhaseLedger(
        derive_workspace_paths(load_config(config_path, repo_root=tmp_path)).ledger_path
    )
    effects = ledger.load_pending_tracker_effects()
    states = [
        (e["target_id"], e["payload"]["state"])
        for e in effects
        if e["effect_type"] == "set_state"
    ]
    comments = [
        e["payload"]["body"] for e in effects if e["effect_type"] == "comment"
    ]
    assert ("DANNY-66", "In Progress") in states
    assert any("SPEC_FINALIZED" in body for body in comments)
