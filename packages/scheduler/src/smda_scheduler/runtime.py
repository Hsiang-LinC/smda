from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import CandidateRoute, CandidateRoutingDecision
from smda_scheduler.child_dependency_gate import (
    ChildDependencyGateResult,
    child_dependency_gate,
    latest_quality_candidate_ref,
)
from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.parent_acceptance import (
    ChildAcceptOperation,
    ParentIntegration,
    ParentLandIntegration,
    ParentLandOperation,
    recover_or_apply_child_accept,
    recover_or_apply_parent_land,
)
from smda_scheduler.role_attempts import (
    AgentSelection,
    ChildTaskContext,
    ParentGraphContext,
    ParentSpecContext,
    RoadmapSpecContext,
    build_child_role_attempt_request,
    build_parent_graph_decomposer_request,
    build_parent_graph_fixer_request,
    build_parent_graph_execution_review_request,
    build_parent_graph_spec_review_request,
    build_parent_qa_review_request,
    build_roadmap_decomposer_request,
)
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.scheduling import (
    AttemptDispatch,
    AttemptOutcome,
    SchedulerState,
    run_once_durable,
)
from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    DependencyEdge,
    GraphError,
    ParentPhase,
    QaBounds,
    RoadmapPhase,
    WorkflowGraph,
    validate_graph,
)
from smda_scheduler.workflow_engine import (
    CHILD_DEFINITION,
    PARENT_DEFINITION,
    ROADMAP_DEFINITION,
    ParentTickContext,
    WorkflowDefinition,
    WorkflowEngine,
)

# The parent workflow is interpreted by the engine; handlers below remain the
# stage work until Phase 1c decomposes them into generic kind interpretation.
_PARENT_ENGINE = WorkflowEngine(PARENT_DEFINITION)
_ROADMAP_ENGINE = WorkflowEngine(ROADMAP_DEFINITION)


class RoleExecutionAdapter(Protocol):
    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome: ...


class BacklogPublicationAdapter(Protocol):
    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ) -> BacklogIssue: ...

    def link_blocking(self, *, blocker_id: str, blocked_id: str) -> None: ...

    def set_coarse_state(self, issue_id: str, state: str) -> None: ...


@dataclass(frozen=True)
class ParentIntakeResult:
    target_state: str
    comment: str


@dataclass(frozen=True)
class ChildCandidateTickResult:
    status: str
    detail: str
    state: SchedulerState


def run_parent_candidate_intake(
    *,
    issue: BacklogIssue,
    decision: CandidateRoutingDecision,
    repo_root: Path,
    ledger: PhaseLedger,
) -> ParentIntakeResult:
    if decision.route not in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}:
        raise GraphError(
            f"run_parent_candidate_intake requires parent route: {decision.route}"
        )

    spec_path = _spec_path(issue.body)
    if spec_path is None:
        return ParentIntakeResult(
            target_state="Blocked",
            comment=(
                f"SMDA parent intake blocked for {issue.id}.\n\n"
                "No approved parent spec path was found in the issue body."
            ),
        )

    spec_text = _read_repo_file(repo_root, spec_path)
    metadata = _front_matter_metadata(spec_text)
    status = metadata.get("status", "")
    approval_evidence = metadata.get("approval_evidence", "")
    approved_at = metadata.get("approved_at", "")
    approved_by = metadata.get("approved_by", "")
    spec_checksum = f"sha256:{hashlib.sha256(spec_text.encode('utf-8')).hexdigest()}"

    missing_approval_fields = [
        label
        for label, value in (
            ("status: approved", status if status.lower().startswith("approved") else ""),
            ("approval_evidence", approval_evidence),
            ("approved_at", approved_at),
            ("approved_by", approved_by),
        )
        if not value
    ]

    if missing_approval_fields:
        ledger.record_parent_run(
            parent_id=issue.id,
            phase="SPEC_INTAKE",
            spec_path=spec_path,
            spec_checksum=spec_checksum,
            approval_evidence=approval_evidence,
        )
        return ParentIntakeResult(
            target_state="Human Review",
            comment=(
                f"SMDA parent spec approval is incomplete for {issue.id}.\n\n"
                f"Spec: `{spec_path}`\n"
                f"Missing approval fields: {', '.join(missing_approval_fields)}\n"
                "Human Review must approve the spec before SPEC_FINALIZED."
            ),
        )

    ledger.record_parent_run(
        parent_id=issue.id,
        phase="SPEC_FINALIZED",
        spec_path=spec_path,
        spec_checksum=spec_checksum,
        approval_evidence=approval_evidence,
    )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA parent reached SPEC_FINALIZED for {issue.id}.\n\n"
            f"Spec: `{spec_path}`\n"
            f"Spec checksum: `{spec_checksum}`\n"
            f"Approval evidence: {approval_evidence}"
        ),
    )


def run_roadmap_candidate_intake(
    *,
    issue: BacklogIssue,
    decision: CandidateRoutingDecision,
    repo_root: Path,
    ledger: PhaseLedger,
) -> ParentIntakeResult:
    if decision.route != CandidateRoute.ROADMAP:
        raise GraphError(
            f"run_roadmap_candidate_intake requires roadmap route: {decision.route}"
        )

    spec_path = _spec_path(issue.body)
    if spec_path is None:
        return ParentIntakeResult(
            target_state="Blocked",
            comment=(
                f"SMDA roadmap intake blocked for {issue.id}.\n\n"
                "No approved roadmap spec path was found in the issue body."
            ),
        )

    spec_text = _read_repo_file(repo_root, spec_path)
    metadata = _front_matter_metadata(spec_text)
    status = metadata.get("status", "")
    approval_evidence = metadata.get("approval_evidence", "")
    approved_at = metadata.get("approved_at", "")
    approved_by = metadata.get("approved_by", "")
    spec_checksum = f"sha256:{hashlib.sha256(spec_text.encode('utf-8')).hexdigest()}"

    missing_approval_fields = [
        label
        for label, value in (
            ("status: approved", status if status.lower().startswith("approved") else ""),
            ("approval_evidence", approval_evidence),
            ("approved_at", approved_at),
            ("approved_by", approved_by),
        )
        if not value
    ]

    if missing_approval_fields:
        ledger.record_parent_run(
            parent_id=issue.id,
            phase="ROADMAP_SPEC_INTAKE",
            spec_path=spec_path,
            spec_checksum=spec_checksum,
            approval_evidence=approval_evidence,
        )
        return ParentIntakeResult(
            target_state="Human Review",
            comment=(
                f"SMDA roadmap spec approval is incomplete for {issue.id}.\n\n"
                f"Spec: `{spec_path}`\n"
                f"Missing approval fields: {', '.join(missing_approval_fields)}"
            ),
        )

    ledger.record_parent_run(
        parent_id=issue.id,
        phase=RoadmapPhase.ROADMAP_DECOMPOSING.value,
        spec_path=spec_path,
        spec_checksum=spec_checksum,
        approval_evidence=approval_evidence,
    )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA roadmap reached ROADMAP_DECOMPOSING for {issue.id}.\n\n"
            f"Spec: `{spec_path}`\n"
            f"Spec checksum: `{spec_checksum}`\n"
            f"Approval evidence: {approval_evidence}"
        ),
    )


def run_parent_workflow_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    backlog: BacklogPublicationAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
    child_labels: frozenset[str] = frozenset(),
    integration: ParentIntegration | None = None,
    integration_branch: str | None = None,
    standalone_base: str = "main",
    qa_bounds: QaBounds | None = None,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    phase = parent_run["phase"]
    # Preserve the CHILDREN_PUBLISHED precondition exactly: acceptance cannot run
    # without an integration target.
    if phase == ParentPhase.CHILDREN_PUBLISHED.value and (
        integration is None or integration_branch is None
    ):
        return ParentIntakeResult(
            target_state="Blocked",
            comment=f"SMDA child acceptance is not configured for {issue.id}.",
        )

    ctx = ParentTickContext(
        issue=issue,
        repo_context=repo_context,
        repo_root=repo_root,
        ledger=ledger,
        execution=execution,
        backlog=backlog,
        sandbox_provider=sandbox_provider,
        agent=agent,
        owner=owner,
        child_labels=child_labels,
        integration=integration,
        integration_branch=integration_branch,
        standalone_base=standalone_base,
        qa_bounds=qa_bounds,
    )
    result = _PARENT_ENGINE.dispatch_parent_stage(phase, ctx)
    if result is not None:
        return result
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA parent workflow idle for {issue.id}.\n\n"
            f"Current parent phase: `{phase}`"
        ),
    )


def run_roadmap_workflow_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    backlog: BacklogPublicationAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
    child_labels: frozenset[str] = frozenset(),
    integration: ParentLandIntegration | None = None,
    standalone_base: str = "main",
) -> ParentIntakeResult:
    roadmap_run = _parent_run_for(ledger, issue.id)
    ctx = ParentTickContext(
        issue=issue,
        repo_context=repo_context,
        repo_root=repo_root,
        ledger=ledger,
        execution=execution,
        backlog=backlog,
        sandbox_provider=sandbox_provider,
        agent=agent,
        owner=owner,
        child_labels=child_labels,
        integration=integration,
        standalone_base=standalone_base,
    )
    result = _ROADMAP_ENGINE.dispatch_parent_stage(roadmap_run["phase"], ctx)
    if result is not None:
        return result
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA roadmap workflow idle for {issue.id}.\n\n"
            f"Current roadmap phase: `{roadmap_run['phase']}`"
        ),
    )


