import pytest

from smda_scheduler.workflow import (
    ChildNode,
    ChildPhase,
    GraphError,
    RoleResult,
    TERMINAL_CHILD_PHASES,
    TRANSITIONS,
    WorkflowGraph,
    eligible_child_ids,
    transition_child_phase,
)
from smda_scheduler.workflow_engine import (
    CHILD_DEFINITION,
    WorkHandlerKind,
    WorkflowEngine,
)


ENGINE = WorkflowEngine(CHILD_DEFINITION)


# --- Task 1: structural guards (definition mirrors the legacy data) ---


def test_child_definition_phases_cover_child_phase_enum():
    assert CHILD_DEFINITION.phases == frozenset(ChildPhase)


def test_child_definition_terminal_matches_legacy():
    assert CHILD_DEFINITION.terminal_phases == TERMINAL_CHILD_PHASES


def test_child_definition_transition_table_matches_legacy():
    assert CHILD_DEFINITION.transitions == TRANSITIONS


def test_child_definition_every_phase_is_role_attempt():
    for phase in ChildPhase:
        assert CHILD_DEFINITION.stage(phase).kind is WorkHandlerKind.ROLE_ATTEMPT


def test_child_definition_role_for_implementing_is_child_implementer():
    contract = CHILD_DEFINITION.stage(ChildPhase.IMPLEMENTING).role_contract
    assert contract is not None
    assert contract.role.value == "child_implementer"


# --- Task 2: behaviour parity with the legacy decision functions ---


@pytest.mark.parametrize("key", list(TRANSITIONS.keys()))
def test_engine_next_phase_matches_legacy_for_every_transition(key):
    phase, verdict, action = key
    result = RoleResult(verdict=verdict, required_next_action=action)
    assert ENGINE.next_phase(phase, result) == transition_child_phase(phase, result)


def test_engine_next_phase_unknown_raises_graph_error():
    with pytest.raises(GraphError):
        ENGINE.next_phase(
            ChildPhase.IMPLEMENTING,
            RoleResult(verdict="NOPE", required_next_action="nope"),
        )


def test_engine_dispatch_phase_maps_ready_to_implementing_else_identity():
    assert ENGINE.dispatch_phase(ChildPhase.READY) == ChildPhase.IMPLEMENTING
    assert ENGINE.dispatch_phase(ChildPhase.SPEC_REVIEWING) == ChildPhase.SPEC_REVIEWING


def test_engine_is_terminal_matches_legacy():
    for phase in ChildPhase:
        assert ENGINE.is_terminal(phase) == (phase in TERMINAL_CHILD_PHASES)


def test_engine_eligible_matches_legacy_eligible_child_ids():
    graph = WorkflowGraph(
        children={
            "a": ChildNode(id="a"),
            "b": ChildNode(id="b", dependencies=frozenset({"a"})),
        }
    )
    completed = frozenset({"a"})
    assert ENGINE.eligible(graph, completed_child_ids=completed) == eligible_child_ids(
        graph, completed_child_ids=completed
    )


# --- Phase 1b: parent stages modeled as a workflow definition ---

from smda_scheduler.workflow import ParentPhase  # noqa: E402
from smda_scheduler.workflow import RoadmapPhase  # noqa: E402
from smda_scheduler.workflow_engine import PARENT_DEFINITION, ROADMAP_DEFINITION  # noqa: E402


def test_stage_spec_work_defaults_none():
    spec = CHILD_DEFINITION.stage(ChildPhase.IMPLEMENTING)
    assert spec.work is None


@pytest.mark.parametrize(
    "phase,kind",
    [
        ("SPEC_FINALIZED", WorkHandlerKind.ROLE_ATTEMPT),
        (ParentPhase.GRAPH_FIXING.value, WorkHandlerKind.ROLE_ATTEMPT),
        (ParentPhase.GRAPH_SPEC_REVIEWING.value, WorkHandlerKind.ROLE_ATTEMPT),
        (ParentPhase.GRAPH_EXECUTION_REVIEWING.value, WorkHandlerKind.ROLE_ATTEMPT),
        (ParentPhase.CHILD_PUBLICATION_READY.value, WorkHandlerKind.EFFECT),
        (ParentPhase.CHILDREN_PUBLISHED.value, WorkHandlerKind.AGGREGATE),
        (ParentPhase.PARENT_QA_READY.value, WorkHandlerKind.ROLE_ATTEMPT),
        (ParentPhase.REMEDIATION_PLANNING.value, WorkHandlerKind.EFFECT),
        (ParentPhase.FINAL_ACCEPT_READY.value, WorkHandlerKind.EFFECT),
    ],
)
def test_parent_stage_kinds(phase, kind):
    assert PARENT_DEFINITION.stage(phase).kind is kind
    assert PARENT_DEFINITION.stage(phase).work is not None


def test_parent_definition_terminal_phases():
    assert PARENT_DEFINITION.terminal_phases == frozenset(
        {ParentPhase.FINAL_ACCEPTED, ParentPhase.HUMAN_REVIEW_REQUIRED}
    )


