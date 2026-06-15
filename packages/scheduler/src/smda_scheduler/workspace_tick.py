from __future__ import annotations

from collections.abc import Callable

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import (
    CandidateRoute,
    CandidateRoutingDecision,
    classify_candidate,
)
from smda_scheduler.daemon import TickResult
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.reconciliation import retry_pending_tracker_effects
from smda_scheduler.scanner import CandidateBacklog, scan_dispatch_candidates


DispatchCandidate = Callable[[BacklogIssue], TickResult]
DispatchRoutedCandidate = Callable[[BacklogIssue, CandidateRoutingDecision], TickResult]


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
    issue_entry_policy: str | None = None,
    dispatch_routed_candidate: DispatchRoutedCandidate | None = None,
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

    candidate = candidates.issues[0]
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
                detail=f"{candidate.id}: {decision.reason}; {detail_suffix}",
            )
        paused_parent_id = _paused_parent_id(candidate, decision)
        if paused_parent_id is not None and ledger.is_parent_paused(paused_parent_id):
            return TickResult(
                status="blocked",
                detail=f"{paused_parent_id} paused; {detail_suffix}",
            )
        if dispatch_routed_candidate is not None:
            result = dispatch_routed_candidate(candidate, decision)
            detail = result.detail or candidate.id
            return TickResult(
                status=result.status,
                detail=f"{detail}; {detail_suffix}",
            )

    result = dispatch_candidate(candidate)
    detail = result.detail or candidate.id
    return TickResult(
        status=result.status,
        detail=f"{detail}; {detail_suffix}",
    )


def _paused_parent_id(
    issue: BacklogIssue,
    decision: CandidateRoutingDecision,
) -> str | None:
    if decision.route in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}:
        return issue.id
    if decision.route == CandidateRoute.CHILD:
        return decision.parent_issue_id
    return None


def _record_block_effects(
    ledger: PhaseLedger,
    *,
    issue: BacklogIssue,
    reason: str,
) -> None:
    ledger.record_tracker_effect(
        effect_id=f"routing-block-comment:{issue.id}",
        idempotency_key=f"routing-block-comment:{issue.id}:{reason}",
        effect_type="comment",
        target_id=issue.id,
        payload={"body": f"SMDA blocked {issue.id}: {reason}"},
    )
    ledger.record_tracker_effect(
        effect_id=f"routing-block-state:{issue.id}",
        idempotency_key=f"routing-block-state:{issue.id}",
        effect_type="state",
        target_id=issue.id,
        payload={"state": "Blocked"},
    )
