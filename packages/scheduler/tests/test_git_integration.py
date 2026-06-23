import subprocess
from pathlib import Path
from types import SimpleNamespace

from smda_scheduler.git_integration import (
    ConflictProbeResult,
    GitParentIntegration,
)
from smda_scheduler.parent_acceptance import ChildAcceptConflictError, ChildAcceptOperation


def test_git_parent_integration_applies_candidate_to_integration_branch(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    git(repo, "switch", "-c", "smda/DANNY-66/integration")
    git(repo, "switch", "-c", "candidate")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "candidate")
    candidate_ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "smda/DANNY-66/integration")
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key=f"parent:DANNY-66:child-001:{candidate_ref}",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref=candidate_ref,
        integration_branch="smda/DANNY-66/integration",
    )
    integration = GitParentIntegration(repo)

    assert integration.has_accepted_child_ref(operation) is False

    integration.apply_child_candidate(operation)

    assert integration.has_accepted_child_ref(operation) is True
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "feature\n"


def test_git_parent_integration_reports_child_accept_conflicted_paths(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "shared.txt")
    git(repo, "commit", "-m", "base")
    git(repo, "switch", "-c", "smda/DANNY-66/integration")
    (repo / "shared.txt").write_text("integration\n", encoding="utf-8")
    git(repo, "commit", "-am", "integration")
    git(repo, "switch", "master")
    git(repo, "switch", "-c", "candidate")
    (repo / "shared.txt").write_text("candidate\n", encoding="utf-8")
    git(repo, "commit", "-am", "candidate")
    candidate_ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key=f"parent:DANNY-66:child-001:{candidate_ref}",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref=candidate_ref,
        integration_branch="smda/DANNY-66/integration",
    )

    try:
        GitParentIntegration(repo).apply_child_candidate(operation)
    except ChildAcceptConflictError as error:
        assert error.conflicted_paths == ("shared.txt",)
    else:
        raise AssertionError("expected child accept conflict")


def test_git_parent_integration_merges_diverged_child_candidate(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    git(repo, "switch", "-c", "smda/DANNY-66/integration")
    (repo / "integration.txt").write_text("integration\n", encoding="utf-8")
    git(repo, "add", "integration.txt")
    git(repo, "commit", "-m", "integration")
    git(repo, "switch", "master")
    git(repo, "switch", "-c", "candidate")
    (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    git(repo, "add", "candidate.txt")
    git(repo, "commit", "-m", "candidate")
    candidate_ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key=f"parent:DANNY-66:child-001:{candidate_ref}",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref=candidate_ref,
        integration_branch="smda/DANNY-66/integration",
    )
    integration = GitParentIntegration(repo)

    integration.apply_child_candidate(operation)

    assert integration.has_accepted_child_ref(operation) is True
    assert (repo / "candidate.txt").read_text(encoding="utf-8") == "candidate\n"


def test_git_parent_integration_detects_existing_candidate(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    candidate_ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "-c", "smda/DANNY-66/integration")
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key=f"parent:DANNY-66:child-001:{candidate_ref}",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref=candidate_ref,
        integration_branch="smda/DANNY-66/integration",
    )

    assert GitParentIntegration(repo).has_accepted_child_ref(operation) is True


def test_git_parent_integration_fast_forwards_parent_integration_to_base(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    git(repo, "branch", "main")
    git(repo, "switch", "-c", "smda/DANNY-66/integration")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "parent integration")
    parent_ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "main")
    operation = SimpleNamespace(
        operation_id="land-1",
        idempotency_key=f"parent:DANNY-66:land:{parent_ref}:main",
        parent_id="DANNY-66",
        parent_ref=parent_ref,
        base_branch="main",
    )
    integration = GitParentIntegration(repo)

    assert integration.has_landed_parent_ref(operation) is False

    integration.land_parent_to_base(operation)

    assert integration.has_landed_parent_ref(operation) is True
    assert git(repo, "rev-parse", "main").stdout.strip() == parent_ref
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "feature\n"


