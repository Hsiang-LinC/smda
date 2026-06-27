from pathlib import Path

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.local_ledger_backlog import LocalLedgerBacklogAdapter


def test_local_ledger_descriptor_declares_supported_capabilities(tmp_path: Path):
    adapter = LocalLedgerBacklogAdapter(root=tmp_path)

    descriptor = adapter.descriptor()

    assert descriptor.id == "local-ledger"
    assert descriptor.capabilities >= frozenset(
        {
            "create_child",
            "coarse_states",
            "comments",
            "hierarchy",
            "blocking_relations",
        }
    )


def test_local_ledger_maps_entry_to_backlog_issue_and_synthesizes_body(
    tmp_path: Path,
):
    ledger = tmp_path / "docs" / "work-ledger" / "active.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        """# Active Work

## parent-1
- status: planned
- title: Parent Spec
- execution: smda-task
- labels: enhancement, ready-for-agent
- acceptance: does the thing
- verify: pytest
- next: implement it
- updated: 2026-06-27
""",
        encoding="utf-8",
    )

    issue = LocalLedgerBacklogAdapter(root=tmp_path).fetch_issue("parent-1")

    assert issue == BacklogIssue(
        id="parent-1",
        title="Parent Spec",
        state="Todo",
        body=(
            "Execution: smda-task\n"
            "Acceptance criteria: does the thing\n"
            "Verification: pytest\n\n"
            "- status: planned\n"
            "- title: Parent Spec\n"
            "- execution: smda-task\n"
            "- labels: enhancement, ready-for-agent\n"
            "- acceptance: does the thing\n"
            "- verify: pytest\n"
            "- next: implement it\n"
            "- updated: 2026-06-27"
        ),
        labels=frozenset({"enhancement", "ready-for-agent"}),
    )


def test_local_ledger_lists_matching_state_without_requiring_label(
    tmp_path: Path,
):
    ledger = tmp_path / "docs" / "work-ledger" / "active.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        """# Active Work

## parent-1
- status: planned
- execution: smda
- acceptance: done
- verify: pytest

## parent-2
- status: blocked
- execution: smda
- labels: agent
- acceptance: done
- verify: pytest
""",
        encoding="utf-8",
    )

    page = LocalLedgerBacklogAdapter(root=tmp_path).list_issues(
        state="Todo",
        label="agent",
        parent_id=None,
        limit=50,
        cursor=None,
    )

    assert [issue.id for issue in page.issues] == ["parent-1"]


def test_local_ledger_writes_state_comment_child_and_blocking_link(
    tmp_path: Path,
):
    ledger = tmp_path / "docs" / "work-ledger" / "active.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        """# Active Work

## parent-1
- status: planned
- execution: smda
""",
        encoding="utf-8",
    )
    adapter = LocalLedgerBacklogAdapter(root=tmp_path)

    adapter.set_coarse_state("parent-1", "In Progress")
    adapter.comment("parent-1", "Started by SMDA\nEvidence line")
    child = adapter.create_child(
        parent_id="parent-1",
        title="Child title",
        body=(
            "Execution: smda-child\n"
            "Parent issue: parent-1\n"
            "Graph checksum: abc123\n"
            "Node id: child-001\n"
            "Acceptance criteria: child done\n"
            "Verification: pytest"
        ),
        labels={"agent"},
    )
    adapter.link_blocking(blocker_id="parent-1", blocked_id=child.id)

    assert child.id == "parent-1-C1"
    reloaded_child = adapter.fetch_issue(child.id)
    assert reloaded_child.parent_id == "parent-1"
    assert reloaded_child.state == "Todo"
    assert adapter.project_hierarchy("parent-1") == [child.id]
    assert adapter.query_blocked_by(child.id) == ["parent-1"]

    text = ledger.read_text(encoding="utf-8")
    assert "- status: in-progress" in text
    assert "- smda-comment: Started by SMDA\n  Evidence line" in text
    assert "## parent-1-C1" in text
    assert "- blocked-by: parent-1" in text
    assert adapter.fetch_issue("parent-1").comments == [
        "Started by SMDA\nEvidence line"
    ]
