from smda_scheduler.scheduling import (
    AttemptDispatch,
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

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        assert dispatch.child_id == "A"
        assert dispatch.phase == ChildPhase.IMPLEMENTING
        assert dispatch.attempt_id == "A-IMPLEMENTING-1"
        assert dispatch.attempt_number == 1
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

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        calls.append(dispatch.child_id)
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

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
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


def test_structured_output_failure_retries_then_human_review():
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        return AttemptOutcome(status="structured_output_failed")

    first = run_once(
        graph,
        SchedulerState(),
        executor=executor,
        now=10.0,
        owner="worker-1",
        max_attempts=2,
        backoff_seconds=5.0,
    )
    second = run_once(
        graph,
        first,
        executor=executor,
        now=16.0,
        owner="worker-1",
        max_attempts=2,
        backoff_seconds=5.0,
    )

    assert first.children["A"].attempts == 1
    assert first.children["A"].phase == ChildPhase.READY
    assert first.children["A"].next_not_before == 15.0
    assert second.children["A"].attempts == 2
    assert second.children["A"].phase == ChildPhase.HUMAN_REVIEW_REQUIRED


def test_execution_failure_records_blocked_when_non_transient():
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        return AttemptOutcome(
            status="execution_failed",
            error_message="non_transient: sandbox image is missing",
        )

    next_state = run_once(
        graph,
        SchedulerState(),
        executor=executor,
        now=10.0,
        owner="worker-1",
        max_attempts=3,
        backoff_seconds=5.0,
    )

    assert next_state.children["A"].attempts == 1
    assert next_state.children["A"].phase == ChildPhase.HUMAN_REVIEW_REQUIRED
    assert next_state.children["A"].next_not_before == 0.0


def test_schema_version_mismatch_blocks_scope_as_protocol_failure():
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        return AttemptOutcome(
            status="agent_protocol_failed",
            error_message="schema version mismatch: expected 0.1.0",
        )

    next_state = run_once(
        graph,
        SchedulerState(),
        executor=executor,
        now=10.0,
        owner="worker-1",
        max_attempts=3,
        backoff_seconds=5.0,
    )

    assert next_state.children["A"].attempts == 1
    assert next_state.children["A"].phase == ChildPhase.HUMAN_REVIEW_REQUIRED
    assert next_state.children["A"].next_not_before == 0.0


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


def test_run_once_bounds_review_fix_cycles_to_human_review():
    graph = WorkflowGraph(
        children={"c1": ChildNode(id="c1", phase=ChildPhase.SPEC_REVIEWING)}
    )
    state = SchedulerState(
        children={
            "c1": ChildRunState(
                phase=ChildPhase.SPEC_REVIEWING, review_fix_cycles=3
            )
        }
    )

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(verdict="FAIL", required_next_action="fix_spec"),
        )

    result = run_once(
        graph,
        state,
        executor=executor,
        now=10.0,
        owner="daemon-1",
        max_review_fix_cycles=3,
    )

    assert result.children["c1"].phase == ChildPhase.HUMAN_REVIEW_REQUIRED


def test_run_once_under_budget_routes_review_fail_to_fixer():
    graph = WorkflowGraph(
        children={"c1": ChildNode(id="c1", phase=ChildPhase.SPEC_REVIEWING)}
    )
    state = SchedulerState(
        children={"c1": ChildRunState(phase=ChildPhase.SPEC_REVIEWING)}
    )

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(verdict="FAIL", required_next_action="fix_spec"),
        )

    result = run_once(
        graph, state, executor=executor, now=10.0, owner="daemon-1",
        max_review_fix_cycles=3,
    )

    assert result.children["c1"].phase == ChildPhase.FIXING_SPEC
    assert result.children["c1"].review_fix_cycles == 1