def run_roadmap_decomposition_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
    backlog: BacklogPublicationAdapter | None = None,
) -> ParentIntakeResult:
    roadmap_run = _parent_run_for(ledger, issue.id)
    if roadmap_run["phase"] != RoadmapPhase.ROADMAP_DECOMPOSING.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA roadmap decomposition skipped for {issue.id}.\n\n"
                f"Current roadmap phase: `{roadmap_run['phase']}`"
            ),
        )

    spec_text = _read_repo_file(repo_root, roadmap_run["spec_path"])
    spec_checksum = f"sha256:{hashlib.sha256(spec_text.encode('utf-8')).hexdigest()}"
    if spec_checksum != roadmap_run["spec_checksum"]:
        raise GraphError(
            "Approved roadmap spec checksum changed for "
            f"{issue.id}: expected {roadmap_run['spec_checksum']} got {spec_checksum}"
        )

    phase = RoadmapPhase.ROADMAP_DECOMPOSING
    attempt_number = _next_attempt_number(
        ledger,
        target_kind="roadmap",
        target_id=issue.id,
        phase=phase.value,
    )
    attempt_id = f"{issue.id}-{phase.value}-{attempt_number}"
    request = build_roadmap_decomposer_request(
        attempt_id=attempt_id,
        roadmap=RoadmapSpecContext(
            roadmap_issue_id=issue.id,
            title=issue.title,
            body=issue.body,
            spec_path=roadmap_run["spec_path"],
            spec_checksum=roadmap_run["spec_checksum"],
            approval_evidence=roadmap_run["approval_evidence"],
            spec_text=spec_text,
            open_parent_snapshot=tuple(_open_parent_snapshot(backlog, exclude_id=issue.id)),
        ),
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )
    resolved_attempt_id = ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="roadmap",
        target_id=issue.id,
        phase=phase,
        idempotency_key=f"roadmap:{issue.id}:{phase.value}:{attempt_number}",
        request_json=request.to_ipc_payload(),
    )
    if resolved_attempt_id != request.attempt_id:
        request = replace(request, attempt_id=resolved_attempt_id)

    outcome = execution.run_role_attempt(request)
    if outcome.status == "succeeded":
        if outcome.role_result is None:
            raise GraphError("succeeded roadmap decomposition requires role_result")
        if (
            outcome.role_result.verdict,
            outcome.role_result.required_next_action,
        ) != ("DONE", "publish_roadmap_parents"):
            raise GraphError(
                "No roadmap transition for "
                f"phase={phase.value} verdict={outcome.role_result.verdict} "
                f"required_next_action={outcome.role_result.required_next_action}"
        )
        members = _roadmap_members_from_outcome(outcome)
        edges = _roadmap_edges_from_outcome(outcome, members)
        next_phase = _ROADMAP_ENGINE.next_phase(phase, outcome.role_result)
        ledger.record_roadmap_members(issue.id, members, roadmap_edges=edges)
        ledger.record_attempt_result_and_parent_run(
            attempt_id=resolved_attempt_id,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
            parent_id=issue.id,
            phase=next_phase,
            spec_path=roadmap_run["spec_path"],
            spec_checksum=roadmap_run["spec_checksum"],
            approval_evidence=roadmap_run["approval_evidence"],
        )
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA roadmap decomposition completed for {issue.id}.\n\n"
                f"Roadmap phase: `{next_phase}`\n"
                f"Attempt: `{resolved_attempt_id}`"
            ),
        )

    ledger.record_attempt_result(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
    )
    return ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA roadmap decomposition failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )


# A newly created member parent is held in a non-scanned coarse state until the
# roadmap edges are recorded + projected, then released to the dispatchable state.
# This closes the crash window where a member issue exists but its blocking edges
# are not yet in the ledger — the parent gate would otherwise dispatch it out of
# order. Release runs over every projected member each tick, so it self-heals on
# re-entry.
_ROADMAP_MEMBER_HELD_STATE = "Blocked"
_ROADMAP_MEMBER_DISPATCH_STATE = "Todo"


def run_roadmap_publication_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    backlog: BacklogPublicationAdapter,
    child_labels: frozenset[str] = frozenset(),
) -> ParentIntakeResult:
    roadmap_run = _parent_run_for(ledger, issue.id)
    if roadmap_run["phase"] != RoadmapPhase.ROADMAP_PUBLICATION_READY.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA roadmap publication skipped for {issue.id}.\n\n"
                f"Current roadmap phase: `{roadmap_run['phase']}`"
            ),
        )

    members = ledger.load_roadmap_members(issue.id)
    if not members:
        raise GraphError(f"Roadmap has no persisted members: {issue.id}")
    projections = ledger.load_roadmap_member_projections(issue.id)

    for member in members:
        node_id = str(member["node_id"])
        if node_id in projections:
            continue
        created = backlog.create_child(
            parent_id=issue.id,
            title=str(member["title"]),
            body=_roadmap_member_issue_body(
                roadmap_id=issue.id,
                spec_path=roadmap_run["spec_path"],
                member=member,
            ),
            labels=child_labels,
        )
        # Hold the member out of the scan until edges are recorded + projected.
        backlog.set_coarse_state(created.id, _ROADMAP_MEMBER_HELD_STATE)
        ledger.record_roadmap_member_projection(
            roadmap_id=issue.id,
            node_id=node_id,
            issue_id=created.id,
        )
        projections[node_id] = created.id

    node_edges = _roadmap_edges_for_publication(ledger, issue.id, members)
    parent_edges = [
        {
            "from_parent_id": projections[str(edge["from"])],
            "to_parent_id": projections[str(edge["to"])],
            "blocks_dispatch": bool(edge["blocks_dispatch"]),
            "reason": str(edge.get("reason", "")),
        }
        for edge in node_edges
    ]
    if parent_edges:
        ledger.record_roadmap_edges(parent_edges)
    for edge in parent_edges:
        if not bool(edge["blocks_dispatch"]):
            continue
        backlog.link_blocking(
            blocker_id=str(edge["from_parent_id"]),
            blocked_id=str(edge["to_parent_id"]),
        )

    # Edges are now recorded and projected: release every member to the scan so
    # the parent gate (not coarse state) owns dispatch ordering from here on.
    for member in members:
        member_issue_id = projections[str(member["node_id"])]
        backlog.set_coarse_state(member_issue_id, _ROADMAP_MEMBER_DISPATCH_STATE)

    next_phase = ROADMAP_DEFINITION.stage(
        RoadmapPhase.ROADMAP_PUBLICATION_READY
    ).next_phase_on_success
    ledger.record_parent_run(
        parent_id=issue.id,
        phase=next_phase,
        spec_path=roadmap_run["spec_path"],
        spec_checksum=roadmap_run["spec_checksum"],
        approval_evidence=roadmap_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA roadmap parent issues published for {issue.id}.\n\n"
            f"Roadmap phase: `{next_phase}`\n"
            f"Published parents: {len(members)}"
        ),
    )


def run_roadmap_completion_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    integration: ParentLandIntegration | None = None,
    standalone_base: str = "main",
) -> ParentIntakeResult:
    """Parent-tier Aggregate: land the roadmap to main once all members land.

    Polls member FINAL_ACCEPTED (no event system, mirrors the 3a auto-unblock).
    When every member is accepted, lands roadmap-integration -> standalone_base
    exactly once (idempotent land op), deletes the roadmap branch, and advances
    to the terminal ROADMAP_COMPLETED. Partial acceptance is a no-op.
    """
    roadmap_run = _parent_run_for(ledger, issue.id)
    if roadmap_run["phase"] != RoadmapPhase.ROADMAP_PUBLISHED.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA roadmap completion skipped for {issue.id}.\n\n"
                f"Current roadmap phase: `{roadmap_run['phase']}`"
            ),
        )

    member_issue_ids = set(ledger.load_roadmap_member_projections(issue.id).values())
    accepted = {
        run["parent_id"]
        for run in ledger.load_parent_runs()
        if run["phase"] == ParentPhase.FINAL_ACCEPTED.value
    }
    if not member_issue_ids or not member_issue_ids <= accepted:
        pending = sorted(member_issue_ids - accepted)
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA roadmap {issue.id} waiting on members to be "
                f"FINAL_ACCEPTED: {', '.join(pending) or 'none published'}"
            ),
        )

    branch = roadmap_integration_branch(issue.id)
    if integration is not None:
        land = ParentLandOperation(
            operation_id=f"roadmap-land:{issue.id}",
            idempotency_key=f"roadmap-land:{issue.id}:{branch}:{standalone_base}",
            parent_id=issue.id,
            parent_ref=branch,
            base_branch=standalone_base,
        )
        outcome = recover_or_apply_parent_land(ledger, integration, land)
        if outcome.status != "completed":
            return ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA roadmap land pending for {issue.id} "
                    f"(base `{standalone_base}`): {outcome.action}"
                ),
            )
        integration.delete_branch(branch)

    ledger.record_parent_run(
        parent_id=issue.id,
        phase=RoadmapPhase.ROADMAP_COMPLETED.value,
        spec_path=roadmap_run["spec_path"],
        spec_checksum=roadmap_run["spec_checksum"],
        approval_evidence=roadmap_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="Done",
        comment=(
            f"SMDA roadmap {issue.id} completed: landed `{branch}` -> "
            f"`{standalone_base}` and deleted the roadmap branch."
        ),
    )


def run_parent_graph_decomposition_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != "SPEC_FINALIZED":
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent graph decomposition skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    spec_text = _read_repo_file(repo_root, parent_run["spec_path"])
    spec_checksum = f"sha256:{hashlib.sha256(spec_text.encode('utf-8')).hexdigest()}"
    if spec_checksum != parent_run["spec_checksum"]:
        raise GraphError(
            "Approved spec checksum changed for "
            f"{issue.id}: expected {parent_run['spec_checksum']} got {spec_checksum}"
        )

    phase = ParentPhase.GRAPH_DECOMPOSING
    attempt_number = _next_attempt_number(
        ledger,
        target_kind="parent",
        target_id=issue.id,
        phase=phase.value,
    )
    attempt_id = f"{issue.id}-{phase.value}-{attempt_number}"
    request = build_parent_graph_decomposer_request(
        attempt_id=attempt_id,
        parent=ParentSpecContext(
            parent_issue_id=issue.id,
            title=issue.title,
            body=issue.body,
            spec_path=parent_run["spec_path"],
            spec_checksum=parent_run["spec_checksum"],
            approval_evidence=parent_run["approval_evidence"],
            spec_text=spec_text,
        ),
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )
    resolved_attempt_id = ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="parent",
        target_id=issue.id,
        phase=phase,
        idempotency_key=f"parent:{issue.id}:{phase.value}:{attempt_number}",
        request_json=request.to_ipc_payload(),
    )
    if resolved_attempt_id != request.attempt_id:
        request = replace(request, attempt_id=resolved_attempt_id)

    outcome = execution.run_role_attempt(request)
    if outcome.status == "succeeded":
        if outcome.role_result is None:
            raise GraphError("succeeded graph decomposition requires role_result")
        if (
            outcome.role_result.verdict,
            outcome.role_result.required_next_action,
        ) != ("DONE", "submit_for_graph_review"):
            raise GraphError(
                "No parent transition for "
                f"phase={phase.value} verdict={outcome.role_result.verdict} "
                f"required_next_action={outcome.role_result.required_next_action}"
            )
        graph_children = _graph_children_from_outcome(outcome)
        dependency_edges = _dependency_edges_from_outcome(outcome, graph_children)
        graph_checksum = _graph_checksum(
            graph_children,
            dependency_edges=dependency_edges,
        )
        next_phase = _PARENT_ENGINE.next_phase(
            "SPEC_FINALIZED", outcome.role_result
        )
        ledger.record_attempt_result_parent_run_and_graph(
            attempt_id=resolved_attempt_id,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
            parent_id=issue.id,
            phase=next_phase,
            spec_path=parent_run["spec_path"],
            spec_checksum=parent_run["spec_checksum"],
            approval_evidence=parent_run["approval_evidence"],
            graph_checksum=graph_checksum,
            children=graph_children,
            dependency_edges=dependency_edges,
        )
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent graph decomposition completed for {issue.id}.\n\n"
                f"Parent phase: `{next_phase}`\n"
                f"Attempt: `{resolved_attempt_id}`"
            ),
        )

    ledger.record_attempt_result(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
    )
    return ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA parent graph decomposition failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )


