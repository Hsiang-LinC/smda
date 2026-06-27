from pathlib import Path

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.role_contracts import CHILD_ROLE_BY_PHASE, PARENT_ROLE_BY_PHASE
from smda_scheduler.role_attempts import (
    AgentSelection,
    ChildTaskContext,
    ParentGraphContext,
    ParentSpecContext,
    build_child_role_attempt_request,
    build_parent_accept_conflict_resolver_request,
    build_parent_graph_decomposer_request,
    build_parent_graph_execution_review_request,
    build_parent_qa_review_request,
    build_parent_graph_spec_review_request,
)
from smda_scheduler.workflow import ChildPhase, ParentPhase


def test_python_role_contracts_reference_supported_ts_schema_manifest():
    supported_schema_ids = {
        "smda.graph-decomposer-result.v1",
        "smda.child-implementer-result.v1",
        "smda.review-result.v1",
        "smda.child-fixer-result.v1",
    }
    supported_output_tags = {
        "smda_graph_decomposer_result",
        "smda_graph_fixer_result",
        "smda_child_implementer_result",
        "smda_graph_spec_review_result",
        "smda_graph_execution_review_result",
        "smda_child_spec_review_result",
        "smda_child_fixer_result",
        "smda_child_quality_review_result",
        "smda_parent_qa_review_result",
        "smda_parent_integration_conflict_result",
    }

    contracts = [
        *PARENT_ROLE_BY_PHASE.values(),
        *CHILD_ROLE_BY_PHASE.values(),
    ]

    assert {contract.schema_id for contract in contracts} <= supported_schema_ids
    assert {contract.output_tag for contract in contracts} <= supported_output_tags


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

    assert request.phase == ChildPhase.IMPLEMENTING
    assert request.branch == "smda/danny-66/child-001/candidate"
    assert request.context_packet == {
        "parent_issue_id": "DANNY-66",
        "child_id": "child-001",
        "child_title": "Move orchestration to product runtime",
        "child_body": "Replace repo-local runtime wiring with SMDA product config.",
        "in_scope": [],
        "out_of_scope": [],
        "touched_surfaces": {},
        "acceptance_criteria": ["validate-config passes"],
        "verification": {},
        "dependencies": [],
        "dependency_outputs": [],
        "candidate_ref": None,
        "review_findings": [],
        "phase": "IMPLEMENTING",
        "role": "child_implementer",
        "bootloader_path": str(bootloader_path),
        "spec_locations": [str(spec_dir)],
        "adr_locations": [],
        "quality_gates": ["pytest tests/harness -q"],
    }
    assert request.role == "child_implementer"
    assert "Role: child implementer" in request.prompt
    assert "Do not call backlog tools or mutate" in request.prompt
    assert "Quality gates:\n- pytest tests/harness -q" in request.prompt
    assert "<smda_child_implementer_result>" in request.prompt
    assert request.output_tag == "smda_child_implementer_result"
    assert request.schema_id == "smda.child-implementer-result.v1"


def test_build_child_role_attempt_request_uses_role_agent_override(
    tmp_path: Path,
):
    repo_packet = RepoContextPacket(
        bootloader_path=tmp_path / "AGENTS.md",
        bootloader_text="# Boot\n",
        spec_locations=(),
        adr_locations=(),
        quality_gates=(),
    )

    request = build_child_role_attempt_request(
        attempt_id="child-001-SPEC_REVIEWING-1",
        parent_issue_id="DANNY-66",
        child=ChildTaskContext(
            child_id="child-001",
            title="Move orchestration to product runtime",
            body="Replace repo-local runtime wiring with SMDA product config.",
        ),
        phase=ChildPhase.SPEC_REVIEWING,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(
            provider="codex",
            model="gpt-5",
            role_overrides={
                "child_spec_reviewer": AgentSelection(
                    provider="codex",
                    model="gpt-5.5",
                    effort="high",
                )
            },
        ),
    )

    assert request.role == "child_spec_reviewer"
    assert request.agent_provider == "codex"
    assert request.agent_model == "gpt-5.5"
    assert request.agent_effort == "high"


