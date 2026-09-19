import threading
from pathlib import Path

from fakes import FakeBacklogAdapter, FakeBacklogIssue

from smda_scheduler.backlog import BacklogIssue, BacklogPage
from smda_scheduler.candidate_routing import CandidateRoute, CandidateRoutingDecision
from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.daemon import TickResult
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.role_attempts import AgentSelection
from smda_scheduler.runtime import (
    RoleExecutionAdapter,
    run_child_candidate_tick,
    run_roadmap_publication_tick,
)
from smda_scheduler.runtime import run_parent_candidate_intake
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.scheduling import AttemptOutcome
from smda_scheduler.workflow import RoadmapPhase, RoleResult
from smda_scheduler.workflow_graph import WorkflowGraphArtifact
from smda_scheduler.workspace_tick import run_workspace_tick


class RecordingBacklog:
    def __init__(self, page: BacklogPage) -> None:
        self.page = page
        self.calls: list[dict] = []
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
        self.calls.append(
            {
                "state": state,
                "label": label,
                "parent_id": parent_id,
                "limit": limit,
                "cursor": cursor,
            }
        )
        return self.page

    def comment(self, issue_id: str, body: str) -> None:
        self.comments.append((issue_id, body))

    def set_coarse_state(self, issue_id: str, state: str) -> None:
        self.states.append((issue_id, state))


class RecordingExecutionAdapter(RoleExecutionAdapter):
    def __init__(self, outcome: AttemptOutcome):
        self.outcome = outcome
        self.requests: list[RoleAttemptRequest] = []

    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome:
        self.requests.append(request)
        return self.outcome


def test_workspace_tick_dispatches_eligible_candidates_concurrently(tmp_path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    class MultiBacklog:
        def __init__(self, pages):
            self.pages = pages

        def list_issues(self, *, state, label, parent_id, limit, cursor):
            return self.pages.get(state, BacklogPage(issues=()))

        def comment(self, issue_id, body): ...

        def set_coarse_state(self, issue_id, state): ...

    in_prog = BacklogIssue(
        id="DANNY-2",
        title="t2",
        state="In Progress",
        labels=frozenset({"agent"}),
        body="Execution: smda-child",
    )
    todo = BacklogIssue(
        id="DANNY-1",
        title="t1",
        state="Todo",
        labels=frozenset({"agent"}),
        body="Execution: smda-child",
    )
    backlog = MultiBacklog(
        {
            "In Progress": BacklogPage(issues=(in_prog,)),
            "Todo": BacklogPage(issues=(todo,)),
        }
    )

    seen: list[str] = []
    in_flight = []
    max_seen = [0]
    lock = threading.Lock()

    def routed(issue, decision):
        with lock:
            in_flight.append(issue.id)
            max_seen[0] = max(max_seen[0], len(in_flight))
            seen.append(issue.id)
        import time as _t

        _t.sleep(0.02)
        with lock:
            in_flight.remove(issue.id)
        return TickResult(status="dispatched", detail=issue.id)

    def classify(issue, **_):
        return CandidateRoutingDecision(
            route=CandidateRoute.CHILD,
            reason="x",
            parent_issue_id="DANNY-0",
            node_id=issue.id,
        )

    import smda_scheduler.workspace_tick as wt

    monkey = wt.classify_candidate
    wt.classify_candidate = classify
    try:
        result = run_workspace_tick(
            ledger=ledger,
            backlog=backlog,
            states=["In Progress", "Todo"],
            label="agent",
            parent_id=None,
            dispatch_candidate=lambda i: TickResult(status="blocked"),
            issue_entry_policy="explicit",
            dispatch_routed_candidate=routed,
            max_parallel=3,
        )
    finally:
        wt.classify_candidate = monkey

    assert set(seen) == {"DANNY-1", "DANNY-2"}
    assert result.dispatched == 2
    assert max_seen[0] == 2


def test_workspace_tick_reconciles_tracker_effects_before_dispatch(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_tracker_effect(
        effect_id="effect-1",
        idempotency_key="comment:DANNY-66:started",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "SMDA started"},
    )
    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-66",
                    title="SMDA parent",
                    state="Todo",
                    labels=frozenset({"smda"}),
                ),
            )
        )
    )
    events: list[str] = []

    def dispatch(issue: BacklogIssue) -> TickResult:
        events.append(f"dispatch:{issue.id}")
        return TickResult(status="dispatched", detail=issue.id)

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="smda",
        parent_id=None,
        dispatch_candidate=dispatch,
    )

    assert result == TickResult(
        status="dispatched",
        detail="dispatched=1; blocked=0; failed=0; skipped=0; pending=0; reconciled=1; failed=0",
        dispatched=1,
    )
    assert backlog.comments == [("DANNY-66", "SMDA started")]
    assert events == ["dispatch:DANNY-66"]
    assert ledger.load_pending_tracker_effects() == []


