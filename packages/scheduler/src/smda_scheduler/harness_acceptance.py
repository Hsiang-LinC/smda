"""Project-owned acceptance policy and revision-bound local Git delivery.

No deployment or remote push. Verification commands are trusted operator policy,
not commands supplied by a worker result. Human gates require manual handoff.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


class AcceptanceError(ValueError):
    """Acceptance is unavailable, stale, failed, or requires a human."""


@dataclass(frozen=True)
class AcceptancePolicy:
    child_integration: str
    parent_merge: str
    merge_target: str
    verification_commands: tuple[tuple[str, ...], ...]
    human_review_paths: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> AcceptancePolicy:
        keys = {'child_integration', 'parent_merge', 'merge_target',
                'verification_commands', 'human_review_paths'}
        if not isinstance(value, dict) or set(value) != keys:
            raise AcceptanceError('acceptance requires exactly ' + ', '.join(sorted(keys)))
        if value['child_integration'] != 'agent':
            raise AcceptanceError('Human child integration is unsupported; use manual execution')
        if value['parent_merge'] not in ('agent', 'human'):
            raise AcceptanceError('parent_merge must be agent or human')
        target = value['merge_target']
        if not isinstance(target, str) or not target or target.startswith('-'):
            raise AcceptanceError('merge_target must name a local branch')
        commands = value['verification_commands']
        if not isinstance(commands, list) or not commands or any(
            not isinstance(cmd, list) or not cmd or any(
                not isinstance(arg, str) or not arg or '\x00' in arg for arg in cmd
            ) for cmd in commands
        ):
            raise AcceptanceError('verification_commands must contain nonempty argv lists')
        paths = value['human_review_paths']
        if not isinstance(paths, list) or any(
            not isinstance(p, str) or not p or p.startswith('/') or '..' in p.split('/')
            for p in paths
        ):
            raise AcceptanceError('human_review_paths must contain repo-relative patterns')
        return cls(value['child_integration'], value['parent_merge'], target,
                   tuple(tuple(cmd) for cmd in commands), tuple(paths))

    def checksum(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def _git(root: Path, *args: str, strip: bool = True) -> str:
    try:
        result = subprocess.run(['git', '-C', str(root), *args], text=True,
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AcceptanceError(f"Git operation failed: {error}") from error
    if result.returncode:
        raise AcceptanceError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip() if strip else result.stdout


def snapshot_candidate(root: Path, branch: str, policy: AcceptancePolicy) -> dict[str, str]:
    if policy.parent_merge != 'agent':
        raise AcceptanceError('Parent merge requires human acceptance')
    _git(root, 'check-ref-format', '--branch', policy.merge_target)
    candidate = _git(root, 'rev-parse', '--verify', f'{branch}^{{commit}}')
    base = _git(root, 'rev-parse', '--verify', f'refs/heads/{policy.merge_target}^{{commit}}')
    # Require QA of a fast-forward candidate; no unreviewed merge commit is created.
    _git(root, 'merge-base', '--is-ancestor', base, candidate)
    changed = _git(root, 'diff', '--no-renames', '--name-only', '-z', base, candidate).split('\x00')
    protected = [p for p in changed if p and any(fnmatchcase(p, pat) for pat in policy.human_review_paths)]
    if protected:
        raise AcceptanceError('Changed paths require human acceptance: ' + ', '.join(protected))
    return {'branch': branch, 'candidate': candidate, 'base': base,
            'target': policy.merge_target, 'policy': policy.checksum()}


def verify_candidate(root: Path, snapshot: dict[str, str], policy: AcceptancePolicy) -> dict:
    if snapshot_candidate(root, snapshot['branch'], policy) != snapshot:
        raise AcceptanceError('Candidate/base/policy changed before verification')
    with tempfile.TemporaryDirectory(prefix='smda-verify-') as directory:
        worktree = Path(directory) / 'tree'
        _git(root, 'worktree', 'add', '--detach', str(worktree), snapshot['candidate'])
        try:
            evidence = []
            for command in policy.verification_commands:
                try:
                    result = subprocess.run(command, cwd=worktree, text=True,
                                            capture_output=True, timeout=300)
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise AcceptanceError(f'Verification failed: {command}: {error}') from error
                if result.returncode:
                    raise AcceptanceError(f'Verification failed: {command}: {result.stderr[-4000:]} {result.stdout[-4000:]}')
                evidence.append({'argv': list(command), 'exit_code': 0,
                                 'stdout': result.stdout[-4000:], 'stderr': result.stderr[-4000:]})
            # Commands may create ignored build outputs, but cannot change reviewed code.
            if _git(worktree, 'rev-parse', 'HEAD') != snapshot['candidate'] or _git(worktree, 'status', '--porcelain', '--untracked-files=no'):
                raise AcceptanceError('Verification changed tracked candidate content')
            return {'snapshot': snapshot, 'checks': evidence}
        finally:
            _git(root, 'worktree', 'remove', '--force', str(worktree))


def land_candidate(root: Path, snapshot: dict[str, str], evidence: dict,
                   policy: AcceptancePolicy) -> None:
    if policy.parent_merge != 'agent' or policy.checksum() != snapshot['policy']:
        raise AcceptanceError('Acceptance policy changed or requires human acceptance')
    if evidence.get('snapshot') != snapshot:
        raise AcceptanceError('Verification evidence does not match reviewed revision')
    checks = evidence.get('checks', [])
    if len(checks) != len(policy.verification_commands) or any(
        check.get('argv') != list(command) or check.get('exit_code') != 0
        for check, command in zip(checks, policy.verification_commands)
    ):
        raise AcceptanceError('Required verification evidence is missing')
    if _git(root, 'rev-parse', '--verify', f"{snapshot['branch']}^{{commit}}") != snapshot['candidate']:
        raise AcceptanceError('Reviewed candidate changed')
    current_base = _git(root, 'rev-parse', '--verify', f"refs/heads/{snapshot['target']}")
    if current_base == snapshot['candidate']:
        return  # Recovery after an atomic update completed but ledger write did not.
    if current_base != snapshot['base']:
        raise AcceptanceError('Target base changed; rebase and repeat QA')
    if snapshot_candidate(root, snapshot['branch'], policy) != snapshot:
        raise AcceptanceError('Candidate/base/policy changed after QA')
    # Updating a checked-out branch would leave its index/worktree inconsistent.
    if f"branch refs/heads/{snapshot['target']}" in _git(root, 'worktree', 'list', '--porcelain').splitlines():
        raise AcceptanceError('Merge target is checked out; switch that worktree before delivery')
    _git(root, 'update-ref', f"refs/heads/{snapshot['target']}", snapshot['candidate'], snapshot['base'])


def run_candidate_review(root, snapshot, request, execution):
    """Start the reviewer from the reviewed commit, not the operator checkout."""
    from dataclasses import replace
    with tempfile.TemporaryDirectory(prefix="smda-review-") as directory:
        worktree = Path(directory) / "tree"
        _git(root, "worktree", "add", "--detach", str(worktree), snapshot["candidate"])
        try:
            # Sandcastle reuses existing named branches. Create this attempt's
            # fresh branch at the snapshot; an existing name fails closed.
            _git(root, "branch", request.branch, snapshot["candidate"])
            outcome = execution.run_role_attempt(replace(request, cwd=worktree))
            if _git(root, "rev-parse", request.branch) != snapshot["candidate"]:
                raise AcceptanceError("QA reviewer changed its review branch")
            if _git(worktree, "status", "--porcelain", "--untracked-files=no"):
                raise AcceptanceError("QA reviewer changed reviewed content")
            return outcome
        finally:
            _git(root, "worktree", "remove", "--force", str(worktree))


def check_candidate_source(root: Path, candidate: str, path: str, checksum: str) -> None:
    content = _git(root, "show", f"{candidate}:{path}", strip=False)
    actual = hashlib.sha256(content.encode()).hexdigest()
    if actual != checksum.removeprefix("sha256:"):
        raise AcceptanceError(f"Candidate changes approved source/policy: {path}")


def require_ancestor(root: Path, ancestor: str, branch: str) -> None:
    """An aggregate candidate must contain every accepted member revision."""
    _git(root, "merge-base", "--is-ancestor", ancestor, branch)
