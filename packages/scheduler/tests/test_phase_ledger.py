from pathlib import Path

from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.scheduling import (
    AttemptDispatch,
    AttemptOutcome,
    ChildRunState,
    Claim,
    SchedulerState,
    run_once_durable,
)
from smda_scheduler.workflow import ChildNode, ChildPhase, RoleResult, WorkflowGraph


def test_phase_ledger_persists_child_run_state_across_instances(tmp_path: Path):
    ledger_path = tmp_path / "ledger.sqlite"
    ledger = PhaseLedger(ledger_path)
    state = SchedulerState(
        children={
            "A": ChildRunState(
                phase=ChildPhase.IMPLEMENTING,
                attempts=2,
                claim=Claim(owner="worker-1", lease_expires_at=20.0),
                next_not_before=15.0,
            )
        }
    )

    ledger.save_scheduler_state(state)

    loaded = PhaseLedger(ledger_path).load_scheduler_state()
    assert loaded == state


def test_run_once_durable_persists_claim_before_dispatch(tmp_path: Path):
    ledger_path = tmp_path / "ledger.sqlite"
    ledger = PhaseLedger(ledger_path)
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        persisted_during_dispatch = PhaseLedger(ledger_path).load_scheduler_state()
        assert persisted_during_dispatch.children["A"].claim == Claim(
            owner="worker-1",
            lease_expires_at=40.0,
        )
        assert dispatch.attempt_id == "A-IMPLEMENTING-1"
        assert dispatch.attempt_number == 1
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )

    next_state = run_once_durable(
        graph,
        ledger,
        executor=executor,
        now=10.0,
        owner="worker-1",
        lease_seconds=30.0,
    )

    persisted_after_dispatch = PhaseLedger(ledger_path).load_scheduler_state()
    assert next_state.children["A"].phase == ChildPhase.SPEC_REVIEWING
    assert persisted_after_dispatch == next_state


def test_run_once_durable_records_attempt_request_and_result(tmp_path: Path):
    ledger_path = tmp_path / "ledger.sqlite"
    ledger = PhaseLedger(ledger_path)
    graph = WorkflowGraph(children={"A": ChildNode(id="A")})

    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        attempts_during_dispatch = PhaseLedger(ledger_path).load_attempts()
        assert attempts_during_dispatch[0]["child_id"] == dispatch.child_id
        assert attempts_during_dispatch[0]["phase"] == dispatch.phase.value
        assert attempts_during_dispatch[0]["status"] == "dispatched"
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
            commits=("abc123",),
            branch="smda/A",
        )

    run_once_durable(
        graph,
        ledger,
        executor=executor,
        now=10.0,
        owner="worker-1",
        lease_seconds=30.0,
    )

    attempts = PhaseLedger(ledger_path).load_attempts()
    assert attempts == [
        {
            "attempt_id": "A-IMPLEMENTING-1",
            "child_id": "A",
            "phase": "IMPLEMENTING",
            "idempotency_key": "A:IMPLEMENTING:1",
            "status": "succeeded",
            "request_json": {
                "child_id": "A",
                "phase": "IMPLEMENTING",
                "attempt_number": 1,
                "owner": "worker-1",
            },
            "result_json": {
                "branch": "smda/A",
                "commits": ["abc123"],
                "required_next_action": "submit_for_spec_review",
                "verdict": "DONE",
            },
            "error_message": None,
        }
    ]


def test_phase_ledger_persists_attempt_request_and_result(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    ledger.record_attempt_request(
        attempt_id="attempt-1",
        child_id="A",
        phase=ChildPhase.IMPLEMENTING,
        idempotency_key="A:IMPLEMENTING:1",
        request_json={"role": "implementer", "branch": "smda/A"},
    )
    ledger.record_attempt_result(
        attempt_id="attempt-1",
        status="succeeded",
        result_json={
            "verdict": "DONE",
            "required_next_action": "submit_for_spec_review",
        },
        error_message=None,
    )

    assert ledger.load_attempts() == [
        {
            "attempt_id": "attempt-1",
            "child_id": "A",
            "phase": "IMPLEMENTING",
            "idempotency_key": "A:IMPLEMENTING:1",
            "status": "succeeded",
            "request_json": {"role": "implementer", "branch": "smda/A"},
            "result_json": {
                "verdict": "DONE",
                "required_next_action": "submit_for_spec_review",
            },
            "error_message": None,
        }
    ]


def test_phase_ledger_reuses_attempt_for_same_idempotency_key(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    first = ledger.record_attempt_request(
        attempt_id="attempt-1",
        child_id="A",
        phase=ChildPhase.IMPLEMENTING,
        idempotency_key="A:IMPLEMENTING:1",
        request_json={"role": "implementer"},
    )
    second = ledger.record_attempt_request(
        attempt_id="attempt-duplicate",
        child_id="A",
        phase=ChildPhase.IMPLEMENTING,
        idempotency_key="A:IMPLEMENTING:1",
        request_json={"role": "implementer"},
    )

    assert first == "attempt-1"
    assert second == "attempt-1"
    assert [attempt["attempt_id"] for attempt in ledger.load_attempts()] == [
        "attempt-1"
    ]


def test_phase_ledger_persists_attempt_result_and_child_state_atomically(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_attempt_request(
        attempt_id="attempt-1",
        child_id="A",
        phase=ChildPhase.IMPLEMENTING,
        idempotency_key="A:IMPLEMENTING:1",
        request_json={"role": "implementer"},
    )
    next_state = SchedulerState(
        children={
            "A": ChildRunState(
                phase=ChildPhase.SPEC_REVIEWING,
                attempts=1,
            )
        }
    )

    ledger.record_attempt_result_and_state(
        attempt_id="attempt-1",
        status="succeeded",
        result_json={
            "verdict": "DONE",
            "required_next_action": "submit_for_spec_review",
        },
        error_message=None,
        state=next_state,
    )

    assert ledger.load_scheduler_state() == next_state
    assert ledger.load_attempts()[0]["status"] == "succeeded"