def test_workspace_tick_reports_idle_when_no_candidates(tmp_path: Path):
    result = run_workspace_tick(
        ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
        backlog=RecordingBacklog(BacklogPage(issues=())),
        states=["Todo"],
        label="smda",
        parent_id=None,
        dispatch_candidate=lambda issue: TickResult(status="dispatched"),
    )

    assert result == TickResult(status="idle", detail="reconciled=0; failed=0")


def test_workspace_tick_blocks_obsolete_orchestrator_without_dispatch(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-66",
                    title="Legacy orchestrator",
                    state="Todo",
                    body="Execution: orchestrator\n",
                    labels=frozenset({"agent"}),
                ),
            )
        )
    )
    dispatched: list[str] = []

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: dispatched.append(issue.id)
        or TickResult(status="dispatched"),
    )

    pending_effects = ledger.load_pending_tracker_effects()
    assert result == TickResult(
        status="blocked",
        detail="dispatched=0; blocked=1; failed=0; skipped=0; pending=0; reconciled=0; failed=0",
        blocked=1,
    )
    assert dispatched == []
    assert [(effect["effect_type"], effect["target_id"]) for effect in pending_effects] == [
        ("comment", "DANNY-66"),
        ("set_state", "DANNY-66"),
    ]
    assert "Execution: orchestrator is obsolete" in pending_effects[0]["payload"]["body"]
    assert pending_effects[1]["payload"] == {"state": "Blocked"}


def test_block_state_effect_reconciles_to_tracker(tmp_path: Path):
    from smda_scheduler.reconciliation import retry_pending_tracker_effects
    from smda_scheduler.workspace_tick import _record_block_effects

    class RecordingTracker:
        def __init__(self) -> None:
            self.states: list[tuple[str, str]] = []
            self.comments: list[tuple[str, str]] = []

        def comment(self, issue_id: str, body: str) -> None:
            self.comments.append((issue_id, body))

        def set_coarse_state(self, issue_id: str, state: str) -> None:
            self.states.append((issue_id, state))

    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    issue = BacklogIssue(
        id="DANNY-66", title="t", state="Todo", body="",
        parent_id=None, labels=frozenset(),
    )
    _record_block_effects(ledger, issue=issue, reason="obsolete")
    tracker = RecordingTracker()

    result = retry_pending_tracker_effects(ledger, tracker)

    assert result.failed_effect_ids == ()
    assert tracker.states == [("DANNY-66", "Blocked")]
    assert ledger.load_pending_tracker_effects() == []


def test_workspace_tick_does_not_dispatch_paused_parent(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.set_parent_pause("DANNY-66", paused=True)
    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-66",
                    title="Paused parent",
                    state="Todo",
                    body="Execution: smda\n",
                    labels=frozenset({"agent"}),
                ),
            )
        )
    )
    dispatched: list[str] = []

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: dispatched.append(issue.id)
        or TickResult(status="dispatched"),
    )

    assert dispatched == []
    assert result.status == "idle"
    assert result.skipped == 1
    assert result.detail == (
        "dispatched=0; blocked=0; failed=0; skipped=1; pending=0; "
        "reconciled=0; failed=0"
    )


