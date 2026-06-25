from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import (
    CandidateRoute,
    CandidateRoutingDecision,
    classify_candidate,
)
from smda_scheduler.daemon import TickResult
from smda_scheduler.parent_dependency_gate import parent_dependency_gate
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.reconciliation import retry_pending_tracker_effects
from smda_scheduler.scanner import CandidateBacklog, scan_dispatch_candidates_multi
from smda_scheduler.workflow import GraphError


DispatchCandidate = Callable[[BacklogIssue], TickResult]
DispatchRoutedCandidate = Callable[[BacklogIssue, CandidateRoutingDecision], TickResult]


class WorkspaceBacklog(CandidateBacklog):
    def comment(self, issue_id: str, body: str) -> None: ...

    def set_coarse_state(self, issue_id: str, state: str) -> None: ...


def run_workspace_tick(
    *,
    ledger: PhaseLedger,
    backlog: WorkspaceBacklog,
    states: Sequence[str],
    label: str,
    parent_id: str | None,
    dispatch_candidate: DispatchCandidate,
    issue_entry_policy: str | None = None,
    dispatch_routed_candidate: DispatchRoutedCandidate | None = None,
    max_parallel: int = 3,
    limit: int = 50,
    cursor: str | None = None,
) -> TickResult:
    reconciliation = retry_pending_tracker_effects(
        ledger,
        backlog,
    )
    detail_suffix = (
        f"reconciled={len(reconciliation.sent_effect_ids)}; "
        f"failed={len(reconciliation.failed_effect_ids)}"
    )
    candidates = scan_dispatch_candidates_multi(
        backlog,
        states=states,
        label=label,
        parent_id=parent_id,
        limit=limit,
        cursor=cursor,
    )
    if not candidates:
        return TickResult(status="idle", detail=detail_suffix)

    final_accepted = _final_accepted_parent_ids(ledger)
    skipped = 0
    blocked = 0
    # Each plan is (issue, thunk) where thunk() -> TickResult. Built from a
    # scan-time snapshot, in states order (in-flight first).
    plans: list[tuple[BacklogIssue, Callable[[], TickResult]]] = []

    for _source_state, candidate in candidates:
        if issue_entry_policy is None:
            plans.append((candidate, lambda c=candidate: dispatch_candidate(c)))
            continue

        decision = classify_candidate(candidate, issue_entry_policy=issue_entry_policy)
        if decision.route == CandidateRoute.BLOCK:
            _record_block_effects(ledger, issue=candidate, reason=decision.reason)
            blocked += 1
            continue

        paused_parent_id = _paused_parent_id(candidate, decision)
        if paused_parent_id is not None and ledger.is_parent_paused(paused_parent_id):
            skipped += 1
            continue

        if decision.route in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}:
            gate = parent_dependency_gate(
                parent_id=candidate.id,
                blockers=ledger.load_roadmap_blockers(candidate.id),
                final_accepted_parent_ids=final_accepted,
            )
            if not gate.eligible:
                skipped += 1
                continue

        if dispatch_routed_candidate is None:
            plans.append((candidate, lambda c=candidate: dispatch_candidate(c)))
        else:
            plans.append(
                (candidate, lambda c=candidate, d=decision: dispatch_routed_candidate(c, d))
            )

    def run_one(entry: tuple[BacklogIssue, Callable[[], TickResult]]) -> TickResult:
        issue, thunk = entry
        try:
            return thunk()
        except GraphError as error:
            _record_block_effects(
                ledger,
                issue=issue,
                reason=f"SMDA workflow error: {error}",
            )
            return TickResult(status="failed", detail=f"{issue.id}: {error}")
        except Exception as error:
            return TickResult(status="failed", detail=f"{issue.id}: {error}")

    results: list[TickResult] = []
    next_plan_index = 0
    capacity_used = 0
    while next_plan_index < len(plans) and capacity_used < max_parallel:
        remaining_capacity = max_parallel - capacity_used
        batch = plans[next_plan_index : next_plan_index + remaining_capacity]
        next_plan_index += len(batch)
        if not batch:
            break

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            batch_results = list(pool.map(run_one, batch))
        results.extend(batch_results)
        capacity_used += sum(1 for result in batch_results if result.status != "skipped")

    dispatched = sum(1 for result in results if result.status == "dispatched")
    failed = sum(1 for result in results if result.status == "failed")
    skipped += sum(1 for result in results if result.status == "skipped")
    blocked += sum(1 for result in results if result.status == "blocked")

    status = "dispatched" if dispatched else ("blocked" if blocked else "idle")
    detail = (
        f"dispatched={dispatched}; blocked={blocked}; failed={failed}; "
        f"skipped={skipped}; pending={max(0, len(plans) - next_plan_index)}; "
        f"{detail_suffix}"
    )
    return TickResult(
        status=status,
        detail=detail,
        dispatched=dispatched,
        blocked=blocked,
        failed=failed,
        skipped=skipped,
    )


def _final_accepted_parent_ids(ledger: PhaseLedger) -> frozenset[str]:
    return frozenset(
        run["parent_id"]
        for run in ledger.load_parent_runs()
        if run["phase"] == "FINAL_ACCEPTED"
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
        effect_type="set_state",
        target_id=issue.id,
        payload={"state": "Blocked"},
    )
