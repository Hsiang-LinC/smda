from smda_scheduler.scheduling import (
    AttemptOutcome,
    ChildRunState,
    Claim,
    SchedulerState,
    reconcile_expired_claims,
    run_once,
)
from smda_scheduler.workflow import ChildNode, ChildPhase, RoleResult, WorkflowGraph


def test_run_once_claims_dispatches_and_applies_workflow_transition():
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})
    state = SchedulerState()

    def executor(child_id: str, phase: ChildPhase) -> AttemptOutcome:
        assert child_id == "A"
        assert phase == ChildPhase.IMPLEMENTING
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )

    next_state = run_once(graph, state, executor=executor, now=10.0, owner="worker-1")

    child = next_state.children["A"]
    assert child.phase == ChildPhase.SPEC_REVIEWING
    assert child.attempts == 1
    assert child.claim is None


def test_run_once_backs_off_after_transient_execution_failure():
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})
    state = SchedulerState()
    calls: list[str] = []

    def executor(child_id: str, phase: ChildPhase) -> AttemptOutcome:
        calls.append(child_id)
        return AttemptOutcome(status="execution_failed")

    failed_state = run_once(
        graph,
        state,
        executor=executor,
        now=10.0,
        owner="worker-1",
        backoff_seconds=5.0,
    )
    backed_off_state = run_once(
        graph,
        failed_state,
        executor=executor,
        now=12.0,
        owner="worker-1",
        backoff_seconds=5.0,
    )

    assert calls == ["A"]
    assert failed_state.children["A"].attempts == 1
    assert failed_state.children["A"].next_not_before == 15.0
    assert backed_off_state == failed_state


def test_run_once_marks_human_review_after_attempt_exhaustion():
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})

    def executor(child_id: str, phase: ChildPhase) -> AttemptOutcome:
        return AttemptOutcome(status="execution_failed")

    first = run_once(
        graph,
        SchedulerState(),
        executor=executor,
        now=10.0,
        owner="worker-1",
        max_attempts=2,
    )
    second = run_once(
        graph,
        first,
        executor=executor,
        now=11.0,
        owner="worker-1",
        max_attempts=2,
    )

    assert second.children["A"].attempts == 2
    assert second.children["A"].phase == ChildPhase.HUMAN_REVIEW_REQUIRED


def test_reconcile_expired_claims_releases_stale_claim():
    state = SchedulerState(
        children={
            "A": ChildRunState(
                phase=ChildPhase.IMPLEMENTING,
                claim=Claim(owner="worker-1", lease_expires_at=10.0),
            )
        }
    )

    reconciled = reconcile_expired_claims(state, now=11.0)

    assert reconciled.children["A"].claim is None
