from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import CandidateRoute, CandidateRoutingDecision
from smda_scheduler.config import derive_workspace_paths, load_config
from smda_scheduler.context_packets import CodexHarnessContextAdapter
from smda_scheduler.daemon import TickResult
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.parent_acceptance import ParentIntegration
from smda_scheduler.role_attempts import AgentSelection
from smda_scheduler.runtime import (
    BacklogPublicationAdapter,
    RoleExecutionAdapter,
    run_child_candidate_tick,
    run_parent_candidate_intake,
    run_parent_workflow_tick,
)
from smda_scheduler.workflow import QaBounds
from smda_scheduler.workspace_tick import WorkspaceBacklog, run_workspace_tick


def build_configured_workspace_tick(
    *,
    config_path: Path,
    repo_root: Path,
    backlog: WorkspaceBacklog,
    execution: RoleExecutionAdapter,
    scan_state: str,
    scan_label: str,
    owner: str,
    parent_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    agent: AgentSelection = AgentSelection(provider="codex", model="gpt-5"),
    integration: ParentIntegration | None = None,
    integration_branch: str | None = None,
) -> Callable[[], TickResult]:
    config = load_config(config_path, repo_root=repo_root)
    workspace = derive_workspace_paths(config)
    ledger = PhaseLedger(workspace.ledger_path)
    repo_context = CodexHarnessContextAdapter().build_repo_packet(config)
    child_labels = _child_labels(config.labels)
    qa_bounds = QaBounds(
        max_same_feedback_fingerprint=config.policy.qa.max_same_feedback_fingerprint,
        max_total_remediation_children=config.policy.qa.max_total_remediation_children,
        max_parent_qa_cycles=config.policy.qa.max_parent_qa_cycles,
    )

    def dispatch_routed_candidate(
        issue: BacklogIssue,
        decision: CandidateRoutingDecision,
    ) -> TickResult:
        if decision.route == CandidateRoute.CHILD:
            run_child_candidate_tick(
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
            return TickResult(status="dispatched", detail=f"child:{issue.id}")

        if decision.route in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}:
            if _has_parent_run(ledger, issue.id):
                result = run_parent_workflow_tick(
                    issue=issue,
                    repo_context=repo_context,
                    repo_root=config.repo_root,
                    ledger=ledger,
                    execution=execution,
                    backlog=_as_publication_backlog(backlog),
                    sandbox_provider=config.adapters.execution.provider,
                    agent=agent,
                    owner=owner,
                    child_labels=child_labels,
                    integration=integration,
                    integration_branch=integration_branch,
                    qa_bounds=qa_bounds,
                )
            else:
                result = run_parent_candidate_intake(
                    issue=issue,
                    decision=decision,
                    repo_root=config.repo_root,
                    ledger=ledger,
                )
            return TickResult(status="dispatched", detail=result.comment)

        return TickResult(status="blocked", detail=decision.reason)

    return lambda: run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        state=scan_state,
        label=scan_label,
        parent_id=parent_id,
        dispatch_candidate=lambda issue: TickResult(
            status="blocked",
            detail=f"SMDA routing was not configured for {issue.id}",
        ),
        issue_entry_policy=config.policy.issue_entry,
        dispatch_routed_candidate=dispatch_routed_candidate,
        limit=limit,
        cursor=cursor,
    )


def _has_parent_run(ledger: PhaseLedger, parent_id: str) -> bool:
    return any(parent["parent_id"] == parent_id for parent in ledger.load_parent_runs())


def _child_labels(labels: dict[str, object]) -> frozenset[str]:
    actor = labels.get("actor")
    if isinstance(actor, str) and actor:
        return frozenset({actor})
    return frozenset()


def _as_publication_backlog(backlog: WorkspaceBacklog) -> BacklogPublicationAdapter:
    return backlog  # type: ignore[return-value]
