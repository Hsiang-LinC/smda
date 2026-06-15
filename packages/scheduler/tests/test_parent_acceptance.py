from pathlib import Path

from smda_scheduler.parent_acceptance import (
    ChildAcceptOperation,
    ParentIntegration,
    recover_or_apply_child_accept,
)
from smda_scheduler.phase_ledger import PhaseLedger


class RecordingIntegration(ParentIntegration):
    def __init__(self, accepted_refs: set[str] | None = None) -> None:
        self.accepted_refs = accepted_refs or set()
        self.applied: list[ChildAcceptOperation] = []

    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool:
        return operation.candidate_ref in self.accepted_refs

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None:
        self.applied.append(operation)
        self.accepted_refs.add(operation.candidate_ref)


def test_parent_accept_recovery_records_completed_when_ref_already_integrated(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key="parent:DANNY-66:child-001:abc123",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="abc123",
        integration_branch="smda/DANNY-66/integration",
    )
    integration = RecordingIntegration(accepted_refs={"abc123"})

    result = recover_or_apply_child_accept(ledger, integration, operation)

    assert result.status == "completed"
    assert result.action == "recorded_existing_accept"
    assert integration.applied == []
    assert ledger.load_parent_accept_operations()[0]["status"] == "completed"


def test_parent_accept_recovery_applies_missing_ref_once(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key="parent:DANNY-66:child-001:abc123",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="abc123",
        integration_branch="smda/DANNY-66/integration",
    )
    integration = RecordingIntegration()

    first = recover_or_apply_child_accept(ledger, integration, operation)
    second = recover_or_apply_child_accept(
        ledger,
        integration,
        ChildAcceptOperation(
            operation_id="accept-duplicate",
            idempotency_key="parent:DANNY-66:child-001:abc123",
            parent_id="DANNY-66",
            child_id="child-001",
            candidate_ref="abc123",
            integration_branch="smda/DANNY-66/integration",
        ),
    )

    assert first.action == "applied_candidate"
    assert second.action == "already_completed"
    assert [operation.operation_id for operation in integration.applied] == ["accept-1"]
    assert [entry["operation_id"] for entry in ledger.load_parent_accept_operations()] == [
        "accept-1"
    ]