def test_workspace_tick_dispatches_routed_parent_candidate(tmp_path: Path):
    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-66",
                    title="SMDA parent",
                    state="Todo",
                    body="Execution: smda\n",
                    labels=frozenset({"agent"}),
                ),
            )
        )
    )
    routed: list[tuple[str, str]] = []

    result = run_workspace_tick(
        ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: routed.append(
            (issue.id, decision.route.value)
        )
        or TickResult(status="dispatched", detail=f"{issue.id}:{decision.route}"),
    )

    assert routed == [("DANNY-66", "parent")]
    assert result == TickResult(
        status="dispatched",
        detail="dispatched=1; blocked=0; failed=0; skipped=0; pending=0; reconciled=0; failed=0",
        dispatched=1,
    )


def _roadmap_blocked_parent_backlog() -> "RecordingBacklog":
    return RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-66",
                    title="Downstream parent",
                    state="Todo",
                    body="Execution: smda\n",
                    labels=frozenset({"agent"}),
                ),
            )
        )
    )


def test_workspace_tick_skips_parent_blocked_by_unaccepted_upstream(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_roadmap_edges(
        [
            {
                "from_parent_id": "DANNY-50",
                "to_parent_id": "DANNY-66",
                "blocks_dispatch": True,
                "reason": "DANNY-66 builds on DANNY-50",
            }
        ]
    )
    dispatched: list[str] = []

    result = run_workspace_tick(
        ledger=ledger,
        backlog=_roadmap_blocked_parent_backlog(),
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: dispatched.append(issue.id)
        or TickResult(status="dispatched"),
    )

    assert dispatched == []
    assert result.status == "idle"
    assert result.skipped == 1
    assert result.detail == (
        "dispatched=0; blocked=0; failed=0; skipped=1; pending=0; "
        "reconciled=0; failed=0"
    )


def test_workspace_tick_dispatches_parent_once_upstream_final_accepted(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_roadmap_edges(
        [
            {
                "from_parent_id": "DANNY-50",
                "to_parent_id": "DANNY-66",
                "blocks_dispatch": True,
                "reason": "DANNY-66 builds on DANNY-50",
            }
        ]
    )
    ledger.create_parent_run(
        parent_id="DANNY-50",
        initial_phase="FINAL_ACCEPTED",
        spec_path="docs/spec.md",
        spec_checksum="sha",
        approval_evidence="approved",
    )
    routed: list[str] = []

    result = run_workspace_tick(
        ledger=ledger,
        backlog=_roadmap_blocked_parent_backlog(),
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: routed.append(issue.id)
        or TickResult(status="dispatched", detail=issue.id),
    )

    assert routed == ["DANNY-66"]
    assert result.status == "dispatched"


def test_workspace_tick_dispatches_published_roadmap_members_in_dependency_order(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-100",
        initial_phase=RoadmapPhase.ROADMAP_PUBLICATION_READY.value,
        spec_path="docs/superpowers/specs/roadmap.md",
        spec_checksum="sha256:roadmap",
        approval_evidence="approved",
    )
    ledger.record_roadmap_members(
        "DANNY-100",
        [
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
        roadmap_edges=[
            {
                "from": "parent-001",
                "to": "parent-002",
                "type": "code_dependency",
                "blocks_dispatch": True,
                "reason": "parent-002 reads parent-001 output.",
            }
        ],
    )
    backlog = FakeBacklogAdapter(
        issues={
            "DANNY-100": FakeBacklogIssue(
                id="DANNY-100",
                title="Roadmap",
                state="In Progress",
                body="Execution: smda-roadmap\n",
            )
        }
    )
    run_roadmap_publication_tick(
        issue=BacklogIssue(
            id="DANNY-100",
            title="Roadmap",
            state="In Progress",
            body="Execution: smda-roadmap\n",
        ),
        ledger=ledger,
        backlog=backlog,
        child_labels=frozenset({"agent"}),
    )
    dispatched: list[str] = []

    first = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id="DANNY-100",
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: dispatched.append(issue.id)
        or TickResult(status="dispatched", detail=issue.id),
    )

    assert first.status == "dispatched"
    assert dispatched == ["DANNY-100-C1"]

    backlog.set_coarse_state("DANNY-100-C1", "Done")
    ledger.create_parent_run(
        parent_id="DANNY-100-C1",
        initial_phase="FINAL_ACCEPTED",
        spec_path="docs/superpowers/specs/roadmap.md",
        spec_checksum="sha256:roadmap",
        approval_evidence="accepted",
    )

    second = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id="DANNY-100",
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: dispatched.append(issue.id)
        or TickResult(status="dispatched", detail=issue.id),
    )

    assert second.status == "dispatched"
    assert dispatched == ["DANNY-100-C1", "DANNY-100-C2"]


def test_workspace_tick_can_dispatch_routed_child_candidate(tmp_path: Path):
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
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_graph(
        WorkflowGraphArtifact.from_dict(
            {
                "parent_id": "DANNY-66",
                "graph_checksum": "sha256:abcdef",
                "children": [
                    {
                        "node_id": "child-001",
                        "title": "Child",
                        "body": "Route to execution.",
                        "acceptance_criteria": ["routes to execution"],
                        "dependencies": [],
                        "in_scope": ["child routing"],
                        "out_of_scope": ["parent routing"],
                        "touched_surfaces": {
                            "files": ["packages/scheduler/tests/test_workspace_tick.py"],
                            "modules": ["smda_scheduler.workspace_tick"],
                            "contracts": ["smda-child"],
                            "docs": ["docs/contracts.md"],
                            "tests": ["packages/scheduler/tests/test_workspace_tick.py"],
                        },
                        "verification": {
                            "required": ["pytest test_workspace_tick.py"],
                            "smoke": [],
                        },
                        "risk_level": "low",
                    }
                ],
                "dependency_edges": [],
            }
        )
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
    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-101",
                    title="Child",
                    state="Todo",
                    body=(
                        "Parent issue: DANNY-66\n"
                        "Graph checksum: sha256:abcdef\n"
                        "Node id: child-001\n"
                        "Execution: smda-child\n"
                        "Acceptance criteria: routes to execution\n"
                    ),
                    labels=frozenset({"agent"}),
                ),
            )
        )
    )

    def dispatch(issue: BacklogIssue, decision) -> TickResult:
        child_result = run_child_candidate_tick(
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
        return TickResult(
            status=child_result.status,
            detail=child_result.detail,
        )

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=dispatch,
    )

    assert result == TickResult(
        status="dispatched",
        detail="dispatched=1; blocked=0; failed=0; skipped=0; pending=0; reconciled=0; failed=0",
        dispatched=1,
    )
    assert execution.requests[0].context_packet["child_id"] == "child-001"
    assert ledger.load_attempts()[0]["status"] == "succeeded"


