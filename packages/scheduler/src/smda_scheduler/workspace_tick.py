from __future__ import annotations

from collections.abc import Callable

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.daemon import TickResult
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.reconciliation import retry_pending_tracker_effects
from smda_scheduler.scanner import CandidateBacklog, scan_dispatch_candidates


DispatchCandidate = Callable[[BacklogIssue], TickResult]


class WorkspaceBacklog(CandidateBacklog):
    def comment(self, issue_id: str, body: str) -> None: ...

    def set_coarse_state(self, issue_id: str, state: str) -> None: ...


def run_workspace_tick(
    *,
    ledger: PhaseLedger,
    backlog: WorkspaceBacklog,
    state: str,
    label: str,
    parent_id: str | None,
    dispatch_candidate: DispatchCandidate,
    limit: int = 50,
    cursor: str | None = None,
) -> TickResult:
    reconciliation = retry_pending_tracker_effects(
        ledger,
        backlog,
    )
    candidates = scan_dispatch_candidates(
        backlog,
        state=state,
        label=label,
        parent_id=parent_id,
        limit=limit,
        cursor=cursor,
    )
    detail_suffix = (
        f"reconciled={len(reconciliation.sent_effect_ids)}; "
        f"failed={len(reconciliation.failed_effect_ids)}"
    )
    if not candidates.issues:
        return TickResult(status="idle", detail=detail_suffix)

    result = dispatch_candidate(candidates.issues[0])
    detail = result.detail or candidates.issues[0].id
    return TickResult(
        status=result.status,
        detail=f"{detail}; {detail_suffix}",
    )
