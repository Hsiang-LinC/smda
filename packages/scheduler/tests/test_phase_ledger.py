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
        assert attempts_during_dispatch[0]["target_kind"] == "child"
        assert attempts_during_dispatch[0]["target_id"] == dispatch.child_id
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
            schema_id="smda.child-implementer-result.v1",
            schema_package_version="0.1.0",
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
            "target_kind": "child",
            "target_id": "A",
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
                "schema_id": "smda.child-implementer-result.v1",
                "schema_package_version": "0.1.0",
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
            "target_kind": "child",
            "target_id": "A",
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


def test_phase_ledger_records_parent_role_attempts_with_target_identity(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    ledger.record_role_attempt_request(
        attempt_id="DANNY-66-GRAPH_DECOMPOSING-1",
        target_kind="parent",
        target_id="DANNY-66",
        phase="GRAPH_DECOMPOSING",
        idempotency_key="parent:DANNY-66:GRAPH_DECOMPOSING:1",
        request_json={"role": "graph_decomposer"},
    )
    ledger.record_attempt_result(
        attempt_id="DANNY-66-GRAPH_DECOMPOSING-1",
        status="succeeded",
        result_json={
            "verdict": "DONE",
            "required_next_action": "submit_for_graph_review",
        },
        error_message=None,
    )

    assert ledger.load_attempts() == [
        {
            "attempt_id": "DANNY-66-GRAPH_DECOMPOSING-1",
            "target_kind": "parent",
            "target_id": "DANNY-66",
            "phase": "GRAPH_DECOMPOSING",
            "idempotency_key": "parent:DANNY-66:GRAPH_DECOMPOSING:1",
            "status": "succeeded",
            "request_json": {"role": "graph_decomposer"},
            "result_json": {
                "verdict": "DONE",
                "required_next_action": "submit_for_graph_review",
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


def test_phase_ledger_persists_parent_run_state(tmp_path: Path):
    ledger_path = tmp_path / "ledger.sqlite"
    ledger = PhaseLedger(ledger_path)

    ledger.record_parent_run(
        parent_id="DANNY-66",
        phase="SPEC_FINALIZED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:abc123",
        approval_evidence="DANNY-66 approval",
    )

    assert PhaseLedger(ledger_path).load_parent_runs() == [
        {
            "parent_id": "DANNY-66",
            "phase": "SPEC_FINALIZED",
            "spec_path": "docs/superpowers/specs/approved.md",
            "spec_checksum": "sha256:abc123",
            "approval_evidence": "DANNY-66 approval",
        }
    ]


def test_phase_ledger_persists_smda_graph(tmp_path: Path):
    ledger_path = tmp_path / "ledger.sqlite"
    ledger = PhaseLedger(ledger_path)
    child_1 = {
        "node_id": "child-001",
        "title": "Extract scheduler runtime",
        "body": "Move scheduler code into the SMDA product.",
        "in_scope": ["scheduler runtime"],
        "out_of_scope": ["consumer repo cleanup"],
        "touched_surfaces": {
            "files": ["packages/scheduler/src/smda_scheduler/runtime.py"],
            "modules": ["smda_scheduler.runtime"],
            "contracts": ["smda.graph-decomposer-result.v1"],
            "docs": ["docs/product-spec.md"],
            "tests": ["packages/scheduler/tests/test_runtime.py"],
        },
        "acceptance_criteria": ["scheduler tests pass"],
        "verification": {
            "required": ["uv run pytest packages/scheduler/tests/test_runtime.py -q"],
            "smoke": ["uv run pytest packages/scheduler/tests -q"],
        },
        "risk_level": "medium",
        "dependencies": [],
    }
    child_2 = {
        **child_1,
        "node_id": "child-002",
        "title": "Wire setup skill",
        "body": "Make setup emit config only.",
        "acceptance_criteria": ["setup emits config only"],
        "dependencies": ["child-001"],
    }
    dependency_edge = {
        "from": "child-001",
        "to": "child-002",
        "type": "code_dependency",
        "blocks_dispatch": True,
        "reason": "child-002 imports the new runtime API",
        "required_artifacts": ["accepted_commit"],
    }

    ledger.record_graph(
        parent_id="DANNY-66",
        graph_checksum="sha256:graph",
        children=[child_1, child_2],
        dependency_edges=[dependency_edge],
    )

    assert PhaseLedger(ledger_path).load_graph("DANNY-66") == {
        "parent_id": "DANNY-66",
        "graph_checksum": "sha256:graph",
        "dependency_edges": [dependency_edge],
        "children": [child_1, child_2],
    }


def test_phase_ledger_persists_child_issue_projections(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    ledger.record_child_issue_projection(
        parent_id="DANNY-66",
        node_id="child-001",
        issue_id="DANNY-101",
    )
    ledger.record_child_issue_projection(
        parent_id="DANNY-66",
        node_id="child-002",
        issue_id="DANNY-102",
    )

    assert ledger.load_child_issue_projections("DANNY-66") == {
        "child-001": "DANNY-101",
        "child-002": "DANNY-102",
    }


def test_phase_ledger_records_parent_pause(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    ledger.set_parent_pause("DANNY-66", paused=True)

    assert ledger.is_parent_paused("DANNY-66") is True
    assert ledger.load_paused_parent_ids() == ["DANNY-66"]

    ledger.set_parent_pause("DANNY-66", paused=False)

    assert ledger.is_parent_paused("DANNY-66") is False
    assert ledger.load_paused_parent_ids() == []


def test_phase_ledger_records_pending_tracker_effects_idempotently(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    first = ledger.record_tracker_effect(
        effect_id="effect-1",
        idempotency_key="comment:DANNY-66:started",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "SMDA started"},
    )
    second = ledger.record_tracker_effect(
        effect_id="effect-duplicate",
        idempotency_key="comment:DANNY-66:started",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "SMDA started"},
    )

    assert first == "effect-1"
    assert second == "effect-1"
    assert PhaseLedger(tmp_path / "ledger.sqlite").load_pending_tracker_effects() == [
        {
            "effect_id": "effect-1",
            "idempotency_key": "comment:DANNY-66:started",
            "effect_type": "comment",
            "target_id": "DANNY-66",
            "payload": {"body": "SMDA started"},
            "status": "pending",
            "last_error": None,
        }
    ]


def test_phase_ledger_marks_tracker_effect_sent_or_failed(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_tracker_effect(
        effect_id="effect-1",
        idempotency_key="state:DANNY-66:In Progress",
        effect_type="set_state",
        target_id="DANNY-66",
        payload={"state": "In Progress"},
    )
    ledger.mark_tracker_effect_failed("effect-1", "Linear timeout")

    assert ledger.load_pending_tracker_effects()[0]["last_error"] == "Linear timeout"

    ledger.mark_tracker_effect_sent("effect-1")

    assert ledger.load_pending_tracker_effects() == []
    assert ledger.load_tracker_effects()[0]["status"] == "sent"
