from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smda_scheduler.scheduling import AttemptOutcome
from smda_scheduler.workflow import ChildPhase, ParentPhase, RoleResult


AttemptPhase = ChildPhase | ParentPhase


@dataclass(frozen=True)
class RoleAttemptRequest:
    attempt_id: str
    role: str
    phase: AttemptPhase
    branch: str
    cwd: Path
    context_packet: dict[str, Any]
    output_tag: str
    schema_id: str
    sandbox_provider: str
    agent_provider: str
    agent_model: str
    agent_effort: str | None = None
    prompt: str | None = None
    prompt_file: Path | None = None

    def to_ipc_payload(self) -> dict[str, Any]:
        if (self.prompt is None) == (self.prompt_file is None):
            raise ValueError("Provide exactly one of prompt or prompt_file")

        payload: dict[str, Any] = {
            "attempt_id": self.attempt_id,
            "role": self.role,
            "phase": self.phase.value,
            "branch": self.branch,
            "cwd": str(self.cwd),
            "context_packet": self.context_packet,
            "output_tag": self.output_tag,
            "schema_id": self.schema_id,
            "sandbox_provider": self.sandbox_provider,
            "agent": {
                "provider": self.agent_provider,
                "model": self.agent_model,
            },
        }
        if self.agent_effort is not None:
            payload["agent"]["effort"] = self.agent_effort
        if self.prompt is not None:
            payload["prompt"] = self.prompt
        if self.prompt_file is not None:
            payload["prompt_file"] = str(self.prompt_file)
        return payload


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class SandcastleExecutionAdapter:
    def __init__(
        self,
        *,
        command: tuple[str, ...] = (
            "npx",
            "tsx",
            "packages/sandcastle-runner/src/cli.ts",
        ),
        process_cwd: Path,
        artifact_dir: Path | None = None,
        runner: Callable[..., ProcessResult] | None = None,
        timeout_seconds: float = 900.0,
    ) -> None:
        self._command = command
        self._process_cwd = process_cwd
        self._artifact_dir = artifact_dir or process_cwd / ".smda" / "artifacts"
        self._runner = runner or _run_process
        self._timeout_seconds = timeout_seconds

    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome:
        result_file = self._result_file_path(request.attempt_id)
        result_file.parent.mkdir(parents=True, exist_ok=True)
        if result_file.exists():
            result_file.unlink()
        process = self._runner(
            (*self._command, "--result-file", str(result_file)),
            input_text=json.dumps(request.to_ipc_payload()),
            cwd=self._process_cwd,
            timeout_seconds=self._timeout_seconds,
        )
        return _map_process_result(process, result_file)

    def _result_file_path(self, attempt_id: str) -> Path:
        return self._artifact_dir / "attempts" / attempt_id / "result.json"


def _run_process(
    command: tuple[str, ...],
    *,
    input_text: str,
    cwd: Path,
    timeout_seconds: float,
) -> ProcessResult:
    completed = subprocess.run(
        list(command),
        input=input_text,
        cwd=cwd,
        timeout=timeout_seconds,
        text=True,
        capture_output=True,
        check=False,
    )
    return ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


# Substrings that mark an execution failure as non-transient (a broken
# environment), so the scheduler escalates to human review immediately instead
# of burning the retry budget on an unfixable error.
_NON_TRANSIENT_ERROR_MARKERS = (
    "permission denied",
    "no such file or directory",
    "executable file not found",
    "command not found",
    "no such image",
    "image not found",
    "pull access denied",
    "manifest unknown",
    "cannot connect to the docker daemon",
    "no space left on device",
)


def _classify_execution_error(message: str) -> str:
    lowered = message.strip().lower()
    if lowered.startswith(("non_transient:", "non-transient:")):
        return message
    if any(marker in lowered for marker in _NON_TRANSIENT_ERROR_MARKERS):
        return f"non_transient: {message}"
    return message


def _map_process_result(process: ProcessResult, result_file: Path) -> AttemptOutcome:
    try:
        raw_artifact = result_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AttemptOutcome(
            status="execution_failed",
            error_message=(
                "Missing Attempt Result Artifact "
                f"(returncode {process.returncode}; {_stream_snippets(process)})"
            ),
        )

    try:
        payload = json.loads(raw_artifact)
    except json.JSONDecodeError as error:
        return AttemptOutcome(
            status="execution_failed",
            error_message=(
                f"Invalid Attempt Result Artifact: {error} "
                f"(returncode {process.returncode}; "
                f"{_artifact_snippet(raw_artifact)}; {_stream_snippets(process)})"
            ),
        )

    if not isinstance(payload, dict):
        return AttemptOutcome(
            status="execution_failed",
            error_message=(
                "Invalid Attempt Result Artifact: envelope must be an object "
                f"(returncode {process.returncode}; "
                f"{_artifact_snippet(raw_artifact)}; {_stream_snippets(process)})"
            ),
        )

    status = payload.get("status")
    if status == "succeeded":
        result = payload.get("result") or {}
        raw_result = result if isinstance(result, dict) else {}
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict=str(result.get("verdict", "")),
                required_next_action=str(result.get("required_next_action", "")),
            ),
            raw_result=raw_result,
            schema_id=payload.get("schema_id"),
            schema_package_version=payload.get("schema_package_version"),
            commits=tuple(
                commit["sha"]
                for commit in payload.get("commits", [])
                if isinstance(commit, dict) and isinstance(commit.get("sha"), str)
            ),
            branch=payload.get("branch"),
        )

    if status == "structured_output_failed":
        return AttemptOutcome(
            status="structured_output_failed",
            error_message=str(payload.get("error_message", "")),
            branch=payload.get("branch"),
            preserved_worktree_path=payload.get("preserved_worktree_path"),
            schema_id=payload.get("schema_id"),
            schema_package_version=payload.get("schema_package_version"),
        )

    if status == "execution_failed":
        return AttemptOutcome(
            status="execution_failed",
            error_message=_classify_execution_error(
                str(payload.get("error_message", ""))
            ),
            schema_id=payload.get("schema_id"),
            schema_package_version=payload.get("schema_package_version"),
        )

    if status == "agent_protocol_failed":
        return AttemptOutcome(
            status="agent_protocol_failed",
            error_message=str(payload.get("error_message", "")),
            schema_id=payload.get("schema_id"),
            schema_package_version=payload.get("schema_package_version"),
        )

    return AttemptOutcome(
        status="execution_failed",
        error_message=f"Unknown Sandcastle IPC status: {status}",
    )


def _stream_snippets(process: ProcessResult) -> str:
    return "; ".join(
        snippet
        for snippet in (
            _stream_snippet("stdout", process.stdout),
            _stream_snippet("stderr", process.stderr),
        )
        if snippet
    )


def _stream_snippet(name: str, value: str, *, limit: int = 240) -> str:
    text = " ".join(value.split())
    if not text:
        return ""
    if len(text) > limit:
        text = f"{text[:limit]}..."
    return f"{name}: {text}"


def _artifact_snippet(value: str, *, limit: int = 240) -> str:
    text = " ".join(value.split())
    if len(text) > limit:
        text = f"{text[:limit]}..."
    return f"artifact: {text}"
