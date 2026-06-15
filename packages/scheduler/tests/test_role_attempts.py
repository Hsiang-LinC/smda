from pathlib import Path

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.role_attempts import (
    AgentSelection,
    ChildTaskContext,
    build_child_role_attempt_request,
)
from smda_scheduler.workflow import ChildPhase


def test_build_child_role_attempt_request_maps_phase_to_role_and_context(
    tmp_path: Path,
):
    bootloader_path = tmp_path / "AGENTS.md"
    spec_dir = tmp_path / "docs" / "specs"
    bootloader_path.write_text("# Boot\nUse pytest.\n", encoding="utf-8")
    spec_dir.mkdir(parents=True)
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\nUse pytest.\n",
        spec_locations=(spec_dir,),
        adr_locations=(),
        quality_gates=("pytest tests/harness -q",),
    )

    request = build_child_role_attempt_request(
        attempt_id="child-001-IMPLEMENTING-1",
        parent_issue_id="DANNY-66",
        child=ChildTaskContext(
            child_id="child-001",
            title="Move orchestration to product runtime",
            body="Replace repo-local runtime wiring with SMDA product config.",
            acceptance_criteria=("validate-config passes",),
        ),
        phase=ChildPhase.IMPLEMENTING,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.role == "implementer"
    assert request.phase == ChildPhase.IMPLEMENTING
    assert request.branch == "smda/danny-66/child-001/implementing"
    assert request.context_packet == {
        "parent_issue_id": "DANNY-66",
        "child_id": "child-001",
        "child_title": "Move orchestration to product runtime",
        "child_body": "Replace repo-local runtime wiring with SMDA product config.",
        "acceptance_criteria": ["validate-config passes"],
        "phase": "IMPLEMENTING",
        "role": "implementer",
        "bootloader_path": str(bootloader_path),
        "spec_locations": [str(spec_dir)],
        "adr_locations": [],
        "quality_gates": ["pytest tests/harness -q"],
    }
    assert "Role: implementer" in request.prompt
    assert "Quality gates:\n- pytest tests/harness -q" in request.prompt
    assert request.output_tag == "smda_role_result"
    assert request.schema_id == "smda.role-result.v1"


def test_build_child_role_attempt_request_maps_review_and_fix_roles(tmp_path: Path):
    bootloader_path = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader_path.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=(),
    )
    child = ChildTaskContext(child_id="child-001", title="T", body="B")

    assert (
        build_child_role_attempt_request(
            attempt_id="a",
            parent_issue_id="DANNY-66",
            child=child,
            phase=ChildPhase.SPEC_REVIEWING,
            repo_context=repo_packet,
            repo_root=tmp_path,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
        ).role
        == "spec_reviewer"
    )
    assert (
        build_child_role_attempt_request(
            attempt_id="a",
            parent_issue_id="DANNY-66",
            child=child,
            phase=ChildPhase.FIXING_SPEC,
            repo_context=repo_packet,
            repo_root=tmp_path,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
        ).role
        == "fixer"
    )
