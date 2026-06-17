from smda_scheduler.parent_dependency_gate import parent_dependency_gate


def test_parent_eligible_when_no_blockers():
    result = parent_dependency_gate(
        parent_id="P1",
        blockers=(),
        final_accepted_parent_ids=frozenset(),
    )
    assert result.eligible
    assert result.blocked_by == ()


def test_parent_blocked_until_upstream_final_accepted():
    blocked = parent_dependency_gate(
        parent_id="P2",
        blockers=("P1",),
        final_accepted_parent_ids=frozenset(),
    )
    assert not blocked.eligible
    assert blocked.blocked_by == ("P1",)
    assert "P1" in blocked.reason

    unblocked = parent_dependency_gate(
        parent_id="P2",
        blockers=("P1",),
        final_accepted_parent_ids=frozenset({"P1"}),
    )
    assert unblocked.eligible


def test_parent_blocked_by_only_unaccepted_subset():
    result = parent_dependency_gate(
        parent_id="P3",
        blockers=("P1", "P2"),
        final_accepted_parent_ids=frozenset({"P1"}),
    )
    assert not result.eligible
    assert result.blocked_by == ("P2",)
