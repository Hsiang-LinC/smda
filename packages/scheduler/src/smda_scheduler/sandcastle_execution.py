from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smda_scheduler.scheduling import AttemptOutcome
from smda_scheduler.workflow import ChildPhase, RoleResult


@dataclass(frozen=True)
class RoleAttemptRequest:
    attempt_id: str
    role: str
    phase: ChildPhase
    branch: str
    cwd: Path
    context_packet: dict[str, Any]
    output_tag: str
    schema_id: str
    sandbox_provider: str
    agent_provider: str
    agent_model: str
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
        runner: Callable[..., ProcessResult] | None = None,
        timeout_seconds: float = 900.0,
    ) -> None:
        self._command = command
        self._process_cwd = process_cwd
        self._runner = runner or _run_process
        self._timeout_seconds = timeout_seconds

    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome:
        process = self._runner(
            self._command,
            input_text=json.dumps(request.to_ipc_payload()),
            cwd=self._process_cwd,
            timeout_seconds=self._timeout_seconds,
        )
        return _map_process_result(process)


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


def _map_process_result(process: ProcessResult) -> AttemptOutcome:
    raw = process.stdout.strip() or process.stderr.strip()
    if not raw:
        return AttemptOutcome(
            status="execution_failed",
            error_message=f"Sandcastle runner exited {process.returncode} with no output",
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        return AttemptOutcome(
            status="execution_failed",
            error_message=f"Invalid Sandcastle IPC JSON: {error}",
        )

    status = payload.get("status")
    if status == "succeeded":
        result = payload.get("result") or {}
        return AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict=str(result.get("verdict", "")),
                required_next_action=str(result.get("required_next_action", "")),
            ),
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
        )

    if status == "execution_failed":
        return AttemptOutcome(
            status="execution_failed",
            error_message=str(payload.get("error_message", "")),
        )

    if status == "agent_protocol_failed":
        return AttemptOutcome(
            status="execution_failed",
            error_message=str(payload.get("error_message", "")),
        )

    return AttemptOutcome(
        status="execution_failed",
        error_message=f"Unknown Sandcastle IPC status: {status}",
    )
