import sqlite3
from pathlib import Path

import pytest

from smda_scheduler.phase_ledger import BacklogEffect, PhaseLedger
from smda_scheduler.reconciliation import retry_pending_tracker_effects


class RecordingTracker:
    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.comments: list[tuple[str, str]] = []
        self.states: list[tuple[str, str]] = []
        self.children: list[dict[str, object]] = []

    def comment(self, issue_id: str, body: str) -> None:
        if self.fail_on == "comment":
            raise RuntimeError("comment failed")
        self.comments.append((issue_id, body))

    def set_coarse_state(self, issue_id: str, state: str) -> None:
        if self.fail_on == "set_state":
            raise RuntimeError("state failed")
        self.states.append((issue_id, state))

    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ):
        if self.fail_on == "create_child":
            raise RuntimeError("create child failed")
        self.children.append(
            {
                "parent_id": parent_id,
                "title": title,
                "body": body,
                "labels": frozenset(labels or ()),
            }
        )
        return object()


def test_retry_pending_tracker_effects_marks_successes_sent(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_tracker_effect(
        effect_id="effect-comment",
        idempotency_key="comment:DANNY-66:started",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "SMDA started"},
    )
    ledger.record_tracker_effect(
        effect_id="effect-state",
        idempotency_key="state:DANNY-66:In Progress",
        effect_type="set_state",
        target_id="DANNY-66",
        payload={"state": "In Progress"},
    )
    tracker = RecordingTracker()

    result = retry_pending_tracker_effects(ledger, tracker)

    assert result.sent_effect_ids == ("effect-comment", "effect-state")
    assert result.failed_effect_ids == ()
    assert tracker.comments == [("DANNY-66", "SMDA started")]
    assert tracker.states == [("DANNY-66", "In Progress")]
    assert ledger.load_pending_tracker_effects() == []


def test_retry_pending_tracker_effects_sends_create_child(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_tracker_effect(
        effect_id="effect-child",
        idempotency_key="child:DANNY-66:concern",
        effect_type="create_child",
        target_id="DANNY-66",
        payload={
            "parent_id": "DANNY-66",
            "title": "Follow up concern",
            "body": "Execution: manual\nConcern report:\nminor issue",
            "labels": ["smda-follow-up"],
        },
    )
    tracker = RecordingTracker()

    result = retry_pending_tracker_effects(ledger, tracker)

    assert result.sent_effect_ids == ("effect-child",)
    assert result.failed_effect_ids == ()
    assert tracker.children == [
        {
            "parent_id": "DANNY-66",
            "title": "Follow up concern",
            "body": "Execution: manual\nConcern report:\nminor issue",
            "labels": frozenset({"smda-follow-up"}),
        }
    ]
    assert ledger.load_pending_tracker_effects() == []


def test_retry_pending_tracker_effects_keeps_failures_pending(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.record_tracker_effect(
        effect_id="effect-comment",
        idempotency_key="comment:DANNY-66:started",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "SMDA started"},
    )

    result = retry_pending_tracker_effects(ledger, RecordingTracker(fail_on="comment"))

    assert result.sent_effect_ids == ()
    assert result.failed_effect_ids == ("effect-comment",)
    pending = ledger.load_pending_tracker_effects()
    assert pending[0]["effect_id"] == "effect-comment"
    assert pending[0]["last_error"] == "comment failed"


def test_duplicate_transition_effect_is_delivered_once(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    ledger.create_parent_run(
        parent_id="DANNY-66",
        initial_phase="SPEC_FINALIZED",
        spec_path="docs/spec.md",
        spec_checksum="sha256:spec",
        approval_evidence="approved",
    )
    effect = BacklogEffect(
        effect_id="lifecycle-comment:DANNY-66:stable",
        idempotency_key="lifecycle-comment:DANNY-66:stable",
        effect_type="comment",
        target_id="DANNY-66",
        payload={"body": "Stable lifecycle projection"},
    )

    ledger.transition_parent(
        parent_id="DANNY-66",
        expected_phase="SPEC_FINALIZED",
        next_phase="SPEC_FINALIZED",
        effects=(effect,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        ledger.transition_parent(
            parent_id="DANNY-66",
            expected_phase="SPEC_FINALIZED",
            next_phase="SPEC_FINALIZED",
            effects=(effect,),
        )

    assert [item["effect_id"] for item in ledger.load_pending_tracker_effects()] == [
        effect.effect_id
    ]
    tracker = RecordingTracker()
    result = retry_pending_tracker_effects(ledger, tracker)
    assert result.sent_effect_ids == (effect.effect_id,)
    assert tracker.comments == [("DANNY-66", "Stable lifecycle projection")]
    assert ledger.load_pending_tracker_effects() == []
