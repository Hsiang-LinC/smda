from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import CandidateRoute, CandidateRoutingDecision
from smda_scheduler.child_dependency_gate import (
    ChildDependencyGateResult,
    child_dependency_gate,
)
from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.git_integration import GitParentIntegration
from smda_scheduler.harness_acceptance import (
    AcceptanceError, AcceptancePolicy, snapshot_candidate, verify_candidate,
    run_candidate_review, land_candidate, check_candidate_source, require_ancestor,
)
from smda_scheduler.phase_ledger import (
    AttemptResultUpdate,
    BacklogEffect,
    PhaseLedger,
    RoadmapMembersUpdate,
)
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
    build_parent_accept_conflict_resolver_request,
    build_child_role_attempt_request,
    build_parent_graph_decomposer_request,
    build_parent_graph_fixer_request,
    build_parent_graph_execution_review_request,
    build_parent_graph_spec_review_request,
    build_parent_qa_review_request,
    build_roadmap_decomposer_request,
)
from smda_scheduler.roadmap_publication import publish_roadmap_members
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
from smda_scheduler.workflow_graph import WorkflowGraphArtifact, WorkflowGraphChild
from smda_scheduler.workflow_engine import (
    CHILD_DEFINITION,
    PARENT_DEFINITION,
    ROADMAP_DEFINITION,
    ParentTickContext,
    StageSpec,
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


def _parent_lifecycle_effects(
    *, issue_id: str, target_state: str, comment: str
) -> tuple[BacklogEffect, BacklogEffect]:
    key = hashlib.sha256(comment.encode("utf-8")).hexdigest()[:16]
    return (
        BacklogEffect(
            effect_id=f"lifecycle-comment:{issue_id}:{key}",
            idempotency_key=f"lifecycle-comment:{issue_id}:{key}",
            effect_type="comment",
            target_id=issue_id,
            payload={"body": comment},
        ),
        BacklogEffect(
            effect_id=f"lifecycle-state:{issue_id}:{key}",
            idempotency_key=f"lifecycle-state:{issue_id}:{key}",
            effect_type="set_state",
            target_id=issue_id,
            payload={"state": target_state},
        ),
    )


def _record_nontransition_parent_result(
    ledger: PhaseLedger,
    issue_id: str,
    result: ParentIntakeResult,
) -> ParentIntakeResult:
    for effect in _parent_lifecycle_effects(
        issue_id=issue_id,
        target_state=result.target_state,
        comment=result.comment,
    ):
        ledger.record_tracker_effect(
            effect_id=effect.effect_id,
            idempotency_key=effect.idempotency_key,
            effect_type=effect.effect_type,
            target_id=effect.target_id,
            payload=effect.payload,
        )
    return result


def run_parent_candidate_intake(
    *,
    issue: BacklogIssue,
    decision: CandidateRoutingDecision,
    repo_root: Path,
    ledger: PhaseLedger,
    spec_locations: tuple[Path, ...] | None = None,
) -> ParentIntakeResult:
    if decision.route not in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}:
        raise GraphError(
            f"run_parent_candidate_intake requires parent route: {decision.route}"
        )

    spec_path = _spec_path(issue.body, repo_root=repo_root, spec_locations=spec_locations)
    if spec_path is None:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="Blocked",
                comment=(
                f"SMDA parent intake blocked for {issue.id}.\n\n"
                "No approved parent spec path was found in the issue body."
                ),
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
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="Human Review",
                comment=(
                    f"SMDA parent spec approval is incomplete for {issue.id}.\n\n"
                    f"Spec: `{spec_path}`\n"
                    f"Missing approval fields: {', '.join(missing_approval_fields)}\n"
                    "Human Review must approve the spec before SPEC_FINALIZED."
                ),
            ),
        )

    result = ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA parent reached SPEC_FINALIZED for {issue.id}.\n\n"
            f"Spec: `{spec_path}`\n"
            f"Spec checksum: `{spec_checksum}`\n"
            f"Approval evidence: {approval_evidence}"
        ),
    )
    ledger.create_parent_run(
        parent_id=issue.id,
        initial_phase="SPEC_FINALIZED",
        spec_path=spec_path,
        spec_checksum=spec_checksum,
        approval_evidence=approval_evidence,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


def run_roadmap_candidate_intake(
    *,
    issue: BacklogIssue,
    decision: CandidateRoutingDecision,
    repo_root: Path,
    ledger: PhaseLedger,
    spec_locations: tuple[Path, ...] | None = None,
) -> ParentIntakeResult:
    if decision.route != CandidateRoute.ROADMAP:
        raise GraphError(
            f"run_roadmap_candidate_intake requires roadmap route: {decision.route}"
        )

    spec_path = _spec_path(issue.body, repo_root=repo_root, spec_locations=spec_locations)
    if spec_path is None:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="Blocked",
                comment=(
                    f"SMDA roadmap intake blocked for {issue.id}.\n\n"
                    "No approved roadmap spec path was found in the issue body."
                ),
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
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="Human Review",
                comment=(
                    f"SMDA roadmap spec approval is incomplete for {issue.id}.\n\n"
                    f"Spec: `{spec_path}`\n"
                    f"Missing approval fields: {', '.join(missing_approval_fields)}"
                ),
            ),
        )

    result = ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA roadmap reached ROADMAP_DECOMPOSING for {issue.id}.\n\n"
            f"Spec: `{spec_path}`\n"
            f"Spec checksum: `{spec_checksum}`\n"
            f"Approval evidence: {approval_evidence}"
        ),
    )
    ledger.create_parent_run(
        parent_id=issue.id,
        initial_phase=RoadmapPhase.ROADMAP_DECOMPOSING.value,
        spec_path=spec_path,
        spec_checksum=spec_checksum,
        approval_evidence=approval_evidence,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


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
    create_follow_up_issues_for_concerns: bool = False,
    concern_followup_labels: frozenset[str] = frozenset(),
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    phase = parent_run["phase"]
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
        create_follow_up_issues_for_concerns=create_follow_up_issues_for_concerns,
        concern_followup_labels=concern_followup_labels,
    )
    result = _PARENT_ENGINE.dispatch_parent_stage(phase, ctx)
    if result is not None:
        return result
    return _record_nontransition_parent_result(
        ledger,
        issue.id,
        ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent workflow idle for {issue.id}.\n\n"
                f"Current parent phase: `{phase}`"
            ),
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
    return _record_nontransition_parent_result(
        ledger,
        issue.id,
        ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA roadmap workflow idle for {issue.id}.\n\n"
                f"Current roadmap phase: `{roadmap_run['phase']}`"
            ),
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
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA roadmap decomposition skipped for {issue.id}.\n\n"
                    f"Current roadmap phase: `{roadmap_run['phase']}`"
                ),
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
            open_parent_snapshot=tuple(_open_parent_snapshot(backlog, exclude_id=issue.id, repo_root=repo_root, spec_locations=repo_context.spec_locations)),
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
        result = ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA roadmap decomposition completed for {issue.id}.\n\n"
                f"Roadmap phase: `{next_phase}`\n"
                f"Attempt: `{resolved_attempt_id}`"
            ),
        )
        ledger.transition_parent(
            parent_id=issue.id,
            expected_phase=roadmap_run["phase"],
            next_phase=next_phase,
            attempt_result=AttemptResultUpdate(
                attempt_id=resolved_attempt_id,
                expected_dispatched_phase=phase,
                status=outcome.status,
                result_json=_attempt_result_json(outcome),
                error_message=outcome.error_message,
            ),
            roadmap_members=RoadmapMembersUpdate(
                members=tuple(members),
                member_edges=tuple(edges),
            ),
            effects=_parent_lifecycle_effects(
                issue_id=issue.id,
                target_state=result.target_state,
                comment=result.comment,
            ),
        )
        return result

    result = ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA roadmap decomposition failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=roadmap_run["phase"],
        next_phase=roadmap_run["phase"],
        attempt_result=AttemptResultUpdate(
            attempt_id=resolved_attempt_id,
            expected_dispatched_phase=phase,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
        ),
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


_CHILD_DISPATCH_STATE = "Todo"


def run_roadmap_publication_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    backlog: BacklogPublicationAdapter,
    child_labels: frozenset[str] = frozenset(),
) -> ParentIntakeResult:
    roadmap_run = _parent_run_for(ledger, issue.id)
    if roadmap_run["phase"] != RoadmapPhase.ROADMAP_PUBLICATION_READY.value:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA roadmap publication skipped for {issue.id}.\n\n"
                    f"Current roadmap phase: `{roadmap_run['phase']}`"
                ),
            ),
        )

    result = publish_roadmap_members(
        issue=issue,
        ledger=ledger,
        backlog=backlog,
        child_labels=child_labels,
    )
    parent_result = ParentIntakeResult(result.target_state, result.comment)
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=roadmap_run["phase"],
        next_phase=RoadmapPhase.ROADMAP_PUBLISHED.value,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=parent_result.target_state,
            comment=parent_result.comment,
        ),
    )
    return parent_result