def run_parent_graph_fixing_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.GRAPH_FIXING.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent graph fixing skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    parent = _parent_spec_context_for_issue(
        issue=issue, parent_run=parent_run, repo_root=repo_root
    )
    persisted_graph = ledger.load_graph(issue.id)
    phase = ParentPhase.GRAPH_FIXING
    attempt_number = _next_attempt_number(
        ledger, target_kind="parent", target_id=issue.id, phase=phase.value
    )
    attempt_id = f"{issue.id}-{phase.value}-{attempt_number}"
    request = build_parent_graph_fixer_request(
        attempt_id=attempt_id,
        graph=ParentGraphContext(
            parent=parent,
            graph_checksum=str(persisted_graph["graph_checksum"]),
            children=tuple(persisted_graph["children"]),
            dependency_edges=tuple(persisted_graph["dependency_edges"]),
        ),
        review_findings=_latest_graph_review_findings(ledger, issue.id),
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )
    resolved_attempt_id = ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="parent",
        target_id=issue.id,
        phase=phase,
        idempotency_key=f"parent:{issue.id}:{phase.value}:{attempt_number}",
        request_json=request.to_ipc_payload(),
    )
    if resolved_attempt_id != request.attempt_id:
        request = replace(request, attempt_id=resolved_attempt_id)

    outcome = execution.run_role_attempt(request)
    if outcome.status == "succeeded":
        if outcome.role_result is None:
            raise GraphError("succeeded graph fixing requires role_result")
        if (
            outcome.role_result.verdict,
            outcome.role_result.required_next_action,
        ) != ("DONE", "submit_for_graph_review"):
            raise GraphError(
                "No parent transition for "
                f"phase={phase.value} verdict={outcome.role_result.verdict} "
                f"required_next_action={outcome.role_result.required_next_action}"
            )
        graph_children = _graph_children_from_outcome(outcome)
        dependency_edges = _dependency_edges_from_outcome(outcome, graph_children)
        graph_checksum = _graph_checksum(
            graph_children, dependency_edges=dependency_edges
        )
        next_phase = _PARENT_ENGINE.next_phase(
            ParentPhase.GRAPH_FIXING.value, outcome.role_result
        )
        ledger.record_attempt_result_parent_run_and_graph(
            attempt_id=resolved_attempt_id,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
            parent_id=issue.id,
            phase=next_phase,
            spec_path=parent_run["spec_path"],
            spec_checksum=parent_run["spec_checksum"],
            approval_evidence=parent_run["approval_evidence"],
            graph_checksum=graph_checksum,
            children=graph_children,
            dependency_edges=dependency_edges,
        )
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent graph fix completed for {issue.id}; re-reviewing.\n\n"
                f"Parent phase: `{next_phase}`\n"
                f"Attempt: `{resolved_attempt_id}`"
            ),
        )

    ledger.record_attempt_result(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
    )
    return ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA parent graph fixing failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )


def run_parent_graph_spec_review_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.GRAPH_SPEC_REVIEWING.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent graph spec review skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    parent = _parent_spec_context_for_issue(
        issue=issue,
        parent_run=parent_run,
        repo_root=repo_root,
    )
    persisted_graph = ledger.load_graph(issue.id)
    phase = ParentPhase.GRAPH_SPEC_REVIEWING
    attempt_number = _next_attempt_number(
        ledger,
        target_kind="parent",
        target_id=issue.id,
        phase=phase.value,
    )
    attempt_id = f"{issue.id}-{phase.value}-{attempt_number}"
    request = build_parent_graph_spec_review_request(
        attempt_id=attempt_id,
        graph=ParentGraphContext(
            parent=parent,
            graph_checksum=str(persisted_graph["graph_checksum"]),
            children=tuple(persisted_graph["children"]),
            dependency_edges=tuple(persisted_graph["dependency_edges"]),
        ),
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )
    resolved_attempt_id = ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="parent",
        target_id=issue.id,
        phase=phase,
        idempotency_key=f"parent:{issue.id}:{phase.value}:{attempt_number}",
        request_json=request.to_ipc_payload(),
    )
    if resolved_attempt_id != request.attempt_id:
        request = replace(request, attempt_id=resolved_attempt_id)

    outcome = execution.run_role_attempt(request)
    if outcome.status == "succeeded":
        if outcome.role_result is None:
            raise GraphError("succeeded graph spec review requires role_result")
        if _is_passing_review(
            outcome.role_result, "submit_for_graph_execution_review"
        ):
            next_phase = _PARENT_ENGINE.next_phase(
                ParentPhase.GRAPH_SPEC_REVIEWING.value, outcome.role_result
            )
            ledger.record_attempt_result_and_parent_run(
                attempt_id=resolved_attempt_id,
                status=outcome.status,
                result_json=_attempt_result_json(outcome),
                error_message=outcome.error_message,
                parent_id=issue.id,
                phase=next_phase,
                spec_path=parent_run["spec_path"],
                spec_checksum=parent_run["spec_checksum"],
                approval_evidence=parent_run["approval_evidence"],
            )
            return ParentIntakeResult(
                target_state="In Progress",
                comment=_passed_review_comment(
                    gate="graph spec review",
                    issue_id=issue.id,
                    next_phase=next_phase,
                    attempt_id=resolved_attempt_id,
                    outcome=outcome,
                ),
            )

        # Graph spec review did not pass. A failed graph review is a workflow
        # verdict, not a protocol error: loop through a graph fixer (bounded),
        # falling back to human review once the fix budget is exhausted.
        return _route_failed_graph_review(
            issue=issue,
            ledger=ledger,
            resolved_attempt_id=resolved_attempt_id,
            outcome=outcome,
            parent_run=parent_run,
            gate="graph spec review",
        )

    ledger.record_attempt_result(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
    )
    return ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA parent graph spec review failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )


def run_parent_graph_execution_review_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.GRAPH_EXECUTION_REVIEWING.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent graph execution review skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    parent = _parent_spec_context_for_issue(
        issue=issue,
        parent_run=parent_run,
        repo_root=repo_root,
    )
    persisted_graph = ledger.load_graph(issue.id)
    phase = ParentPhase.GRAPH_EXECUTION_REVIEWING
    attempt_number = _next_attempt_number(
        ledger,
        target_kind="parent",
        target_id=issue.id,
        phase=phase.value,
    )
    attempt_id = f"{issue.id}-{phase.value}-{attempt_number}"
    request = build_parent_graph_execution_review_request(
        attempt_id=attempt_id,
        graph=ParentGraphContext(
            parent=parent,
            graph_checksum=str(persisted_graph["graph_checksum"]),
            children=tuple(persisted_graph["children"]),
            dependency_edges=tuple(persisted_graph["dependency_edges"]),
        ),
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )
    resolved_attempt_id = ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="parent",
        target_id=issue.id,
        phase=phase,
        idempotency_key=f"parent:{issue.id}:{phase.value}:{attempt_number}",
        request_json=request.to_ipc_payload(),
    )
    if resolved_attempt_id != request.attempt_id:
        request = replace(request, attempt_id=resolved_attempt_id)

    outcome = execution.run_role_attempt(request)
    if outcome.status == "succeeded":
        if outcome.role_result is None:
            raise GraphError("succeeded graph execution review requires role_result")
        if _is_passing_review(outcome.role_result, "publish_child_issues"):
            next_phase = _PARENT_ENGINE.next_phase(
                ParentPhase.GRAPH_EXECUTION_REVIEWING.value, outcome.role_result
            )
            ledger.record_attempt_result_and_parent_run(
                attempt_id=resolved_attempt_id,
                status=outcome.status,
                result_json=_attempt_result_json(outcome),
                error_message=outcome.error_message,
                parent_id=issue.id,
                phase=next_phase,
                spec_path=parent_run["spec_path"],
                spec_checksum=parent_run["spec_checksum"],
                approval_evidence=parent_run["approval_evidence"],
            )
            return ParentIntakeResult(
                target_state="In Progress",
                comment=_passed_review_comment(
                    gate="graph execution review",
                    issue_id=issue.id,
                    next_phase=next_phase,
                    attempt_id=resolved_attempt_id,
                    outcome=outcome,
                ),
            )

        # Failed graph execution review loops through the graph fixer (bounded),
        # falling back to human review once the fix budget is exhausted.
        return _route_failed_graph_review(
            issue=issue,
            ledger=ledger,
            resolved_attempt_id=resolved_attempt_id,
            outcome=outcome,
            parent_run=parent_run,
            gate="graph execution review",
        )

    ledger.record_attempt_result(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
    )
    return ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA parent graph execution review failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )


def run_parent_child_publication_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    backlog: BacklogPublicationAdapter,
    child_labels: frozenset[str] = frozenset(),
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.CHILD_PUBLICATION_READY.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA child publication skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    graph = ledger.load_graph(issue.id)
    graph_checksum = str(graph["graph_checksum"])
    children = _graph_children_from_persisted_graph(graph)
    dependency_edges = _dependency_edges_from_persisted_graph(graph, children)
    projections = ledger.load_child_issue_projections(issue.id)

    for child in children:
        node_id = str(child["node_id"])
        if node_id in projections:
            continue
        created = backlog.create_child(
            parent_id=issue.id,
            title=str(child["title"]),
            body=_child_issue_body(
                parent_id=issue.id,
                graph_checksum=graph_checksum,
                spec_path=parent_run["spec_path"],
                child=child,
                dependency_edges=dependency_edges,
            ),
            labels=child_labels,
        )
        ledger.record_child_issue_projection(
            parent_id=issue.id,
            node_id=node_id,
            issue_id=created.id,
        )
        projections[node_id] = created.id

    for child in children:
        blocked_id = projections[str(child["node_id"])]
        for dependency in child["dependencies"]:
            blocker_id = projections[str(dependency)]
            backlog.link_blocking(blocker_id=blocker_id, blocked_id=blocked_id)

    next_phase = PARENT_DEFINITION.stage(
        ParentPhase.CHILD_PUBLICATION_READY.value
    ).next_phase_on_success
    ledger.record_parent_run(
        parent_id=issue.id,
        phase=next_phase,
        spec_path=parent_run["spec_path"],
        spec_checksum=parent_run["spec_checksum"],
        approval_evidence=parent_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA child issues published for {issue.id}.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Published children: {len(children)}"
        ),
    )


