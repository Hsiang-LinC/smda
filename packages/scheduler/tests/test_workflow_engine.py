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