def run_roadmap_completion_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    integration: ParentLandIntegration | None = None,
    standalone_base: str = "main",
    context: ParentTickContext | None = None,
) -> ParentIntakeResult:
    """Parent-tier Aggregate: land the roadmap to main once all members land.

    Polls member FINAL_ACCEPTED (no event system, mirrors the 3a auto-unblock).
    When every member is accepted, lands roadmap-integration -> standalone_base
    exactly once (idempotent land op) and advances to ROADMAP_COMPLETED.
    Checked delivery retains its reviewed branch and requires aggregate QA;
    legacy delivery deletes the branch. Partial acceptance is a no-op.
    """
    roadmap_run = _parent_run_for(ledger, issue.id)
    if roadmap_run["phase"] != RoadmapPhase.ROADMAP_PUBLISHED.value:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA roadmap completion skipped for {issue.id}.\n\n"
                    f"Current roadmap phase: `{roadmap_run['phase']}`"
                ),
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
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA roadmap {issue.id} waiting on members to be "
                    f"FINAL_ACCEPTED: {', '.join(pending) or 'none published'}"
                ),
            ),
        )

    branch = roadmap_integration_branch(issue.id)
    checked = context is not None and context.repo_context.acceptance_policy is not None
    if checked:
        parent = _parent_spec_context_for_issue(
            issue=issue, parent_run=roadmap_run, repo_root=context.repo_root)
        children, edges = _roadmap_acceptance_members(ledger, issue.id, context.repo_root)
        accepted = _checked_delivery_review(
            issue=issue, ledger=ledger, repo_context=context.repo_context,
            repo_root=context.repo_root, execution=context.execution,
            sandbox_provider=context.sandbox_provider, agent=context.agent,
            parent=parent, children=children, dependency_edges=edges,
            branch=branch, policy=context.repo_context.acceptance_policy,
        )
        if not accepted:
            return _record_nontransition_parent_result(
                ledger, issue.id, ParentIntakeResult(
                    target_state="In Progress",
                    comment=f"SMDA roadmap {issue.id} delivery QA passed; awaiting checked merge.",
                ),
            )
    elif integration is not None:
        land = ParentLandOperation(
            operation_id=f"roadmap-land:{issue.id}",
            idempotency_key=f"roadmap-land:{issue.id}:{branch}:{standalone_base}",
            parent_id=issue.id,
            parent_ref=branch,
            base_branch=standalone_base,
        )
        outcome = recover_or_apply_parent_land(ledger, integration, land)
        if outcome.status != "completed":
            return _record_nontransition_parent_result(
                ledger,
                issue.id,
                ParentIntakeResult(
                    target_state="In Progress",
                    comment=(
                        f"SMDA roadmap land pending for {issue.id} "
                        f"(base `{standalone_base}`): {outcome.action}"
                    ),
                ),
            )
        integration.delete_branch(branch)

    result = ParentIntakeResult(
        target_state="Done",
        comment=(
            f"SMDA roadmap {issue.id} completed: landed `{branch}` -> "
            f"`{context.repo_context.acceptance_policy.merge_target if checked else standalone_base}`. "
            + ("Reviewed integration branch retained for evidence/recovery." if checked else "Deleted the roadmap branch.")
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=roadmap_run["phase"],
        next_phase=RoadmapPhase.ROADMAP_COMPLETED.value,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


# --- Generic parent role-attempt runner (ADR-0006: decision A / A3 / B2) ---
#
# The five parent ROLE_ATTEMPT handlers share one spine: precondition gate ->
# build request -> record request -> execute -> on success route via the parent
# transition table; on protocol failure record + Blocked. Each stage's bespoke
# bits are injected closures: build_request (validation + context + request),
# passing (succeeded-but-failed fork), build_success (optional graph payload +
# comment), on_failure (stateful escalation). The runner owns the uniform spine
# and a single atomic success write.


@dataclass(frozen=True)
class ParentRoleHooks:
    """Stateful callables needed by a parent role attempt."""

    gate_label: str
    build_request: Callable[..., RoleAttemptRequest]
    build_success: Callable[..., tuple[WorkflowGraphArtifact | None, str]]
    passing: Callable[[AttemptOutcome], bool] = lambda outcome: True
    on_failure: Callable[..., ParentIntakeResult] | None = None


def _write_parent_success(
    *,
    ledger: PhaseLedger,
    parent_id: str,
    resolved_attempt_id: str,
    attempt_phase: ParentPhase,
    outcome: AttemptOutcome,
    next_phase: str,
    parent_run: dict[str, str],
    extra: WorkflowGraphArtifact | None,
    effects: tuple[BacklogEffect, ...],
) -> None:
    """One atomic success write; folds optional graph payload (B2)."""
    ledger.transition_parent(
        parent_id=parent_id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        attempt_result=AttemptResultUpdate(
            attempt_id=resolved_attempt_id,
            expected_dispatched_phase=attempt_phase,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
        ),
        graph=extra,
        effects=effects,
    )


def run_parent_role_attempt(
    *,
    issue: BacklogIssue,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    owner: str,
    stage: StageSpec,
    attempt_phase: ParentPhase,
    hooks: ParentRoleHooks,
    create_follow_up_issues_for_concerns: bool = False,
    concern_followup_labels: frozenset[str] = frozenset(),
    review_branch: str | None = None,
) -> ParentIntakeResult:
    gate_phase = getattr(stage.phase, "value", stage.phase)
    role_contract = stage.role_contract
    if role_contract is None:
        raise GraphError(f"parent ROLE_ATTEMPT stage {gate_phase} requires role_contract")
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != gate_phase:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA parent {hooks.gate_label} skipped for {issue.id}.\n\n"
                    f"Current parent phase: `{parent_run['phase']}`"
                ),
            ),
        )

    attempt_number = _next_attempt_number(
        ledger,
        target_kind="parent",
        target_id=issue.id,
        phase=attempt_phase.value,
    )
    attempt_id = f"{issue.id}-{attempt_phase.value}-{attempt_number}"
    request = hooks.build_request(
        contract=role_contract,
        issue=issue,
        repo_context=repo_context,
        repo_root=repo_root,
        ledger=ledger,
        sandbox_provider=sandbox_provider,
        agent=agent,
        parent_run=parent_run,
        attempt_id=attempt_id,
    )
    acceptance = repo_context.acceptance_policy
    if acceptance is not None:
        acceptance = replace(acceptance, merge_target=resolve_parent_base(
            ledger, issue.id, standalone_base=acceptance.merge_target))
    snapshot = None
    if attempt_phase == ParentPhase.PARENT_QA_REVIEWING and acceptance is not None:
        if acceptance.merge_target != repo_context.acceptance_policy.merge_target:
            GitParentIntegration(repo_root).ensure_branch(
                acceptance.merge_target, start_point=repo_context.acceptance_policy.merge_target)
        snapshot = snapshot_candidate(
            repo_root, review_branch or parent_integration_branch(issue.id), acceptance
        )
        check_candidate_source(repo_root, snapshot["candidate"], parent_run["spec_path"], parent_run["spec_checksum"])
        if repo_context.harness_contract_path is not None:
            check_candidate_source(repo_root, snapshot["candidate"],
                                   str(repo_context.harness_contract_path.relative_to(repo_root)),
                                   repo_context.harness_contract_checksum)
        request = replace(
            request,
            branch=f"{request.branch}-{attempt_number}-{snapshot['candidate']}",
            context_packet={**request.context_packet, "acceptance_snapshot": snapshot},
            prompt=(request.prompt or "") + "\n\nReview this exact candidate without edits:\n" + json.dumps(snapshot),
        )
    resolved_attempt_id = ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="parent",
        target_id=issue.id,
        phase=attempt_phase,
        idempotency_key=(
            f"parent:{issue.id}:{attempt_phase.value}:{attempt_number}"
        ),
        request_json=request.to_ipc_payload(),
    )
    if resolved_attempt_id != request.attempt_id:
        request = replace(request, attempt_id=resolved_attempt_id)

    try:
        if snapshot is None:
            outcome = execution.run_role_attempt(request)
        else:
            outcome = run_candidate_review(repo_root, snapshot, request, execution)
            if outcome.status == "succeeded" and _is_passing_review(outcome.role_result, "accept_parent"):
                if outcome.commits:
                    raise AcceptanceError("QA reviewer changed code; repeat review of the resulting candidate")
                evidence = verify_candidate(repo_root, snapshot, acceptance)
                evidence["issue_body_checksum"] = hashlib.sha256(issue.body.encode()).hexdigest()
                outcome = replace(outcome, raw_result={**(outcome.raw_result or {}), "acceptance_evidence": evidence})
    except AcceptanceError as error:
        ledger.record_attempt_result(
            attempt_id=resolved_attempt_id, status="failed",
            result_json=None, error_message=str(error),
        )
        raise
    if outcome.status == "succeeded":
        if outcome.role_result is None:
            raise GraphError(
                f"succeeded {hooks.gate_label} requires role_result"
            )
        if hooks.on_failure is not None and not hooks.passing(outcome):
            return hooks.on_failure(
                issue=issue,
                ledger=ledger,
                resolved_attempt_id=resolved_attempt_id,
                outcome=outcome,
                parent_run=parent_run,
            )
        next_phase = _PARENT_ENGINE.next_phase(
            gate_phase, outcome.role_result
        )
        extra, comment = hooks.build_success(
            issue=issue,
            ledger=ledger,
            outcome=outcome,
            next_phase=next_phase,
            resolved_attempt_id=resolved_attempt_id,
            parent_run=parent_run,
        )
        _write_parent_success(
            ledger=ledger,
            parent_id=issue.id,
            resolved_attempt_id=resolved_attempt_id,
            attempt_phase=attempt_phase,
            outcome=outcome,
            next_phase=next_phase,
            parent_run=parent_run,
            extra=extra,
            effects=(
                *_parent_lifecycle_effects(
                    issue_id=issue.id,
                    target_state="In Progress",
                    comment=comment,
                ),
                *_concern_followup_effects(
                    issue_id=issue.id,
                    gate=hooks.gate_label,
                    attempt_id=resolved_attempt_id,
                    outcome=outcome,
                    enabled=create_follow_up_issues_for_concerns,
                    labels=concern_followup_labels,
                ),
            ),
        )
        return ParentIntakeResult(target_state="In Progress", comment=comment)

    result = ParentIntakeResult(
        target_state="Blocked",
        comment=(
            f"SMDA parent {hooks.gate_label} failed for {issue.id}.\n\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Status: `{outcome.status}`\n"
            f"Error: {outcome.error_message or 'none'}"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=parent_run["phase"],
        attempt_result=AttemptResultUpdate(
            attempt_id=resolved_attempt_id,
            expected_dispatched_phase=attempt_phase,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
        ),
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


def _graph_payload_from_outcome(
    outcome: AttemptOutcome, *, parent_id: str
) -> WorkflowGraphArtifact:
    if outcome.raw_result is None:
        raise GraphError("graph decomposer succeeded without raw_result")
    graph = WorkflowGraphArtifact.from_dict(
        {
            "parent_id": parent_id,
            "graph_checksum": "pending",
            "children": outcome.raw_result.get("children"),
            "dependency_edges": outcome.raw_result.get("dependency_edges"),
        }
    )
    id_map = {
        child.node_id: _parent_scoped_child_id(parent_id, child.node_id)
        for child in graph.children
    }
    graph = replace(
        graph,
        children=tuple(
            replace(
                child,
                node_id=id_map[child.node_id],
                dependencies=tuple(
                    id_map.get(dependency, dependency)
                    for dependency in child.dependencies
                ),
            )
            for child in graph.children
        ),
        dependency_edges=tuple(
            replace(
                edge,
                from_node_id=id_map.get(edge.from_node_id, edge.from_node_id),
                to_node_id=id_map.get(edge.to_node_id, edge.to_node_id),
            )
            for edge in graph.dependency_edges
        ),
    )
    if len({child.node_id for child in graph.children}) != len(graph.children):
        raise GraphError("graph child IDs must be unique")
    validate_graph(graph.scheduling_view())
    serialized = graph.to_dict()
    return replace(
        graph,
        graph_checksum=_graph_checksum(
            serialized["children"],
            dependency_edges=serialized["dependency_edges"],
        ),
    )


def _decomposition_build_request(
    *, contract, issue, repo_context, repo_root, ledger, sandbox_provider, agent,
    parent_run, attempt_id,
) -> RoleAttemptRequest:
    spec_text = _read_repo_file(repo_root, parent_run["spec_path"])
    spec_checksum = f"sha256:{hashlib.sha256(spec_text.encode('utf-8')).hexdigest()}"
    if spec_checksum != parent_run["spec_checksum"]:
        raise GraphError(
            "Approved spec checksum changed for "
            f"{issue.id}: expected {parent_run['spec_checksum']} got {spec_checksum}"
        )
    return build_parent_graph_decomposer_request(
        attempt_id=attempt_id,
        contract=contract,
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


def _decomposition_build_success(
    *, issue, ledger, outcome, next_phase, resolved_attempt_id, parent_run,
) -> tuple[WorkflowGraphArtifact, str]:
    return (
        _graph_payload_from_outcome(outcome, parent_id=issue.id),
        (
            f"SMDA parent graph decomposition completed for {issue.id}.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`"
        ),
    )


def _graph_context_request(
    builder: Callable[..., RoleAttemptRequest],
    **extra_kwargs,
) -> Callable[..., RoleAttemptRequest]:
    def build(
        *, contract, issue, repo_context, repo_root, ledger, sandbox_provider, agent,
        parent_run, attempt_id,
    ) -> RoleAttemptRequest:
        parent = _parent_spec_context_for_issue(
            issue=issue, parent_run=parent_run, repo_root=repo_root
        )
        persisted_graph = ledger.load_graph(issue.id)
        kwargs = dict(extra_kwargs)
        for key in ("review_findings", "conflict_history"):
            if key in kwargs and callable(kwargs[key]):
                kwargs[key] = kwargs[key](ledger, issue.id)
        serialized_graph = persisted_graph.to_dict()
        return builder(
            attempt_id=attempt_id,
            contract=contract,
            graph=ParentGraphContext(
                parent=parent,
                graph_checksum=persisted_graph.graph_checksum,
                children=tuple(serialized_graph["children"]),
                dependency_edges=tuple(serialized_graph["dependency_edges"]),
            ),
            repo_context=repo_context,
            repo_root=repo_root,
            sandbox_provider=sandbox_provider,
            agent=agent,
            **kwargs,
        )

    return build


def _fixing_build_success(
    *, issue, ledger, outcome, next_phase, resolved_attempt_id, parent_run,
) -> tuple[WorkflowGraphArtifact, str]:
    return (
        _graph_payload_from_outcome(outcome, parent_id=issue.id),
        (
            f"SMDA parent graph fix completed for {issue.id}; re-reviewing.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`"
        ),
    )


def _passed_review_build_success(gate: str) -> Callable[..., tuple[None, str]]:
    def build(
        *, issue, ledger, outcome, next_phase, resolved_attempt_id, parent_run,
    ) -> tuple[None, str]:
        return (
            None,
            _passed_review_comment(
                gate=gate,
                issue_id=issue.id,
                next_phase=next_phase,
                attempt_id=resolved_attempt_id,
                outcome=outcome,
            ),
        )

    return build


def _qa_build_success(
    *, issue, ledger, outcome, next_phase, resolved_attempt_id, parent_run,
) -> tuple[None, str]:
    if next_phase == ParentPhase.FINAL_ACCEPT_READY.value:
        return (
            None,
            _passed_review_comment(
                gate="QA review",
                issue_id=issue.id,
                next_phase=next_phase,
                attempt_id=resolved_attempt_id,
                outcome=outcome,
            ),
        )
    return (
        None,
        (
            f"SMDA parent QA review failed for {issue.id}; planning remediation.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`"
        ),
    )


_MAX_CHILD_ACCEPT_CONFLICT_RESOLVER_ATTEMPTS = 2


def _child_accept_conflict_build_success(
    *, issue, ledger, outcome, next_phase, resolved_attempt_id, parent_run,
) -> tuple[None, str]:
    operation = _latest_parent_accept_conflict_operation(ledger, issue.id)
    attempts = ledger.increment_parent_accept_resolver_attempts(
        str(operation["operation_id"])
    )
    return (
        None,
        (
            f"SMDA parent accept conflict resolver completed for {issue.id}; "
            "retrying deterministic child acceptance.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Accept operation: `{operation['operation_id']}`\n"
            f"Resolver attempts for fingerprint: {attempts}"
        ),
    )


def _child_accept_conflict_on_failure(
    *, issue, ledger, resolved_attempt_id, outcome, parent_run
) -> ParentIntakeResult:
    next_phase = ParentPhase.HUMAN_REVIEW_REQUIRED.value
    report = _review_report(outcome) or "Resolver did not provide a report."
    history = _parent_accept_conflict_history(ledger, issue.id)
    result = ParentIntakeResult(
        target_state="Human Review",
        comment=(
            f"SMDA parent accept conflict requires human review for {issue.id}.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`\n"
            f"Accept operation: `{history.get('operation_id', 'unknown')}`\n"
            f"Conflict fingerprint: `{history.get('conflict_fingerprint', '')}`\n\n"
            f"Resolver report:\n{report}"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        attempt_result=AttemptResultUpdate(
            attempt_id=resolved_attempt_id,
            expected_dispatched_phase=ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING,
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
        ),
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


def _graph_review_on_failure(gate: str) -> Callable[..., ParentIntakeResult]:
    def route(*, issue, ledger, resolved_attempt_id, outcome, parent_run):
        return _route_failed_graph_review(
            issue=issue,
            ledger=ledger,
            resolved_attempt_id=resolved_attempt_id,
            outcome=outcome,
            parent_run=parent_run,
            gate=gate,
        )

    return route


def _parent_role_hooks() -> dict[str, ParentRoleHooks]:
    return {
        "SPEC_FINALIZED": ParentRoleHooks(
            gate_label="graph decomposition",
            build_request=_decomposition_build_request,
            build_success=_decomposition_build_success,
        ),
        ParentPhase.GRAPH_FIXING.value: ParentRoleHooks(
            gate_label="graph fixing",
            build_request=_graph_context_request(
                build_parent_graph_fixer_request,
                review_findings=_latest_graph_review_findings,
            ),
            build_success=_fixing_build_success,
        ),
        ParentPhase.GRAPH_SPEC_REVIEWING.value: ParentRoleHooks(
            gate_label="graph spec review",
            build_request=_graph_context_request(
                build_parent_graph_spec_review_request
            ),
            build_success=_passed_review_build_success("graph spec review"),
            passing=lambda outcome: _is_passing_review(
                outcome.role_result, "submit_for_graph_execution_review"
            ),
            on_failure=_graph_review_on_failure("graph spec review"),
        ),
        ParentPhase.GRAPH_EXECUTION_REVIEWING.value: ParentRoleHooks(
            gate_label="graph execution review",
            build_request=_graph_context_request(
                build_parent_graph_execution_review_request
            ),
            build_success=_passed_review_build_success("graph execution review"),
            passing=lambda outcome: _is_passing_review(
                outcome.role_result, "publish_child_issues"
            ),
            on_failure=_graph_review_on_failure("graph execution review"),
        ),
        ParentPhase.PARENT_QA_READY.value: ParentRoleHooks(
            gate_label="QA review",
            build_request=_graph_context_request(build_parent_qa_review_request),
            build_success=_qa_build_success,
        ),
        ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING.value: ParentRoleHooks(
            gate_label="child accept conflict resolver",
            build_request=_graph_context_request(
                build_parent_accept_conflict_resolver_request,
                conflict_history=_parent_accept_conflict_history,
            ),
            build_success=_child_accept_conflict_build_success,
            passing=lambda outcome: (
                outcome.role_result is not None
                and outcome.role_result.verdict == "DONE"
                and outcome.role_result.required_next_action
                == "retry_child_acceptance"
            ),
            on_failure=_child_accept_conflict_on_failure,
        ),
    }


_PARENT_ROLE_HOOKS: dict[str, ParentRoleHooks] | None = None


def _resolve_parent_role_hooks(phase: str) -> ParentRoleHooks:
    """Map a parent gate phase to its stateful role-attempt hooks."""

    global _PARENT_ROLE_HOOKS
    if _PARENT_ROLE_HOOKS is None:
        _PARENT_ROLE_HOOKS = _parent_role_hooks()
    return _PARENT_ROLE_HOOKS[phase]


def _role_ctx_args(ctx) -> dict:
    return dict(
        issue=ctx.issue,
        repo_context=ctx.repo_context,
        repo_root=ctx.repo_root,
        ledger=ctx.ledger,
        execution=ctx.execution,
        sandbox_provider=ctx.sandbox_provider,
        agent=ctx.agent,
        owner=ctx.owner,
    )


def dispatch_role_attempt_stage(stage: StageSpec, attempt_phase, ctx) -> ParentIntakeResult:
    """Dispatch a ROLE_ATTEMPT stage by phase (ADR-0006 D3).

    Parent role attempts ride the generic runner; roadmap decomposition keeps
    its own handler (it authors the parent set and needs the backlog seam).
    """
    gate_phase = getattr(stage.phase, "value", stage.phase)
    if gate_phase == RoadmapPhase.ROADMAP_DECOMPOSING.value:
        return run_roadmap_decomposition_tick(
            **_role_ctx_args(ctx), backlog=ctx.backlog
        )
    return run_parent_role_attempt(
        **_role_ctx_args(ctx),
        stage=stage,
        attempt_phase=ParentPhase(attempt_phase),
        hooks=_resolve_parent_role_hooks(gate_phase),
        review_branch=ctx.integration_branch,
        create_follow_up_issues_for_concerns=(
            ctx.create_follow_up_issues_for_concerns
        ),
        concern_followup_labels=ctx.concern_followup_labels,
    )


def _parent_effect_handlers() -> dict[str, Callable[..., ParentIntakeResult]]:
    return {
        ParentPhase.CHILD_PUBLICATION_READY.value: lambda ctx: (
            run_parent_child_publication_tick(
                issue=ctx.issue,
                ledger=ctx.ledger,
                backlog=ctx.backlog,
                child_labels=ctx.child_labels,
            )
        ),
        ParentPhase.CHILDREN_PUBLISHED.value: lambda ctx: (
            run_parent_child_acceptance_tick(
                issue=ctx.issue,
                ledger=ctx.ledger,
                integration=ctx.integration,
                integration_branch=ctx.integration_branch,
            )
        ),
        ParentPhase.REMEDIATION_PLANNING.value: lambda ctx: (
            run_parent_remediation_planning_tick(
                issue=ctx.issue,
                ledger=ctx.ledger,
                backlog=ctx.backlog,
                child_labels=ctx.child_labels,
                qa_bounds=ctx.qa_bounds,
            )
        ),
        ParentPhase.FINAL_ACCEPT_READY.value: lambda ctx: (
            run_parent_final_accept_tick(
                issue=ctx.issue,
                ledger=ctx.ledger,
                integration=ctx.integration,
                integration_branch=ctx.integration_branch,
                standalone_base=ctx.standalone_base,
                acceptance_policy=ctx.repo_context.acceptance_policy,
                repo_root=ctx.repo_root,
            )
        ),
        ParentPhase.LANDING_CONFLICT_REBASING.value: lambda ctx: (
            run_landing_conflict_rebase_tick(
                issue=ctx.issue,
                ledger=ctx.ledger,
                integration=ctx.integration,
                integration_branch=ctx.integration_branch,
                standalone_base=ctx.standalone_base,
                qa_bounds=ctx.qa_bounds,
            )
        ),
        RoadmapPhase.ROADMAP_PUBLICATION_READY.value: lambda ctx: (
            run_roadmap_publication_tick(
                issue=ctx.issue,
                ledger=ctx.ledger,
                backlog=ctx.backlog,
                child_labels=ctx.child_labels,
            )
        ),
        RoadmapPhase.ROADMAP_PUBLISHED.value: lambda ctx: (
            run_roadmap_completion_tick(
                issue=ctx.issue,
                ledger=ctx.ledger,
                integration=ctx.integration,
                standalone_base=ctx.standalone_base,
                context=ctx,
            )
        ),
    }


_PARENT_EFFECT_HANDLERS: dict[str, Callable[..., ParentIntakeResult]] | None = None


def resolve_parent_effect(phase) -> Callable[..., ParentIntakeResult]:
    """Map an EFFECT / AGGREGATE phase to its handler (ADR-0006 D3).

    Built lazily so the handler closures can reference module-level tick
    functions defined further down the file.
    """
    global _PARENT_EFFECT_HANDLERS
    if _PARENT_EFFECT_HANDLERS is None:
        _PARENT_EFFECT_HANDLERS = _parent_effect_handlers()
    return _PARENT_EFFECT_HANDLERS[getattr(phase, "value", phase)]


def run_parent_child_publication_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    backlog: BacklogPublicationAdapter,
    child_labels: frozenset[str] = frozenset(),
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.CHILD_PUBLICATION_READY.value:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA child publication skipped for {issue.id}.\n\n"
                    f"Current parent phase: `{parent_run['phase']}`"
                ),
            ),
        )

    graph = ledger.load_graph(issue.id)
    projections = ledger.load_child_issue_projections(issue.id)

    for child in graph.children:
        node_id = child.node_id
        if node_id in projections:
            continue
        created = backlog.create_child(
            parent_id=issue.id,
            title=child.title,
            body=_child_issue_body(
                parent_id=issue.id,
                graph_checksum=graph.graph_checksum,
                spec_path=parent_run["spec_path"],
                child=child,
                dependency_edges=graph.dependency_edges,
            ),
            labels=child_labels,
        )
        ledger.record_child_issue_projection(
            parent_id=issue.id,
            node_id=node_id,
            issue_id=created.id,
        )
        projections[node_id] = created.id
        backlog.set_coarse_state(created.id, _CHILD_DISPATCH_STATE)

    for child in graph.children:
        blocked_id = projections[child.node_id]
        for dependency in child.dependencies:
            blocker_id = projections[dependency]
            backlog.link_blocking(blocker_id=blocker_id, blocked_id=blocked_id)

    next_phase = PARENT_DEFINITION.stage(
        ParentPhase.CHILD_PUBLICATION_READY.value
    ).next_phase_on_success
    result = ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA child issues published for {issue.id}.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Published children: {len(graph.children)}"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


def run_parent_child_acceptance_tick(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    integration: ParentIntegration | None,
    integration_branch: str | None,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.CHILDREN_PUBLISHED.value:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA child acceptance skipped for {issue.id}.\n\n"
                    f"Current parent phase: `{parent_run['phase']}`"
                ),
            ),
        )

    graph = ledger.load_graph(issue.id)
    child_state = ledger.load_scheduler_state().children
    completed_accept_operations = ledger.load_parent_accept_operations()
    accepted_latest_child_ids: set[str] = set()
    projections = ledger.load_child_issue_projections(issue.id)
    active_integration_branch = (
        integration_branch or parent_integration_branch(issue.id)
    )

    for child in graph.children:
        child_id = child.node_id
        state = child_state.get(child_id)
        if state is None or state.phase != ChildPhase.QUALITY_REVIEW_PASSED:
            continue
        if integration is None:
            return _record_nontransition_parent_result(
                ledger,
                issue.id,
                ParentIntakeResult(
                    target_state="Blocked",
                    comment=f"SMDA child acceptance is not configured for {issue.id}.",
                ),
            )
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
                integration_branch=active_integration_branch,
            ),
        )
        if result.status != "completed":
            if result.conflict_fingerprint:
                return _route_child_accept_conflict(
                    issue=issue,
                    ledger=ledger,
                    parent_run=parent_run,
                    operation_id=result.operation_id,
                )
            return _record_nontransition_parent_result(
                ledger,
                issue.id,
                ParentIntakeResult(
                    target_state="Blocked",
                    comment=(
                        f"SMDA parent child acceptance failed for {issue.id}.\n\n"
                        f"Child: `{child_id}`\n"
                        f"Operation: `{result.operation_id}`\n"
                        f"Action: `{result.action}`"
                    ),
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
                integration_branch=active_integration_branch,
            )

    if {child.node_id for child in graph.children} <= accepted_latest_child_ids:
        next_phase = PARENT_DEFINITION.stage(
            ParentPhase.CHILDREN_PUBLISHED.value
        ).next_phase_on_success
        result = ParentIntakeResult(
            target_state="In Progress",
            comment=(
                f"SMDA parent accepted all child candidates for {issue.id}.\n\n"
                f"Parent phase: `{next_phase}`"
            ),
        )
        ledger.transition_parent(
            parent_id=issue.id,
            expected_phase=parent_run["phase"],
            next_phase=next_phase,
            effects=_parent_lifecycle_effects(
                issue_id=issue.id,
                target_state=result.target_state,
                comment=result.comment,
            ),
        )
        return result

    return _record_nontransition_parent_result(
        ledger,
        issue.id,
        ParentIntakeResult(
            target_state="In Progress",
            comment=f"SMDA parent waiting for quality-passed children for {issue.id}.",
        ),
    )


def _route_child_accept_conflict(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    parent_run: dict[str, str],
    operation_id: str,
) -> ParentIntakeResult:
    operation = _parent_accept_operation_with_id(ledger, operation_id)
    if int(operation["resolver_attempts"]) >= _MAX_CHILD_ACCEPT_CONFLICT_RESOLVER_ATTEMPTS:
        next_phase = ParentPhase.HUMAN_REVIEW_REQUIRED.value
        target_state = "Human Review"
        headline = (
            "SMDA parent child acceptance conflict resolver attempts exhausted "
            f"for {issue.id}."
        )
    else:
        next_phase = ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING.value
        target_state = "In Progress"
        headline = (
            f"SMDA parent child acceptance conflicted for {issue.id}; "
            "routing to conflict resolver."
        )
    result = ParentIntakeResult(
        target_state=target_state,
        comment=(
            f"{headline}\n\n"
            f"Child: `{operation['child_id']}`\n"
            f"Operation: `{operation_id}`\n"
            f"Conflict fingerprint: `{operation['conflict_fingerprint']}`\n"
            f"Conflicted paths: {', '.join(operation['conflicted_paths']) or 'none'}\n"
            f"Resolver attempts: {operation['resolver_attempts']}\n"
            f"Parent phase: `{next_phase}`"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


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
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA remediation planning skipped for {issue.id}.\n\n"
                    f"Current parent phase: `{parent_run['phase']}`"
                ),
            ),
        )

    graph = ledger.load_graph(issue.id)
    if qa_bounds is not None and _remediation_bounds_exhausted(
        ledger,
        issue.id,
        graph.children,
        qa_bounds=qa_bounds,
    ):
        next_phase = ParentPhase.HUMAN_REVIEW_REQUIRED.value
        result = ParentIntakeResult(
            target_state="Human Review",
            comment=(
                f"SMDA remediation bounds exhausted for {issue.id}.\n\n"
                f"Parent phase: `{next_phase}`"
            ),
        )
        ledger.transition_parent(
            parent_id=issue.id,
            expected_phase=parent_run["phase"],
            next_phase=next_phase,
            effects=_parent_lifecycle_effects(
                issue_id=issue.id,
                target_state=result.target_state,
                comment=result.comment,
            ),
        )
        return result
    node_id = _parent_scoped_child_id(
        issue.id, _next_remediation_node_id(graph.children)
    )
    if any(child.node_id == node_id for child in graph.children):
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
        "dependencies": [child.node_id for child in graph.children],
    }
    updated_graph = replace(
        graph,
        children=(
            *graph.children,
            WorkflowGraphChild.from_dict(remediation_child),
        ),
        dependency_edges=(
            *graph.dependency_edges,
            *(
                DependencyEdge(
                    from_node_id=child.node_id,
                    to_node_id=node_id,
                    type="sequencing_only",
                    blocks_dispatch=True,
                    reason=(
                        "Remediation starts after the existing child has been "
                        "accepted into the parent integration branch."
                    ),
                    required_artifacts=("accepted_commit",),
                )
                for child in graph.children
            ),
        ),
    )
    serialized_graph = updated_graph.to_dict()
    updated_graph = replace(
        updated_graph,
        graph_checksum=_graph_checksum(
            serialized_graph["children"],
            dependency_edges=serialized_graph["dependency_edges"],
        ),
    )
    validate_graph(updated_graph.scheduling_view())
    remediation = updated_graph.children[-1]

    created = backlog.create_child(
        parent_id=issue.id,
        title=remediation.title,
        body=_child_issue_body(
            parent_id=issue.id,
            graph_checksum=updated_graph.graph_checksum,
            spec_path=parent_run["spec_path"],
            child=remediation,
            dependency_edges=updated_graph.dependency_edges,
        ),
        labels=child_labels,
    )
    ledger.record_child_issue_projection(
        parent_id=issue.id,
        node_id=node_id,
        issue_id=created.id,
    )
    backlog.set_coarse_state(created.id, _CHILD_DISPATCH_STATE)

    projections = ledger.load_child_issue_projections(issue.id)
    for dependency in remediation.dependencies:
        backlog.link_blocking(
            blocker_id=projections[str(dependency)],
            blocked_id=created.id,
        )

    next_phase = PARENT_DEFINITION.stage(
        ParentPhase.REMEDIATION_PLANNING.value
    ).next_phase_on_success
    result = ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA remediation child published for {issue.id}.\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Remediation child: `{created.id}`"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        graph=updated_graph,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