def run_parent_child_acceptance_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    integration: ParentIntegration,
    integration_branch: str,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.CHILDREN_PUBLISHED.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA child acceptance skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    graph = ledger.load_graph(issue.id)
    children = _graph_children_from_persisted_graph(graph)
    dependency_edges = _dependency_edges_from_persisted_graph(graph, children)
    child_state = ledger.load_scheduler_state().children
    completed_accept_operations = ledger.load_parent_accept_operations()
    accepted_latest_child_ids: set[str] = set()
    projections = ledger.load_child_issue_projections(issue.id)

    for child in children:
        child_id = str(child["node_id"])
        state = child_state.get(child_id)
        if state is None or state.phase != ChildPhase.QUALITY_REVIEW_PASSED:
            continue
        candidate_ref = _latest_child_candidate_ref(ledger, child_id)
        if _has_completed_parent_accept_ref(
            completed_accept_operations,
            parent_id=issue.id,
            child_id=child_id,
            candidate_ref=candidate_ref,
        ):
            accepted_latest_child_ids.add(child_id)
            continue
        result = recover_or_apply_child_accept(
            ledger,
            integration,
            ChildAcceptOperation(
                operation_id=f"accept:{issue.id}:{child_id}:{candidate_ref}",
                idempotency_key=f"parent:{issue.id}:{child_id}:{candidate_ref}",
                parent_id=issue.id,
                child_id=child_id,
                candidate_ref=candidate_ref,
                integration_branch=integration_branch,
            ),
        )
        if result.status != "completed":
            return ParentIntakeResult(
                target_state="Blocked",
                comment=(
                    f"SMDA parent child acceptance failed for {issue.id}.\n\n"
                    f"Child: `{child_id}`\n"
                    f"Operation: `{result.operation_id}`\n"
                    f"Action: `{result.action}`"
                ),
            )
        accepted_latest_child_ids.add(child_id)
        completed_accept_operations = ledger.load_parent_accept_operations()
        child_issue_id = projections.get(child_id)
        if child_issue_id is not None:
            _record_child_accepted_tracker_effect(
                ledger,
                parent_id=issue.id,
                child_id=child_id,
                issue_id=child_issue_id,
                candidate_ref=candidate_ref,
                integration_branch=integration_branch,
            )

    if {str(child["node_id"]) for child in children} <= accepted_latest_child_ids:
        next_phase = PARENT_DEFINITION.stage(
            ParentPhase.CHILDREN_PUBLISHED.value
        ).next_phase_on_success
        ledger.record_parent_run(
            parent_id=issue.id,
            phase=next_phase,
            spec_path=parent_run["spec_path"],
            spec_checksum=parent_run["spec_checksum"],
            approval_evidence=parent_run["approval_evidence"],
        )
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent accepted all child candidates for {issue.id}.\n\n"
                f"Parent phase: `{next_phase}`"
            ),
        )

    return ParentIntakeResult(
        target_state="In Progress",
        comment=f"SMDA parent waiting for quality-passed children for {issue.id}.",
    )


def run_parent_qa_review_tick(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.PARENT_QA_READY.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent QA review skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    parent = _parent_spec_context_for_issue(
        issue=issue,
        parent_run=parent_run,
        repo_root=repo_root,
    )
    persisted_graph = ledger.load_graph(issue.id)
    phase = ParentPhase.PARENT_QA_REVIEWING
    attempt_number = _next_attempt_number(
        ledger,
        target_kind="parent",
        target_id=issue.id,
        phase=phase.value,
    )
    attempt_id = f"{issue.id}-{phase.value}-{attempt_number}"
    request = build_parent_qa_review_request(
        attempt_id=attempt_id,
        graph=ParentGraphContext(
            parent=parent,
            graph_checksum=str(persisted_graph["graph_checksum"]),
            children=tuple(persisted_graph["children"]),
            dependency_edges=tuple(persisted_graph["dependency_edges"]),
        ),
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )
    resolved_attempt_id = ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="parent",
        target_id=issue.id,
        phase=phase,
        idempotency_key=f"parent:{issue.id}:{phase.value}:{attempt_number}",
        request_json=request.to_ipc_payload(),
    )
    if resolved_attempt_id != request.attempt_id:
        request = replace(request, attempt_id=resolved_attempt_id)

    outcome = execution.run_role_attempt(request)
    if outcome.status == "succeeded":
        if outcome.role_result is None:
            raise GraphError("succeeded parent QA review requires role_result")
        route = (
            outcome.role_result.verdict,
            outcome.role_result.required_next_action,
        )
        if _is_passing_review(outcome.role_result, "accept_parent"):
            next_phase = _PARENT_ENGINE.next_phase(
                ParentPhase.PARENT_QA_READY.value, outcome.role_result
            )
        elif route == ("FAIL", "plan_remediation"):
            next_phase = _PARENT_ENGINE.next_phase(
                ParentPhase.PARENT_QA_READY.value, outcome.role_result
            )
        else:
            raise GraphError(
                "No parent transition for "
                f"phase={phase.value} verdict={outcome.role_result.verdict} "
                f"required_next_action={outcome.role_result.required_next_action}"
            )
        ledger.record_attempt_result_and_parent_run(
            attempt_id=resolved_attempt_id,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
            parent_id=issue.id,
            phase=next_phase,
            spec_path=parent_run["spec_path"],
            spec_checksum=parent_run["spec_checksum"],
            approval_evidence=parent_run["approval_evidence"],
        )
        if next_phase == ParentPhase.FINAL_ACCEPT_READY.value:
            return ParentIntakeResult(
                target_state="In Progress",
                comment=_passed_review_comment(
                    gate="QA review",
                    issue_id=issue.id,
                    next_phase=next_phase,
                    attempt_id=resolved_attempt_id,
                    outcome=outcome,
                ),
            )
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent QA review failed for {issue.id}; planning remediation.\n\n"
                f"Parent phase: `{next_phase}`\n"
                f"Attempt: `{resolved_attempt_id}`"
            ),
        )

    ledger.record_attempt_result(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
    )
    return ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA parent QA review failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )


def run_parent_remediation_planning_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    backlog: BacklogPublicationAdapter,
    child_labels: frozenset[str] = frozenset(),
    qa_bounds: QaBounds | None = None,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.REMEDIATION_PLANNING.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA remediation planning skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    graph = ledger.load_graph(issue.id)
    children = _graph_children_from_persisted_graph(graph)
    dependency_edges = _dependency_edges_from_persisted_graph(graph, children)
    if qa_bounds is not None and _remediation_bounds_exhausted(
        ledger,
        issue.id,
        children,
        qa_bounds=qa_bounds,
    ):
        next_phase = ParentPhase.HUMAN_REVIEW_REQUIRED.value
        ledger.record_parent_run(
            parent_id=issue.id,
            phase=next_phase,
            spec_path=parent_run["spec_path"],
            spec_checksum=parent_run["spec_checksum"],
            approval_evidence=parent_run["approval_evidence"],
        )
        return ParentIntakeResult(
            target_state="Human Review",
            comment=(
                f"SMDA remediation bounds exhausted for {issue.id}.\n\n"
                f"Parent phase: `{next_phase}`"
            ),
        )
    node_id = _next_remediation_node_id(children)
    if any(str(child["node_id"]) == node_id for child in children):
        raise GraphError(f"Remediation node already exists: {node_id}")

    report = _latest_parent_qa_failure_report(ledger, issue.id)
    remediation_child = {
        "node_id": node_id,
        "title": f"Remediate parent QA failure for {issue.id}",
        "body": (
            "Resolve the parent QA failure while preserving the approved parent "
            "spec and existing child issue boundaries.\n\n"
            f"Parent QA report:\n{report}"
        ),
        "acceptance_criteria": [
            "The parent QA failure is resolved.",
            "The approved parent spec remains satisfied.",
            "Configured quality gates pass.",
        ],
        "in_scope": ["parent QA remediation"],
        "out_of_scope": ["unrelated parent graph changes"],
        "touched_surfaces": {
            "files": ["<to-be-determined-by-remediation-worker>"],
            "modules": ["<to-be-determined-by-remediation-worker>"],
            "contracts": ["smda.parent-qa-remediation.v1"],
            "docs": ["<to-be-determined-by-remediation-worker>"],
            "tests": ["<to-be-determined-by-remediation-worker>"],
        },
        "verification": {
            "required": ["configured quality gates pass"],
            "smoke": [],
        },
        "risk_level": "medium",
        "dependencies": [str(child["node_id"]) for child in children],
    }
    updated_children = [*children, remediation_child]
    updated_dependency_edges = [
        *dependency_edges,
        *[
            {
                "from": str(child["node_id"]),
                "to": node_id,
                "type": "sequencing_only",
                "blocks_dispatch": True,
                "reason": (
                    "Remediation starts after the existing child has been accepted "
                    "into the parent integration branch."
                ),
                "required_artifacts": ["accepted_commit"],
            }
            for child in children
        ],
    ]
    graph_checksum = _graph_checksum(
        updated_children,
        dependency_edges=updated_dependency_edges,
    )
    ledger.record_graph(
        parent_id=issue.id,
        graph_checksum=graph_checksum,
        children=updated_children,
        dependency_edges=updated_dependency_edges,
    )

    created = backlog.create_child(
        parent_id=issue.id,
        title=str(remediation_child["title"]),
        body=_child_issue_body(
            parent_id=issue.id,
            graph_checksum=graph_checksum,
            spec_path=parent_run["spec_path"],
            child=remediation_child,
            dependency_edges=updated_dependency_edges,
        ),
        labels=child_labels,
    )
    ledger.record_child_issue_projection(
        parent_id=issue.id,
        node_id=node_id,
        issue_id=created.id,
    )

    projections = ledger.load_child_issue_projections(issue.id)
    for dependency in remediation_child["dependencies"]:
        backlog.link_blocking(
            blocker_id=projections[str(dependency)],
            blocked_id=created.id,
        )

    next_phase = PARENT_DEFINITION.stage(
        ParentPhase.REMEDIATION_PLANNING.value
    ).next_phase_on_success
    ledger.record_parent_run(
        parent_id=issue.id,
        phase=next_phase,
        spec_path=parent_run["spec_path"],
        spec_checksum=parent_run["spec_checksum"],
        approval_evidence=parent_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA remediation child published for {issue.id}.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Remediation child: `{created.id}`"
        ),
    )


def roadmap_integration_branch(roadmap_id: str) -> str:
    """The shared base branch roadmap members land onto (parent-tier base)."""
    return f"smda/{roadmap_id}/integration"


def resolve_parent_base(
    ledger: PhaseLedger,
    parent_id: str,
    *,
    standalone_base: str = "main",
) -> str:
    """The base branch a parent's FINAL_ACCEPT lands onto (ADR-0003).

    A roadmap member lands onto its roadmap-integration branch so later members
    build on landed work; a standalone parent lands onto ``standalone_base``.
    """
    membership = ledger.load_roadmap_for_member(parent_id)
    if membership is None:
        return standalone_base
    return roadmap_integration_branch(membership["roadmap_id"])


