from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import CandidateRoute, CandidateRoutingDecision
from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.parent_acceptance import (
    ChildAcceptOperation,
    ParentIntegration,
    recover_or_apply_child_accept,
)
from smda_scheduler.role_attempts import (
    AgentSelection,
    ChildTaskContext,
    ParentGraphContext,
    ParentSpecContext,
    build_child_role_attempt_request,
    build_parent_graph_decomposer_request,
    build_parent_graph_execution_review_request,
    build_parent_graph_spec_review_request,
    build_parent_qa_review_request,
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
    WorkflowGraph,
    validate_graph,
)


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


@dataclass(frozen=True)
class ParentIntakeResult:
    target_state: str
    comment: str


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
    qa_bounds: QaBounds | None = None,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    phase = parent_run["phase"]
    if phase == "SPEC_FINALIZED":
        return run_parent_graph_decomposition_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=repo_root,
            ledger=ledger,
            execution=execution,
            sandbox_provider=sandbox_provider,
            agent=agent,
            owner=owner,
        )
    if phase == ParentPhase.GRAPH_SPEC_REVIEWING.value:
        return run_parent_graph_spec_review_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=repo_root,
            ledger=ledger,
            execution=execution,
            sandbox_provider=sandbox_provider,
            agent=agent,
            owner=owner,
        )
    if phase == ParentPhase.GRAPH_EXECUTION_REVIEWING.value:
        return run_parent_graph_execution_review_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=repo_root,
            ledger=ledger,
            execution=execution,
            sandbox_provider=sandbox_provider,
            agent=agent,
            owner=owner,
        )
    if phase == ParentPhase.CHILD_PUBLICATION_READY.value:
        return run_parent_child_publication_tick(
            issue=issue,
            ledger=ledger,
            backlog=backlog,
            child_labels=child_labels,
        )
    if phase == ParentPhase.CHILDREN_PUBLISHED.value:
        if integration is None or integration_branch is None:
            return ParentIntakeResult(
                target_state="Blocked",
                comment=(
                    f"SMDA child acceptance is not configured for {issue.id}."
                ),
            )
        return run_parent_child_acceptance_tick(
            issue=issue,
            ledger=ledger,
            integration=integration,
            integration_branch=integration_branch,
        )
    if phase == ParentPhase.PARENT_QA_READY.value:
        return run_parent_qa_review_tick(
            issue=issue,
            repo_context=repo_context,
            repo_root=repo_root,
            ledger=ledger,
            execution=execution,
            sandbox_provider=sandbox_provider,
            agent=agent,
            owner=owner,
        )
    if phase == ParentPhase.REMEDIATION_PLANNING.value:
        return run_parent_remediation_planning_tick(
            issue=issue,
            ledger=ledger,
            backlog=backlog,
            child_labels=child_labels,
            qa_bounds=qa_bounds,
        )
    if phase == ParentPhase.FINAL_ACCEPT_READY.value:
        return run_parent_final_accept_tick(
            issue=issue,
            ledger=ledger,
        )
    return ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA parent workflow idle for {issue.id}.\n\n"
            f"Current parent phase: `{phase}`"
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
        next_phase = ParentPhase.GRAPH_SPEC_REVIEWING.value
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
        if (
            outcome.role_result.verdict,
            outcome.role_result.required_next_action,
        ) != ("PASS", "submit_for_graph_execution_review"):
            raise GraphError(
                "No parent transition for "
                f"phase={phase.value} verdict={outcome.role_result.verdict} "
                f"required_next_action={outcome.role_result.required_next_action}"
            )
        next_phase = ParentPhase.GRAPH_EXECUTION_REVIEWING.value
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
                f"SMDA parent graph spec review passed for {issue.id}.\n\n"
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
        if (
            outcome.role_result.verdict,
            outcome.role_result.required_next_action,
        ) != ("PASS", "publish_child_issues"):
            raise GraphError(
                "No parent transition for "
                f"phase={phase.value} verdict={outcome.role_result.verdict} "
                f"required_next_action={outcome.role_result.required_next_action}"
            )
        next_phase = ParentPhase.CHILD_PUBLICATION_READY.value
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
                f"SMDA parent graph execution review passed for {issue.id}.\n\n"
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

    next_phase = ParentPhase.CHILDREN_PUBLISHED.value
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
    accepted_child_ids = _completed_parent_accept_child_ids(ledger, issue.id)

    for child in children:
        child_id = str(child["node_id"])
        if child_id in accepted_child_ids:
            continue
        state = child_state.get(child_id)
        if state is None or state.phase != ChildPhase.QUALITY_REVIEW_PASSED:
            continue
        candidate_ref = _latest_child_candidate_ref(ledger, child_id)
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
        accepted_child_ids.add(child_id)

    if {str(child["node_id"]) for child in children} <= accepted_child_ids:
        next_phase = ParentPhase.PARENT_QA_READY.value
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
        if route == ("PASS", "accept_parent"):
            next_phase = ParentPhase.FINAL_ACCEPT_READY.value
        elif route == ("FAIL", "plan_remediation"):
            next_phase = ParentPhase.REMEDIATION_PLANNING.value
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
        label = "passed" if next_phase == ParentPhase.FINAL_ACCEPT_READY.value else "failed"
        return ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent QA review {label} for {issue.id}.\n\n"
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

    next_phase = ParentPhase.CHILDREN_PUBLISHED.value
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