def roadmap_integration_branch(roadmap_id: str) -> str:
    """The shared base branch roadmap members land onto (parent-tier base)."""
    return f"smda/{roadmap_id}/integration"


def parent_integration_branch(parent_id: str) -> str:
    return f"smda/{parent_id.lower()}/integration"


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
    acceptance_policy: AcceptancePolicy | None = None,
    repo_root: Path | None = None,
) -> ParentIntakeResult:
    parent_run = _parent_run_for(ledger, issue.id)
    if parent_run["phase"] != ParentPhase.FINAL_ACCEPT_READY.value:
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA final accept skipped for {issue.id}.\n\n"
                    f"Current parent phase: `{parent_run['phase']}`"
                ),
            ),
        )

    if acceptance_policy is not None:
        if repo_root is None:
            raise AcceptanceError("Acceptance requires the repository root")
        acceptance_policy = replace(acceptance_policy, merge_target=resolve_parent_base(
            ledger, issue.id, standalone_base=acceptance_policy.merge_target))
        _parent_spec_context_for_issue(issue=issue, parent_run=parent_run, repo_root=repo_root)
        _land_checked_delivery(
            issue=issue, ledger=ledger, repo_root=repo_root, policy=acceptance_policy,
            spec_checksum=parent_run["spec_checksum"],
            graph_checksum=ledger.load_graph(issue.id).graph_checksum,
            branch=integration_branch or parent_integration_branch(issue.id),
        )

    # Real land (ADR-0003) when an integration seam is configured; otherwise the
    # historical no-op land path is preserved for parity.
    if integration is not None and acceptance_policy is None:
        active_integration_branch = (
            integration_branch or parent_integration_branch(issue.id)
        )
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
        probe = integration.probe_conflict(
            head=active_integration_branch,
            base=base_branch,
        )
        if not probe.clean:
            result = ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA final accept blocked by a base conflict for {issue.id} "
                    f"(base `{base_branch}`): {', '.join(probe.conflicted_paths)}. "
                    "Routing to bounded rebase + re-review."
                ),
            )
            ledger.transition_parent(
                parent_id=issue.id,
                expected_phase=parent_run["phase"],
                next_phase=ParentPhase.LANDING_CONFLICT_REBASING.value,
                effects=_parent_lifecycle_effects(
                    issue_id=issue.id,
                    target_state=result.target_state,
                    comment=result.comment,
                ),
            )
            return result
        land = ParentLandOperation(
            operation_id=f"parent-land:{issue.id}",
            idempotency_key=(
                f"parent-land:{issue.id}:{active_integration_branch}:{base_branch}"
            ),
            parent_id=issue.id,
            parent_ref=active_integration_branch,
            base_branch=base_branch,
        )
        outcome = recover_or_apply_parent_land(ledger, integration, land)
        if outcome.status != "completed":
            return _record_nontransition_parent_result(
                ledger,
                issue.id,
                ParentIntakeResult(
                    target_state="In Progress",
                    comment=(
                        f"SMDA final accept land pending for {issue.id} "
                        f"(base `{base_branch}`): {outcome.action}"
                    ),
                ),
            )

    report = _latest_parent_qa_pass_report(ledger, issue.id)
    next_phase = PARENT_DEFINITION.stage(
        ParentPhase.FINAL_ACCEPT_READY.value
    ).next_phase_on_success
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        effects=(
            BacklogEffect(
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
            ),
            BacklogEffect(
                effect_id=f"final-accept-state:{issue.id}",
                idempotency_key=f"final-accept-state:{issue.id}",
                effect_type="set_state",
                target_id=issue.id,
                payload={"state": "Done"},
            ),
        ),
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
        return _record_nontransition_parent_result(
            ledger,
            issue.id,
            ParentIntakeResult(
                target_state="In Progress",
                comment=(
                    f"SMDA landing-conflict rebase skipped for {issue.id}.\n\n"
                    f"Current parent phase: `{parent_run['phase']}`"
                ),
            ),
        )

    if integration is None:
        raise GraphError(
            f"Landing-conflict rebase requires an integration seam: {issue.id}"
        )
    active_integration_branch = (
        integration_branch or parent_integration_branch(issue.id)
    )

    qa_cycles = len(_parent_qa_result_jsons(ledger, issue.id))
    if qa_bounds is not None and qa_cycles > qa_bounds.max_parent_qa_cycles:
        result = ParentIntakeResult(
            target_state="Blocked",
            comment=(
                f"SMDA landing-conflict rebase exhausted for {issue.id} after "
                f"{qa_cycles} parent QA cycles. Escalating to human review."
            ),
        )
        ledger.transition_parent(
            parent_id=issue.id,
            expected_phase=parent_run["phase"],
            next_phase=ParentPhase.HUMAN_REVIEW_REQUIRED.value,
            effects=_parent_lifecycle_effects(
                issue_id=issue.id,
                target_state=result.target_state,
                comment=result.comment,
            ),
        )
        return result

    base_branch = resolve_parent_base(
        ledger, issue.id, standalone_base=standalone_base
    )
    integration.rebase_onto_base(head=active_integration_branch, base=base_branch)
    result = ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA rebased {issue.id} onto `{base_branch}` after a base conflict; "
            "re-running parent QA review before re-attempting the land."
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=ParentPhase.PARENT_QA_READY.value,
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


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
    workflow_definition: WorkflowDefinition = CHILD_DEFINITION,
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
        and persisted_graph.graph_checksum != decision.graph_checksum
    ):
        raise GraphError(
            f"Stale child handle for {issue.id}: graph checksum "
            f"{decision.graph_checksum} != current "
            f"{persisted_graph.graph_checksum}"
        )
    _assert_graph_contains_child(
        persisted_graph,
        parent_id=decision.parent_issue_id,
        child_id=decision.node_id,
    )
    _assert_child_id_not_owned_by_other_parent(
        ledger=ledger,
        parent_id=decision.parent_issue_id,
        child_id=decision.node_id,
    )

    gate = child_dependency_gate(
        parent_id=decision.parent_issue_id,
        child_id=decision.node_id,
        graph=persisted_graph.scheduling_view(),
        scheduler_state=ledger.load_scheduler_state(),
        candidate_ref_lookup=ledger.latest_quality_candidate_ref,
        parent_accept_operations=ledger.load_parent_accept_operations(),
    )
    if not gate.eligible:
        _record_child_dependency_wait_effect(
            ledger,
            issue_id=issue.id,
            parent_id=decision.parent_issue_id,
            child_id=decision.node_id,
            graph_checksum=persisted_graph.graph_checksum,
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
        child=_child_task_context_from_graph(
            persisted_graph,
            child_id=decision.node_id,
        ),
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
    child: ChildTaskContext | None = None,
) -> ChildCandidateTickResult:
    child = child or _child_task_context_from_issue(issue, child_id=child_id)
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
    _record_child_lifecycle_effect(
        ledger, issue.id, child_id, state,
        delivery_pending=(repo_context.acceptance_policy is not None
                          and workflow_definition.name == "smda-task"
                          and state.children[child_id].phase == ChildPhase.QUALITY_REVIEW_PASSED),
    )
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


