import pytest

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.candidate_routing import (
    CandidateRoutingDecision,
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


def test_classifies_explicit_smda_roadmap():
    decision = classify_candidate(
        issue(
            "Source: docs/superpowers/specs/roadmap.md\n"
            "Execution: smda-roadmap\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.ROADMAP
    assert decision.reason == "Execution: smda-roadmap"


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


def test_routing_decision_does_not_thread_workflow_options():
    assert "workflow_options" not in CandidateRoutingDecision.__dataclass_fields__


def test_classifies_smda_task():
    decision = classify_candidate(
        issue(
            "Execution: smda-task\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest packages/scheduler/tests -q\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.TASK


def test_classifies_smda_task_with_mode_tag():
    decision = classify_candidate(
        issue(
            "Execution: smda-task\n"
            "Mode tags: full_review\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.TASK


def test_blocks_smda_task_with_invalid_tag_combination():
    decision = classify_candidate(
        issue(
            "Execution: smda-task\n"
            "Mode tags: quality_only, high_risk\n"
            "Acceptance criteria: bug fixed\n"
            "Verification: pytest\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "quality_only cannot be combined with high_risk" in decision.reason


def test_blocks_smda_task_without_minimum_context():
    decision = classify_candidate(
        issue("Execution: smda-task\nAcceptance criteria: bug fixed\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "Verification" in decision.reason


def test_manual_execution_never_dispatches():
    decision = classify_candidate(
        issue("Execution: manual\nAcceptance criteria: human only\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "manual" in decision.reason


def test_smda_review_is_cataloged_but_not_enabled():
    decision = classify_candidate(
        issue(
            "Execution: smda-review\n"
            "Candidate ref: feature/ref\n"
            "Acceptance criteria: review it\n"
            "Verification: pytest\n"
        ),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert "smda-review is not enabled" in decision.reason


def test_blocks_unmodeled_issue_under_explicit_only_policy():
    decision = classify_candidate(
        issue("Source: docs/spec.md\nAcceptance criteria: works\nVerification: pytest\n"),
        issue_entry_policy="explicit-only",
    )

    assert decision.route == CandidateRoute.BLOCK
    assert decision.reason == "Missing Execution mode under explicit-only policy"


def test_normalizes_unmodeled_issue_under_implicit_one_child_policy_to_task():
    decision = classify_candidate(
        issue("Source: docs/spec.md\nAcceptance criteria: works\nVerification: pytest\n"),
        issue_entry_policy="implicit-one-child",
    )

    assert decision.route == CandidateRoute.TASK
    assert decision.reason == "implicit-one-child policy -> smda-task"


@pytest.mark.parametrize('tag', ['human_approval_required', 'high_risk'])
def test_implicit_work_cannot_bypass_human_gate(tag):
    issue=BacklogIssue(id='NOTE-1',title='Sensitive change',state='Todo',labels=frozenset({'agent'}),body=f'Source: docs/spec.md\nAcceptance criteria: works\nVerification: pytest\nMode tags: {tag}')
    assert classify_candidate(issue,issue_entry_policy='implicit-one-child').route==CandidateRoute.BLOCK
