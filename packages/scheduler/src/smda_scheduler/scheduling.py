from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    RoleResult,
    WorkflowGraph,
    eligible_child_ids,
    transition_child_phase,
)


@dataclass(frozen=True)
class Claim:
    owner: str
    lease_expires_at: float


@dataclass(frozen=True)
class ChildRunState:
    phase: ChildPhase
    attempts: int = 0
    claim: Claim | None = None
    next_not_before: float = 0.0


@dataclass(frozen=True)
class SchedulerState:
    children: dict[str, ChildRunState] | None = None

    def __post_init__(self) -> None:
        if self.children is None:
            object.__setattr__(self, "children", {})


@dataclass(frozen=True)
class AttemptOutcome:
    status: str
    role_result: RoleResult | None = None


Executor = Callable[[str, ChildPhase], AttemptOutcome]


def run_once(
    graph: WorkflowGraph,
    state: SchedulerState,
    *,
    executor: Executor,
    now: float,
    owner: str,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    lease_seconds: float = 30.0,
) -> SchedulerState:
    current_state = reconcile_expired_claims(state, now=now)
    effective_graph = _effective_graph(graph, current_state)
    completed = frozenset(
        child_id
        for child_id, child in current_state.children.items()
        if child.phase == ChildPhase.QUALITY_REVIEW_PASSED
    )

    for child_id in eligible_child_ids(effective_graph, completed_child_ids=completed):
        child = _child_state_for(graph, current_state, child_id)
        if child.claim is not None or child.next_not_before > now:
            continue

        dispatch_phase = _dispatch_phase(child.phase)
        claimed = replace(
            child,
            phase=dispatch_phase,
            claim=Claim(owner=owner, lease_expires_at=now + lease_seconds),
        )
        claimed_state = _with_child(current_state, child_id, claimed)
        outcome = executor(child_id, dispatch_phase)
        attempted = replace(claimed, attempts=claimed.attempts + 1, claim=None)

        if outcome.status == "succeeded":
            if outcome.role_result is None:
                raise ValueError("succeeded attempt requires role_result")
            transitioned = replace(
                attempted,
                phase=transition_child_phase(dispatch_phase, outcome.role_result),
                next_not_before=0.0,
            )
            return _with_child(claimed_state, child_id, transitioned)

        failed_phase = (
            ChildPhase.HUMAN_REVIEW_REQUIRED
            if attempted.attempts >= max_attempts
            else child.phase
        )
        failed = replace(
            attempted,
            phase=failed_phase,
            next_not_before=now + backoff_seconds,
        )
        return _with_child(claimed_state, child_id, failed)

    return current_state


def reconcile_expired_claims(state: SchedulerState, *, now: float) -> SchedulerState:
    next_children: dict[str, ChildRunState] = {}
    changed = False
    for child_id, child in state.children.items():
        if child.claim is not None and child.claim.lease_expires_at <= now:
            next_children[child_id] = replace(child, claim=None)
            changed = True
        else:
            next_children[child_id] = child
    if not changed:
        return state
    return SchedulerState(children=next_children)


def _dispatch_phase(phase: ChildPhase) -> ChildPhase:
    if phase == ChildPhase.READY:
        return ChildPhase.IMPLEMENTING
    return phase


def _child_state_for(
    graph: WorkflowGraph,
    state: SchedulerState,
    child_id: str,
) -> ChildRunState:
    if child_id in state.children:
        return state.children[child_id]
    return ChildRunState(phase=graph.children[child_id].phase)


def _effective_graph(graph: WorkflowGraph, state: SchedulerState) -> WorkflowGraph:
    children = {
        child_id: ChildNode(
            id=node.id,
            dependencies=node.dependencies,
            phase=state.children.get(child_id, ChildRunState(node.phase)).phase,
        )
        for child_id, node in graph.children.items()
    }
    return WorkflowGraph(children=children)


def _with_child(
    state: SchedulerState,
    child_id: str,
    child: ChildRunState,
) -> SchedulerState:
    next_children = dict(state.children)
    next_children[child_id] = child
    return SchedulerState(children=next_children)