def test_build_child_role_attempt_request_carries_static_and_runtime_context(
    tmp_path: Path,
):
    bootloader_path = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader_path.write_text("# Boot\nUse pytest.\n", encoding="utf-8")
    docs.mkdir()
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\nUse pytest.\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest packages/scheduler/tests -q",),
    )

    request = build_child_role_attempt_request(
        attempt_id="child-001-SPEC_REVIEWING-1",
        parent_issue_id="DANNY-66",
        child=ChildTaskContext(
            child_id="child-001",
            title="Implement runtime wiring",
            body="Dispatch through Sandcastle.",
            in_scope=("scheduler runtime",),
            out_of_scope=("consumer repo cleanup",),
            touched_surfaces={
                "files": ["packages/scheduler/src/smda_scheduler/runtime.py"],
                "modules": ["smda_scheduler.runtime"],
                "contracts": ["smda.child-role-context.v1"],
                "docs": ["docs/product-spec.md"],
                "tests": ["packages/scheduler/tests/test_runtime.py"],
            },
            acceptance_criteria=("scheduler tests pass",),
            verification={
                "required": ["uv run pytest packages/scheduler/tests/test_runtime.py -q"],
                "smoke": ["uv run pytest packages/scheduler/tests -q"],
            },
            dependencies=("child-000",),
            dependency_outputs=(
                {
                    "dependency_id": "child-000",
                    "required_artifacts": ["accepted_commit"],
                    "reason": "child-001 imports the accepted runtime API.",
                },
            ),
            candidate_ref="smda/danny-66/child-001/candidate",
            review_findings=("Spec reviewer requested tighter acceptance coverage.",),
        ),
        phase=ChildPhase.SPEC_REVIEWING,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.context_packet["in_scope"] == ["scheduler runtime"]
    assert request.context_packet["out_of_scope"] == ["consumer repo cleanup"]
    assert request.context_packet["touched_surfaces"]["modules"] == [
        "smda_scheduler.runtime"
    ]
    assert request.context_packet["verification"]["required"] == [
        "uv run pytest packages/scheduler/tests/test_runtime.py -q"
    ]
    assert request.context_packet["dependencies"] == ["child-000"]
    assert request.context_packet["dependency_outputs"] == [
        {
            "dependency_id": "child-000",
            "required_artifacts": ["accepted_commit"],
            "reason": "child-001 imports the accepted runtime API.",
        }
    ]
    assert request.context_packet["candidate_ref"] == (
        "smda/danny-66/child-001/candidate"
    )
    assert request.context_packet["review_findings"] == [
        "Spec reviewer requested tighter acceptance coverage."
    ]
    assert request.branch == "smda/danny-66/child-001/candidate"


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

    spec_review_request = build_child_role_attempt_request(
        attempt_id="a",
        parent_issue_id="DANNY-66",
        child=child,
        phase=ChildPhase.SPEC_REVIEWING,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )
    assert spec_review_request.role == "child_spec_reviewer"
    assert spec_review_request.branch == "smda/danny-66/child-001/candidate"
    assert "submit_for_quality_review" in spec_review_request.prompt
    assert "fix_spec" in spec_review_request.prompt
    fixer_request = build_child_role_attempt_request(
            attempt_id="a",
            parent_issue_id="DANNY-66",
            child=child,
            phase=ChildPhase.FIXING_SPEC,
            repo_context=repo_packet,
            repo_root=tmp_path,
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
    )
    assert fixer_request.role == "child_fixer"
    assert fixer_request.branch == "smda/danny-66/child-001/candidate"
    assert "submit_for_spec_review" in fixer_request.prompt


def test_build_parent_graph_decomposer_request_carries_spec_context(tmp_path: Path):
    bootloader_path = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader_path.write_text("# Boot\nUse pytest.\n", encoding="utf-8")
    docs.mkdir()
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\nUse pytest.\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest packages/scheduler/tests -q",),
    )

    request = build_parent_graph_decomposer_request(
        attempt_id="DANNY-66-GRAPH_DECOMPOSING-1",
        parent=ParentSpecContext(
            parent_issue_id="DANNY-66",
            title="Migrate orchestration to SMDA product",
            body="Source: docs/superpowers/specs/smda.md\nExecution: smda\n",
            spec_path="docs/superpowers/specs/smda.md",
            spec_checksum="sha256:abcdef",
            approval_evidence="DANNY-66 approved",
            spec_text="# Approved spec\n\nBuild graph children.",
        ),
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.phase == "GRAPH_DECOMPOSING"
    assert request.branch == "smda/danny-66/graph-decomposing"
    assert request.role == "graph_decomposer"
    assert request.schema_id == "smda.graph-decomposer-result.v1"
    assert request.output_tag == "smda_graph_decomposer_result"
    assert request.context_packet["parent_issue_id"] == "DANNY-66"
    assert request.context_packet["spec_path"] == "docs/superpowers/specs/smda.md"
    assert request.context_packet["spec_checksum"] == "sha256:abcdef"
    assert request.context_packet["approval_evidence"] == "DANNY-66 approved"
    assert request.context_packet["spec_text"] == "# Approved spec\n\nBuild graph children."
    assert "Role: graph decomposer" in request.prompt
    assert "Do not publish child issues or mutate tracker state" in request.prompt
    assert "Spec checksum: sha256:abcdef" in request.prompt
    assert "Quality gates:\n- pytest packages/scheduler/tests -q" in request.prompt
    assert "<smda_graph_decomposer_result>" in request.prompt


def test_build_parent_graph_spec_review_request_carries_graph_context(
    tmp_path: Path,
):
    bootloader_path = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader_path.write_text("# Boot\nUse pytest.\n", encoding="utf-8")
    docs.mkdir()
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\nUse pytest.\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest packages/scheduler/tests -q",),
    )

    request = build_parent_graph_spec_review_request(
        attempt_id="DANNY-66-GRAPH_SPEC_REVIEWING-1",
        graph=ParentGraphContext(
            parent=ParentSpecContext(
                parent_issue_id="DANNY-66",
                title="Migrate orchestration to SMDA product",
                body="Source: docs/superpowers/specs/smda.md\nExecution: smda\n",
                spec_path="docs/superpowers/specs/smda.md",
                spec_checksum="sha256:abcdef",
                approval_evidence="DANNY-66 approved",
                spec_text="# Approved spec\n\nBuild graph children.",
            ),
            graph_checksum="sha256:graph",
            children=(
                {
                    "node_id": "child-001",
                    "title": "Extract scheduler runtime",
                    "body": "Move scheduler code into the SMDA product.",
                    "acceptance_criteria": ["scheduler tests pass"],
                    "dependencies": [],
                },
            ),
        ),
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.phase == "GRAPH_SPEC_REVIEWING"
    assert request.branch == "smda/danny-66/graph-spec-reviewing"
    assert request.role == "graph_spec_reviewer"
    assert request.schema_id == "smda.review-result.v1"
    assert request.output_tag == "smda_graph_spec_review_result"
    assert request.context_packet["graph_checksum"] == "sha256:graph"
    assert request.context_packet["children"][0]["node_id"] == "child-001"
    assert "Role: graph spec reviewer" in request.prompt
    assert "Review the child graph against the approved parent spec" in request.prompt
    assert "Do not publish child issues or mutate tracker state" in request.prompt


def test_build_parent_graph_execution_review_request_carries_graph_context(
    tmp_path: Path,
):
    bootloader_path = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader_path.write_text("# Boot\nUse pytest.\n", encoding="utf-8")
    docs.mkdir()
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\nUse pytest.\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest packages/scheduler/tests -q",),
    )
    graph = ParentGraphContext(
        parent=ParentSpecContext(
            parent_issue_id="DANNY-66",
            title="Migrate orchestration to SMDA product",
            body="Source: docs/superpowers/specs/smda.md\nExecution: smda\n",
            spec_path="docs/superpowers/specs/smda.md",
            spec_checksum="sha256:abcdef",
            approval_evidence="DANNY-66 approved",
            spec_text="# Approved spec\n\nBuild graph children.",
        ),
        graph_checksum="sha256:graph",
        children=(
            {
                "node_id": "child-001",
                "title": "Extract scheduler runtime",
                "body": "Move scheduler code into the SMDA product.",
                "acceptance_criteria": ["scheduler tests pass"],
                "dependencies": [],
            },
        ),
    )

    request = build_parent_graph_execution_review_request(
        attempt_id="DANNY-66-GRAPH_EXECUTION_REVIEWING-1",
        graph=graph,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.phase == "GRAPH_EXECUTION_REVIEWING"
    assert request.branch == "smda/danny-66/graph-execution-reviewing"
    assert request.role == "graph_execution_reviewer"
    assert request.schema_id == "smda.review-result.v1"
    assert request.output_tag == "smda_graph_execution_review_result"
    assert request.context_packet["graph_checksum"] == "sha256:graph"
    assert request.context_packet["children"][0]["node_id"] == "child-001"
    assert "Role: graph execution reviewer" in request.prompt
    assert "Review dependency order, merge risk, and safe parallelism" in request.prompt
    assert "Do not publish child issues or mutate tracker state" in request.prompt


def test_build_parent_qa_review_request_carries_final_integration_context(
    tmp_path: Path,
):
    bootloader_path = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader_path.write_text("# Boot\nUse pytest.\n", encoding="utf-8")
    docs.mkdir()
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\nUse pytest.\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest packages/scheduler/tests -q",),
    )
    graph = ParentGraphContext(
        parent=ParentSpecContext(
            parent_issue_id="DANNY-66",
            title="Migrate orchestration to SMDA product",
            body="Source: docs/superpowers/specs/smda.md\nExecution: smda\n",
            spec_path="docs/superpowers/specs/smda.md",
            spec_checksum="sha256:abcdef",
            approval_evidence="DANNY-66 approved",
            spec_text="# Approved spec\n\nBuild graph children.",
        ),
        graph_checksum="sha256:graph",
        children=(
            {
                "node_id": "child-001",
                "title": "Extract scheduler runtime",
                "body": "Move scheduler code into the SMDA product.",
                "acceptance_criteria": ["scheduler tests pass"],
                "dependencies": [],
            },
        ),
    )

    request = build_parent_qa_review_request(
        attempt_id="DANNY-66-PARENT_QA_REVIEWING-1",
        graph=graph,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.phase == ParentPhase.PARENT_QA_REVIEWING
    assert request.branch == "smda/danny-66/parent-qa-reviewing"
    assert request.role == "parent_qa_reviewer"
    assert request.schema_id == "smda.review-result.v1"
    assert request.output_tag == "smda_parent_qa_review_result"
    assert request.context_packet["graph_checksum"] == "sha256:graph"
    assert request.context_packet["children"][0]["node_id"] == "child-001"
    assert "Role: parent QA reviewer" in request.prompt
    assert "accept_parent" in request.prompt
    assert "plan_remediation" in request.prompt


def test_build_parent_accept_conflict_resolver_request_carries_history(
    tmp_path: Path,
):
    bootloader_path = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader_path.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    repo_packet = RepoContextPacket(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    graph = ParentGraphContext(
        parent=ParentSpecContext(
            parent_issue_id="DANNY-66",
            title="Parent",
            body="Execution: smda",
            spec_path="docs/spec.md",
            spec_checksum="sha256:spec",
            approval_evidence="approved",
            spec_text="# Spec",
        ),
        graph_checksum="sha256:graph",
        children=(
            {
                "node_id": "child-001",
                "title": "Extract scheduler runtime",
                "body": "Move scheduler code into the SMDA product.",
                "acceptance_criteria": ["scheduler tests pass"],
                "dependencies": [],
            },
        ),
    )
    history = {
        "operation_id": "accept:DANNY-66:child-001:candidate",
        "conflicted_paths": ["shared.txt"],
    }

    request = build_parent_accept_conflict_resolver_request(
        attempt_id="DANNY-66-CHILD_ACCEPT_CONFLICT_RESOLVING-1",
        graph=graph,
        conflict_history=history,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )

    assert request.phase == ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING
    assert request.role == "parent_integration_conflict_resolver"
    assert request.output_tag == "smda_parent_integration_conflict_result"
    assert request.context_packet["conflict_history"] == history
    assert "shared.txt" in request.prompt
    assert "retry_child_acceptance" in request.prompt


def _impl_request(tmp_path: Path, *, skills=None):
    bootloader_path = tmp_path / "AGENTS.md"
    spec_dir = tmp_path / "docs"
    bootloader_path.write_text("# Boot\n", encoding="utf-8")
    spec_dir.mkdir(exist_ok=True)
    kwargs = dict(
        bootloader_path=bootloader_path,
        bootloader_text="# Boot\n",
        spec_locations=(spec_dir,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    if skills is not None:
        kwargs["skills"] = skills
    repo_packet = RepoContextPacket(**kwargs)
    return build_child_role_attempt_request(
        attempt_id="child-001-IMPLEMENTING-1",
        parent_issue_id="DANNY-1",
        child=ChildTaskContext(
            child_id="child-001", title="t", body="b", acceptance_criteria=("x",)
        ),
        phase=ChildPhase.IMPLEMENTING,
        repo_context=repo_packet,
        repo_root=tmp_path,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
    )


def test_child_prompt_injects_bound_methodology(tmp_path: Path):
    request = _impl_request(tmp_path, skills={"tdd": "Red green refactor methodology."})
    assert "## Methodology: tdd" in request.prompt
    assert "Red green refactor methodology." in request.prompt


def test_child_prompt_unchanged_without_skills(tmp_path: Path):
    request = _impl_request(tmp_path)  # skills defaults to {}
    assert "## Methodology" not in request.prompt