def test_workspace_tick_can_dispatch_routed_parent_candidate_to_spec_finalized(
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
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
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
                ),
            )
        )
    )

    def dispatch(issue: BacklogIssue, decision) -> TickResult:
        result = run_parent_candidate_intake(
            issue=issue,
            decision=decision,
            repo_root=tmp_path,
            ledger=ledger,
        )
        return TickResult(status="dispatched", detail=f"{issue.id}:{result.target_state}")

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=dispatch,
    )

    assert result == TickResult(
        status="dispatched",
        detail="dispatched=1; blocked=0; failed=0; skipped=0; pending=0; reconciled=0; failed=0",
        dispatched=1,
    )
    assert ledger.load_parent_runs()[0]["phase"] == "SPEC_FINALIZED"
    assert [
        (effect["effect_type"], effect["payload"]["state"])
        for effect in ledger.load_pending_tracker_effects()
        if effect["effect_type"] == "set_state"
    ] == [("set_state", "In Progress")]


def test_workspace_tick_contains_graph_error_as_block_effect(tmp_path: Path):
    from smda_scheduler.workflow import GraphError

    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-66",
                    title="SMDA parent",
                    state="Todo",
                    body="Execution: smda\n",
                    labels=frozenset({"agent"}),
                ),
            )
        )
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    def boom(issue, decision):
        raise GraphError("approved spec checksum changed")

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=boom,
    )

    assert result.status == "idle"
    assert result.failed == 1
    assert "failed=1" in (result.detail or "")
    effects = ledger.load_pending_tracker_effects()
    states = [
        (e["target_id"], e["payload"]["state"])
        for e in effects
        if e["effect_type"] == "set_state"
    ]
    assert ("DANNY-66", "Blocked") in states


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
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=dispatch,
    )

    assert result.status == "dispatched"
    assert result.dispatched == 1
    assert result.skipped == 1
    assert dispatched == ["DANNY-66-C1"]


