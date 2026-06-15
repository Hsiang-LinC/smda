from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from smda_scheduler.backlog import BacklogIssue


class CandidateRoute(StrEnum):
    PARENT = "parent"
    IMPLICIT_PARENT = "implicit_parent"
    CHILD = "child"
    BLOCK = "block"


@dataclass(frozen=True)
class CandidateRoutingDecision:
    route: CandidateRoute
    reason: str
    parent_issue_id: str | None = None
    node_id: str | None = None
    graph_checksum: str | None = None


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
    if normalized == "smda":
        return CandidateRoutingDecision(
            route=CandidateRoute.PARENT,
            reason="Execution: smda",
        )
    if normalized == "smda-child":
        return _classify_child(issue)
    if normalized == "orchestrator":
        return CandidateRoutingDecision(
            route=CandidateRoute.BLOCK,
            reason="Execution: orchestrator is obsolete; use Execution: smda or Execution: smda-child",
        )

    return CandidateRoutingDecision(
        route=CandidateRoute.BLOCK,
        reason=f"Unsupported Execution mode: {execution_mode}",
    )


def _classify_child(issue: BacklogIssue) -> CandidateRoutingDecision:
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
        )

    return CandidateRoutingDecision(
        route=CandidateRoute.CHILD,
        reason="Execution: smda-child",
        parent_issue_id=parent_issue_id,
        node_id=node_id,
        graph_checksum=graph_checksum,
    )


def _classify_unmodeled_issue(
    body: str,
    *,
    issue_entry_policy: str,
) -> CandidateRoutingDecision:
    if issue_entry_policy == "implicit-one-child" and _has_minimal_context(body):
        return CandidateRoutingDecision(
            route=CandidateRoute.IMPLICIT_PARENT,
            reason="implicit-one-child policy",
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