def _child_task_context_from_graph(
    graph: WorkflowGraphArtifact,
    *,
    child_id: str,
) -> ChildTaskContext:
    child = _graph_child(graph, child_id=child_id)
    return ChildTaskContext(
        child_id=child_id,
        title=child.title,
        body=child.body,
        in_scope=child.in_scope,
        out_of_scope=child.out_of_scope,
        touched_surfaces=child.touched_surfaces.to_dict(),
        acceptance_criteria=child.acceptance_criteria,
        verification=child.verification.to_dict(),
        dependencies=child.dependencies,
        dependency_outputs=tuple(
            {
                "dependency_id": edge.from_node_id,
                "required_artifacts": list(edge.required_artifacts),
                "reason": edge.reason,
            }
            for edge in graph.dependency_edges
            if edge.to_node_id == child_id
        ),
    )


def _graph_child(
    graph: WorkflowGraphArtifact, *, child_id: str
) -> WorkflowGraphChild:
    for child in graph.children:
        if child.node_id == child_id:
            return child
    raise GraphError(f"Graph child not found: {child_id}")


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


def _spec_path(
    body: str, *, repo_root: Path | None = None,
    spec_locations: tuple[Path, ...] | None = None,
) -> str | None:
    if spec_locations is None:
        # Legacy callers retain the historical source convention.
        match = re.search(r"(docs/superpowers/specs/[A-Za-z0-9_./-]+\.md)", body)
        return match.group(1) if match else None
    root = repo_root.resolve()
    sources = _field_values(body, "Source")
    text = "\n".join(sources) if sources else body
    matches = re.findall(r"(?<![A-Za-z0-9_/.-])([A-Za-z0-9_./-]+\.md)(?![A-Za-z0-9_.-])", text)
    paths = []
    for value in matches:
        path = (root / value).resolve()
        allowed = not Path(value).is_absolute() and path.is_relative_to(root) and any(
            path.is_relative_to(location.resolve()) for location in spec_locations
        )
        if not allowed:
            if sources:
                raise GraphError(f"Source is outside configured spec locations: {value}")
            continue
        paths.append(path.relative_to(root).as_posix())
    unique = set(paths)
    if len(unique) > 1:
        raise GraphError("Multiple spec sources; provide one approved Source")
    return next(iter(unique), None)


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
    parent_run = ledger.load_parent_run(parent_id)
    if parent_run is not None:
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
    repo_root: Path | None = None,
    spec_locations: tuple[Path, ...] | None = None,
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
            try:
                source = _spec_path(issue.body, repo_root=repo_root, spec_locations=spec_locations) or ""
            except GraphError:
                # Unrelated invalid intake must not block this roadmap's context.
                source = ""
            snapshot.append(
                {
                    "issue_id": issue.id,
                    "title": issue.title,
                    "state": issue.state,
                    "source": source,
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
    return ledger.next_attempt_number(
        target_kind=target_kind,
        target_id=target_id,
        phase=phase,
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


def _parent_scoped_child_id(parent_id: str, child_id: str) -> str:
    prefix = f"{parent_id}-"
    if child_id.startswith(prefix):
        return child_id
    return f"{prefix}{child_id}"


def _next_remediation_node_id(children: tuple[WorkflowGraphChild, ...]) -> str:
    prefix = "remediation-"
    existing_numbers = []
    for child in children:
        node_id = child.node_id
        if not node_id.startswith(prefix):
            continue
        suffix = node_id[len(prefix) :]
        if suffix.isdigit():
            existing_numbers.append(int(suffix))
    return f"{prefix}{max(existing_numbers, default=0) + 1:03d}"


def _remediation_bounds_exhausted(
    ledger: PhaseLedger,
    parent_id: str,
    children: tuple[WorkflowGraphChild, ...],
    *,
    qa_bounds: QaBounds,
) -> bool:
    remediation_count = sum(
        1
        for child in children
        if child.node_id.startswith("remediation-")
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
    return ledger.parent_qa_results(parent_id)


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
    return ledger.latest_review_findings(
        target_kind="parent",
        target_id=parent_id,
        phases=(
            ParentPhase.GRAPH_SPEC_REVIEWING,
            ParentPhase.GRAPH_EXECUTION_REVIEWING,
        ),
    ) or "No graph review findings were recorded."


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


def _concern_followup_effects(
    *,
    issue_id: str,
    gate: str,
    attempt_id: str,
    outcome: AttemptOutcome,
    enabled: bool,
    labels: frozenset[str],
) -> tuple[BacklogEffect, ...]:
    if not enabled or outcome.role_result is None:
        return ()
    if outcome.role_result.verdict != "DONE_WITH_CONCERNS":
        return ()
    report = _review_report(outcome)
    if not report:
        return ()
    key = hashlib.sha256(f"{issue_id}:{gate}:{attempt_id}:{report}".encode()).hexdigest()[:16]
    body = (
        "Execution: manual\n"
        f"Parent issue: {issue_id}\n"
        f"Source gate: {gate}\n"
        f"Source attempt: {attempt_id}\n\n"
        "Concern report:\n"
        f"{report}\n\n"
        "Next: triage whether this deferred concern should become scoped SMDA work."
    )
    return (
        BacklogEffect(
            effect_id=f"concern-follow-up:{issue_id}:{key}",
            idempotency_key=f"concern-follow-up:{issue_id}:{key}",
            effect_type="create_child",
            target_id=issue_id,
            payload={
                "parent_id": issue_id,
                "title": f"Follow up: {gate} concern for {issue_id}",
                "body": body,
                "labels": sorted(labels),
            },
        ),
    )


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
    result = ParentIntakeResult(
        target_state="In Progress",
        comment=(
            f"SMDA parent {gate} failed for {issue.id}; routing to graph fix.\n\n"
            f"Findings:\n{_graph_review_findings(outcome, gate)}\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        attempt_result=AttemptResultUpdate(
            attempt_id=resolved_attempt_id,
            expected_dispatched_phase=parent_run["phase"],
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
        ),
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


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
    result = ParentIntakeResult(
        target_state="Human Review",
        comment=(
            f"SMDA parent {gate} requires human review for {issue.id}.\n\n"
            f"Findings:\n{report.strip()}\n\n"
            f"Parent phase: `{next_phase}`\n"
            f"Attempt: `{resolved_attempt_id}`"
        ),
    )
    ledger.transition_parent(
        parent_id=issue.id,
        expected_phase=parent_run["phase"],
        next_phase=next_phase,
        attempt_result=AttemptResultUpdate(
            attempt_id=resolved_attempt_id,
            expected_dispatched_phase=parent_run["phase"],
            status=outcome.status,
            result_json=_attempt_result_json(outcome),
            error_message=outcome.error_message,
        ),
        effects=_parent_lifecycle_effects(
            issue_id=issue.id,
            target_state=result.target_state,
            comment=result.comment,
        ),
    )
    return result


# Child SDD phase -> consumer tracker state. Active phases map to In Progress;
# the terminal/parked phases get their own coarse state.
_CHILD_PHASE_TRACKER_STATE: dict[ChildPhase, str] = {
    ChildPhase.QUALITY_REVIEW_PASSED: "Agent Review",
    ChildPhase.HUMAN_REVIEW_REQUIRED: "Human Review",
}


def _assert_graph_contains_child(
    graph: WorkflowGraphArtifact,
    *,
    parent_id: str,
    child_id: str,
) -> None:
    if child_id not in {child.node_id for child in graph.children}:
        raise GraphError(
            f"Child node {child_id} is not present in current graph for {parent_id}"
        )


def _assert_child_id_not_owned_by_other_parent(
    *,
    ledger: PhaseLedger,
    parent_id: str,
    child_id: str,
) -> None:
    for owner_parent_id in ledger.child_parent_ids(child_id):
        if owner_parent_id != parent_id:
            raise GraphError(
                f"Child node {child_id} belongs to parent {owner_parent_id}; "
                f"refusing to run it for {parent_id}"
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
    *,
    delivery_pending: bool = False,
) -> None:
    """Sync a child SDD phase change to the child issue's tracker state.

    Parent transitions already sync; without this, child issues never reflect
    their In Progress / Agent Review / Human Review lifecycle in the tracker.
    Keyed by phase so repeated ticks at the same phase dedupe.
    """
    child = state.children.get(child_id)
    if child is None:
        return
    tracker_state = "In Progress" if delivery_pending else _CHILD_PHASE_TRACKER_STATE.get(child.phase, "In Progress")
    key = child.phase.value + (":delivery-pending" if delivery_pending else "")
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
    return ledger.latest_child_report(child_id)


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
    findings = ledger.latest_review_findings(
        target_kind="child",
        target_id=child_id,
        phases=(review_phase,),
    )
    return (findings,) if findings is not None else ()


def _latest_parent_qa_report(
    ledger: PhaseLedger,
    parent_id: str,
    *,
    verdicts: tuple[str, ...],
    fallback: str,
) -> str:
    for result in reversed(ledger.parent_qa_results(parent_id)):
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
    child: WorkflowGraphChild,
    dependency_edges: tuple[DependencyEdge, ...] = (),
) -> str:
    incoming_edges = [
        edge
        for edge in dependency_edges
        if edge.to_node_id == child.node_id
    ]

    context_lines = [
        *_prefixed_lines("In scope", child.in_scope),
        *_prefixed_lines("Out of scope", child.out_of_scope),
        *_prefixed_lines("Touched files", child.touched_surfaces.files),
        *_prefixed_lines("Touched modules", child.touched_surfaces.modules),
        *_prefixed_lines("Touched contracts", child.touched_surfaces.contracts),
        *_prefixed_lines("Touched docs", child.touched_surfaces.docs),
        *_prefixed_lines("Touched tests", child.touched_surfaces.tests),
        *_prefixed_lines("Acceptance criteria", child.acceptance_criteria),
        *_prefixed_lines("Verification required", child.verification.required),
        *_prefixed_lines("Verification smoke", child.verification.smoke),
        f"Risk level: {child.risk_level}",
        *_dependency_reason_lines(incoming_edges),
    ]

    return "\n".join(
        [
            "Execution: smda-child",
            f"Parent issue: {parent_id}",
            f"Graph checksum: {graph_checksum}",
            f"Node id: {child.node_id}",
            f"Source: {spec_path}",
            *context_lines,
            "",
            child.body,
        ]
    )


def _prefixed_lines(prefix: str, values: list[str] | tuple[str, ...]) -> list[str]:
    if not values:
        return [f"{prefix}: none"]
    return [f"{prefix}: {value}" for value in values]


def _dependency_reason_lines(edges: list[DependencyEdge]) -> list[str]:
    if not edges:
        return ["Dependency reasons: none"]
    lines: list[str] = []
    for edge in edges:
        lines.append(
            "Dependency reasons: "
            f"{edge.from_node_id} -> {edge.to_node_id} "
            f"({edge.type}, blocks_dispatch={edge.blocks_dispatch}): "
            f"{edge.reason}"
        )
        lines.extend(
            _prefixed_lines(
                "Required artifacts",
                edge.required_artifacts,
            )
        )
    return lines


def _parent_accept_operation_with_id(
    ledger: PhaseLedger,
    operation_id: str,
) -> dict:
    for operation in ledger.load_parent_accept_operations():
        if operation["operation_id"] == operation_id:
            return operation
    raise GraphError(f"Parent accept operation not found: {operation_id}")


def _latest_parent_accept_conflict_operation(
    ledger: PhaseLedger,
    parent_id: str,
) -> dict:
    for operation in reversed(ledger.load_parent_accept_operations()):
        if (
            operation["parent_id"] == parent_id
            and operation["status"] == "pending"
            and operation["conflict_fingerprint"]
        ):
            return operation
    raise GraphError(f"No pending parent accept conflict for {parent_id}")


def _parent_accept_conflict_history(
    ledger: PhaseLedger,
    parent_id: str,
) -> dict[str, object]:
    operation = _latest_parent_accept_conflict_operation(ledger, parent_id)
    resolver_attempts = []
    for attempt in ledger.conflict_attempt_history(parent_id):
        if attempt["operation_id"] != operation["operation_id"]:
            continue
        resolver_attempts.append(
            {
                "attempt_id": attempt["attempt_id"],
                "status": attempt["status"],
                "verdict": attempt["verdict"],
                "required_next_action": attempt["required_next_action"],
                "report": attempt["report"],
            }
        )
    return {
        "operation_id": operation["operation_id"],
        "fingerprint": operation["conflict_fingerprint"],
        "conflict_fingerprint": operation["conflict_fingerprint"],
        "resolver_attempts": operation["resolver_attempts"],
        "parent_id": operation["parent_id"],
        "child_id": operation["child_id"],
        "candidate_ref": operation["candidate_ref"],
        "integration_branch": operation["integration_branch"],
        "conflicted_paths": list(operation["conflicted_paths"]),
        "last_error": operation["last_error"],
        "resolver_attempt_history": resolver_attempts,
    }


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
    candidate_ref = ledger.latest_quality_candidate_ref(child_id)
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


def _land_checked_delivery(*, issue, ledger, repo_root, policy, spec_checksum,
                           graph_checksum, branch):
    attempt = ledger.latest_parent_qa_attempt(issue.id)
    if not attempt or attempt["status"] != "succeeded":
        raise AcceptanceError("No successful revision-bound delivery QA")
    result = attempt["result_json"] or {}
    if result.get("verdict") not in ("PASS", "DONE_WITH_CONCERNS") or result.get("required_next_action") != "accept_parent":
        raise AcceptanceError("Latest delivery QA did not pass")
    packet = attempt["request_json"].get("context_packet", {})
    snapshot = packet.get("acceptance_snapshot")
    evidence = result.get("acceptance_evidence", {})
    if not snapshot or evidence.get("issue_body_checksum") != hashlib.sha256(issue.body.encode()).hexdigest():
        raise AcceptanceError("Missing or stale work authorization evidence")
    if packet.get("spec_checksum") != spec_checksum or packet.get("graph_checksum") != graph_checksum:
        raise AcceptanceError("Source or work graph changed after QA")
    if snapshot.get("branch") != branch:
        raise AcceptanceError("Delivery branch differs from reviewed candidate")
    operation_id = f"checked-land:{issue.id}:{attempt['attempt_id']}"
    for operation in ledger.load_parent_land_operations():
        if operation["operation_id"] == operation_id and operation["status"] == "completed":
            if (operation["parent_id"] != issue.id
                    or operation["parent_ref"] != snapshot["candidate"]
                    or operation["base_branch"] != snapshot["target"]):
                raise AcceptanceError("Completed delivery identity changed")
            return snapshot["candidate"]
    ledger.record_parent_land_operation(
        operation_id=operation_id, idempotency_key=operation_id,
        parent_id=issue.id, parent_ref=snapshot["candidate"], base_branch=snapshot["target"],
    )
    try:
        land_candidate(repo_root, snapshot, evidence, policy)
    except AcceptanceError as error:
        ledger.mark_parent_land_failed(operation_id, str(error))
        raise
    ledger.mark_parent_land_completed(operation_id)
    return snapshot["candidate"]


def _checked_delivery_review(*, issue, ledger, repo_context, repo_root, execution,
                             sandbox_provider, agent, parent, children, dependency_edges,
                             branch, policy):
    """Prepare evidence once; the following tick validates and lands it.

    Task and roadmap delivery reuse the parent acceptance role and attempt ledger.
    Their existing resting phases remain in place until delivery completes.
    """
    graph_checksum = _graph_checksum(list(children), dependency_edges=list(dependency_edges))
    previous = ledger.latest_parent_qa_attempt(issue.id)
    if previous is not None:
        _land_checked_delivery(
            issue=issue, ledger=ledger, repo_root=repo_root, policy=policy,
            spec_checksum=parent.spec_checksum, graph_checksum=graph_checksum, branch=branch,
        )
        return True
    snapshot = snapshot_candidate(repo_root, branch, policy)
    for child in children:
        if "accepted_candidate" in child:
            require_ancestor(repo_root, child["accepted_candidate"], snapshot["candidate"])
            check_candidate_source(repo_root, snapshot["candidate"], child["spec_path"], child["spec_checksum"])
    if not parent.spec_path.startswith("issue:"):
        check_candidate_source(repo_root, snapshot["candidate"], parent.spec_path, parent.spec_checksum)
    check_candidate_source(
        repo_root, snapshot["candidate"],
        str(repo_context.harness_contract_path.relative_to(repo_root)),
        repo_context.harness_contract_checksum,
    )
    attempt_number = ledger.next_attempt_number(
        target_kind="parent", target_id=issue.id, phase=ParentPhase.PARENT_QA_REVIEWING,
    )
    request = build_parent_qa_review_request(
        attempt_id=f"{issue.id}-PARENT_QA_REVIEWING-{attempt_number}",
        contract=PARENT_DEFINITION.stage(ParentPhase.PARENT_QA_READY.value).role_contract,
        graph=ParentGraphContext(parent=parent, graph_checksum=graph_checksum,
                                 children=children, dependency_edges=dependency_edges),
        repo_context=repo_context, repo_root=repo_root,
        sandbox_provider=sandbox_provider, agent=agent,
    )
    request = replace(
        request, branch=f"{request.branch}-{attempt_number}-{snapshot['candidate']}",
        context_packet={**request.context_packet, "acceptance_snapshot": snapshot},
        prompt=(request.prompt or "") + "\n\nReview the entire delivery against its source and work items. Do not modify it.\n" + json.dumps(snapshot),
    )
    ledger.record_role_attempt_request(
        attempt_id=request.attempt_id, target_kind="parent", target_id=issue.id,
        phase=ParentPhase.PARENT_QA_REVIEWING, idempotency_key=request.attempt_id,
        request_json=request.to_ipc_payload(),
    )
    outcome = None
    try:
        outcome = run_candidate_review(repo_root, snapshot, request, execution)
        if not (outcome.status == "succeeded" and _is_passing_review(outcome.role_result, "accept_parent")):
            raise AcceptanceError("Delivery QA requires human attention; no automatic merge")
        if outcome.commits:
            raise AcceptanceError("Delivery reviewer changed code; repeat QA")
        evidence = verify_candidate(repo_root, snapshot, policy)
        evidence["issue_body_checksum"] = hashlib.sha256(issue.body.encode()).hexdigest()
        outcome = replace(outcome, raw_result={**(outcome.raw_result or {}), "acceptance_evidence": evidence})
    except AcceptanceError as error:
        ledger.record_attempt_result(attempt_id=request.attempt_id, status="failed",
                                     result_json=_attempt_result_json(outcome) if outcome else None,
                                     error_message=str(error))
        raise
    ledger.record_attempt_result(attempt_id=request.attempt_id, status=outcome.status,
                                 result_json=_attempt_result_json(outcome), error_message=None)
    return False


def _task_source_context(issue, repo_root):
    sources = _field_values(issue.body, "Source")
    if len(sources) != 1:
        raise AcceptanceError("Checked tasks require one Source reference")
    source = sources[0]
    if source.endswith(".md") or source.startswith("docs/"):
        text = _read_repo_file(repo_root, source)
        path = source
    else:
        # A directly authorized small task may cite a conversation/tracker decision.
        path, text = f"issue:{issue.id}", issue.body
    return ParentSpecContext(
        parent_issue_id=issue.id, title=issue.title, body=issue.body,
        spec_path=path, spec_text=text,
        spec_checksum="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        approval_evidence=f"Scoped task under project acceptance policy; Source: {source}",
    )


def run_checked_task_tick(*, issue, repo_context, repo_root, ledger, execution,
                          sandbox_provider, agent, now, owner, workflow_definition):
    parent = _task_source_context(issue, repo_root)
    state = ledger.load_scheduler_state()
    child = state.children.get(issue.id)
    if child is None or child.phase != ChildPhase.QUALITY_REVIEW_PASSED:
        return run_sdd_candidate_tick(
            issue=issue, child_id=issue.id, parent_issue_id=issue.id,
            repo_context=repo_context, repo_root=repo_root, ledger=ledger,
            execution=execution, sandbox_provider=sandbox_provider, agent=agent,
            now=now, owner=owner, workflow_definition=workflow_definition,
        )
    branch = ledger.latest_quality_candidate_ref(issue.id)
    if not branch:
        raise AcceptanceError("Task quality review did not provide a candidate ref")
    task = asdict(_child_task_context_from_issue(issue, child_id=issue.id))
    accepted = _checked_delivery_review(
        issue=issue, ledger=ledger, repo_context=repo_context, repo_root=repo_root,
        execution=execution, sandbox_provider=sandbox_provider, agent=agent,
        parent=parent, children=(task,), dependency_edges=(), branch=branch,
        policy=repo_context.acceptance_policy,
    )
    delivery_state = "Done" if accepted else "In Progress"
    ledger.record_tracker_effect(
        effect_id=f"task-acceptance:{issue.id}:{delivery_state}",
        idempotency_key=f"task-acceptance:{issue.id}:{delivery_state}",
        effect_type="set_state", target_id=issue.id, payload={"state": delivery_state},
    )
    return ChildCandidateTickResult(status="dispatched", state=state,
        detail=f"{issue.id}: {'accepted' if accepted else 'delivery QA passed; awaiting merge'}")


def _roadmap_acceptance_members(ledger, roadmap_id, repo_root):
    members = ledger.load_roadmap_members(roadmap_id)
    projections = ledger.load_roadmap_member_projections(roadmap_id)
    if not members or set(projections) != {member["node_id"] for member in members}:
        raise AcceptanceError("Roadmap publication is incomplete; cannot accept aggregate")
    children = []
    branch = roadmap_integration_branch(roadmap_id)
    operations = ledger.load_parent_land_operations()
    for member in members:
        parent_id = projections[member["node_id"]]
        run = ledger.load_parent_run(parent_id)
        attempt = ledger.latest_parent_qa_attempt(parent_id)
        if not run or run["phase"] != ParentPhase.FINAL_ACCEPTED.value or not attempt or attempt["status"] != "succeeded":
            raise AcceptanceError(f"Roadmap member lacks accepted QA: {parent_id}")
        evidence = (attempt["result_json"] or {}).get("acceptance_evidence", {})
        snapshot = evidence.get("snapshot", {})
        candidate = snapshot.get("candidate")
        if not candidate or snapshot.get("target") != branch or not any(
            op["parent_id"] == parent_id and op["parent_ref"] == candidate
            and op["base_branch"] == branch and op["status"] == "completed"
            for op in operations
        ):
            raise AcceptanceError(f"Roadmap member lacks checked integration evidence: {parent_id}")
        require_ancestor(repo_root, candidate, branch)
        check_candidate_source(repo_root, candidate, run["spec_path"], run["spec_checksum"])
        check_candidate_source(repo_root, branch, run["spec_path"], run["spec_checksum"])
        if ledger.load_graph(parent_id).graph_checksum != attempt["request_json"].get("context_packet", {}).get("graph_checksum"):
            raise AcceptanceError(f"Roadmap member graph changed after acceptance: {parent_id}")
        current_spec = _read_repo_file(repo_root, run["spec_path"])
        if "sha256:" + hashlib.sha256(current_spec.encode()).hexdigest() != run["spec_checksum"]:
            raise AcceptanceError(f"Roadmap member source changed: {parent_id}")
        children.append({**member, "parent_id": parent_id, "accepted_candidate": candidate,
                         "spec_checksum": run["spec_checksum"], "spec_path": run["spec_path"],
                         "graph_checksum": ledger.load_graph(parent_id).graph_checksum})
    return tuple(children), tuple(ledger.load_roadmap_member_edges(roadmap_id))
