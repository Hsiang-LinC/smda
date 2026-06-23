from pathlib import Path

from smda_scheduler.parent_acceptance import (
    ChildAcceptConflictError,
    ChildAcceptOperation,
    ParentLandOperation,
    ParentIntegration,
    recover_or_apply_child_accept,
    recover_or_apply_parent_land,
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


class FailingProbeIntegration(ParentIntegration):
    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool:
        raise RuntimeError("missing integration branch")

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None:
        raise AssertionError("apply should not run after probe failure")


class ConflictingIntegration(ParentIntegration):
    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool:
        return False

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None:
        raise ChildAcceptConflictError(
            "cherry-pick conflict",
            conflicted_paths=("shared.txt",),
        )


class RecordingParentLandIntegration:
    def __init__(self, landed_refs: set[tuple[str, str]] | None = None) -> None:
        self.landed_refs = landed_refs or set()
        self.applied: list[ParentLandOperation] = []

    def has_landed_parent_ref(self, operation: ParentLandOperation) -> bool:
        return (operation.parent_ref, operation.base_branch) in self.landed_refs

    def land_parent_to_base(self, operation: ParentLandOperation) -> None:
        self.applied.append(operation)
        self.landed_refs.add((operation.parent_ref, operation.base_branch))


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


def test_parent_accept_recovery_records_probe_failures(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key="parent:DANNY-66:child-001:abc123",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="abc123",
        integration_branch="smda/danny-66/integration",
    )

    result = recover_or_apply_child_accept(
        ledger,
        FailingProbeIntegration(),
        operation,
    )

    assert result.status == "pending"
    assert result.action == "apply_failed"
    recorded = ledger.load_parent_accept_operations()[0]
    assert recorded["status"] == "pending"
    assert recorded["last_error"] == "missing integration branch"


def test_parent_accept_recovery_records_conflict_details(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    operation = ChildAcceptOperation(
        operation_id="accept-1",
        idempotency_key="parent:DANNY-66:child-001:abc123",
        parent_id="DANNY-66",
        child_id="child-001",
        candidate_ref="abc123",
        integration_branch="smda/danny-66/integration",
    )

    result = recover_or_apply_child_accept(
        ledger,
        ConflictingIntegration(),
        operation,
    )

    assert result.status == "pending"
    assert result.action == "apply_conflicted"
    assert result.conflict_fingerprint
    recorded = ledger.load_parent_accept_operations()[0]
    assert recorded["status"] == "pending"
    assert recorded["last_error"] == "cherry-pick conflict"
    assert recorded["conflicted_paths"] == ("shared.txt",)
    assert recorded["conflict_fingerprint"] == result.conflict_fingerprint
    assert recorded["resolver_attempts"] == 0


def test_parent_land_recovery_records_completed_when_ref_already_landed(
    tmp_path: Path,
):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    operation = ParentLandOperation(
        operation_id="land-1",
        idempotency_key="parent:DANNY-66:land:abc123:main",
        parent_id="DANNY-66",
        parent_ref="abc123",
        base_branch="main",
    )
    integration = RecordingParentLandIntegration(landed_refs={("abc123", "main")})

    result = recover_or_apply_parent_land(ledger, integration, operation)

    assert result.status == "completed"
    assert result.action == "recorded_existing_land"
    assert integration.applied == []
    assert ledger.load_parent_land_operations()[0]["status"] == "completed"


def test_parent_land_recovery_applies_missing_ref_once(tmp_path: Path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    operation = ParentLandOperation(
        operation_id="land-1",
        idempotency_key="parent:DANNY-66:land:abc123:main",
        parent_id="DANNY-66",
        parent_ref="abc123",
        base_branch="main",
    )
    integration = RecordingParentLandIntegration()

    first = recover_or_apply_parent_land(ledger, integration, operation)
    second = recover_or_apply_parent_land(
        ledger,
        integration,
        ParentLandOperation(
            operation_id="land-duplicate",
            idempotency_key="parent:DANNY-66:land:abc123:main",
            parent_id="DANNY-66",
            parent_ref="abc123",
            base_branch="main",
        ),
    )

    assert first.action == "landed_parent"
    assert second.action == "already_completed"
    assert [operation.operation_id for operation in integration.applied] == ["land-1"]
    assert [entry["operation_id"] for entry in ledger.load_parent_land_operations()] == [
        "land-1"
    ]
