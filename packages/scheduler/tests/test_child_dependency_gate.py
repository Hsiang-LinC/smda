from smda_scheduler.child_dependency_gate import child_dependency_gate
from smda_scheduler.scheduling import ChildRunState, SchedulerState
from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    DependencyEdge,
    WorkflowGraph,
)


def graph_with_edge(*, blocks_dispatch: bool = True) -> WorkflowGraph:
    return WorkflowGraph(
        children={
            "child-001": ChildNode(id="child-001"),
            "child-002": ChildNode(
                id="child-002", dependencies=frozenset({"child-001"})
            ),
        },
        dependency_edges=(
            DependencyEdge(
                from_node_id="child-001",
                to_node_id="child-002",
                type="code_dependency",
                blocks_dispatch=blocks_dispatch,
                reason="child-002 imports the accepted API.",
                required_artifacts=("accepted_commit",),
            ),
        ),
    )


def accept_operation(
    *,
    parent_id: str = "DANNY-66",
    child_id: str = "child-001",
    candidate_ref: str = "branch-1",
    status: str = "completed",
) -> dict:
    return {
        "operation_id": f"accept:{parent_id}:{child_id}:{candidate_ref}",
        "idempotency_key": f"parent:{parent_id}:{child_id}:{candidate_ref}",
        "parent_id": parent_id,
        "child_id": child_id,
        "candidate_ref": candidate_ref,
        "integration_branch": "smda/DANNY-66/integration",
        "status": status,
        "last_error": None,
    }


def test_child_dependency_gate_allows_child_without_blocking_dependencies():
    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-001",
        graph=graph_with_edge(),
        scheduler_state=SchedulerState(),
        candidate_ref_lookup=lambda _: None,
        parent_accept_operations=[],
    )

    assert result.eligible is True
    assert result.blocked_by == ()
    assert result.missing_artifacts == ()


def test_child_dependency_gate_blocks_when_upstream_has_no_scheduler_state():
    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=SchedulerState(),
        candidate_ref_lookup=lambda _: None,
        parent_accept_operations=[],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:quality_review_passed",)
    assert "child-001" in result.reason


def test_child_dependency_gate_blocks_when_upstream_not_quality_passed():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEWING)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: None,
        parent_accept_operations=[],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:quality_review_passed",)


def test_child_dependency_gate_blocks_when_upstream_has_no_candidate_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: None,
        parent_accept_operations=[],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:candidate_ref",)


def test_child_dependency_gate_blocks_when_accept_operation_not_completed():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: "branch-1",
        parent_accept_operations=[accept_operation(status="pending")],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:accepted_commit",)


def test_child_dependency_gate_allows_when_accept_completed_for_same_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: "branch-1",
        parent_accept_operations=[accept_operation(candidate_ref="branch-1")],
    )

    assert result.eligible is True
    assert result.blocked_by == ()
    assert result.missing_artifacts == ()


def test_child_dependency_gate_blocks_when_accept_completed_for_different_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: "branch-new",
        parent_accept_operations=[accept_operation(candidate_ref="branch-old")],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:accepted_commit",)


def test_child_dependency_gate_blocks_when_candidate_lookup_has_no_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: None,
        parent_accept_operations=[accept_operation(candidate_ref="branch-old")],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:candidate_ref",)


def test_child_dependency_gate_uses_semantic_candidate_ref_lookup():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: "branch-10",
        parent_accept_operations=[accept_operation(candidate_ref="branch-10")],
    )

    assert result.eligible is True
    assert result.blocked_by == ()
    assert result.missing_artifacts == ()


def test_child_dependency_gate_requires_accept_for_candidate_ref():
    state = SchedulerState(
        children={"child-001": ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}
    )

    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(),
        scheduler_state=state,
        candidate_ref_lookup=lambda _: "branch-10",
        parent_accept_operations=[accept_operation(candidate_ref="branch-9")],
    )

    assert result.eligible is False
    assert result.blocked_by == ("child-001",)
    assert result.missing_artifacts == ("child-001:accepted_commit",)


def test_child_dependency_gate_ignores_non_blocking_edges():
    result = child_dependency_gate(
        parent_id="DANNY-66",
        child_id="child-002",
        graph=graph_with_edge(blocks_dispatch=False),
        scheduler_state=SchedulerState(),
        candidate_ref_lookup=lambda _: None,
        parent_accept_operations=[],
    )

    assert result.eligible is True
    assert result.blocked_by == ()
    assert result.missing_artifacts == ()
