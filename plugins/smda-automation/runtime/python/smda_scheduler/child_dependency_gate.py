from __future__ import annotations

from collections.abc import Callable
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
    candidate_ref_lookup: Callable[[str], str | None],
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

        candidate_ref = candidate_ref_lookup(upstream_id)
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