def test_git_parent_integration_merges_parent_integration_when_base_diverged(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    git(repo, "branch", "main")
    git(repo, "switch", "-c", "smda/DANNY-66/integration")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "parent integration")
    parent_ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "main")
    (repo / "base-only.txt").write_text("base only\n", encoding="utf-8")
    git(repo, "add", "base-only.txt")
    git(repo, "commit", "-m", "base advanced")
    operation = SimpleNamespace(
        operation_id="land-1",
        idempotency_key=f"parent:DANNY-66:land:{parent_ref}:main",
        parent_id="DANNY-66",
        parent_ref=parent_ref,
        base_branch="main",
    )

    GitParentIntegration(repo).land_parent_to_base(operation)

    assert GitParentIntegration(repo).has_landed_parent_ref(operation) is True
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "feature\n"
    assert (repo / "base-only.txt").read_text(encoding="utf-8") == "base only\n"


def test_git_parent_integration_parent_land_is_idempotent(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    git(repo, "branch", "main")
    git(repo, "switch", "-c", "smda/DANNY-66/integration")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "parent integration")
    parent_ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    operation = SimpleNamespace(
        operation_id="land-1",
        idempotency_key=f"parent:DANNY-66:land:{parent_ref}:main",
        parent_id="DANNY-66",
        parent_ref=parent_ref,
        base_branch="main",
    )
    integration = GitParentIntegration(repo)

    integration.land_parent_to_base(operation)
    landed_ref = git(repo, "rev-parse", "main").stdout.strip()
    integration.land_parent_to_base(operation)

    assert integration.has_landed_parent_ref(operation) is True
    assert git(repo, "rev-parse", "main").stdout.strip() == landed_ref


def _probe_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "shared.txt")
    git(repo, "commit", "-m", "base")
    git(repo, "branch", "-M", "main")
    return repo


def test_probe_conflict_reports_clean_for_disjoint_changes(tmp_path: Path):
    repo = _probe_repo(tmp_path)
    git(repo, "switch", "-c", "parent-integration")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "feature")
    git(repo, "switch", "main")

    integration = GitParentIntegration(repo)
    result = integration.probe_conflict(head="parent-integration", base="main")

    assert result == ConflictProbeResult(clean=True)


def test_probe_conflict_reports_conflicted_paths(tmp_path: Path):
    repo = _probe_repo(tmp_path)
    # main edits shared.txt one way...
    (repo / "shared.txt").write_text("main change\n", encoding="utf-8")
    git(repo, "add", "shared.txt")
    git(repo, "commit", "-m", "main edit")
    # ...parent-integration edits the same line the other way (off the base).
    git(repo, "switch", "-c", "parent-integration", "HEAD~1")
    (repo / "shared.txt").write_text("parent change\n", encoding="utf-8")
    git(repo, "add", "shared.txt")
    git(repo, "commit", "-m", "parent edit")
    git(repo, "switch", "main")

    integration = GitParentIntegration(repo)
    result = integration.probe_conflict(head="parent-integration", base="main")

    assert result.clean is False
    assert "shared.txt" in result.conflicted_paths


def test_ensure_branch_creates_absent_branch_off_start_point(tmp_path: Path):
    repo = _probe_repo(tmp_path)
    integration = GitParentIntegration(repo)

    assert integration.branch_exists("smda/DANNY-100/integration") is False
    integration.ensure_branch("smda/DANNY-100/integration", start_point="main")
    assert integration.branch_exists("smda/DANNY-100/integration") is True

    # Idempotent: a second ensure on an existing branch is a no-op.
    integration.ensure_branch("smda/DANNY-100/integration", start_point="main")
    assert integration.branch_exists("smda/DANNY-100/integration") is True


def test_delete_branch_removes_branch(tmp_path: Path):
    repo = _probe_repo(tmp_path)
    integration = GitParentIntegration(repo)
    integration.ensure_branch("smda/DANNY-100/integration", start_point="main")

    integration.delete_branch("smda/DANNY-100/integration")

    assert integration.branch_exists("smda/DANNY-100/integration") is False
    # Idempotent: deleting an absent branch is a no-op.
    integration.delete_branch("smda/DANNY-100/integration")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
