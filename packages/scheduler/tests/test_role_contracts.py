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


def test_child_implementer_prompt_explains_role_payload_not_report_envelope():
    rendered = CHILD_ROLE_BY_PHASE[ChildPhase.IMPLEMENTING].render_prompt(
        {
            "phase": "IMPLEMENTING",
            "parent_issue_id": "DANNY-70",
            "child_id": "child-001",
            "child_title": "Add workflow repository",
            "child_body": "Implement the workflow repository.",
            "acceptance_criteria": "- Tests pass",
            "bootloader_text": "# Boot",
            "spec_locations": "- docs/superpowers/specs",
            "adr_locations": "- docs/adr",
            "quality_gates": "- pytest",
            "schema_id": "smda.child-implementer-result.v1",
        }
    )

    assert "payload only" in rendered
    assert "not a scheduler report envelope" in rendered
    assert "verdict DONE" in rendered
    assert "required_next_action submit_for_spec_review" in rendered
    assert "report string" in rendered


def test_child_quality_reviewer_binds_architecture_skill():
    contract = CHILD_ROLE_BY_PHASE[ChildPhase.QUALITY_REVIEWING]
    assert "improve-codebase-architecture" in contract.methodology_skills


def test_graph_decomposer_binds_to_issues():
    assert "to-issues" in PARENT_ROLE_BY_PHASE[ParentPhase.GRAPH_DECOMPOSING].methodology_skills


def test_parent_integration_conflict_resolver_contract_is_narrow():
    contract = PARENT_ROLE_BY_PHASE[ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING]

    assert contract.role is RoleName.PARENT_INTEGRATION_CONFLICT_RESOLVER
    assert contract.schema_id == "smda.review-result.v1"
    assert contract.output_tag == "smda_parent_integration_conflict_result"
    rendered = contract.render_prompt(
        {
            "phase": "CHILD_ACCEPT_CONFLICT_RESOLVING",
            "parent_issue_id": "DANNY-66",
            "parent_title": "Parent",
            "parent_body": "Execution: smda",
            "spec_path": "docs/spec.md",
            "spec_checksum": "sha256:spec",
            "approval_evidence": "approved",
            "spec_text": "# Spec",
            "graph_checksum": "sha256:graph",
            "children": "[]",
            "conflict_history": "{}",
            "bootloader_text": "# Boot",
            "spec_locations": "- docs",
            "adr_locations": "- docs/adr",
            "quality_gates": "- pytest",
            "schema_id": "smda.review-result.v1",
        }
    )
    assert "retry_child_acceptance" in rendered
    assert "Do not use DONE_WITH_CONCERNS" in rendered


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
