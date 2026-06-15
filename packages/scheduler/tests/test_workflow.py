import pytest

from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    GraphError,
    QaBounds,
    QaDecision,
    QaState,
    RoleResult,
    WorkflowGraph,
    eligible_child_ids,
    record_qa_failure,
    transition_child_phase,
)


def test_graph_eligibility_uses_dependencies():
    graph = WorkflowGraph(
        children={
            "A": ChildNode(id="A"),
            "B": ChildNode(id="B", dependencies=frozenset({"A"})),
            "C": ChildNode(id="C", dependencies=frozenset({"A"})),
        }
    )

    assert eligible_child_ids(graph, completed_child_ids=frozenset()) == ["A"]
    assert eligible_child_ids(graph, completed_child_ids=frozenset({"A"})) == [
        "B",
        "C",
    ]


def test_eligibility_dispatches_active_non_terminal_phases():
    graph = WorkflowGraph(
        children={
            "A": ChildNode(id="A", phase=ChildPhase.SPEC_REVIEWING),
            "B": ChildNode(id="B", phase=ChildPhase.QUALITY_REVIEW_PASSED),
            "C": ChildNode(id="C", phase=ChildPhase.HUMAN_REVIEW_REQUIRED),
            "D": ChildNode(id="D", phase=ChildPhase.FIXING_SPEC),
        }
    )

    # SPEC_REVIEWING + FIXING_SPEC are active -> dispatchable; QUALITY_REVIEW_PASSED
    # (terminal/completed) and HUMAN_REVIEW_REQUIRED (blocked) are not.
    assert eligible_child_ids(
        graph, completed_child_ids=frozenset({"B"})
    ) == ["A", "D"]


def test_graph_rejects_unknown_dependency():
    graph = WorkflowGraph(
        children={"B": ChildNode(id="B", dependencies=frozenset({"A"}))}
    )

    with pytest.raises(GraphError, match="unknown dependency"):
        eligible_child_ids(graph, completed_child_ids=frozenset())


def test_graph_rejects_dependency_cycle():
    graph = WorkflowGraph(
        children={
            "A": ChildNode(id="A", dependencies=frozenset({"B"})),
            "B": ChildNode(id="B", dependencies=frozenset({"A"})),
        }
    )

    with pytest.raises(GraphError, match="cycle"):
        eligible_child_ids(graph, completed_child_ids=frozenset())


def test_child_transition_table_routes_role_results():
    assert (
        transition_child_phase(
            ChildPhase.IMPLEMENTING,
            RoleResult(verdict="DONE", required_next_action="submit_for_spec_review"),
        )
        == ChildPhase.SPEC_REVIEWING
    )
    assert (
        transition_child_phase(
            ChildPhase.SPEC_REVIEWING,
            RoleResult(verdict="FAIL", required_next_action="fix_spec"),
        )
        == ChildPhase.FIXING_SPEC
    )
    assert (
        transition_child_phase(
            ChildPhase.SPEC_REVIEWING,
            RoleResult(
                verdict="PASS",
                required_next_action="submit_for_quality_review",
            ),
        )
        == ChildPhase.QUALITY_REVIEWING
    )
    assert (
        transition_child_phase(
            ChildPhase.FIXING_SPEC,
            RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )
        == ChildPhase.SPEC_REVIEWING
    )
    assert (
        transition_child_phase(
            ChildPhase.QUALITY_REVIEWING,
            RoleResult(verdict="PASS", required_next_action="accept_candidate"),
        )
        == ChildPhase.QUALITY_REVIEW_PASSED
    )


def test_child_transition_table_rejects_unknown_route():
    with pytest.raises(GraphError, match="No transition"):
        transition_child_phase(
            ChildPhase.IMPLEMENTING,
            RoleResult(verdict="FAIL", required_next_action="accept_candidate"),
        )


def test_qa_bounds_stop_repeated_feedback_fingerprint():
    state = QaState()
    bounds = QaBounds(
        max_same_feedback_fingerprint=2,
        max_total_remediation_children=5,
        max_parent_qa_cycles=5,
    )

    first = record_qa_failure(state, bounds, feedback_fingerprint="same")
    second = record_qa_failure(first.state, bounds, feedback_fingerprint="same")
    third = record_qa_failure(second.state, bounds, feedback_fingerprint="same")

    assert first.decision == QaDecision.CREATE_REMEDIATION_CHILD
    assert second.decision == QaDecision.CREATE_REMEDIATION_CHILD
    assert third.decision == QaDecision.HUMAN_REVIEW_REQUIRED


def test_qa_bounds_stop_total_remediation_children():
    state = QaState()
    bounds = QaBounds(
        max_same_feedback_fingerprint=5,
        max_total_remediation_children=1,
        max_parent_qa_cycles=5,
    )

    first = record_qa_failure(state, bounds, feedback_fingerprint="one")
    second = record_qa_failure(first.state, bounds, feedback_fingerprint="two")

    assert first.decision == QaDecision.CREATE_REMEDIATION_CHILD
    assert second.decision == QaDecision.HUMAN_REVIEW_REQUIRED
