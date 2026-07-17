from __future__ import annotations

import re
from dataclasses import dataclass
from smda_scheduler.scheduling import SchedulerState
from smda_scheduler.workflow import ChildPhase, DependencyEdge, WorkflowGraph


@dataclass(frozen=True)
class ChildDependencyGateResult:
    eligible: bool
    blocked_by: tuple[str, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    reason: str = ""


def child_dependency_gate(
    *,
    parent_id: str,
    child_id: str,
    graph: WorkflowGraph,
    scheduler_state: SchedulerState,
    attempts: list[dict],
    parent_accept_operations: list[dict],
) -> ChildDependencyGateResult:
    blocked_by: list[str] = []
    missing_artifacts: list[str] = []

    for edge in _incoming_blocking_edges(graph, child_id):
        upstream_id = edge.from_node_id
        upstream_state = scheduler_state.children.get(upstream_id)
        if (
            upstream_state is None
            or upstream_state.phase != ChildPhase.QUALITY_REVIEW_PASSED
        ):
            blocked_by.append(upstream_id)
            missing_artifacts.append(f"{upstream_id}:quality_review_passed")
            continue

        candidate_ref = latest_quality_candidate_ref(attempts, upstream_id)
        if candidate_ref is None:
            blocked_by.append(upstream_id)
            missing_artifacts.append(f"{upstream_id}:candidate_ref")
            continue

        if not _has_completed_accept(
            parent_accept_operations,
            parent_id=parent_id,
            child_id=upstream_id,
            candidate_ref=candidate_ref,
        ):
            blocked_by.append(upstream_id)
            missing_artifacts.append(f"{upstream_id}:accepted_commit")

    unique_blocked_by = tuple(dict.fromkeys(blocked_by))
    unique_missing = tuple(dict.fromkeys(missing_artifacts))
    if not unique_blocked_by:
        return ChildDependencyGateResult(eligible=True)

    return ChildDependencyGateResult(
        eligible=False,
        blocked_by=unique_blocked_by,
        missing_artifacts=unique_missing,
        reason=_reason(unique_blocked_by, unique_missing),
    )


def latest_quality_candidate_ref(attempts: list[dict], child_id: str) -> str | None:
    matching_attempts = [
        (index, attempt)
        for index, attempt in enumerate(attempts)
        if (
            attempt.get("target_kind") == "child"
            and attempt.get("target_id") == child_id
            and attempt.get("phase") == ChildPhase.QUALITY_REVIEWING.value
            and attempt.get("status") == "succeeded"
        )
    ]
    if not matching_attempts:
        return None

    _, latest_attempt = max(
        matching_attempts,
        key=lambda indexed_attempt: _attempt_order_key(
            indexed_attempt[1],
            fallback_index=indexed_attempt[0],
        ),
    )
    result = latest_attempt.get("result_json") or {}
    if not isinstance(result, dict):
        return None
    branch = result.get("branch")
    if isinstance(branch, str) and branch:
        return branch
    commits = result.get("commits")
    if isinstance(commits, list) and commits and isinstance(commits[-1], str):
        return commits[-1]
    return None


def _attempt_order_key(attempt: dict, *, fallback_index: int) -> tuple[int, int]:
    sequence = _attempt_sequence(attempt)
    if sequence is None:
        return (0, fallback_index)
    return (1, sequence)


def _attempt_sequence(attempt: dict) -> int | None:
    for key in ("idempotency_key", "attempt_id"):
        value = attempt.get(key)
        if not isinstance(value, str):
            continue
        match = re.search(r"(?P<sequence>\d+)$", value)
        if match is not None:
            return int(match.group("sequence"))
    return None


def _incoming_blocking_edges(
    graph: WorkflowGraph, child_id: str
) -> list[DependencyEdge]:
    return [
        edge
        for edge in graph.dependency_edges
        if edge.to_node_id == child_id and edge.blocks_dispatch
    ]


def _has_completed_accept(
    parent_accept_operations: list[dict],
    *,
    parent_id: str,
    child_id: str,
    candidate_ref: str,
) -> bool:
    for operation in parent_accept_operations:
        if (
            operation.get("parent_id") == parent_id
            and operation.get("child_id") == child_id
            and operation.get("candidate_ref") == candidate_ref
            and operation.get("status") == "completed"
        ):
            return True
    return False


def _reason(
    blocked_by: tuple[str, ...],
    missing_artifacts: tuple[str, ...],
) -> str:
    blocked = ", ".join(blocked_by)
    missing = ", ".join(missing_artifacts)
    return f"Waiting for accepted upstream dependencies: {blocked}. Missing: {missing}"
