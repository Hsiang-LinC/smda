"""Phase 4 end-to-end: real-git landing + the conflict state machine across ticks.

These exercise ADR-0003 integrated, not just per-unit:
  - a standalone parent lands to main (real git);
  - a 3-tier roadmap lands members onto the roadmap branch and then the roadmap
    branch to main, once (real git);
  - the probe -> rebase -> re-review -> re-land loop drives the real phase
    transitions across multiple ticks (controllable integration).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.git_integration import ConflictProbeResult, GitParentIntegration
from smda_scheduler.parent_acceptance import ParentLandOperation
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.runtime import (
    run_landing_conflict_rebase_tick,
    run_parent_final_accept_tick,
    run_roadmap_completion_tick,
)
from smda_scheduler.workflow import ParentPhase, QaBounds, RoadmapPhase


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "smda@example.com")
    git(repo, "config", "user.name", "SMDA Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    git(repo, "branch", "-M", "main")
    return repo


def _branch_with_file(repo: Path, branch: str, *, filename: str, content: str) -> str:
    git(repo, "switch", "-c", branch, "main")
    (repo / filename).write_text(content, encoding="utf-8")
    git(repo, "add", filename)
    git(repo, "commit", "-m", f"{branch} change")
    ref = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "main")
    return ref


def _seed_parent(ledger: PhaseLedger, parent_id: str, phase: str) -> None:
    ledger.create_parent_run(
        parent_id=parent_id,
        initial_phase=phase,
        spec_path="docs/spec.md",
        spec_checksum="sha256:spec",
        approval_evidence=f"{parent_id} approval",
    )


def _issue(parent_id: str, body: str = "Execution: smda\n") -> BacklogIssue:
    return BacklogIssue(id=parent_id, title=parent_id, state="In Progress", body=body)


def _phase_of(ledger: PhaseLedger, parent_id: str) -> str:
    return next(
        run["phase"]
        for run in ledger.load_parent_runs()
        if run["parent_id"] == parent_id
    )


def _head_file(repo: Path, branch: str, filename: str) -> str:
    return git(repo, "show", f"{branch}:{filename}").stdout


# --- E2E 1: standalone parent lands to main (real git) ----------------------


def test_e2e_standalone_parent_lands_to_main(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _branch_with_file(
        repo, "smda/DANNY-1/integration", filename="feature.txt", content="feature\n"
    )
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _seed_parent(ledger, "DANNY-1", ParentPhase.FINAL_ACCEPT_READY.value)
    integration = GitParentIntegration(repo)

    result = run_parent_final_accept_tick(
        issue=_issue("DANNY-1"),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-1/integration",
        standalone_base="main",
    )

    assert result.target_state == "Done"
    assert _phase_of(ledger, "DANNY-1") == ParentPhase.FINAL_ACCEPTED.value
    # main now carries the parent's landed work.
    assert _head_file(repo, "main", "feature.txt") == "feature\n"


# --- E2E 2: roadmap lands members in order then roadmap -> main once --------


def test_e2e_roadmap_members_then_roadmap_lands_to_main(tmp_path: Path):
    repo = _init_repo(tmp_path)
    # Two members, each editing a distinct file off main (no textual conflict).
    _branch_with_file(repo, "smda/M1/integration", filename="m1.txt", content="m1\n")
    _branch_with_file(repo, "smda/M2/integration", filename="m2.txt", content="m2\n")

    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _seed_parent(ledger, "R", RoadmapPhase.ROADMAP_PUBLISHED.value)
    ledger.record_roadmap_member_projection(roadmap_id="R", node_id="n1", issue_id="M1")
    ledger.record_roadmap_member_projection(roadmap_id="R", node_id="n2", issue_id="M2")
    _seed_parent(ledger, "M1", ParentPhase.FINAL_ACCEPT_READY.value)
    _seed_parent(ledger, "M2", ParentPhase.FINAL_ACCEPT_READY.value)
    integration = GitParentIntegration(repo)

    # Member 1 lands -> creates the roadmap branch off main and lands onto it.
    run_parent_final_accept_tick(
        issue=_issue("M1"),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/M1/integration",
        standalone_base="main",
    )
    assert integration.branch_exists("smda/R/integration")
    assert _head_file(repo, "smda/R/integration", "m1.txt") == "m1\n"

    # Member 2 lands onto the roadmap branch (builds on member 1's landed work).
    run_parent_final_accept_tick(
        issue=_issue("M2"),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/M2/integration",
        standalone_base="main",
    )
    assert _head_file(repo, "smda/R/integration", "m1.txt") == "m1\n"
    assert _head_file(repo, "smda/R/integration", "m2.txt") == "m2\n"
    # main is untouched until roadmap completion.
    assert _file_missing_on(repo, "main", "m1.txt")

    # Both members accepted -> roadmap completion lands roadmap -> main once.
    first = run_roadmap_completion_tick(
        issue=_issue("R", body="Execution: smda-roadmap\n"),
        ledger=ledger,
        integration=integration,
        standalone_base="main",
    )
    assert first.target_state == "Done"
    assert _head_file(repo, "main", "m1.txt") == "m1\n"
    assert _head_file(repo, "main", "m2.txt") == "m2\n"
    assert integration.branch_exists("smda/R/integration") is False
    assert _phase_of(ledger, "R") == RoadmapPhase.ROADMAP_COMPLETED.value

    # Idempotent: a second completion tick is a no-op (already terminal).
    second = run_roadmap_completion_tick(
        issue=_issue("R", body="Execution: smda-roadmap\n"),
        ledger=ledger,
        integration=integration,
        standalone_base="main",
    )
    assert _phase_of(ledger, "R") == RoadmapPhase.ROADMAP_COMPLETED.value
    assert second.target_state == "In Progress"  # skipped, not re-landed


def _file_missing_on(repo: Path, branch: str, filename: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{branch}:{filename}"],
        cwd=repo,
        capture_output=True,
    )
    return result.returncode != 0


# --- E2E 3: conflict -> rebase -> re-review -> re-land, across ticks --------


@dataclass
class TogglingIntegration:
    """Parent land integration whose probe conflicts until a rebase clears it."""

    conflicted: bool = True
    landed: list[ParentLandOperation] = field(default_factory=list)
    rebased: list[tuple[str, str]] = field(default_factory=list)

    def has_landed_parent_ref(self, operation: ParentLandOperation) -> bool:
        return False

    def land_parent_to_base(self, operation: ParentLandOperation) -> None:
        self.landed.append(operation)

    def probe_conflict(self, *, head: str, base: str) -> ConflictProbeResult:
        if self.conflicted:
            return ConflictProbeResult(clean=False, conflicted_paths=("shared.txt",))
        return ConflictProbeResult(clean=True)

    def rebase_onto_base(self, *, head: str, base: str) -> None:
        self.rebased.append((head, base))
        self.conflicted = False  # rebase resolves the textual conflict

    def ensure_branch(self, name: str, *, start_point: str) -> None:
        return None

    def branch_exists(self, name: str) -> bool:
        return False

    def delete_branch(self, name: str) -> None:
        return None


def test_e2e_conflict_loser_rebases_then_lands(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    _seed_parent(ledger, "DANNY-2", ParentPhase.FINAL_ACCEPT_READY.value)
    integration = TogglingIntegration()
    bounds = QaBounds(
        max_same_feedback_fingerprint=3,
        max_total_remediation_children=3,
        max_parent_qa_cycles=3,
    )

    # Tick 1: final accept -> probe conflicts -> routed to rebasing, no land.
    run_parent_final_accept_tick(
        issue=_issue("DANNY-2"),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-2/integration",
        standalone_base="main",
    )
    assert integration.landed == []
    assert _phase_of(ledger, "DANNY-2") == ParentPhase.LANDING_CONFLICT_REBASING.value

    # Tick 2: rebase loser onto base, requeue for parent QA re-review.
    run_landing_conflict_rebase_tick(
        issue=_issue("DANNY-2"),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-2/integration",
        standalone_base="main",
        qa_bounds=bounds,
    )
    assert integration.rebased == [("smda/DANNY-2/integration", "main")]
    assert _phase_of(ledger, "DANNY-2") == ParentPhase.PARENT_QA_READY.value

    # Re-review passes (simulated): parent is back at FINAL_ACCEPT_READY.
    ledger.transition_parent(
        parent_id="DANNY-2",
        expected_phase=ParentPhase.PARENT_QA_READY.value,
        next_phase=ParentPhase.FINAL_ACCEPT_READY.value,
    )

    # Tick 3: final accept again -> probe now clean -> lands.
    result = run_parent_final_accept_tick(
        issue=_issue("DANNY-2"),
        ledger=ledger,
        integration=integration,
        integration_branch="smda/DANNY-2/integration",
        standalone_base="main",
    )
    assert result.target_state == "Done"
    assert [op.base_branch for op in integration.landed] == ["main"]
    assert _phase_of(ledger, "DANNY-2") == ParentPhase.FINAL_ACCEPTED.value