def run_parent_final_accept_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    integration: ParentLandIntegration | None = None,
    integration_branch: str | None = None,
    standalone_base: str = "main",
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.FINAL_ACCEPT_READY.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA final accept skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    # Real land (ADR-0003) when an integration seam is configured; otherwise the
    # historical no-op land path is preserved for parity.
    if integration is not None and integration_branch is not None:
        base_branch = resolve_parent_base(
            ledger, issue.id, standalone_base=standalone_base
        )
        # A roadmap member lands onto the shared roadmap-integration branch;
        # create it off the standalone base on first member land (ADR-0003).
        if base_branch != standalone_base:
            integration.ensure_branch(base_branch, start_point=standalone_base)
        # Read-only conflict probe before the land. A conflict is a dependency
        # discovered late (ADR-0003): route to bounded rebase + re-review instead
        # of landing.
        probe = integration.probe_conflict(head=integration_branch, base=base_branch)
        if not probe.clean:
            ledger.record_parent_run(
                parent_id=issue.id,
                phase=ParentPhase.LANDING_CONFLICT_REBASING.value,
                spec_path=parent_run["spec_path"],
                spec_checksum=parent_run["spec_checksum"],
                approval_evidence=parent_run["approval_evidence"],
            )
            return ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA final accept blocked by a base conflict for {issue.id} "
                    f"(base `{base_branch}`): {', '.join(probe.conflicted_paths)}. "
                    "Routing to bounded rebase + re-review."
                ),
            )
        land = ParentLandOperation(
            operation_id=f"parent-land:{issue.id}",
            idempotency_key=(
                f"parent-land:{issue.id}:{integration_branch}:{base_branch}"
            ),
            parent_id=issue.id,
            parent_ref=integration_branch,
            base_branch=base_branch,
        )
        outcome = recover_or_apply_parent_land(ledger, integration, land)
        if outcome.status != "completed":
            return ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA final accept land pending for {issue.id} "
                    f"(base `{base_branch}`): {outcome.action}"
                ),
            )

    report = _latest_parent_qa_pass_report(ledger, issue.id)
    ledger.record_tracker_effect(
        effect_id=f"final-accept-comment:{issue.id}",
        idempotency_key=f"final-accept-comment:{issue.id}",
        effect_type="comment",
        target_id=issue.id,
        payload={
            "body": (
                f"SMDA final accept completed for {issue.id}.\n\n"
                f"Parent QA report:\n{report}"
            )
        },
    )
    ledger.record_tracker_effect(
        effect_id=f"final-accept-state:{issue.id}",
        idempotency_key=f"final-accept-state:{issue.id}",
        effect_type="set_state",
        target_id=issue.id,
        payload={"state": "Done"},
    )
    next_phase = PARENT_DEFINITION.stage(
        ParentPhase.FINAL_ACCEPT_READY.value
    ).next_phase_on_success
    ledger.record_parent_run(
        parent_id=issue.id,
        phase=next_phase,
        spec_path=parent_run["spec_path"],
        spec_checksum=parent_run["spec_checksum"],
        approval_evidence=parent_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="Done",
        comment=(
            f"SMDA parent final accept recorded for {issue.id}.\n\n"
            f"Parent phase: `{next_phase}`"
        ),
    )


def run_landing_conflict_rebase_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    integration: ParentLandIntegration | None = None,
    integration_branch: str | None = None,
    standalone_base: str = "main",
    qa_bounds: QaBounds | None = None,
) -> ParentIntakeResult:
    """Rebase a conflict loser onto the landed base, then re-review (ADR-0003).

    The mandatory re-review (back through PARENT_QA_READY) catches rebase
    semantic breakage. Bounded by the existing parent QA cycle cap
    (QaBounds.max_parent_qa_cycles): once exhausted, escalate to
    HUMAN_REVIEW_REQUIRED instead of rebase livelock.
    """
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.LANDING_CONFLICT_REBASING.value:
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA landing-conflict rebase skipped for {issue.id}.\n\n"
                f"Current parent phase: `{parent_run['phase']}`"
            ),
        )

    if integration is None or integration_branch is None:
        raise GraphError(
            f"Landing-conflict rebase requires an integration seam: {issue.id}"
        )

    qa_cycles = len(_parent_qa_result_jsons(ledger, issue.id))
    if qa_bounds is not None and qa_cycles > qa_bounds.max_parent_qa_cycles:
        ledger.record_parent_run(
            parent_id=issue.id,
            phase=ParentPhase.HUMAN_REVIEW_REQUIRED.value,
            spec_path=parent_run["spec_path"],
            spec_checksum=parent_run["spec_checksum"],
            approval_evidence=parent_run["approval_evidence"],
        )
        return ParentIntakeResult(
            target_state="Blocked",
            comment=(
                f"SMDA landing-conflict rebase exhausted for {issue.id} after "
                f"{qa_cycles} parent QA cycles. Escalating to human review."
            ),
        )

    base_branch = resolve_parent_base(
        ledger, issue.id, standalone_base=standalone_base
    )
    integration.rebase_onto_base(head=integration_branch, base=base_branch)
    ledger.record_parent_run(
        parent_id=issue.id,
        phase=ParentPhase.PARENT_QA_READY.value,
        spec_path=parent_run["spec_path"],
        spec_checksum=parent_run["spec_checksum"],
        approval_evidence=parent_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA rebased {issue.id} onto `{base_branch}` after a base conflict; "
            "re-running parent QA review before re-attempting the land."
        ),
    )


def run_child_candidate_tick(
    *,
    issue: BacklogIssue,
    decision: CandidateRoutingDecision,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    now: float,
    owner: str,
) -> ChildCandidateTickResult:
    if decision.route != CandidateRoute.CHILD:
        raise GraphError(f"run_child_candidate_tick requires child route: {decision.route}")
    if decision.parent_issue_id is None or decision.node_id is None:
        raise GraphError("Child route is missing parent issue or node id")

    try:
        persisted_graph = ledger.load_graph(decision.parent_issue_id)
    except KeyError as error:
        raise GraphError(
            f"SMDA graph not found for child parent: {decision.parent_issue_id}"
        ) from error
    if (
        decision.graph_checksum is not None
        and str(persisted_graph["graph_checksum"]) != decision.graph_checksum
    ):
        raise GraphError(
            f"Stale child handle for {issue.id}: graph checksum "
            f"{decision.graph_checksum} != current "
            f"{persisted_graph['graph_checksum']}"
        )
    _assert_graph_contains_child(
        persisted_graph,
        parent_id=decision.parent_issue_id,
        child_id=decision.node_id,
    )

    gate = child_dependency_gate(
        parent_id=decision.parent_issue_id,
        child_id=decision.node_id,
        graph=persisted_graph,
        scheduler_state=ledger.load_scheduler_state(),
        attempts=ledger.load_attempts(),
        parent_accept_operations=ledger.load_parent_accept_operations(),
    )
    if not gate.eligible:
        _record_child_dependency_wait_effect(
            ledger,
            issue_id=issue.id,
            parent_id=decision.parent_issue_id,
            child_id=decision.node_id,
            graph_checksum=str(persisted_graph["graph_checksum"]),
            gate=gate,
        )
        return ChildCandidateTickResult(
            status="skipped",
            detail=gate.reason,
            state=ledger.load_scheduler_state(),
        )

    return run_sdd_candidate_tick(
        issue=issue,
        child_id=decision.node_id,
        parent_issue_id=decision.parent_issue_id,
        repo_context=repo_context,
        repo_root=repo_root,
        ledger=ledger,
        execution=execution,
        sandbox_provider=sandbox_provider,
        agent=agent,
        now=now,
        owner=owner,
        workflow_definition=CHILD_DEFINITION,
    )


def run_sdd_candidate_tick(
    *,
    issue: BacklogIssue,
    child_id: str,
    parent_issue_id: str,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    now: float,
    owner: str,
    workflow_definition: WorkflowDefinition,
) -> ChildCandidateTickResult:
    child = _child_task_context_from_issue(issue, child_id=child_id)
    state = run_child_workflow_tick(
        graph=WorkflowGraph(children={child_id: ChildNode(id=child_id)}),
        child_tasks={child_id: child},
        parent_issue_id=parent_issue_id,
        repo_context=repo_context,
        repo_root=repo_root,
        ledger=ledger,
        execution=execution,
        sandbox_provider=sandbox_provider,
        agent=agent,
        now=now,
        owner=owner,
        workflow_definition=workflow_definition,
    )
    _record_child_lifecycle_effect(ledger, issue.id, child_id, state)
    return ChildCandidateTickResult(
        status="dispatched",
        detail=f"{issue.id}:{state.children[child_id].phase}",
        state=state,
    )


def _child_task_context_from_issue(issue: BacklogIssue, *, child_id: str) -> ChildTaskContext:
    verification_required = _field_values(
        issue.body, "Verification required"
    ) or _field_values(issue.body, "Verification")
    return ChildTaskContext(
        child_id=child_id,
        title=issue.title,
        body=issue.body,
        in_scope=_field_values(issue.body, "In scope"),
        out_of_scope=_field_values(issue.body, "Out of scope"),
        touched_surfaces={
            "files": list(_field_values(issue.body, "Touched files")),
            "modules": list(_field_values(issue.body, "Touched modules")),
            "contracts": list(_field_values(issue.body, "Touched contracts")),
            "docs": list(_field_values(issue.body, "Touched docs")),
            "tests": list(_field_values(issue.body, "Touched tests")),
        },
        acceptance_criteria=_field_values(issue.body, "Acceptance criteria"),
        verification={
            "required": list(verification_required),
            "smoke": list(_field_values(issue.body, "Verification smoke")),
        },
        dependencies=_dependency_ids_from_issue_body(issue.body),
        dependency_outputs=_dependency_outputs_from_issue_body(issue.body),
    )


def run_child_workflow_tick(
    *,
    graph: WorkflowGraph,
    child_tasks: dict[str, ChildTaskContext],
    parent_issue_id: str,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    now: float,
    owner: str,
    workflow_definition: WorkflowDefinition = CHILD_DEFINITION,
) -> SchedulerState:
    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        try:
            child = child_tasks[dispatch.child_id]
        except KeyError as error:
            raise GraphError(
                f"Missing child task context: {dispatch.child_id}"
            ) from error

        findings = _review_findings_for_fixer(ledger, dispatch.child_id, dispatch.phase)
        if findings:
            child = replace(child, review_findings=findings)

        request = build_child_role_attempt_request(
            attempt_id=dispatch.attempt_id,
            parent_issue_id=parent_issue_id,
            child=child,
            phase=dispatch.phase,
            repo_context=repo_context,
            repo_root=repo_root,
            sandbox_provider=sandbox_provider,
            agent=agent,
        )
        return execution.run_role_attempt(request)

    return run_once_durable(
        graph,
        ledger,
        executor=executor,
        now=now,
        owner=owner,
        workflow_definition=workflow_definition,
    )


def _field_values(body: str, label: str) -> tuple[str, ...]:
    prefix = f"{label}:"
    values: list[str] = []
    for line in body.splitlines():
        if line.lower().startswith(prefix.lower()):
            value = line[len(prefix) :].strip()
            if value:
                values.append(value)
    return tuple(values)


def _dependency_ids_from_issue_body(body: str) -> tuple[str, ...]:
    dependency_ids: list[str] = []
    for reason in _field_values(body, "Dependency reasons"):
        match = re.match(r"(?P<dependency_id>[^ ]+)\s+->\s+[^:]+:\s+.+", reason)
        if match is None:
            continue
        dependency_ids.append(match.group("dependency_id"))
    return tuple(dependency_ids)


