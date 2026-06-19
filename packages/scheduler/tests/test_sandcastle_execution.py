import json
from pathlib import Path

from smda_scheduler.sandcastle_execution import (
    ProcessResult,
    RoleAttemptRequest,
    SandcastleExecutionAdapter,
)
from smda_scheduler.workflow import ChildPhase, ParentPhase, RoleResult


class RecordingRunner:
    def __init__(
        self,
        result: ProcessResult,
        artifact_payload: dict | None = None,
        artifact_text: str | None = None,
    ):
        self.result = result
        self.artifact_payload = artifact_payload
        self.artifact_text = artifact_text
        self.calls = []

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        input_text: str,
        cwd: Path,
        timeout_seconds: float,
    ) -> ProcessResult:
        result_file_path = _result_file_path(command)
        self.calls.append(
            {
                "command": command,
                "input": json.loads(input_text),
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "result_file_path": result_file_path,
            }
        )
        if self.artifact_payload is not None or self.artifact_text is not None:
            assert result_file_path is not None
            result_file_path.parent.mkdir(parents=True, exist_ok=True)
            result_file_path.write_text(
                self.artifact_text
                if self.artifact_text is not None
                else json.dumps(self.artifact_payload),
                encoding="utf-8",
            )
        return self.result


def _result_file_path(command: tuple[str, ...]) -> Path | None:
    if "--result-file" not in command:
        return None
    index = command.index("--result-file")
    return Path(command[index + 1])


def test_sandcastle_execution_adapter_maps_successful_result_artifact(tmp_path: Path):
    runner = RecordingRunner(
        ProcessResult(
            returncode=0,
            stdout="npm warn this process log is not control data\n",
            stderr="",
        ),
        artifact_payload={
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
        },
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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
        agent_model="gpt-5.5",
        agent_effort="high",
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
    result_file_path = tmp_path / "artifacts" / "attempts" / "attempt-1" / "result.json"
    assert runner.calls == [
        {
            "command": ("node", "runner.js", "--result-file", str(result_file_path)),
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
                "agent": {
                    "provider": "codex",
                    "model": "gpt-5.5",
                    "effort": "high",
                },
            },
            "cwd": tmp_path,
            "timeout_seconds": 60.0,
            "result_file_path": result_file_path,
        }
    ]


def test_sandcastle_execution_adapter_ignores_stdout_json_when_artifact_exists(
    tmp_path: Path,
):
    runner = RecordingRunner(
        ProcessResult(
            returncode=0,
            stdout=(
                '{"status":"succeeded","result":{"verdict":"WRONG",'
                '"required_next_action":"wrong"}}'
                + "\n"
            ),
            stderr="",
        ),
        artifact_payload={
            "status": "succeeded",
            "attempt_id": "attempt-1",
            "schema_id": "smda.child-implementer-result.v1",
            "schema_package_version": "0.1.0",
            "result": {
                "verdict": "DONE",
                "required_next_action": "submit_for_spec_review",
            },
            "commits": [],
            "branch": "smda/child-A",
        },
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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
            schema_id="smda.child-implementer-result.v1",
            sandbox_provider="noSandbox",
            agent_provider="codex",
            agent_model="gpt-5",
        )
    )

    assert outcome.status == "succeeded"
    assert outcome.role_result == RoleResult(
        verdict="DONE",
        required_next_action="submit_for_spec_review",
    )


def test_sandcastle_execution_adapter_maps_protocol_failure_artifact(
    tmp_path: Path,
):
    runner = RecordingRunner(
        ProcessResult(
            returncode=1,
            stdout="",
            stderr="ExperimentalWarning: process log only\n",
        ),
        artifact_payload={
            "status": "agent_protocol_failed",
            "attempt_id": "attempt-1",
            "schema_id": "smda.unknown-result.v1",
            "schema_package_version": "0.1.0",
            "error_message": "Invalid JSON IPC request",
        },
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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


def test_sandcastle_execution_adapter_reports_missing_result_artifact(
    tmp_path: Path,
):
    runner = RecordingRunner(
        ProcessResult(
            returncode=1,
            stdout="",
            stderr="tsx failed before loading the runner\nSyntaxError: boom\n",
        )
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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

    assert outcome.status == "execution_failed"
    assert outcome.error_message is not None
    assert "Missing Attempt Result Artifact" in outcome.error_message
    assert "stderr: tsx failed before loading the runner" in outcome.error_message
    assert "SyntaxError: boom" in outcome.error_message


def test_sandcastle_execution_adapter_reports_invalid_result_artifact(
    tmp_path: Path,
):
    runner = RecordingRunner(
        ProcessResult(
            returncode=0,
            stdout="ordinary log\n",
            stderr="",
        ),
        artifact_text="{not json",
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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

    assert outcome.status == "execution_failed"
    assert outcome.error_message is not None
    assert "Invalid Attempt Result Artifact" in outcome.error_message
    assert "stdout: ordinary log" in outcome.error_message


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
            stdout="",
            stderr="",
        ),
        artifact_payload={
            "status": "succeeded",
            "attempt_id": "attempt-1",
            "schema_id": "smda.graph-decomposer-result.v1",
            "schema_package_version": "0.1.0",
            "result": graph_result,
            "commits": [],
            "branch": "smda/danny-66/graph-decomposing",
        },
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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
            stdout="",
            stderr="",
        ),
        artifact_payload={
            "status": "structured_output_failed",
            "attempt_id": "attempt-1",
            "schema_id": "smda.review-result.v1",
            "schema_package_version": "0.1.0",
            "error_message": "No valid output block",
            "preserved_worktree_path": "/tmp/worktree",
        },
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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
            stderr="",
        ),
        artifact_payload={
            "status": "agent_protocol_failed",
            "schema_id": "smda.unknown-result.v1",
            "schema_package_version": "0.1.0",
            "error_message": "Invalid JSON IPC request",
        },
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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


def test_sandcastle_execution_adapter_marks_env_errors_non_transient(tmp_path: Path):
    runner = RecordingRunner(
        ProcessResult(
            returncode=1,
            stdout="",
            stderr="",
        ),
        artifact_payload={
            "status": "execution_failed",
            "attempt_id": "attempt-1",
            "error_message": "Error: permission denied while creating worktree",
        },
    )
    adapter = SandcastleExecutionAdapter(
        command=("node", "runner.js"),
        process_cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
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
            prompt_file=tmp_path / "prompt.md",
            output_tag="result",
            schema_id="smda.child-implementer-result.v1",
            sandbox_provider="noSandbox",
            agent_provider="codex",
            agent_model="gpt-5",
        )
    )

    assert outcome.status == "execution_failed"
    assert outcome.error_message.startswith("non_transient:")
    assert "permission denied" in outcome.error_message