def test_workspace_tick_skipped_dependencies_do_not_exhaust_max_parallel(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    def child(issue_id: str, node_id: str) -> BacklogIssue:
        return BacklogIssue(
            id=issue_id,
            title=issue_id,
            state="Todo",
            body=(
                "Parent issue: DANNY-70\n"
                "Graph checksum: sha256:graph\n"
                f"Node id: {node_id}\n"
                "Execution: smda-child\n"
                "Acceptance criteria: runs\n"
            ),
            labels=frozenset({"agent"}),
        )

    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                child("DANNY-78", "child-006"),
                child("DANNY-77", "child-005"),
                child("DANNY-76", "child-004"),
                child("DANNY-73", "child-001"),
                child("DANNY-74", "child-002"),
            )
        )
    )
    dispatched: list[str] = []

    def dispatch(issue: BacklogIssue, decision) -> TickResult:
        if issue.id in {"DANNY-78", "DANNY-77", "DANNY-76"}:
            return TickResult(status="skipped", detail=f"{issue.id}: dependency wait")
        dispatched.append(issue.id)
        return TickResult(status="dispatched", detail=f"child:{issue.id}")

    result = run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=["Todo"],
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=dispatch,
        max_parallel=3,
    )

    assert result.status == "dispatched"
    assert result.dispatched == 2
    assert result.skipped == 3
    assert dispatched == ["DANNY-73", "DANNY-74"]
    assert "pending=0" in (result.detail or "")


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
        states=["Todo"],
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
    assert result.skipped == 1
    assert result.detail == (
        "dispatched=0; blocked=0; failed=0; skipped=1; pending=0; "
        "reconciled=0; failed=0"
    )


def test_harness_readiness_gate_applies_to_routed_and_direct_dispatch(tmp_path):
    from dataclasses import replace

    for policy in (None, 'explicit-only'):
        issue = BacklogIssue(id='gated', title='Task', state='Todo',
            labels=frozenset({'agent', 'needs-info'}),
            body='Execution: smda-task\nAcceptance criteria: works\nVerification: pytest')
        backlog = RecordingBacklog(BacklogPage(issues=(issue,)))
        calls = []
        kwargs = dict(ledger=PhaseLedger(tmp_path / f'{policy}.sqlite'), backlog=backlog,
            states=['Todo'], label='agent', parent_id=None, issue_entry_policy=policy,
            blocking_labels=frozenset({'needs-info'}),
            dispatch_candidate=lambda item: calls.append(item.id) or TickResult(status='dispatched'))
        result = run_workspace_tick(**kwargs)
        assert calls == []
        assert 'needs-info' in result.detail
        assert backlog.states == []  # ordinary readiness waiting does not mutate lifecycle
        backlog.page = BacklogPage(issues=(replace(issue, labels=frozenset({'agent'})),))
        run_workspace_tick(**kwargs)
        assert calls == ['gated']
