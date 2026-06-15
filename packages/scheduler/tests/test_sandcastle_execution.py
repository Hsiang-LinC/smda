import json
from pathlib import Path

from smda_scheduler.sandcastle_execution import (
    ProcessResult,
    RoleAttemptRequest,
    SandcastleExecutionAdapter,
)
from smda_scheduler.workflow import ChildPhase, ParentPhase, RoleResult


class RecordingRunner:
    def __init__(self, result: ProcessResult):
        self.result = result
        self.calls = []

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        input_text: str,
        cwd: Path,
        timeout_seconds: float,
    ) -> ProcessResult:
        self.calls.append(
            {
                "command": command,
                "input": json.loads(input_text),
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.result


def test_sandcastle_execution_adapter_maps_successful_ipc_result(tmp_path: Path):
    runner = RecordingRunner(
        ProcessResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "succeeded",
                    "attempt_id": "attempt-1",
                    "schema_id": "smda.child-implementer-result.v1",
                    "schema_package_version": "0.1.0",
                    "result": {
                        "verdict": "DONE",
                        "required_next_action": "submit_for_spec_review",
                    },
                    "commits": [{"sha": "abc123"}],
                    "branch": "smda/child-A",
                }
            ),
            stderr="",
        )
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        runner=runner,
        timeout_seconds=60.0,
    )
    request = RoleAttemptRequest(
        attempt_id="attempt-1",
        role="implementer",
        phase=ChildPhase.IMPLEMENTING,
        branch="smda/child-A",
        cwd=tmp_path / "repo",
        context_packet={"child_id": "A", "quality_gates": ["pytest"]},
        prompt="Implement child A",
        output_tag="smda_child_implementer_result",
        schema_id="smda.child-implementer-result.v1",
        sandbox_provider="noSandbox",
        agent_provider="codex",
        agent_model="gpt-5",
    )

    outcome = adapter.run_role_attempt(request)

    assert outcome.status == "succeeded"
    assert outcome.role_result == RoleResult(
        verdict="DONE",
        required_next_action="submit_for_spec_review",
    )
    assert outcome.schema_id == "smda.child-implementer-result.v1"
    assert outcome.schema_package_version == "0.1.0"
    assert outcome.commits == ("abc123",)
    assert runner.calls == [
        {
            "command": ("node", "runner.js"),
            "input": {
                "attempt_id": "attempt-1",
                "role": "implementer",
                "phase": "IMPLEMENTING",
                "branch": "smda/child-A",
                "cwd": str(tmp_path / "repo"),
                "context_packet": {"child_id": "A", "quality_gates": ["pytest"]},
                "prompt": "Implement child A",
                "output_tag": "smda_child_implementer_result",
                "schema_id": "smda.child-implementer-result.v1",
                "sandbox_provider": "noSandbox",
                "agent": {"provider": "codex", "model": "gpt-5"},
            },
            "cwd": tmp_path,
            "timeout_seconds": 60.0,
        }
    ]


def test_sandcastle_execution_adapter_preserves_raw_graph_decomposer_result(
    tmp_path: Path,
):
    graph_result = {
        "verdict": "DONE",
        "required_next_action": "submit_for_graph_review",
        "children": [
            {
                "node_id": "child-001",
                "title": "Extract scheduler runtime",
                "body": "Move scheduler code into the SMDA product.",
                "acceptance_criteria": ["scheduler tests pass"],
                "dependencies": [],
            }
        ],
    }
    runner = RecordingRunner(
        ProcessResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "succeeded",
                    "attempt_id": "attempt-1",
                    "schema_id": "smda.graph-decomposer-result.v1",
                    "schema_package_version": "0.1.0",
                    "result": graph_result,
                    "commits": [],
                    "branch": "smda/danny-66/graph-decomposing",
                }
            ),
            stderr="",
        )
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        runner=runner,
        timeout_seconds=60.0,
    )

    outcome = adapter.run_role_attempt(
        RoleAttemptRequest(
            attempt_id="attempt-1",
            role="graph_decomposer",
            phase=ParentPhase.GRAPH_DECOMPOSING,
            branch="smda/danny-66/graph-decomposing",
            cwd=tmp_path / "repo",
            context_packet={"parent_issue_id": "DANNY-66"},
            prompt="Decompose graph",
            output_tag="smda_graph_decomposer_result",
            schema_id="smda.graph-decomposer-result.v1",
            sandbox_provider="noSandbox",
            agent_provider="codex",
            agent_model="gpt-5",
        )
    )

    assert outcome.status == "succeeded"
    assert outcome.role_result == RoleResult(
        verdict="DONE",
        required_next_action="submit_for_graph_review",
    )
    assert outcome.raw_result == graph_result


def test_sandcastle_execution_adapter_maps_structured_output_failure(tmp_path: Path):
    runner = RecordingRunner(
        ProcessResult(
            returncode=1,
            stdout=json.dumps(
                {
                    "status": "structured_output_failed",
                    "attempt_id": "attempt-1",
                    "schema_id": "smda.review-result.v1",
                    "schema_package_version": "0.1.0",
                    "error_message": "No valid output block",
                    "preserved_worktree_path": "/tmp/worktree",
                }
            ),
            stderr="",
        )
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        runner=runner,
    )

    outcome = adapter.run_role_attempt(
        RoleAttemptRequest(
            attempt_id="attempt-1",
            role="reviewer",
            phase=ChildPhase.SPEC_REVIEWING,
            branch="smda/child-A",
            cwd=tmp_path / "repo",
            context_packet={"child_id": "A"},
            prompt_file=tmp_path / "prompt.md",
            output_tag="result",
            schema_id="smda.role-result.v1",
            sandbox_provider="noSandbox",
            agent_provider="codex",
            agent_model="gpt-5",
        )
    )

    assert outcome.status == "structured_output_failed"
    assert outcome.error_message == "No valid output block"
    assert outcome.schema_id == "smda.review-result.v1"
    assert outcome.schema_package_version == "0.1.0"
    assert outcome.preserved_worktree_path == "/tmp/worktree"
    assert runner.calls[0]["input"]["prompt_file"] == str(tmp_path / "prompt.md")
    assert "prompt" not in runner.calls[0]["input"]


def test_sandcastle_execution_adapter_maps_protocol_failure(tmp_path: Path):
    runner = RecordingRunner(
        ProcessResult(
            returncode=1,
            stdout="",
            stderr=json.dumps(
                {
                    "status": "agent_protocol_failed",
                    "schema_id": "smda.unknown-result.v1",
                    "schema_package_version": "0.1.0",
                    "error_message": "Invalid JSON IPC request",
                }
            ),
        )
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        runner=runner,
    )

    outcome = adapter.run_role_attempt(
        RoleAttemptRequest(
            attempt_id="attempt-1",
            role="implementer",
            phase=ChildPhase.IMPLEMENTING,
            branch="smda/child-A",
            cwd=tmp_path / "repo",
            context_packet={"child_id": "A"},
            prompt="Implement child A",
            output_tag="result",
            schema_id="smda.role-result.v1",
            sandbox_provider="noSandbox",
            agent_provider="codex",
            agent_model="gpt-5",
        )
    )

    assert outcome.status == "agent_protocol_failed"
    assert outcome.error_message == "Invalid JSON IPC request"
    assert outcome.schema_id == "smda.unknown-result.v1"
    assert outcome.schema_package_version == "0.1.0"
