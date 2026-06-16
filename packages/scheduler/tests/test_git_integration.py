import subprocess
from pathlib import Path
from types import SimpleNamespace

from smda_scheduler.git_integration import GitParentIntegration
from smda_scheduler.parent_acceptance import ChildAcceptOperation


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


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