def run_parent_final_accept_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
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
    next_phase = ParentPhase.FINAL_ACCEPTED.value
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
) -> SchedulerState:
    if decision.route != CandidateRoute.CHILD:
        raise GraphError(f"run_child_candidate_tick requires child route: {decision.route}")
    if decision.parent_issue_id is None or decision.node_id is None:
        raise GraphError("Child route is missing parent issue or node id")

    child = ChildTaskContext(
        child_id=decision.node_id,
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
            "required": list(_field_values(issue.body, "Verification required")),
            "smoke": list(_field_values(issue.body, "Verification smoke")),
        },
        dependencies=_dependency_ids_from_issue_body(issue.body),
        dependency_outputs=_dependency_outputs_from_issue_body(issue.body),
    )
    return run_child_workflow_tick(
        graph=WorkflowGraph(children={decision.node_id: ChildNode(id=decision.node_id)}),
        child_tasks={decision.node_id: child},
        parent_issue_id=decision.parent_issue_id,
        repo_context=repo_context,
        repo_root=repo_root,
        ledger=ledger,
        execution=execution,
        sandbox_provider=sandbox_provider,
        agent=agent,
        now=now,
        owner=owner,
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
        verdict="FAIL",
        fallback="Parent QA requested remediation, but no report was recorded.",
    )


def _latest_parent_qa_pass_report(ledger: PhaseLedger, parent_id: str) -> str:
    return _latest_parent_qa_report(
        ledger,
        parent_id,
        verdict="PASS",
        fallback="Parent QA passed, but no report was recorded.",
    )


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
    verdict: str,
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
                if result.get("verdict") != verdict:
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


def _completed_parent_accept_child_ids(ledger: PhaseLedger, parent_id: str) -> set[str]:
    return {
        operation["child_id"]
        for operation in ledger.load_parent_accept_operations()
        if operation["parent_id"] == parent_id and operation["status"] == "completed"
    }


def _latest_child_candidate_ref(ledger: PhaseLedger, child_id: str) -> str:
    for attempt in reversed(ledger.load_attempts()):
        if (
            attempt["target_kind"] == "child"
            and attempt["target_id"] == child_id
            and attempt["phase"] == ChildPhase.QUALITY_REVIEWING.value
            and attempt["status"] == "succeeded"
        ):
            result = attempt["result_json"] or {}
            branch = result.get("branch")
            if isinstance(branch, str) and branch:
                return branch
            commits = result.get("commits")
            if isinstance(commits, list) and commits and isinstance(commits[-1], str):
                return commits[-1]
    raise GraphError(f"Accepted child has no candidate ref: {child_id}")


def _required_string(value: dict[str, object], key: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field:
        raise GraphError(f"graph child missing {key}")
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
