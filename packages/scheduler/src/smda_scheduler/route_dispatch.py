from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import CandidateRoute, CandidateRoutingDecision
from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.daemon import TickResult
from smda_scheduler.execution_modes import ExecutionMode
from smda_scheduler.parent_acceptance import ParentIntegration
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.role_attempts import AgentSelection
from smda_scheduler.runtime import (
    BacklogPublicationAdapter,
    RoleExecutionAdapter,
    run_child_candidate_tick,
    run_parent_candidate_intake,
    run_parent_workflow_tick,
    run_roadmap_candidate_intake,
    run_roadmap_workflow_tick,
    run_sdd_candidate_tick,
)
from smda_scheduler.workflow import QaBounds
from smda_scheduler.workflow_registry import definition_for_mode
from smda_scheduler.workspace_tick import WorkspaceBacklog


@dataclass(frozen=True)
class RouteDispatcher:
    repo_context: RepoContextPacket
    repo_root: Path
    ledger: PhaseLedger
    execution: RoleExecutionAdapter
    backlog: WorkspaceBacklog
    sandbox_provider: str
    agent: AgentSelection
    owner: str
    child_labels: frozenset[str]
    qa_bounds: QaBounds
    integration: ParentIntegration | None = None
    integration_branch: str | None = None
    standalone_base: str = "main"

    def __call__(
        self,
        issue: BacklogIssue,
        decision: CandidateRoutingDecision,
    ) -> TickResult:
        if decision.route == CandidateRoute.CHILD:
            result = run_child_candidate_tick(
                issue=issue,
                decision=decision,
                repo_context=self.repo_context,
                repo_root=self.repo_root,
                ledger=self.ledger,
                execution=self.execution,
                sandbox_provider=self.sandbox_provider,
                agent=self.agent,
                now=time.time(),
                owner=self.owner,
                workflow_definition=definition_for_mode(ExecutionMode.SMDA_CHILD),
            )
            return TickResult(status=result.status, detail=result.detail)

        if decision.route == CandidateRoute.TASK:
            result = run_sdd_candidate_tick(
                issue=issue,
                child_id=issue.id,
                parent_issue_id=issue.id,
                repo_context=self.repo_context,
                repo_root=self.repo_root,
                ledger=self.ledger,
                execution=self.execution,
                sandbox_provider=self.sandbox_provider,
                agent=self.agent,
                now=time.time(),
                owner=self.owner,
                workflow_definition=definition_for_mode(ExecutionMode.SMDA_TASK),
            )
            return TickResult(status=result.status, detail=result.detail)

        if decision.route in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}:
            if _has_parent_run(self.ledger, issue.id):
                result = run_parent_workflow_tick(
                    issue=issue,
                    repo_context=self.repo_context,
                    repo_root=self.repo_root,
                    ledger=self.ledger,
                    execution=self.execution,
                    backlog=_as_publication_backlog(self.backlog),
                    sandbox_provider=self.sandbox_provider,
                    agent=self.agent,
                    owner=self.owner,
                    child_labels=self.child_labels,
                    integration=self.integration,
                    integration_branch=self.integration_branch,
                    standalone_base=self.standalone_base,
                    qa_bounds=self.qa_bounds,
                )
            else:
                result = run_parent_candidate_intake(
                    issue=issue,
                    decision=decision,
                    repo_root=self.repo_root,
                    ledger=self.ledger,
                )
            _record_parent_lifecycle_effects(self.ledger, issue.id, result)
            return TickResult(status="dispatched", detail=result.comment)

        if decision.route == CandidateRoute.ROADMAP:
            if _has_parent_run(self.ledger, issue.id):
                result = run_roadmap_workflow_tick(
                    issue=issue,
                    repo_context=self.repo_context,
                    repo_root=self.repo_root,
                    ledger=self.ledger,
                    execution=self.execution,
                    backlog=_as_publication_backlog(self.backlog),
                    sandbox_provider=self.sandbox_provider,
                    agent=self.agent,
                    owner=self.owner,
                    child_labels=self.child_labels,
                    integration=self.integration,
                    standalone_base=self.standalone_base,
                )
            else:
                result = run_roadmap_candidate_intake(
                    issue=issue,
                    decision=decision,
                    repo_root=self.repo_root,
                    ledger=self.ledger,
                )
            _record_parent_lifecycle_effects(self.ledger, issue.id, result)
            return TickResult(status="dispatched", detail=result.comment)

        return TickResult(status="blocked", detail=decision.reason)


def _record_parent_lifecycle_effects(
    ledger: PhaseLedger,
    issue_id: str,
    result,
) -> None:
    key = hashlib.sha256(result.comment.encode("utf-8")).hexdigest()[:16]
    ledger.record_tracker_effect(
        effect_id=f"lifecycle-comment:{issue_id}:{key}",
        idempotency_key=f"lifecycle-comment:{issue_id}:{key}",
        effect_type="comment",
        target_id=issue_id,
        payload={"body": result.comment},
    )
    ledger.record_tracker_effect(
        effect_id=f"lifecycle-state:{issue_id}:{key}",
        idempotency_key=f"lifecycle-state:{issue_id}:{key}",
        effect_type="set_state",
        target_id=issue_id,
        payload={"state": result.target_state},
    )


def _has_parent_run(ledger: PhaseLedger, parent_id: str) -> bool:
    return any(parent["parent_id"] == parent_id for parent in ledger.load_parent_runs())


def _as_publication_backlog(backlog: WorkspaceBacklog) -> BacklogPublicationAdapter:
    return backlog  # type: ignore[return-value]
