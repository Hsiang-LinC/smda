from pathlib import Path

from smda_scheduler.backlog import BacklogIssue, BacklogPage
from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.daemon import TickResult
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.role_attempts import AgentSelection
from smda_scheduler.runtime import RoleExecutionAdapter, run_child_candidate_tick
from smda_scheduler.runtime import run_parent_candidate_intake
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.scheduling import AttemptOutcome
from smda_scheduler.workflow import RoleResult
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
        state="Todo",
        label="smda",
        parent_id=None,
        dispatch_candidate=dispatch,
    )

    assert result == TickResult(
        status="dispatched",
        detail="DANNY-66; reconciled=1; failed=0",
    )
    assert backlog.comments == [("DANNY-66", "SMDA started")]
    assert events == ["dispatch:DANNY-66"]
    assert ledger.load_pending_tracker_effects() == []


def test_workspace_tick_reports_idle_when_no_candidates(tmp_path: Path):
    result = run_workspace_tick(
        ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
        backlog=RecordingBacklog(BacklogPage(issues=())),
        state="Todo",
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
        state="Todo",
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: dispatched.append(issue.id)
        or TickResult(status="dispatched"),
    )

    pending_effects = ledger.load_pending_tracker_effects()
    assert result == TickResult(
        status="blocked",
        detail="DANNY-66: Execution: orchestrator is obsolete; use Execution: smda or Execution: smda-child; reconciled=0; failed=0",
    )
    assert dispatched == []
    assert [(effect["effect_type"], effect["target_id"]) for effect in pending_effects] == [
        ("comment", "DANNY-66"),
        ("state", "DANNY-66"),
    ]
    assert "Execution: orchestrator is obsolete" in pending_effects[0]["payload"]["body"]
    assert pending_effects[1]["payload"] == {"state": "Blocked"}


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
        state="Todo",
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=lambda issue, decision: dispatched.append(issue.id)
        or TickResult(status="dispatched"),
    )

    assert dispatched == []
    assert result.status == "blocked"
    assert "paused" in (result.detail or "")


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
        state="Todo",
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
        detail="DANNY-66:parent; reconciled=0; failed=0",
    )


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
        state = run_child_candidate_tick(
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
            status="dispatched",
            detail=f"{issue.id}:{state.children[decision.node_id].phase}",
        )

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

    assert result == TickResult(
        status="dispatched",
        detail="DANNY-101:SPEC_REVIEWING; reconciled=0; failed=0",
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
        state="Todo",
        label="agent",
        parent_id=None,
        issue_entry_policy="explicit-only",
        dispatch_candidate=lambda issue: TickResult(status="wrong"),
        dispatch_routed_candidate=dispatch,
    )

    assert result == TickResult(
        status="dispatched",
        detail="DANNY-66:In Progress; reconciled=0; failed=0",
    )
    assert ledger.load_parent_runs()[0]["phase"] == "SPEC_FINALIZED"