# --- Phase 1c: parent transitions as data ---

from smda_scheduler.workflow_engine import PARENT_TRANSITIONS  # noqa: E402

PARENT_ENGINE = WorkflowEngine(PARENT_DEFINITION)


def test_parent_transitions_golden_success_edges():
    P = ParentPhase
    expected = {
        ("SPEC_FINALIZED", "DONE", "submit_for_graph_review"): P.GRAPH_SPEC_REVIEWING.value,
        (P.GRAPH_FIXING.value, "DONE", "submit_for_graph_review"): P.GRAPH_SPEC_REVIEWING.value,
        (P.GRAPH_SPEC_REVIEWING.value, "PASS", "submit_for_graph_execution_review"): P.GRAPH_EXECUTION_REVIEWING.value,
        (P.GRAPH_SPEC_REVIEWING.value, "DONE_WITH_CONCERNS", "submit_for_graph_execution_review"): P.GRAPH_EXECUTION_REVIEWING.value,
        (P.GRAPH_EXECUTION_REVIEWING.value, "PASS", "publish_child_issues"): P.CHILD_PUBLICATION_READY.value,
        (P.GRAPH_EXECUTION_REVIEWING.value, "DONE_WITH_CONCERNS", "publish_child_issues"): P.CHILD_PUBLICATION_READY.value,
        (P.PARENT_QA_READY.value, "PASS", "accept_parent"): P.FINAL_ACCEPT_READY.value,
        (P.PARENT_QA_READY.value, "DONE_WITH_CONCERNS", "accept_parent"): P.FINAL_ACCEPT_READY.value,
        (P.PARENT_QA_READY.value, "FAIL", "plan_remediation"): P.REMEDIATION_PLANNING.value,
    }
    assert PARENT_TRANSITIONS == expected


def test_parent_engine_next_phase_for_passing_review():
    nxt = PARENT_ENGINE.next_phase(
        ParentPhase.GRAPH_SPEC_REVIEWING.value,
        RoleResult(verdict="PASS", required_next_action="submit_for_graph_execution_review"),
    )
    assert nxt == ParentPhase.GRAPH_EXECUTION_REVIEWING.value


def test_parent_deterministic_success_edges():
    P = ParentPhase
    assert PARENT_DEFINITION.stage(P.CHILD_PUBLICATION_READY.value).next_phase_on_success == P.CHILDREN_PUBLISHED.value
    assert PARENT_DEFINITION.stage(P.CHILDREN_PUBLISHED.value).next_phase_on_success == P.PARENT_QA_READY.value
    assert PARENT_DEFINITION.stage(P.REMEDIATION_PLANNING.value).next_phase_on_success == P.CHILDREN_PUBLISHED.value
    assert PARENT_DEFINITION.stage(P.FINAL_ACCEPT_READY.value).next_phase_on_success == P.FINAL_ACCEPTED.value


def test_roadmap_definition_is_thin_authoring_path():
    R = RoadmapPhase
    assert ROADMAP_DEFINITION.phases == frozenset(RoadmapPhase)
    assert ROADMAP_DEFINITION.stage(R.ROADMAP_DECOMPOSING).kind is WorkHandlerKind.ROLE_ATTEMPT
    assert ROADMAP_DEFINITION.stage(R.ROADMAP_DECOMPOSING).role_contract is not None
    assert ROADMAP_DEFINITION.stage(R.ROADMAP_DECOMPOSING).role_contract.role.value == "roadmap_decomposer"
    assert ROADMAP_DEFINITION.stage(R.ROADMAP_PUBLICATION_READY).kind is WorkHandlerKind.EFFECT
    assert (
        ROADMAP_DEFINITION.stage(R.ROADMAP_PUBLICATION_READY).next_phase_on_success
        == R.ROADMAP_PUBLISHED.value
    )
    # ROADMAP_PUBLISHED is the parent-tier completion Aggregate (Phase 4c), not
    # terminal; ROADMAP_COMPLETED is the terminal landed state.
    assert ROADMAP_DEFINITION.stage(R.ROADMAP_PUBLISHED).kind is WorkHandlerKind.AGGREGATE
    assert (
        ROADMAP_DEFINITION.stage(R.ROADMAP_PUBLISHED).next_phase_on_success
        == R.ROADMAP_COMPLETED.value
    )
    assert ROADMAP_DEFINITION.terminal_phases == frozenset(
        {R.ROADMAP_COMPLETED, R.HUMAN_REVIEW_REQUIRED}
    )


def test_roadmap_decomposition_transition_targets_publication_ready():
    engine = WorkflowEngine(ROADMAP_DEFINITION)

    assert engine.next_phase(
        RoadmapPhase.ROADMAP_DECOMPOSING,
        RoleResult(verdict="DONE", required_next_action="publish_roadmap_parents"),
    ) == RoadmapPhase.ROADMAP_PUBLICATION_READY.value
