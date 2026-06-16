from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any
from typing import Protocol

from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    RoleResult,
    WorkflowGraph,
)
from smda_scheduler.workflow_engine import CHILD_DEFINITION, WorkflowEngine

# The child SDD workflow is interpreted by the engine; the scheduler keeps owning
# claim/lease, durable recording, backoff, and fix-cycle escalation.
_CHILD_ENGINE = WorkflowEngine(CHILD_DEFINITION)


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
    review_fix_cycles: int = 0


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
    raw_result: dict[str, Any] | None = None
    error_message: str | None = None
    commits: tuple[str, ...] = ()
    branch: str | None = None
    preserved_worktree_path: str | None = None
    schema_id: str | None = None
    schema_package_version: str | None = None


@dataclass(frozen=True)
class AttemptDispatch:
    child_id: str
    phase: ChildPhase
    attempt_id: str
    attempt_number: int
    owner: str


Executor = Callable[[AttemptDispatch], AttemptOutcome]
StateSink = Callable[[SchedulerState], None]


class SchedulerStateStore(Protocol):
    def load_scheduler_state(self) -> SchedulerState: ...

    def save_scheduler_state(self, state: SchedulerState) -> None: ...

    def record_attempt_request(
        self,
        *,
        attempt_id: str,
        child_id: str,
        phase: ChildPhase,
        idempotency_key: str,
        request_json: dict,
    ) -> str: ...

    def record_attempt_result_and_state(
        self,
        *,
        attempt_id: str,
        status: str,
        result_json: dict | None,
        error_message: str | None,
        state: SchedulerState,
    ) -> None: ...


_FIXING_PHASES = frozenset({ChildPhase.FIXING_SPEC, ChildPhase.FIXING_QUALITY})


def run_once(
    graph: WorkflowGraph,
    state: SchedulerState,
    *,
    executor: Executor,
    now: float,
    owner: str,
    max_attempts: int = 3,
    max_review_fix_cycles: int = 3,
    backoff_seconds: float = 1.0,
    lease_seconds: float = 30.0,
    state_sink: StateSink | None = None,
) -> SchedulerState:
    current_state = reconcile_expired_claims(state, now=now)
    effective_graph = _effective_graph(graph, current_state)
    completed = frozenset(
        child_id
        for child_id, child in current_state.children.items()
        if child.phase == ChildPhase.QUALITY_REVIEW_PASSED
    )

    for child_id in _CHILD_ENGINE.eligible(
        effective_graph, completed_child_ids=completed
    ):
        child = _child_state_for(graph, current_state, child_id)
        if child.claim is not None or child.next_not_before > now:
            continue

        dispatch_phase = _CHILD_ENGINE.dispatch_phase(child.phase)
        attempt_number = child.attempts + 1
        dispatch = AttemptDispatch(
            child_id=child_id,
            phase=dispatch_phase,
            attempt_id=_attempt_id(child_id, dispatch_phase, attempt_number),
            attempt_number=attempt_number,
            owner=owner,
        )
        claimed = replace(
            child,
            phase=dispatch_phase,
            claim=Claim(owner=owner, lease_expires_at=now + lease_seconds),
        )
        claimed_state = _with_child(current_state, child_id, claimed)
        if state_sink is not None:
            state_sink(claimed_state)

        outcome = executor(dispatch)
        attempted = replace(claimed, attempts=claimed.attempts + 1, claim=None)

        if outcome.status == "succeeded":
            if outcome.role_result is None:
                raise ValueError("succeeded attempt requires role_result")
            next_phase = _CHILD_ENGINE.next_phase(dispatch_phase, outcome.role_result)
            fix_cycles = attempted.review_fix_cycles
            if next_phase in _FIXING_PHASES:
                fix_cycles += 1
                if fix_cycles > max_review_fix_cycles:
                    # Reviewer keeps failing the fix: stop the review<->fix
                    # oscillation and escalate instead of looping forever.
                    next_phase = ChildPhase.HUMAN_REVIEW_REQUIRED
            transitioned = replace(
                attempted,
                phase=next_phase,
                review_fix_cycles=fix_cycles,
                next_not_before=0.0,
            )
            next_state = _with_child(claimed_state, child_id, transitioned)
            if state_sink is not None:
                state_sink(next_state)
            return next_state

        immediate_block = _requires_immediate_human_review(outcome)
        failed_phase = (
            ChildPhase.HUMAN_REVIEW_REQUIRED
            if immediate_block or attempted.attempts >= max_attempts
            else child.phase
        )
        failed = replace(
            attempted,
            phase=failed_phase,
            next_not_before=0.0 if immediate_block else now + backoff_seconds,
        )
        next_state = _with_child(claimed_state, child_id, failed)
        if state_sink is not None:
            state_sink(next_state)
        return next_state

    return current_state


