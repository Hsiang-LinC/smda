from pathlib import Path

from smda_scheduler.backlog import BacklogIssue, BacklogPage
from smda_scheduler.daemon import TickResult
from smda_scheduler.phase_ledger import PhaseLedger
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
