from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from smda_scheduler.parent_acceptance import (
    ChildAcceptConflictError,
    ChildAcceptOperation,
)


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


GitRunner = Callable[[Path, tuple[str, ...]], GitResult]


class GitIntegrationError(RuntimeError):
    """Raised when parent integration git operations fail."""


@dataclass(frozen=True)
class ConflictProbeResult:
    clean: bool
    conflicted_paths: tuple[str, ...] = ()


class ParentLandLike(Protocol):
    parent_ref: str
    base_branch: str


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
        fast_forward = self._runner(
            self._repo_root,
            ("merge", "--ff-only", operation.candidate_ref),
        )
        if fast_forward.returncode == 0:
            return
        try:
            self._git("merge", "--no-edit", operation.candidate_ref)
        except GitIntegrationError as error:
            conflicted_paths = self._conflicted_paths()
            if conflicted_paths:
                raise ChildAcceptConflictError(
                    str(error), conflicted_paths=conflicted_paths
                ) from error
            raise

    def has_landed_parent_ref(self, operation: ParentLandLike) -> bool:
        result = self._runner(
            self._repo_root,
            (
                "merge-base",
                "--is-ancestor",
                operation.parent_ref,
                operation.base_branch,
            ),
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        raise GitIntegrationError(result.stderr.strip() or result.stdout.strip())

    def land_parent_to_base(self, operation: ParentLandLike) -> None:
        if self.has_landed_parent_ref(operation):
            return

        self._git("switch", operation.base_branch)
        fast_forward = self._runner(
            self._repo_root,
            ("merge", "--ff-only", operation.parent_ref),
        )
        if fast_forward.returncode == 0:
            return
        self._git("merge", "--no-edit", operation.parent_ref)

    def branch_exists(self, name: str) -> bool:
        result = self._runner(
            self._repo_root,
            ("rev-parse", "--verify", "--quiet", f"refs/heads/{name}"),
        )
        return result.returncode == 0

    def ensure_branch(self, name: str, *, start_point: str) -> None:
        """Create ``name`` off ``start_point`` if absent (idempotent)."""
        if self.branch_exists(name):
            return
        self._git("branch", name, start_point)

    def delete_branch(self, name: str) -> None:
        """Delete ``name`` if present (idempotent)."""
        if not self.branch_exists(name):
            return
        self._git("branch", "-D", name)

    def rebase_onto_base(self, *, head: str, base: str) -> None:
        """Rebase the loser head onto the winner's landed base (ADR-0003).

        Idempotent: a head already based on `base` rebases to a no-op.
        """
        self._git("switch", head)
        self._git("rebase", base)

    def probe_conflict(self, *, head: str, base: str) -> ConflictProbeResult:
        """Read-only `merge-tree --write-tree` probe of head against base.

        Returns clean when the trees merge; otherwise reports the conflicted
        paths. Mutates no branch (ADR-0003). `merge-tree --write-tree` needs
        git >= 2.38.
        """
        result = self._runner(
            self._repo_root,
            ("merge-tree", "--write-tree", "--name-only", base, head),
        )
        if result.returncode == 0:
            return ConflictProbeResult(clean=True)
        if result.returncode == 1:
            # stdout = "<tree-oid>\n<path>\n...\n\n<informational messages>".
            # Conflicted paths are the lines after the tree oid up to the blank.
            paths: list[str] = []
            for line in result.stdout.splitlines()[1:]:
                if not line.strip():
                    break
                paths.append(line.strip())
            return ConflictProbeResult(clean=False, conflicted_paths=tuple(paths))
        raise GitIntegrationError(result.stderr.strip() or result.stdout.strip())

    def _git(self, *args: str) -> GitResult:
        result = self._runner(self._repo_root, tuple(args))
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise GitIntegrationError(message)
        return result

    def _conflicted_paths(self) -> tuple[str, ...]:
        result = self._runner(
            self._repo_root,
            ("diff", "--name-only", "--diff-filter=U"),
        )
        if result.returncode != 0:
            return ()
        return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


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
