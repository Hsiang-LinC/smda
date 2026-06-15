from pathlib import Path

from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.scheduling import (
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

    def executor(child_id: str, phase: ChildPhase) -> AttemptOutcome:
        persisted_during_dispatch = PhaseLedger(ledger_path).load_scheduler_state()
        assert persisted_during_dispatch.children["A"].claim == Claim(
            owner="worker-1",
            lease_expires_at=40.0,
        )
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
