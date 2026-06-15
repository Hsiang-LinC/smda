from smda_scheduler.backlog import BacklogIssue, LocalBacklogAdapter


def test_local_backlog_adapter_exposes_contract_capabilities():
    adapter = LocalBacklogAdapter()

    descriptor = adapter.descriptor()

    assert descriptor.id == "local"
    assert descriptor.capabilities >= frozenset(
        {
            "create_child",
            "coarse_states",
            "comments",
            "hierarchy",
            "blocking_relations",
            "labels",
        }
    )


def test_local_backlog_adapter_updates_issue_state_and_comments():
    adapter = LocalBacklogAdapter(
        issues={
            "PARENT-1": BacklogIssue(
                id="PARENT-1",
                title="Parent spec",
                state="Todo",
            )
        }
    )

    adapter.set_coarse_state("PARENT-1", "In Progress")
    adapter.comment("PARENT-1", "Started by SMDA")

    issue = adapter.fetch_issue("PARENT-1")
    assert issue.state == "In Progress"
    assert issue.comments == ["Started by SMDA"]


def test_local_backlog_adapter_creates_child_and_projects_hierarchy():
    adapter = LocalBacklogAdapter(
        issues={
            "PARENT-1": BacklogIssue(
                id="PARENT-1",
                title="Parent spec",
                state="Todo",
            )
        }
    )

    child = adapter.create_child(
        parent_id="PARENT-1",
        title="Implement child A",
        body="Context packet",
        labels={"smda:child"},
    )

    assert child.parent_id == "PARENT-1"
    assert child.body == "Context packet"
    assert child.labels == frozenset({"smda:child"})
    assert adapter.project_hierarchy("PARENT-1") == [child.id]


def test_local_backlog_adapter_projects_blocking_relations():
    adapter = LocalBacklogAdapter(
        issues={
            "A": BacklogIssue(id="A", title="A", state="Todo"),
            "B": BacklogIssue(id="B", title="B", state="Todo"),
        }
    )

    adapter.link_blocking(blocker_id="A", blocked_id="B")

    assert adapter.query_blocked_by("B") == ["A"]