def _dependency_outputs_from_issue_body(
    body: str,
) -> tuple[dict[str, object], ...]:
    reasons = _field_values(body, "Dependency reasons")
    artifacts = _field_values(body, "Required artifacts")
    outputs: list[dict[str, object]] = []
    for index, reason in enumerate(reasons):
        match = re.match(r"(?P<dependency_id>[^ ]+)\s+->\s+[^:]+:\s+(?P<reason>.+)", reason)
        if match is None:
            continue
        required_artifacts = (
            [item.strip() for item in artifacts[index].split(",") if item.strip()]
            if index < len(artifacts)
            else []
        )
        outputs.append(
            {
                "dependency_id": match.group("dependency_id"),
                "required_artifacts": required_artifacts,
                "reason": match.group("reason").strip(),
            }
        )
    return tuple(outputs)


def _spec_path(body: str) -> str | None:
    match = re.search(r"(docs/superpowers/specs/[A-Za-z0-9_./-]+\.md)", body)
    return match.group(1) if match else None


def _read_repo_file(repo_root: Path, relative_path: str) -> str:
    root = repo_root.resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise GraphError(f"Spec path escapes repo root: {relative_path}") from error
    if not path.exists():
        raise GraphError(f"Spec path does not exist: {relative_path}")
    return path.read_text(encoding="utf-8")


def _front_matter_metadata(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}

    metadata: dict[str, str] = {}
    for line in lines[1:end_index]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = key.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in {"status", "approval_evidence", "approved_at", "approved_by"}:
            metadata[normalized] = value.strip()
    return metadata


def _parent_run_for(ledger: PhaseLedger, parent_id: str) -> dict[str, str]:
    for parent_run in ledger.load_parent_runs():
        if parent_run["parent_id"] == parent_id:
            return parent_run
    raise GraphError(f"Parent run state not found: {parent_id}")


def _parent_spec_context_for_issue(
    *,
    issue: BacklogIssue,
    parent_run: dict[str, str],
    repo_root: Path,
) -> ParentSpecContext:
    spec_text = _read_repo_file(repo_root, parent_run["spec_path"])
    spec_checksum = f"sha256:{hashlib.sha256(spec_text.encode('utf-8')).hexdigest()}"
    if spec_checksum != parent_run["spec_checksum"]:
        raise GraphError(
            "Approved spec checksum changed for "
            f"{issue.id}: expected {parent_run['spec_checksum']} got {spec_checksum}"
        )
    return ParentSpecContext(
        parent_issue_id=issue.id,
        title=issue.title,
        body=issue.body,
        spec_path=parent_run["spec_path"],
        spec_checksum=parent_run["spec_checksum"],
        approval_evidence=parent_run["approval_evidence"],
        spec_text=spec_text,
    )


def _open_parent_snapshot(
    backlog: BacklogPublicationAdapter | None,
    *,
    exclude_id: str,
) -> list[dict[str, object]]:
    if backlog is None or not hasattr(backlog, "list_issues"):
        return []
    list_issues = getattr(backlog, "list_issues")
    snapshot: list[dict[str, object]] = []
    for state in ("Todo", "In Progress"):
        page = list_issues(
            state=state,
            label="agent",
            parent_id=None,
            limit=100,
            cursor=None,
        )
        for issue in page.issues:
            if issue.id == exclude_id:
                continue
            if "Execution: smda" not in issue.body:
                continue
            snapshot.append(
                {
                    "issue_id": issue.id,
                    "title": issue.title,
                    "state": issue.state,
                    "source": _spec_path(issue.body) or "",
                }
            )
    return sorted(snapshot, key=lambda item: str(item["issue_id"]))


def _next_attempt_number(
    ledger: PhaseLedger,
    *,
    target_kind: str,
    target_id: str,
    phase: str,
) -> int:
    return (
        sum(
            1
            for attempt in ledger.load_attempts()
            if attempt["target_kind"] == target_kind
            and attempt["target_id"] == target_id
            and attempt["phase"] == phase
        )
        + 1
    )


def _attempt_result_json(outcome: AttemptOutcome) -> dict[str, object] | None:
    if (
        outcome.role_result is None
        and outcome.raw_result is None
        and not outcome.commits
        and outcome.branch is None
    ):
        return None
    result: dict[str, object] = {}
    if outcome.raw_result is not None:
        result.update(outcome.raw_result)
    if outcome.role_result is not None:
        result["verdict"] = outcome.role_result.verdict
        result["required_next_action"] = outcome.role_result.required_next_action
    if outcome.commits:
        result["commits"] = list(outcome.commits)
    if outcome.branch is not None:
        result["branch"] = outcome.branch
    if outcome.preserved_worktree_path is not None:
        result["preserved_worktree_path"] = outcome.preserved_worktree_path
    if outcome.schema_id is not None:
        result["schema_id"] = outcome.schema_id
    if outcome.schema_package_version is not None:
        result["schema_package_version"] = outcome.schema_package_version
    return result


def _graph_children_from_outcome(outcome: AttemptOutcome) -> list[dict[str, object]]:
    if outcome.raw_result is None:
        raise GraphError("graph decomposer succeeded without raw_result")
    children = outcome.raw_result.get("children")
    if not isinstance(children, list) or not children:
        raise GraphError("graph decomposer result must include non-empty children")

    normalized: list[dict[str, object]] = []
    graph_nodes: dict[str, ChildNode] = {}
    for child in children:
        if not isinstance(child, dict):
            raise GraphError("graph child must be an object")
        normalized_child = _normalize_graph_child(child)
        node_id = str(normalized_child["node_id"])
        dependencies = list(normalized_child["dependencies"])
        if node_id in graph_nodes:
            raise GraphError(f"Duplicate graph child id: {node_id}")
        graph_nodes[node_id] = ChildNode(
            id=node_id,
            dependencies=frozenset(dependencies),
        )
        normalized.append(normalized_child)
    validate_graph(WorkflowGraph(children=graph_nodes))
    return normalized


def _roadmap_members_from_outcome(outcome: AttemptOutcome) -> list[dict[str, object]]:
    if outcome.raw_result is None:
        raise GraphError("roadmap decomposer succeeded without raw_result")
    parents = outcome.raw_result.get("parents")
    if not isinstance(parents, list) or not parents:
        raise GraphError("roadmap decomposer result must include non-empty parents")

    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for parent in parents:
        if not isinstance(parent, dict):
            raise GraphError("roadmap parent must be an object")
        normalized_parent = {
            "node_id": _required_string(parent, "node_id"),
            "title": _required_string(parent, "title"),
            "body": _required_string(parent, "body"),
            "risk_level": _required_string(parent, "risk_level"),
            "dependencies": _string_list(parent.get("dependencies", []), "dependencies"),
        }
        node_id = str(normalized_parent["node_id"])
        if node_id in seen:
            raise GraphError(f"Duplicate roadmap parent id: {node_id}")
        seen.add(node_id)
        normalized.append(normalized_parent)
    _validate_roadmap_member_dependencies(normalized)
    return normalized


def _roadmap_edges_from_outcome(
    outcome: AttemptOutcome,
    members: list[dict[str, object]],
) -> list[dict[str, object]]:
    if outcome.raw_result is None:
        raise GraphError("roadmap decomposer succeeded without raw_result")
    raw_edges = outcome.raw_result.get("roadmap_edges", [])
    return _normalize_roadmap_edges(raw_edges, members)


