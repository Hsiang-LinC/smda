from smda_scheduler.role_contracts import (
    CHILD_ROLE_BY_PHASE,
    PARENT_ROLE_BY_PHASE,
)
from smda_scheduler.workflow import ChildPhase, ParentPhase


def test_child_implementer_binds_tdd():
    assert "tdd" in CHILD_ROLE_BY_PHASE[ChildPhase.IMPLEMENTING].methodology_skills


def test_child_quality_reviewer_binds_architecture_skill():
    contract = CHILD_ROLE_BY_PHASE[ChildPhase.QUALITY_REVIEWING]
    assert "improve-codebase-architecture" in contract.methodology_skills


def test_graph_decomposer_binds_to_issues():
    assert "to-issues" in PARENT_ROLE_BY_PHASE[ParentPhase.GRAPH_DECOMPOSING].methodology_skills


def test_every_role_contract_declares_a_methodology_skill():
    contracts = [*CHILD_ROLE_BY_PHASE.values(), *PARENT_ROLE_BY_PHASE.values()]
    for contract in contracts:
        assert contract.methodology_skills, f"{contract.role} has no methodology skill"
