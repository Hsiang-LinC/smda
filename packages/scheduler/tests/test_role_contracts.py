from smda_scheduler.role_contracts import (
    CHILD_ROLE_BY_PHASE,
    PARENT_ROLE_BY_PHASE,
    ROADMAP_ROLE_BY_PHASE,
    RoleName,
    roadmap_role_contract_for_phase,
)
from smda_scheduler.workflow import ChildPhase, ParentPhase, RoadmapPhase


def test_child_implementer_binds_tdd():
    assert "tdd" in CHILD_ROLE_BY_PHASE[ChildPhase.IMPLEMENTING].methodology_skills


def test_child_quality_reviewer_binds_architecture_skill():
    contract = CHILD_ROLE_BY_PHASE[ChildPhase.QUALITY_REVIEWING]
    assert "improve-codebase-architecture" in contract.methodology_skills


def test_graph_decomposer_binds_to_issues():
    assert "to-issues" in PARENT_ROLE_BY_PHASE[ParentPhase.GRAPH_DECOMPOSING].methodology_skills


def test_roadmap_decomposer_contract_authors_parent_set_without_tracker_mutation():
    contract = roadmap_role_contract_for_phase(RoadmapPhase.ROADMAP_DECOMPOSING)

    assert contract is ROADMAP_ROLE_BY_PHASE[RoadmapPhase.ROADMAP_DECOMPOSING]
    assert contract.role is RoleName.ROADMAP_DECOMPOSER
    assert contract.methodology_skills == ("to-prd", "to-issues")
    assert contract.schema_id == "smda.roadmap-decomposer-result.v1"
    assert contract.output_tag == "smda_roadmap_decomposer_result"
    rendered = contract.render_prompt(
        {
            "phase": "ROADMAP_DECOMPOSING",
            "roadmap_issue_id": "DANNY-100",
            "roadmap_title": "Roadmap",
            "roadmap_body": "Execution: smda-roadmap",
            "spec_path": "docs/superpowers/specs/roadmap.md",
            "spec_checksum": "sha256:spec",
            "approval_evidence": "approved",
            "spec_text": "# Roadmap spec",
            "open_parent_snapshot": "[]",
            "bootloader_text": "# Boot",
            "spec_locations": "- docs",
            "adr_locations": "- docs/adr",
            "quality_gates": "- pytest",
            "schema_id": "smda.roadmap-decomposer-result.v1",
        }
    )
    assert "open-parent snapshot" in rendered.lower()
    assert "must not create issues" in rendered.lower()


def test_every_role_contract_declares_a_methodology_skill():
    contracts = [
        *CHILD_ROLE_BY_PHASE.values(),
        *PARENT_ROLE_BY_PHASE.values(),
        *ROADMAP_ROLE_BY_PHASE.values(),
    ]
    for contract in contracts:
        assert contract.methodology_skills, f"{contract.role} has no methodology skill"
