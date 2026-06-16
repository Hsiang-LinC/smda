from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.execution_modes import (
    ExecutionMode,
    WorkflowOptions,
    WorkflowOptionsError,
    parse_execution_mode,
    parse_mode_tags,
    resolve_workflow_options,
)


class CandidateRoute(StrEnum):
    PARENT = "parent"
    IMPLICIT_PARENT = "implicit_parent"
    ROADMAP = "roadmap"
    CHILD = "child"
    TASK = "task"
    BLOCK = "block"


@dataclass(frozen=True)
class CandidateRoutingDecision:
    route: CandidateRoute
    reason: str
    parent_issue_id: str | None = None
    node_id: str | None = None
    graph_checksum: str | None = None
    workflow_options: WorkflowOptions | None = None


def classify_candidate(
    issue: BacklogIssue,
    *,
    issue_entry_policy: str,
) -> CandidateRoutingDecision:
    body = issue.body
    execution_mode = _field(body, "Execution")
    if execution_mode is None:
        return _classify_unmodeled_issue(
            body,
            issue_entry_policy=issue_entry_policy,
        )

    normalized = execution_mode.lower()
    if normalized == "orchestrator":
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Execution: orchestrator is obsolete; use Execution: smda, Execution: smda-child, or Execution: smda-task",
        )

    try:
        mode = parse_execution_mode(execution_mode)
        tags = parse_mode_tags(_field(body, "Mode tags"))
        workflow_options = resolve_workflow_options(mode=mode, tags=tags)
    except WorkflowOptionsError as error:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason=str(error),
        )

    if mode == ExecutionMode.SMDA:
        return CandidateRoutingDecision(
            route=CandidateRoute.PARENT,
            reason="Execution: smda",
            workflow_options=workflow_options,
        )
    if mode == ExecutionMode.SMDA_ROADMAP:
        return CandidateRoutingDecision(
            route=CandidateRoute.ROADMAP,
            reason="Execution: smda-roadmap",
            workflow_options=workflow_options,
        )
    if mode == ExecutionMode.SMDA_CHILD:
        return _classify_child(issue, workflow_options=workflow_options)
    if mode == ExecutionMode.SMDA_TASK:
        return _classify_task(issue, workflow_options=workflow_options)
    if mode == ExecutionMode.MANUAL:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Execution: manual prevents automatic claim",
            workflow_options=workflow_options,
        )
    if mode == ExecutionMode.SMDA_REVIEW:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Execution: smda-review is not enabled in this implementation slice",
            workflow_options=workflow_options,
        )

    return CandidateRoutingDecision(
        route=CandidateRoute.BLOCK,
        reason=f"Unsupported Execution mode: {execution_mode}",
    )


def _classify_child(
    issue: BacklogIssue,
    *,
    workflow_options: WorkflowOptions,
) -> CandidateRoutingDecision:
    parent_issue_id = _field(issue.body, "Parent issue")
    graph_checksum = _field(issue.body, "Graph checksum")
    node_id = _field(issue.body, "Node id")
    acceptance_criteria = _field(issue.body, "Acceptance criteria")
    missing = [
        label
        for label, value in (
            ("Parent issue", parent_issue_id),
            ("Graph checksum", graph_checksum),
            ("Node id", node_id),
            ("Acceptance criteria", acceptance_criteria),
        )
        if value is None
    ]
    if missing:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason=f"Missing smda-child context: {', '.join(missing)}",
            workflow_options=workflow_options,
        )

    return CandidateRoutingDecision(
        route=CandidateRoute.CHILD,
        reason="Execution: smda-child",
        parent_issue_id=parent_issue_id,
        node_id=node_id,
        graph_checksum=graph_checksum,
        workflow_options=workflow_options,
    )


def _classify_task(
    issue: BacklogIssue,
    *,
    workflow_options: WorkflowOptions,
) -> CandidateRoutingDecision:
    acceptance_criteria = _field(issue.body, "Acceptance criteria")
    verification = _field(issue.body, "Verification")
    missing = [
        label
        for label, value in (
            ("Acceptance criteria", acceptance_criteria),
            ("Verification", verification),
        )
        if value is None
    ]
    if missing:
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason=f"Missing smda-task context: {', '.join(missing)}",
            workflow_options=workflow_options,
        )

    return CandidateRoutingDecision(
        route=CandidateRoute.TASK,
        reason="Execution: smda-task",
        workflow_options=workflow_options,
    )


def _classify_unmodeled_issue(
    body: str,
    *,
    issue_entry_policy: str,
) -> CandidateRoutingDecision:
    if issue_entry_policy == "implicit-one-child" and _has_minimal_context(body):
        workflow_options = resolve_workflow_options(
            mode=ExecutionMode.SMDA_TASK,
            tags=frozenset(),
        )
        return CandidateRoutingDecision(
            route=CandidateRoute.TASK,
            reason="implicit-one-child policy -> smda-task",
            workflow_options=workflow_options,
        )
    if issue_entry_policy == "blocked":
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Unmodeled work is blocked by policy",
        )
    return CandidateRoutingDecision(
        route=CandidateRoute.BLOCK,
        reason="Missing Execution mode under explicit-only policy",
    )


def _has_minimal_context(body: str) -> bool:
    return all(
        _field(body, label) is not None
        for label in ("Source", "Acceptance criteria", "Verification")
    )


def _field(body: str, label: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", re.I | re.M)
    match = pattern.search(body)
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None
