from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from smda_scheduler.parent_acceptance import ChildAcceptOperation


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


GitRunner = Callable[[Path, tuple[str, ...]], GitResult]


class GitIntegrationError(RuntimeError):
    """Raised when parent integration git operations fail."""


class GitParentIntegration:
    def __init__(
        self,
        repo_root: Path,
        *,
        runner: GitRunner | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._runner = runner or _run_git

    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool:
        result = self._runner(
            self._repo_root,
            (
                "merge-base",
                "--is-ancestor",
                operation.candidate_ref,
                operation.integration_branch,
            ),
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        raise GitIntegrationError(result.stderr.strip() or result.stdout.strip())

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None:
        self._git("switch", operation.integration_branch)
        self._git("cherry-pick", operation.candidate_ref)

    def _git(self, *args: str) -> GitResult:
        result = self._runner(self._repo_root, tuple(args))
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise GitIntegrationError(message)
        return result


def _run_git(repo_root: Path, args: tuple[str, ...]) -> GitResult:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return GitResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
