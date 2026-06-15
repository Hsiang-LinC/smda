from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import (
    CandidateRoute,
    classify_candidate,
)


def issue(body: str) -> BacklogIssue:
    return BacklogIssue(
        id="DANNY-66",
        title="Candidate",
        state="Todo",
        body=body,
        labels=frozenset({"agent"}),
    )


def test_classifies_explicit_smda_parent():
    decision = classify_candidate(
        issue(
            "Source: docs/spec.md\n"
            "Execution: smda\n"
            "Acceptance criteria: works\n"
            "Verification: pytest\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.PARENT
    assert decision.reason == "Execution: smda"


def test_classifies_smda_child_handle_with_required_context():
    decision = classify_candidate(
        issue(
            "Parent issue: DANNY-1\n"
            "Graph checksum: sha256:abcdef\n"
            "Node id: child-001\n"
            "Execution: smda-child\n"
            "Acceptance criteria: child passes review\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.CHILD
    assert decision.parent_issue_id == "DANNY-1"
    assert decision.node_id == "child-001"
    assert decision.graph_checksum == "sha256:abcdef"


def test_blocks_smda_child_handle_without_acceptance_criteria():
    decision = classify_candidate(
        issue(
            "Parent issue: DANNY-1\n"
            "Graph checksum: sha256:abcdef\n"
            "Node id: child-001\n"
            "Execution: smda-child\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "Acceptance criteria" in decision.reason


def test_blocks_smda_child_handle_when_required_context_is_missing():
    decision = classify_candidate(
        issue("Execution: smda-child\nParent issue: DANNY-1\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert (
        decision.reason
        == "Missing smda-child context: Graph checksum, Node id, Acceptance criteria"
    )


def test_blocks_obsolete_orchestrator_mode():
    decision = classify_candidate(
        issue("Execution: orchestrator\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "obsolete" in decision.reason


def test_blocks_unmodeled_issue_under_explicit_only_policy():
    decision = classify_candidate(
        issue("Source: docs/spec.md\nAcceptance criteria: works\nVerification: pytest\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert decision.reason == "Missing Execution mode under explicit-only policy"


def test_normalizes_unmodeled_issue_under_implicit_one_child_policy():
    decision = classify_candidate(
        issue("Source: docs/spec.md\nAcceptance criteria: works\nVerification: pytest\n"),
        issue_entry_policy="implicit-one-child",
    )

    assert decision.route == CandidateRoute.IMPLICIT_PARENT
    assert decision.reason == "implicit-one-child policy"
