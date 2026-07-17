import sqlite3
import threading
from pathlib import Path

import pytest

from smda_scheduler.phase_ledger import (
    AttemptResultUpdate,
    BacklogEffect,
    ParentRunExists,
    PhaseLedger,
    StaleParentTransition,
)
from smda_scheduler.scheduling import (
    AttemptDispatch,
    AttemptOutcome,
    ChildRunState,
    Claim,
    SchedulerState,
    run_once_durable,
)
from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    GraphError,
    ParentPhase,
    RoleResult,
    WorkflowGraph,
)
from smda_scheduler.workflow_graph import WorkflowGraphArtifact


def test_record_and_load_roadmap_blockers(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_roadmap_edges(
        [
            {
                "from_parent_id": "P1",
                "to_parent_id": "P2",
                "blocks_dispatch": True,
                "reason": "P2 builds on P1",
            },
        ]
    )
    assert ledger.load_roadmap_blockers("P2") == ("P1",)
    assert ledger.load_roadmap_blockers("P1") == ()


def test_record_and_load_roadmap_members(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    parent_1 = {
        "node_id": "parent-001",
        "title": "Introduce member store",
        "body": "Persist roadmap parent specs.",
        "risk_level": "medium",
        "dependencies": [],
    }
    parent_2 = {
        "node_id": "parent-002",
        "title": "Publish member parents",
        "body": "Create parent issues from roadmap specs.",
        "risk_level": "high",
        "dependencies": ["parent-001"],
    }

    ledger.record_roadmap_members("DANNY-100", [parent_1, parent_2])

    assert PhaseLedger(tmp_path / "ledger.sqlite").load_roadmap_members(
        "DANNY-100"
    ) == [parent_1, parent_2]


def test_roadmap_member_projection_round_trips_idempotently(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    ledger.record_roadmap_member_projection(
        roadmap_id="DANNY-100",
        node_id="parent-001",
        issue_id="DANNY-101",
    )
    ledger.record_roadmap_member_projection(
        roadmap_id="DANNY-100",
        node_id="parent-001",
        issue_id="DANNY-201",
    )
    ledger.record_roadmap_member_projection(
        roadmap_id="DANNY-100",
        node_id="parent-002",
        issue_id="DANNY-102",
    )

    assert ledger.load_roadmap_member_projections("DANNY-100") == {
        "parent-001": "DANNY-201",
        "parent-002": "DANNY-102",
    }


def test_load_roadmap_for_member_returns_owner_and_node(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_roadmap_member_projection(
        roadmap_id="DANNY-100",
        node_id="parent-001",
        issue_id="DANNY-101",
    )

    assert ledger.load_roadmap_for_member("DANNY-101") == {
        "roadmap_id": "DANNY-100",
        "node_id": "parent-001",
    }
    assert ledger.load_roadmap_for_member("DANNY-66") is None


def test_parent_land_ledger_round_trips_idempotently(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    first_id = ledger.record_parent_land_operation(
        operation_id="land-1",
        idempotency_key="parent:DANNY-66:land:abc123:main",
        parent_id="DANNY-66",
        parent_ref="abc123",
        base_branch="main",
    )
    second_id = ledger.record_parent_land_operation(
        operation_id="land-duplicate",
        idempotency_key="parent:DANNY-66:land:abc123:main",
        parent_id="DANNY-66",
        parent_ref="abc123",
        base_branch="main",
    )
    ledger.mark_parent_land_completed(first_id)

    assert first_id == "land-1"
    assert second_id == "land-1"
    assert PhaseLedger(tmp_path / "ledger.sqlite").load_parent_land_operations() == [
        {
            "operation_id": "land-1",
            "idempotency_key": "parent:DANNY-66:land:abc123:main",
            "parent_id": "DANNY-66",
            "parent_ref": "abc123",
            "base_branch": "main",
            "status": "completed",
            "last_error": None,
        }
    ]


def test_parent_land_ledger_records_failed_as_pending_with_error(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    operation_id = ledger.record_parent_land_operation(
        operation_id="land-1",
        idempotency_key="parent:DANNY-66:land:abc123:main",
        parent_id="DANNY-66",
        parent_ref="abc123",
        base_branch="main",
    )

    ledger.mark_parent_land_failed(operation_id, "merge failed")

    assert ledger.load_parent_land_operations()[0]["status"] == "pending"
    assert ledger.load_parent_land_operations()[0]["last_error"] == "merge failed"


def test_record_roadmap_edges_ignores_non_blocking(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_roadmap_edges(
        [
            {
                "from_parent_id": "P1",
                "to_parent_id": "P2",
                "blocks_dispatch": False,
                "reason": "related",
            },
        ]
    )
    assert ledger.load_roadmap_blockers("P2") == ()


def test_record_roadmap_edges_rejects_cycle(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    with pytest.raises(GraphError):
        ledger.record_roadmap_edges(
            [
                {
                    "from_parent_id": "P1",
                    "to_parent_id": "P2",
                    "blocks_dispatch": True,
                    "reason": "x",
                },
                {
                    "from_parent_id": "P2",
                    "to_parent_id": "P1",
                    "blocks_dispatch": True,
                    "reason": "y",
                },
            ]
        )


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


def test_phase_ledger_selects_semantic_attempt_history_in_numeric_order(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    def record(
        *,
        target_kind: str,
        target_id: str,
        phase: ChildPhase | ParentPhase,
        number: int,
        result_json: dict,
        request_json: dict | None = None,
    ) -> None:
        attempt_id = f"{target_id}-{phase.value}-{number}"
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind=target_kind,
            target_id=target_id,
            phase=phase,
            idempotency_key=f"{target_kind}:{target_id}:{phase.value}:{number}",
            request_json=request_json or {},
        )
        ledger.record_attempt_result(
            attempt_id=attempt_id,
            status="succeeded",
            result_json=result_json,
            error_message=None,
        )

    for number, report in ((10, "second review report"), (2, "first review report")):
        record(
            target_kind="parent",
            target_id="DANNY-66",
            phase=ParentPhase.GRAPH_SPEC_REVIEWING,
            number=number,
            result_json={"report": report},
        )
    for number, candidate_ref in ((10, "commit-10"), (2, "commit-2")):
        record(
            target_kind="child",
            target_id="DANNY-66:child-001",
            phase=ChildPhase.QUALITY_REVIEWING,
            number=number,
            request_json={"context_packet": {"parent_issue_id": "DANNY-66"}},
            result_json={
                "commits": [candidate_ref],
                "report": f"child report {number}",
            },
        )
    for number, verdict in ((10, "FAIL"), (2, "PASS")):
        record(
            target_kind="parent",
            target_id="DANNY-66",
            phase=ParentPhase.PARENT_QA_REVIEWING,
            number=number,
            result_json={"verdict": verdict},
        )
    for number in (10, 2):
        record(
            target_kind="parent",
            target_id="DANNY-66",
            phase=ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING,
            number=number,
            request_json={
                "context_packet": {"conflict_history": {"operation_id": "accept-1"}}
            },
            result_json={"verdict": "DONE"},
        )

    assert ledger.next_attempt_number(
        target_kind="parent",
        target_id="DANNY-66",
        phase=ParentPhase.GRAPH_SPEC_REVIEWING,
    ) == 3
    assert ledger.latest_review_findings(
        target_kind="parent",
        target_id="DANNY-66",
        phases=(ParentPhase.GRAPH_SPEC_REVIEWING,),
    ) == "second review report"
    assert ledger.latest_quality_candidate_ref("DANNY-66:child-001") == "commit-10"
    assert ledger.latest_child_report("DANNY-66:child-001") == "child report 10"
    assert ledger.child_parent_ids("DANNY-66:child-001") == ("DANNY-66",)
    assert ledger.parent_qa_results("DANNY-66")[-1]["verdict"] == "FAIL"
    assert ledger.conflict_attempt_history("DANNY-66")[-1][
        "attempt_id"
    ].endswith("-10")


def test_latest_review_findings_preserves_cross_phase_chronology(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    for phase, number, report in (
        (ParentPhase.GRAPH_SPEC_REVIEWING, 2, "earlier spec report"),
        (ParentPhase.GRAPH_EXECUTION_REVIEWING, 1, "later execution report"),
    ):
        attempt_id = f"DANNY-66-{phase.value}-{number}"
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind="parent",
            target_id="DANNY-66",
            phase=phase,
            idempotency_key=f"parent:DANNY-66:{phase.value}:{number}",
            request_json={},
        )
        ledger.record_attempt_result(
            attempt_id=attempt_id,
            status="succeeded",
            result_json={"verdict": "FAIL", "report": report},
            error_message=None,
        )

    assert ledger.latest_review_findings(
        target_kind="parent",
        target_id="DANNY-66",
        phases=(
            ParentPhase.GRAPH_SPEC_REVIEWING,
            ParentPhase.GRAPH_EXECUTION_REVIEWING,
        ),
    ) == "later execution report"


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


def test_parent_transition_preserves_intake_facts_and_rejects_stale_phase(
    tmp_path: Path,
):
    ledger_path = tmp_path / "ledger.sqlite"
    ledger = PhaseLedger(ledger_path)

    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="SPEC_FINALIZED",
        spec_path="docs/superpowers/specs/approved.md",
        spec_checksum="sha256:abc123",
        approval_evidence="DANNY-66 approval",
    )
    ledger.transition_parent(
        parent_id="DANNY-66",
        expected_phase="SPEC_FINALIZED",
        next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
    )

    assert PhaseLedger(ledger_path).load_parent_run("DANNY-66") == {
        "parent_id": "DANNY-66",
        "phase": ParentPhase.GRAPH_SPEC_REVIEWING.value,
        "spec_path": "docs/superpowers/specs/approved.md",
        "spec_checksum": "sha256:abc123",
        "approval_evidence": "DANNY-66 approval",
    }
    with pytest.raises(StaleParentTransition):
        ledger.transition_parent(
            parent_id="DANNY-66",
            expected_phase="SPEC_FINALIZED",
            next_phase=ParentPhase.GRAPH_EXECUTION_REVIEWING.value,
        )


def test_parent_transition_rolls_back_attempt_graph_and_all_effects_together(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="SPEC_FINALIZED",
        spec_path="docs/spec.md",
        spec_checksum="sha256:spec",
        approval_evidence="approved by user",
    )
    attempt_id = "DANNY-66-GRAPH_DECOMPOSING-1"
    ledger.record_role_attempt_request(
        attempt_id=attempt_id,
        target_kind="parent",
        target_id="DANNY-66",
        phase=ParentPhase.GRAPH_DECOMPOSING,
        idempotency_key="parent:DANNY-66:GRAPH_DECOMPOSING:1",
        request_json={"role": "graph_decomposer"},
    )
    ledger.record_tracker_effect(
        effect_id="existing-effect",
        idempotency_key="lifecycle:DANNY-66:conflict",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "existing"},
    )
    graph = WorkflowGraphArtifact.from_dict(
        {
            "parent_id": "DANNY-66",
            "graph_checksum": "sha256:graph",
            "children": [
                {
                    "node_id": "child-001",
                    "title": "Implement atomic outcome",
                    "body": "Commit the parent outcome atomically.",
                    "acceptance_criteria": ["all facts commit together"],
                    "dependencies": [],
                    "in_scope": ["parent outcome"],
                    "out_of_scope": ["external delivery"],
                    "touched_surfaces": {
                        "files": ["phase_ledger.py"],
                        "modules": ["smda_scheduler.phase_ledger"],
                        "contracts": ["Parent Transition"],
                        "docs": ["docs/CONTEXT.md"],
                        "tests": ["test_phase_ledger.py"],
                    },
                    "verification": {
                        "required": ["pytest test_phase_ledger.py"],
                        "smoke": [],
                    },
                    "risk_level": "high",
                }
            ],
            "dependency_edges": [],
        }
    )
    attempt_result = AttemptResultUpdate(
        attempt_id=attempt_id,
        status="succeeded",
        result_json={
            "verdict": "DONE",
            "required_next_action": "submit_for_graph_review",
        },
        error_message=None,
    )
    comment_effect = BacklogEffect(
        effect_id="lifecycle-comment:DANNY-66:new",
        idempotency_key="lifecycle-comment:DANNY-66:new",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "Graph decomposition completed."},
    )
    conflicting_effect = BacklogEffect(
        effect_id="lifecycle-state:DANNY-66:conflict",
        idempotency_key="lifecycle:DANNY-66:conflict",
        effect_type="set_state",
        target_id="DANNY-66",
        payload={"state": "In Progress"},
    )

    with pytest.raises(sqlite3.IntegrityError):
        ledger.transition_parent(
            parent_id="DANNY-66",
            expected_phase="SPEC_FINALIZED",
            next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
            attempt_result=attempt_result,
            graph=graph,
            effects=(comment_effect, conflicting_effect),
        )

    assert ledger.load_parent_run("DANNY-66")["phase"] == "SPEC_FINALIZED"
    assert ledger.load_attempts()[0]["status"] == "dispatched"
    assert ledger.load_attempts()[0]["result_json"] is None
    with pytest.raises(KeyError, match="SMDA graph not found"):
        ledger.load_graph("DANNY-66")
    assert [effect["effect_id"] for effect in ledger.load_tracker_effects()] == [
        "existing-effect"
    ]

    state_effect = BacklogEffect(
        effect_id="lifecycle-state:DANNY-66:new",
        idempotency_key="lifecycle-state:DANNY-66:new",
        effect_type="set_state",
        target_id="DANNY-66",
        payload={"state": "In Progress"},
    )
    ledger.transition_parent(
        parent_id="DANNY-66",
        expected_phase="SPEC_FINALIZED",
        next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
        attempt_result=attempt_result,
        graph=graph,
        effects=(comment_effect, state_effect),
    )

    assert ledger.load_parent_run("DANNY-66")["phase"] == (
        ParentPhase.GRAPH_SPEC_REVIEWING.value
    )
    assert ledger.load_attempts()[0]["status"] == "succeeded"
    assert ledger.load_attempts()[0]["result_json"] == attempt_result.result_json
    assert ledger.load_graph("DANNY-66") == graph
    assert {effect["effect_id"] for effect in ledger.load_tracker_effects()} == {
        "existing-effect",
        comment_effect.effect_id,
        state_effect.effect_id,
    }


@pytest.mark.parametrize("attempt_state", ["missing", "wrong_target", "terminal"])
def test_parent_transition_rejects_invalid_attempt_without_partial_writes(
    tmp_path: Path,
    attempt_state: str,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="SPEC_FINALIZED",
        spec_path="docs/spec.md",
        spec_checksum="sha256:spec",
        approval_evidence="approved by user",
    )
    attempt_id = "missing-attempt"
    if attempt_state != "missing":
        attempt_id = f"{attempt_state}-attempt"
        ledger.record_role_attempt_request(
            attempt_id=attempt_id,
            target_kind="parent",
            target_id=("DANNY-99" if attempt_state == "wrong_target" else "DANNY-66"),
            phase=ParentPhase.GRAPH_DECOMPOSING,
            idempotency_key=f"parent:{attempt_state}:GRAPH_DECOMPOSING:1",
            request_json={"role": "graph_decomposer"},
        )
        if attempt_state == "terminal":
            ledger.record_attempt_result(
                attempt_id=attempt_id,
                status="succeeded",
                result_json={"verdict": "DONE"},
                error_message=None,
            )
    ledger.record_tracker_effect(
        effect_id="existing-effect",
        idempotency_key="existing-effect",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "existing"},
    )
    graph = WorkflowGraphArtifact.from_dict(
        {
            "parent_id": "DANNY-66",
            "graph_checksum": "sha256:graph",
            "children": [
                {
                    "node_id": "child-001",
                    "title": "Implement atomic outcome",
                    "body": "Commit the parent outcome atomically.",
                    "acceptance_criteria": ["all facts commit together"],
                    "dependencies": [],
                    "in_scope": ["parent outcome"],
                    "out_of_scope": ["external delivery"],
                    "touched_surfaces": {
                        "files": ["phase_ledger.py"],
                        "modules": ["smda_scheduler.phase_ledger"],
                        "contracts": ["Parent Transition"],
                        "docs": ["docs/CONTEXT.md"],
                        "tests": ["test_phase_ledger.py"],
                    },
                    "verification": {
                        "required": ["pytest test_phase_ledger.py"],
                        "smoke": [],
                    },
                    "risk_level": "high",
                }
            ],
            "dependency_edges": [],
        }
    )
    parent_before = ledger.load_parent_run("DANNY-66")
    attempts_before = ledger.load_attempts()
    effects_before = ledger.load_tracker_effects()

    with pytest.raises(RuntimeError, match="attempt result update rejected"):
        ledger.transition_parent(
            parent_id="DANNY-66",
            expected_phase="SPEC_FINALIZED",
            next_phase=ParentPhase.GRAPH_SPEC_REVIEWING.value,
            attempt_result=AttemptResultUpdate(
                attempt_id=attempt_id,
                status="succeeded",
                result_json={"verdict": "DONE"},
                error_message=None,
            ),
            graph=graph,
            effects=(
                BacklogEffect(
                    effect_id="new-effect",
                    idempotency_key="new-effect",
                    effect_type="set_state",
                    target_id="DANNY-66",
                    payload={"state": "In Progress"},
                ),
            ),
        )

    assert ledger.load_parent_run("DANNY-66") == parent_before
    assert ledger.load_attempts() == attempts_before
    with pytest.raises(KeyError, match="SMDA graph not found"):
        ledger.load_graph("DANNY-66")
    assert ledger.load_tracker_effects() == effects_before


def test_create_parent_run_rejects_duplicate_intake(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    intake = {
        "parent_id": "DANNY-66",
        "initial_phase": "SPEC_FINALIZED",
        "spec_path": "docs/superpowers/specs/approved.md",
        "spec_checksum": "sha256:abc123",
        "approval_evidence": "DANNY-66 approval",
    }

    ledger.create_parent_run(**intake)

    with pytest.raises(ParentRunExists):
        ledger.create_parent_run(**{**intake, "spec_path": "docs/other.md"})
    assert ledger.load_parent_run("DANNY-66") == {
        "parent_id": "DANNY-66",
        "phase": "SPEC_FINALIZED",
        "spec_path": "docs/superpowers/specs/approved.md",
        "spec_checksum": "sha256:abc123",
        "approval_evidence": "DANNY-66 approval",
    }
    assert ledger.load_parent_run("missing") is None


def test_create_parent_run_rolls_back_parent_and_all_initial_effects(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_tracker_effect(
        effect_id="existing-effect",
        idempotency_key="intake-conflict",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "existing"},
    )
    effects = (
        BacklogEffect(
            effect_id="intake-comment",
            idempotency_key="intake-comment",
            effect_type="comment",
            target_id="DANNY-66",
            payload={"body": "admitted"},
        ),
        BacklogEffect(
            effect_id="intake-state",
            idempotency_key="intake-conflict",
            effect_type="set_state",
            target_id="DANNY-66",
            payload={"state": "In Progress"},
        ),
    )

    with pytest.raises(sqlite3.IntegrityError):
        ledger.create_parent_run(
            parent_id="DANNY-66",
            initial_phase="SPEC_FINALIZED",
            spec_path="docs/spec.md",
            spec_checksum="sha256:spec",
            approval_evidence="approved",
            effects=effects,
        )

    assert ledger.load_parent_run("DANNY-66") is None
    assert [effect["effect_id"] for effect in ledger.load_tracker_effects()] == [
        "existing-effect"
    ]


def test_create_parent_run_does_not_translate_non_duplicate_integrity_error(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    with pytest.raises(sqlite3.IntegrityError) as caught:
        ledger.create_parent_run(
            parent_id="DANNY-66",
            initial_phase="SPEC_FINALIZED",
            spec_path="docs/superpowers/specs/approved.md",
            spec_checksum="sha256:abc123",
            approval_evidence=None,  # type: ignore[arg-type]
        )

    assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_NOTNULL


def test_phase_ledger_persists_smda_graph_without_reordering_children(tmp_path: Path):
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

    graph = WorkflowGraphArtifact.from_dict({
        "parent_id": "DANNY-66",
        "graph_checksum": "sha256:graph",
        "dependency_edges": [dependency_edge],
        "children": [child_2, child_1],
    })
    ledger.record_graph(graph)

    assert PhaseLedger(ledger_path).load_graph("DANNY-66") == graph


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


def test_concurrent_tracker_effect_writes_do_not_lock(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            ledger.record_tracker_effect(
                effect_id=f"effect-{n}",
                idempotency_key=f"key-{n}",
                effect_type="comment",
                target_id=f"DANNY-{n}",
                payload={"body": f"body {n}"},
            )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(ledger.load_pending_tracker_effects()) == 20


def test_wal_mode_enabled(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    import sqlite3

    with sqlite3.connect(ledger.path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


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