def _normalize_roadmap_edges(
    value: object,
    members: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise GraphError("roadmap_edges must be a list")
    member_ids = {str(member["node_id"]) for member in members}
    normalized: list[dict[str, object]] = []
    for edge in value:
        if not isinstance(edge, dict):
            raise GraphError("roadmap edge must be an object")
        from_node = _required_string(edge, "from")
        to_node = _required_string(edge, "to")
        if from_node not in member_ids:
            raise GraphError(f"Roadmap edge references unknown source node: {from_node}")
        if to_node not in member_ids:
            raise GraphError(f"Roadmap edge references unknown target node: {to_node}")
        normalized.append(
            {
                "from": from_node,
                "to": to_node,
                "type": _required_string(edge, "type"),
                "blocks_dispatch": _required_bool(edge, "blocks_dispatch"),
                "reason": _required_dependency_edge_string(
                    edge.get("reason"), "roadmap edge reason"
                ),
            }
        )
    return normalized


def _validate_roadmap_member_dependencies(members: list[dict[str, object]]) -> None:
    member_ids = {str(member["node_id"]) for member in members}
    for member in members:
        unknown = [
            dependency
            for dependency in _string_list(member.get("dependencies", []), "dependencies")
            if dependency not in member_ids
        ]
        if unknown:
            names = ", ".join(sorted(unknown))
            raise GraphError(
                f"Roadmap parent {member['node_id']} has unknown dependency: {names}"
            )


def _roadmap_edges_for_publication(
    ledger: PhaseLedger,
    roadmap_id: str,
    members: list[dict[str, object]],
) -> list[dict[str, object]]:
    edges = ledger.load_roadmap_member_edges(roadmap_id)
    if edges:
        return edges
    fallback_edges: list[dict[str, object]] = []
    for member in members:
        for dependency in _string_list(member.get("dependencies", []), "dependencies"):
            fallback_edges.append(
                {
                    "from": dependency,
                    "to": str(member["node_id"]),
                    "type": "sequencing_only",
                    "blocks_dispatch": True,
                    "reason": f"{member['node_id']} depends on {dependency}",
                }
            )
    return fallback_edges


def _graph_checksum(
    children: list[dict[str, object]],
    *,
    dependency_edges: list[dict[str, object]] | None = None,
) -> str:
    encoded = json.dumps(
        {
            "children": children,
            "dependency_edges": dependency_edges or [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _graph_children_from_persisted_graph(
    graph: dict[str, object],
) -> list[dict[str, object]]:
    children = graph.get("children")
    if not isinstance(children, list) or not children:
        raise GraphError("persisted graph must include non-empty children")
    normalized: list[dict[str, object]] = []
    for child in children:
        if not isinstance(child, dict):
            raise GraphError("persisted graph child must be an object")
        normalized.append(_normalize_graph_child(child))
    return normalized


def _dependency_edges_from_outcome(
    outcome: AttemptOutcome,
    children: list[dict[str, object]],
) -> list[dict[str, object]]:
    if outcome.raw_result is None:
        raise GraphError("graph decomposer succeeded without raw_result")
    raw_edges = outcome.raw_result.get("dependency_edges")
    if raw_edges is None:
        raw_edges = outcome.raw_result.get("edges", [])
    return _normalize_dependency_edges(raw_edges, children)


def _dependency_edges_from_persisted_graph(
    graph: dict[str, object],
    children: list[dict[str, object]],
) -> list[dict[str, object]]:
    return _normalize_dependency_edges(graph.get("dependency_edges", []), children)


def _normalize_dependency_edges(
    value: object,
    children: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise GraphError("dependency_edges must be a list")

    graph_nodes = {
        str(child["node_id"]): ChildNode(
            id=str(child["node_id"]),
            dependencies=frozenset(
                _string_list(child.get("dependencies", []), "dependencies")
            ),
        )
        for child in children
    }
    normalized: list[dict[str, object]] = []
    edge_nodes: list[DependencyEdge] = []
    for edge in value:
        if not isinstance(edge, dict):
            raise GraphError("dependency edge must be an object")
        blocks_dispatch = edge.get("blocks_dispatch")
        if not isinstance(blocks_dispatch, bool):
            raise GraphError("dependency edge blocks_dispatch must be a boolean")
        required_artifacts = _required_string_list(
            edge.get("required_artifacts", []),
            "dependency edge required_artifacts",
        )
        normalized_edge = {
            "from": _required_string(edge, "from"),
            "to": _required_string(edge, "to"),
            "type": _required_string(edge, "type"),
            "blocks_dispatch": blocks_dispatch,
            "reason": _required_dependency_edge_string(
                edge.get("reason"),
                "dependency edge reason",
            ),
            "required_artifacts": required_artifacts,
        }
        normalized.append(normalized_edge)
        edge_nodes.append(
            DependencyEdge(
                from_node_id=str(normalized_edge["from"]),
                to_node_id=str(normalized_edge["to"]),
                type=str(normalized_edge["type"]),
                blocks_dispatch=blocks_dispatch,
                reason=str(normalized_edge["reason"]),
                required_artifacts=tuple(required_artifacts),
            )
        )
    validate_graph(
        WorkflowGraph(
            children=graph_nodes,
            dependency_edges=tuple(edge_nodes),
        )
    )
    return normalized


def _next_remediation_node_id(children: list[dict[str, object]]) -> str:
    prefix = "remediation-"
    existing_numbers = []
    for child in children:
        node_id = str(child["node_id"])
        if not node_id.startswith(prefix):
            continue
        suffix = node_id[len(prefix) :]
        if suffix.isdigit():
            existing_numbers.append(int(suffix))
    return f"{prefix}{max(existing_numbers, default=0) + 1:03d}"


def _remediation_bounds_exhausted(
    ledger: PhaseLedger,
    parent_id: str,
    children: list[dict[str, object]],
    *,
    qa_bounds: QaBounds,
) -> bool:
    remediation_count = sum(
        1
        for child in children
        if str(child["node_id"]).startswith("remediation-")
    )
    if remediation_count >= qa_bounds.max_total_remediation_children:
        return True

    qa_attempts = _parent_qa_result_jsons(ledger, parent_id)
    if len(qa_attempts) > qa_bounds.max_parent_qa_cycles:
        return True

    latest_report = _latest_parent_qa_failure_report(ledger, parent_id)
    latest_fingerprint = _feedback_fingerprint(latest_report)
    same_feedback_count = sum(
        1
        for result in qa_attempts
        if result.get("verdict") == "FAIL"
        and _feedback_fingerprint(str(result.get("report", ""))) == latest_fingerprint
    )
    return same_feedback_count > qa_bounds.max_same_feedback_fingerprint


def _parent_qa_result_jsons(
    ledger: PhaseLedger,
    parent_id: str,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for attempt in ledger.load_attempts():
        if (
            attempt["target_kind"] == "parent"
            and attempt["target_id"] == parent_id
            and attempt["phase"] == ParentPhase.PARENT_QA_REVIEWING.value
            and attempt["status"] == "succeeded"
            and isinstance(attempt["result_json"], dict)
        ):
            results.append(attempt["result_json"])
    return results


def _feedback_fingerprint(report: str) -> str:
    normalized = " ".join(report.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _latest_parent_qa_failure_report(ledger: PhaseLedger, parent_id: str) -> str:
    return _latest_parent_qa_report(
        ledger,
        parent_id,
        verdicts=("FAIL",),
        fallback="Parent QA requested remediation, but no report was recorded.",
    )


def _latest_parent_qa_pass_report(ledger: PhaseLedger, parent_id: str) -> str:
    return _latest_parent_qa_report(
        ledger,
        parent_id,
        verdicts=("PASS", "DONE_WITH_CONCERNS"),
        fallback="Parent QA passed, but no report was recorded.",
    )


# Bounded graph review->fix->review cycles before escalating to human review.
_MAX_GRAPH_FIX_CYCLES = 2


def _latest_graph_review_findings(ledger: PhaseLedger, parent_id: str) -> str:
    review_phases = {
        ParentPhase.GRAPH_SPEC_REVIEWING.value,
        ParentPhase.GRAPH_EXECUTION_REVIEWING.value,
    }
    for attempt in reversed(ledger.load_attempts()):
        if (
            attempt["target_kind"] == "parent"
            and attempt["target_id"] == parent_id
            and attempt["phase"] in review_phases
            and attempt["status"] == "succeeded"
        ):
            result = attempt["result_json"]
            if isinstance(result, dict):
                report = result.get("report")
                if isinstance(report, str) and report.strip():
                    return report.strip()
    return "No graph review findings were recorded."


def _is_passing_review(role_result, expected_action: str) -> bool:
    # PASS and DONE_WITH_CONCERNS both proceed; DONE_WITH_CONCERNS just carries a
    # recorded concern in the report rather than blocking for a fix loop.
    return (
        role_result.required_next_action == expected_action
        and role_result.verdict in ("PASS", "DONE_WITH_CONCERNS")
    )


def _review_report(outcome: AttemptOutcome) -> str:
    report = (outcome.raw_result or {}).get("report")
    if isinstance(report, str) and report.strip():
        return report.strip()
    return ""


def _passed_review_comment(
    *, gate: str, issue_id: str, next_phase: str, attempt_id: str, outcome: AttemptOutcome
) -> str:
    verdict = outcome.role_result.verdict if outcome.role_result else "PASS"
    headline = "passed with concerns" if verdict == "DONE_WITH_CONCERNS" else "passed"
    body = (
        f"SMDA parent {gate} {headline} for {issue_id}.\n\n"
        f"Parent phase: `{next_phase}`\n"
        f"Attempt: `{attempt_id}`"
    )
    report = _review_report(outcome)
    if report:
        body += f"\n\nReviewer report:\n{report}"
    return body


def _graph_review_findings(outcome: AttemptOutcome, gate: str) -> str:
    report = (outcome.raw_result or {}).get("report")
    if isinstance(report, str) and report.strip():
        return report.strip()
    return f"{gate} reported a failure without a report."


def _route_failed_graph_review(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    resolved_attempt_id: str,
    outcome: AttemptOutcome,
    parent_run: dict[str, str],
    gate: str,
) -> ParentIntakeResult:
    prior_fix_cycles = (
        _next_attempt_number(
            ledger,
            target_kind="parent",
            target_id=issue.id,
            phase=ParentPhase.GRAPH_FIXING.value,
        )
        - 1
    )
    if prior_fix_cycles >= _MAX_GRAPH_FIX_CYCLES:
        return _route_graph_review_to_human_review(
            issue=issue,
            ledger=ledger,
            resolved_attempt_id=resolved_attempt_id,
            outcome=outcome,
            parent_run=parent_run,
            gate=f"{gate} (graph fix budget exhausted)",
        )

    next_phase = ParentPhase.GRAPH_FIXING.value
    ledger.record_attempt_result_and_parent_run(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
        parent_id=issue.id,
        phase=next_phase,
        spec_path=parent_run["spec_path"],
        spec_checksum=parent_run["spec_checksum"],
        approval_evidence=parent_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA parent {gate} failed for {issue.id}; routing to graph fix.\n\n"
            f"Findings:\n{_graph_review_findings(outcome, gate)}\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`"
        ),
    )


def _route_graph_review_to_human_review(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    resolved_attempt_id: str,
    outcome: AttemptOutcome,
    parent_run: dict[str, str],
    gate: str,
) -> ParentIntakeResult:
    report = (outcome.raw_result or {}).get("report")
    if not isinstance(report, str) or not report.strip():
        report = f"{gate} reported a failure without a report."
    next_phase = ParentPhase.HUMAN_REVIEW_REQUIRED.value
    ledger.record_attempt_result_and_parent_run(
        attempt_id=resolved_attempt_id,
        status=outcome.status,
        result_json=_attempt_result_json(outcome),
        error_message=outcome.error_message,
        parent_id=issue.id,
        phase=next_phase,
        spec_path=parent_run["spec_path"],
        spec_checksum=parent_run["spec_checksum"],
        approval_evidence=parent_run["approval_evidence"],
    )
    return ParentIntakeResult(
        target_state="Human Review",
        comment=(
            f"SMDA parent {gate} requires human review for {issue.id}.\n\n"
            f"Findings:\n{report.strip()}\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`"
        ),
    )


# Child SDD phase -> consumer tracker state. Active phases map to In Progress;
# the terminal/parked phases get their own coarse state.
_CHILD_PHASE_TRACKER_STATE: dict[ChildPhase, str] = {
    ChildPhase.QUALITY_REVIEW_PASSED: "Agent Review",
    ChildPhase.HUMAN_REVIEW_REQUIRED: "Human Review",
}


def _assert_graph_contains_child(
    graph: dict,
    *,
    parent_id: str,
    child_id: str,
) -> None:
    child_ids = {
        str(child["node_id"])
        for child in graph.get("children", [])
        if isinstance(child, dict) and "node_id" in child
    }
    if child_id not in child_ids:
        raise GraphError(
            f"Child node {child_id} is not present in current graph for {parent_id}"
        )


def _record_child_dependency_wait_effect(
    ledger: PhaseLedger,
    *,
    issue_id: str,
    parent_id: str,
    child_id: str,
    graph_checksum: str,
    gate: ChildDependencyGateResult,
) -> None:
    blocked_key = ",".join(gate.blocked_by)
    missing_key = ",".join(gate.missing_artifacts)
    key = hashlib.sha256(
        f"{parent_id}:{child_id}:{graph_checksum}:{blocked_key}:{missing_key}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    body = (
        f"SMDA is waiting to dispatch {issue_id} until dependencies are accepted.\n\n"
        f"Child node: `{child_id}`\n"
        f"Blocked by: {', '.join(gate.blocked_by)}\n"
        f"Missing artifacts: {', '.join(gate.missing_artifacts)}"
    )
    ledger.record_tracker_effect(
        effect_id=f"child-dependency-wait:{issue_id}:{key}",
        idempotency_key=f"child-dependency-wait:{issue_id}:{key}",
        effect_type="comment",
        target_id=issue_id,
        payload={"body": body},
    )


def _record_child_accepted_tracker_effect(
    ledger: PhaseLedger,
    *,
    parent_id: str,
    child_id: str,
    issue_id: str,
    candidate_ref: str,
    integration_branch: str,
) -> None:
    key = hashlib.sha256(
        f"{parent_id}:{child_id}:{candidate_ref}:{integration_branch}".encode("utf-8")
    ).hexdigest()[:16]
    body = (
        f"SMDA child {issue_id} accepted into parent integration branch.\n\n"
        f"Parent: `{parent_id}`\n"
        f"Child node: `{child_id}`\n"
        f"Candidate ref: `{candidate_ref}`\n"
        f"Integration branch: `{integration_branch}`"
    )
    ledger.record_tracker_effect(
        effect_id=f"child-accepted-state:{issue_id}:{key}",
        idempotency_key=f"child-accepted-state:{issue_id}:{key}",
        effect_type="set_state",
        target_id=issue_id,
        payload={"state": "Done"},
    )
    ledger.record_tracker_effect(
        effect_id=f"child-accepted-comment:{issue_id}:{key}",
        idempotency_key=f"child-accepted-comment:{issue_id}:{key}",
        effect_type="comment",
        target_id=issue_id,
        payload={"body": body},
    )


def _record_child_lifecycle_effect(
    ledger: PhaseLedger,
    issue_id: str,
    child_id: str,
    state: SchedulerState,
) -> None:
    """Sync a child SDD phase change to the child issue's tracker state.

    Parent transitions already sync; without this, child issues never reflect
    their In Progress / Agent Review / Human Review lifecycle in the tracker.
    Keyed by phase so repeated ticks at the same phase dedupe.
    """
    child = state.children.get(child_id)
    if child is None:
        return
    tracker_state = _CHILD_PHASE_TRACKER_STATE.get(child.phase, "In Progress")
    key = child.phase.value
    body = f"SMDA child {issue_id} reached `{key}`."
    report = _latest_child_report(ledger, child_id)
    if report:
        body += f"\n\nLatest report:\n{report}"
    ledger.record_tracker_effect(
        effect_id=f"child-lifecycle-state:{issue_id}:{key}",
        idempotency_key=f"child-lifecycle-state:{issue_id}:{key}",
        effect_type="set_state",
        target_id=issue_id,
        payload={"state": tracker_state},
    )
    ledger.record_tracker_effect(
        effect_id=f"child-lifecycle-comment:{issue_id}:{key}",
        idempotency_key=f"child-lifecycle-comment:{issue_id}:{key}",
        effect_type="comment",
        target_id=issue_id,
        payload={"body": body},
    )


def _latest_child_report(ledger: PhaseLedger, child_id: str) -> str | None:
    for attempt in reversed(ledger.load_attempts()):
        if attempt["target_kind"] != "child" or attempt["target_id"] != child_id:
            continue
        result = attempt["result_json"]
        if isinstance(result, dict):
            report = result.get("report")
            if isinstance(report, str) and report.strip():
                return report.strip()
        if attempt.get("error_message"):
            return str(attempt["error_message"])
        return None
    return None


# Fixing phase -> the review phase whose findings the fixer must act on.
_FIXER_REVIEW_PHASE: dict[ChildPhase, ChildPhase] = {
    ChildPhase.FIXING_SPEC: ChildPhase.SPEC_REVIEWING,
    ChildPhase.FIXING_QUALITY: ChildPhase.QUALITY_REVIEWING,
}


def _review_findings_for_fixer(
    ledger: PhaseLedger,
    child_id: str,
    fixing_phase: ChildPhase,
) -> tuple[str, ...]:
    """Carry the latest review report into a fixer attempt.

    Without this the fixer runs blind on the same defect, wasting an agent run
    and risking a review->fix->review livelock.
    """
    review_phase = _FIXER_REVIEW_PHASE.get(fixing_phase)
    if review_phase is None:
        return ()
    for attempt in reversed(ledger.load_attempts()):
        if (
            attempt["target_kind"] == "child"
            and attempt["target_id"] == child_id
            and attempt["phase"] == review_phase.value
            and attempt["status"] == "succeeded"
        ):
            result = attempt["result_json"]
            if isinstance(result, dict):
                report = result.get("report")
                if isinstance(report, str) and report.strip():
                    return (report.strip(),)
    return ()


def _latest_parent_qa_report(
    ledger: PhaseLedger,
    parent_id: str,
    *,
    verdicts: tuple[str, ...],
    fallback: str,
) -> str:
    for attempt in reversed(ledger.load_attempts()):
        if (
            attempt["target_kind"] == "parent"
            and attempt["target_id"] == parent_id
            and attempt["phase"] == ParentPhase.PARENT_QA_REVIEWING.value
            and attempt["status"] == "succeeded"
        ):
            result = attempt["result_json"]
            if isinstance(result, dict):
                if result.get("verdict") not in verdicts:
                    continue
                report = result.get("report")
                if isinstance(report, str) and report.strip():
                    return report.strip()
    return fallback


def _child_issue_body(
    *,
    parent_id: str,
    graph_checksum: str,
    spec_path: str,
    child: dict[str, object],
    dependency_edges: list[dict[str, object]] | None = None,
) -> str:
    touched_surfaces = child.get("touched_surfaces", {})
    if not isinstance(touched_surfaces, dict):
        raise GraphError("graph child touched_surfaces must be an object")
    verification = child.get("verification", {})
    if not isinstance(verification, dict):
        raise GraphError("graph child verification must be an object")
    incoming_edges = [
        edge
        for edge in dependency_edges or []
        if str(edge.get("to")) == str(child["node_id"])
    ]

    context_lines = [
        *_prefixed_lines("In scope", _string_list(child.get("in_scope", []), "in_scope")),
        *_prefixed_lines(
            "Out of scope",
            _string_list(child.get("out_of_scope", []), "out_of_scope"),
        ),
        *_prefixed_lines(
            "Touched files",
            _string_list(touched_surfaces.get("files", []), "touched_surfaces.files"),
        ),
        *_prefixed_lines(
            "Touched modules",
            _string_list(
                touched_surfaces.get("modules", []),
                "touched_surfaces.modules",
            ),
        ),
        *_prefixed_lines(
            "Touched contracts",
            _string_list(
                touched_surfaces.get("contracts", []),
                "touched_surfaces.contracts",
            ),
        ),
        *_prefixed_lines(
            "Touched docs",
            _string_list(touched_surfaces.get("docs", []), "touched_surfaces.docs"),
        ),
        *_prefixed_lines(
            "Touched tests",
            _string_list(touched_surfaces.get("tests", []), "touched_surfaces.tests"),
        ),
        *_prefixed_lines(
            "Acceptance criteria",
            _string_list(child.get("acceptance_criteria", []), "acceptance_criteria"),
        ),
        *_prefixed_lines(
            "Verification required",
            _string_list(verification.get("required", []), "verification.required"),
        ),
        *_prefixed_lines(
            "Verification smoke",
            _string_list(verification.get("smoke", []), "verification.smoke"),
        ),
        f"Risk level: {child['risk_level']}",
        *_dependency_reason_lines(incoming_edges),
    ]

    return "\n".join(
        [
            "Execution: smda-child",
            f"Parent issue: {parent_id}",
            f"Graph checksum: {graph_checksum}",
            f"Node id: {child['node_id']}",
            f"Source: {spec_path}",
            *context_lines,
            "",
            str(child["body"]),
        ]
    )


def _roadmap_member_issue_body(
    *,
    roadmap_id: str,
    spec_path: str,
    member: dict[str, object],
) -> str:
    dependencies = _string_list(member.get("dependencies", []), "dependencies")
    lines = [
        "Execution: smda",
        f"Source: {spec_path}",
        f"Roadmap issue: {roadmap_id}",
        f"Roadmap node id: {member['node_id']}",
        f"Risk level: {member['risk_level']}",
        *_prefixed_lines("Roadmap dependencies", dependencies),
        "",
        str(member["body"]),
    ]
    return "\n".join(lines)


def _prefixed_lines(prefix: str, values: list[str]) -> list[str]:
    if not values:
        return [f"{prefix}: none"]
    return [f"{prefix}: {value}" for value in values]


def _dependency_reason_lines(edges: list[dict[str, object]]) -> list[str]:
    if not edges:
        return ["Dependency reasons: none"]
    lines: list[str] = []
    for edge in edges:
        lines.append(
            "Dependency reasons: "
            f"{edge['from']} -> {edge['to']} "
            f"({edge['type']}, blocks_dispatch={edge['blocks_dispatch']}): "
            f"{edge['reason']}"
        )
        lines.extend(
            _prefixed_lines(
                "Required artifacts",
                _string_list(
                    edge.get("required_artifacts", []),
                    "dependency edge required_artifacts",
                ),
            )
        )
    return lines


def _has_completed_parent_accept_ref(
    operations: list[dict],
    *,
    parent_id: str,
    child_id: str,
    candidate_ref: str,
) -> bool:
    return any(
        operation["parent_id"] == parent_id
        and operation["child_id"] == child_id
        and operation["candidate_ref"] == candidate_ref
        and operation["status"] == "completed"
        for operation in operations
    )


def _latest_child_candidate_ref(ledger: PhaseLedger, child_id: str) -> str:
    candidate_ref = latest_quality_candidate_ref(ledger.load_attempts(), child_id)
    if candidate_ref is None:
        raise GraphError(f"Accepted child has no candidate ref: {child_id}")
    return candidate_ref


def _required_string(value: dict[str, object], key: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field:
        raise GraphError(f"graph child missing {key}")
    return field


def _required_bool(value: dict[str, object], key: str) -> bool:
    field = value.get(key)
    if not isinstance(field, bool):
        raise GraphError(f"{key} must be a boolean")
    return field


def _required_dependency_edge_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise GraphError(f"{field_name} must not be empty")
    return value


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise GraphError(f"graph child {field_name} must be a string list")
    return value


def _required_string_list(value: object, field_name: str) -> list[str]:
    values = _string_list(value, field_name)
    if not values:
        raise GraphError(f"graph child {field_name} must not be empty")
    return values


def _normalize_graph_child(child: dict[str, object]) -> dict[str, object]:
    risk_level = _required_string(child, "risk_level")
    if risk_level not in {"low", "medium", "high"}:
        raise GraphError("graph child risk_level must be one of: low, medium, high")

    return {
        "node_id": _required_string(child, "node_id"),
        "title": _required_string(child, "title"),
        "body": _required_string(child, "body"),
        "in_scope": _required_string_list(child.get("in_scope", []), "in_scope"),
        "out_of_scope": _required_string_list(
            child.get("out_of_scope", []),
            "out_of_scope",
        ),
        "touched_surfaces": _required_surface_map(child.get("touched_surfaces")),
        "acceptance_criteria": _required_string_list(
            child.get("acceptance_criteria", []),
            "acceptance_criteria",
        ),
        "verification": _required_verification(child.get("verification")),
        "risk_level": risk_level,
        "dependencies": _string_list(child.get("dependencies", []), "dependencies"),
    }


def _required_surface_map(value: object) -> dict[str, list[str]]:
    required_keys = ("files", "modules", "contracts", "docs", "tests")
    if not isinstance(value, dict):
        raise GraphError("graph child touched_surfaces must be an object")
    return {
        key: _required_string_list(value.get(key, []), f"touched_surfaces.{key}")
        for key in required_keys
    }


def _required_verification(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise GraphError("graph child verification must be an object")
    return {
        "required": _required_string_list(
            value.get("required", []),
            "verification.required",
        ),
        "smoke": _string_list(value.get("smoke", []), "verification.smoke"),
    }