def run_once_durable(
    graph: WorkflowGraph,
    state_store: SchedulerStateStore,
    *,
    executor: Executor,
    now: float,
    owner: str,
    max_attempts: int = 3,
    max_review_fix_cycles: int = 3,
    backoff_seconds: float = 1.0,
    lease_seconds: float = 30.0,
) -> SchedulerState:
    initial_state = state_store.load_scheduler_state()
    active_attempt: dict[str, str | AttemptOutcome] = {}

    def durable_executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        idempotency_key = _idempotency_key(
            dispatch.child_id,
            dispatch.phase,
            dispatch.attempt_number,
        )
        resolved_attempt_id = state_store.record_attempt_request(
            attempt_id=dispatch.attempt_id,
            child_id=dispatch.child_id,
            phase=dispatch.phase,
            idempotency_key=idempotency_key,
            request_json={
                "child_id": dispatch.child_id,
                "phase": dispatch.phase.value,
                "attempt_number": dispatch.attempt_number,
                "owner": dispatch.owner,
            },
        )
        outcome = executor(
            AttemptDispatch(
                child_id=dispatch.child_id,
                phase=dispatch.phase,
                attempt_id=resolved_attempt_id,
                attempt_number=dispatch.attempt_number,
                owner=dispatch.owner,
            )
        )
        active_attempt["attempt_id"] = resolved_attempt_id
        active_attempt["outcome"] = outcome
        return outcome

    def durable_state_sink(state: SchedulerState) -> None:
        outcome = active_attempt.get("outcome")
        attempt_id = active_attempt.get("attempt_id")
        if isinstance(outcome, AttemptOutcome) and isinstance(attempt_id, str):
            state_store.record_attempt_result_and_state(
                attempt_id=attempt_id,
                status=outcome.status,
                result_json=_attempt_result_json(outcome),
                error_message=outcome.error_message,
                state=state,
            )
            active_attempt.clear()
            return
        state_store.save_scheduler_state(state)

    return run_once(
        graph,
        initial_state,
        executor=durable_executor,
        now=now,
        owner=owner,
        max_attempts=max_attempts,
        max_review_fix_cycles=max_review_fix_cycles,
        backoff_seconds=backoff_seconds,
        lease_seconds=lease_seconds,
        state_sink=durable_state_sink,
    )


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


def _attempt_id(child_id: str, phase: ChildPhase, attempt_number: int) -> str:
    return f"{child_id}-{phase.value}-{attempt_number}"


def _idempotency_key(
    child_id: str,
    phase: ChildPhase,
    attempt_number: int,
) -> str:
    return f"{child_id}:{phase.value}:{attempt_number}"


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


def _requires_immediate_human_review(outcome: AttemptOutcome) -> bool:
    if outcome.status == "agent_protocol_failed":
        return True
    if outcome.status != "execution_failed":
        return False
    error_message = (outcome.error_message or "").strip().lower()
    return error_message.startswith(("non_transient:", "non-transient:"))


def _attempt_result_json(outcome: AttemptOutcome) -> dict | None:
    if (
        outcome.role_result is None
        and outcome.raw_result is None
        and not outcome.commits
        and outcome.branch is None
    ):
        return None
    result: dict = {}
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
