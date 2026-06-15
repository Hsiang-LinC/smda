from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GraphError(ValueError):
    """Raised when workflow graph or phase routing is invalid."""


class ChildPhase(StrEnum):
    READY = "READY"
    IMPLEMENTING = "IMPLEMENTING"
    SPEC_REVIEWING = "SPEC_REVIEWING"
    FIXING_SPEC = "FIXING_SPEC"
    QUALITY_REVIEWING = "QUALITY_REVIEWING"
    QUALITY_REVIEW_PASSED = "QUALITY_REVIEW_PASSED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class ParentPhase(StrEnum):
    GRAPH_DECOMPOSING = "GRAPH_DECOMPOSING"
    GRAPH_SPEC_REVIEWING = "GRAPH_SPEC_REVIEWING"
    GRAPH_EXECUTION_REVIEWING = "GRAPH_EXECUTION_REVIEWING"
    CHILD_PUBLICATION_READY = "CHILD_PUBLICATION_READY"
    CHILDREN_PUBLISHED = "CHILDREN_PUBLISHED"
    PARENT_QA_READY = "PARENT_QA_READY"
    PARENT_QA_REVIEWING = "PARENT_QA_REVIEWING"
    REMEDIATION_PLANNING = "REMEDIATION_PLANNING"
    FINAL_ACCEPT_READY = "FINAL_ACCEPT_READY"
    FINAL_ACCEPTED = "FINAL_ACCEPTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class QaDecision(StrEnum):
    CREATE_REMEDIATION_CHILD = "CREATE_REMEDIATION_CHILD"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


@dataclass(frozen=True)
class ChildNode:
    id: str
    dependencies: frozenset[str] = frozenset()
    phase: ChildPhase = ChildPhase.READY


@dataclass(frozen=True)
class DependencyEdge:
    from_node_id: str
    to_node_id: str
    type: str
    blocks_dispatch: bool
    reason: str
    required_artifacts: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowGraph:
    children: dict[str, ChildNode]
    dependency_edges: tuple[DependencyEdge, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RoleResult:
    verdict: str
    required_next_action: str


@dataclass(frozen=True)
class QaBounds:
    max_same_feedback_fingerprint: int
    max_total_remediation_children: int
    max_parent_qa_cycles: int


@dataclass(frozen=True)
class QaState:
    feedback_counts: dict[str, int] = field(default_factory=dict)
    total_remediation_children: int = 0
    parent_qa_cycles: int = 0


@dataclass(frozen=True)
class QaFailureResult:
    state: QaState
    decision: QaDecision


TRANSITIONS: dict[tuple[ChildPhase, str, str], ChildPhase] = {
    (
        ChildPhase.IMPLEMENTING,
        "DONE",
        "submit_for_spec_review",
    ): ChildPhase.SPEC_REVIEWING,
    (ChildPhase.SPEC_REVIEWING, "FAIL", "fix_spec"): ChildPhase.FIXING_SPEC,
    (
        ChildPhase.SPEC_REVIEWING,
        "PASS",
        "submit_for_quality_review",
    ): ChildPhase.QUALITY_REVIEWING,
    (
        ChildPhase.FIXING_SPEC,
        "DONE",
        "submit_for_spec_review",
    ): ChildPhase.SPEC_REVIEWING,
    (
        ChildPhase.QUALITY_REVIEWING,
        "PASS",
        "accept_candidate",
    ): ChildPhase.QUALITY_REVIEW_PASSED,
}


def eligible_child_ids(
    graph: WorkflowGraph,
    *,
    completed_child_ids: frozenset[str],
) -> list[str]:
    validate_graph(graph)
    return sorted(
        child.id
        for child in graph.children.values()
        if child.phase == ChildPhase.READY
        and child.id not in completed_child_ids
        and child.dependencies <= completed_child_ids
    )


def validate_graph(graph: WorkflowGraph) -> None:
    child_ids = frozenset(graph.children)
    for child in graph.children.values():
        unknown = child.dependencies - child_ids
        if unknown:
            names = ", ".join(sorted(unknown))
            raise GraphError(f"Child {child.id} has unknown dependency: {names}")
    for edge in graph.dependency_edges:
        if edge.from_node_id not in child_ids:
            raise GraphError(
                f"Dependency edge references unknown source node: {edge.from_node_id}"
            )
        if edge.to_node_id not in child_ids:
            raise GraphError(
                f"Dependency edge references unknown target node: {edge.to_node_id}"
            )
        if edge.type not in {
            "code_dependency",
            "contract_dependency",
            "test_dependency",
            "sequencing_only",
        }:
            raise GraphError(f"Dependency edge has unknown type: {edge.type}")
        if not isinstance(edge.blocks_dispatch, bool):
            raise GraphError("Dependency edge blocks_dispatch must be a boolean")
        if not edge.reason:
            raise GraphError("Dependency edge reason must not be empty")
        if not edge.required_artifacts:
            raise GraphError("Dependency edge required_artifacts must not be empty")
    _reject_cycles(graph)


def transition_child_phase(phase: ChildPhase, result: RoleResult) -> ChildPhase:
    key = (phase, result.verdict, result.required_next_action)
    try:
        return TRANSITIONS[key]
    except KeyError as error:
        raise GraphError(
            "No transition for "
            f"phase={phase} verdict={result.verdict} "
            f"required_next_action={result.required_next_action}"
        ) from error


def record_qa_failure(
    state: QaState,
    bounds: QaBounds,
    *,
    feedback_fingerprint: str,
) -> QaFailureResult:
    feedback_counts = dict(state.feedback_counts)
    next_count = feedback_counts.get(feedback_fingerprint, 0) + 1
    feedback_counts[feedback_fingerprint] = next_count
    next_state = QaState(
        feedback_counts=feedback_counts,
        total_remediation_children=state.total_remediation_children + 1,
        parent_qa_cycles=state.parent_qa_cycles + 1,
    )

    if (
        next_count > bounds.max_same_feedback_fingerprint
        or next_state.total_remediation_children
        > bounds.max_total_remediation_children
        or next_state.parent_qa_cycles > bounds.max_parent_qa_cycles
    ):
        return QaFailureResult(
            state=next_state,
            decision=QaDecision.HUMAN_REVIEW_REQUIRED,
        )

    return QaFailureResult(
        state=next_state,
        decision=QaDecision.CREATE_REMEDIATION_CHILD,
    )


def _reject_cycles(graph: WorkflowGraph) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(child_id: str) -> None:
        if child_id in visited:
            return
        if child_id in visiting:
            raise GraphError(f"Dependency cycle detected at child: {child_id}")

        visiting.add(child_id)
        for dependency_id in graph.children[child_id].dependencies:
            visit(dependency_id)
        visiting.remove(child_id)
        visited.add(child_id)

    for child_id in graph.children:
        visit(child_id)
