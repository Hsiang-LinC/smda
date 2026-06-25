from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from smda_scheduler.phase_ledger import PhaseLedger


@dataclass(frozen=True)
class ChildAcceptOperation:
    operation_id: str
    idempotency_key: str
    parent_id: str
    child_id: str
    candidate_ref: str
    integration_branch: str


@dataclass(frozen=True)
class ParentLandOperation:
    operation_id: str
    idempotency_key: str
    parent_id: str
    parent_ref: str
    base_branch: str


class ChildAcceptConflictError(RuntimeError):
    def __init__(self, message: str, *, conflicted_paths: tuple[str, ...]) -> None:
        super().__init__(message)
        self.conflicted_paths = conflicted_paths


class ParentIntegration(Protocol):
    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool: ...

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None: ...


class ParentLandIntegration(Protocol):
    def has_landed_parent_ref(self, operation: ParentLandOperation) -> bool: ...

    def land_parent_to_base(self, operation: ParentLandOperation) -> None: ...


@dataclass(frozen=True)
class ParentAcceptResult:
    operation_id: str
    status: str
    action: str
    conflict_fingerprint: str = ""


def recover_or_apply_child_accept(
    ledger: PhaseLedger,
    integration: ParentIntegration,
    operation: ChildAcceptOperation,
) -> ParentAcceptResult:
    operation_id = ledger.record_parent_accept_operation(
        operation_id=operation.operation_id,
        idempotency_key=operation.idempotency_key,
        parent_id=operation.parent_id,
        child_id=operation.child_id,
        candidate_ref=operation.candidate_ref,
        integration_branch=operation.integration_branch,
    )
    recorded = _operation_with_id(ledger, operation_id)
    if recorded["status"] == "completed":
        return ParentAcceptResult(
            operation_id=operation_id,
            status="completed",
            action="already_completed",
        )

    effective_operation = ChildAcceptOperation(
        operation_id=operation_id,
        idempotency_key=recorded["idempotency_key"],
        parent_id=recorded["parent_id"],
        child_id=recorded["child_id"],
        candidate_ref=recorded["candidate_ref"],
        integration_branch=recorded["integration_branch"],
    )
    try:
        if integration.has_accepted_child_ref(effective_operation):
            ledger.mark_parent_accept_completed(operation_id)
            return ParentAcceptResult(
                operation_id=operation_id,
                status="completed",
                action="recorded_existing_accept",
            )
        integration.apply_child_candidate(effective_operation)
    except ChildAcceptConflictError as error:
        fingerprint = child_accept_conflict_fingerprint(
            effective_operation,
            conflicted_paths=error.conflicted_paths,
            error_message=str(error),
        )
        ledger.mark_parent_accept_failed(
            operation_id,
            str(error),
            conflicted_paths=error.conflicted_paths,
            conflict_fingerprint=fingerprint,
        )
        return ParentAcceptResult(
            operation_id=operation_id,
            status="pending",
            action="apply_conflicted",
            conflict_fingerprint=fingerprint,
        )
    except Exception as error:
        ledger.mark_parent_accept_failed(operation_id, str(error))
        return ParentAcceptResult(
            operation_id=operation_id,
            status="pending",
            action="apply_failed",
        )

    ledger.mark_parent_accept_completed(operation_id)
    return ParentAcceptResult(
        operation_id=operation_id,
        status="completed",
        action="applied_candidate",
    )


def recover_or_apply_parent_land(
    ledger: PhaseLedger,
    integration: ParentLandIntegration,
    operation: ParentLandOperation,
) -> ParentAcceptResult:
    operation_id = ledger.record_parent_land_operation(
        operation_id=operation.operation_id,
        idempotency_key=operation.idempotency_key,
        parent_id=operation.parent_id,
        parent_ref=operation.parent_ref,
        base_branch=operation.base_branch,
    )
    recorded = _parent_land_operation_with_id(ledger, operation_id)
    if recorded["status"] == "completed":
        return ParentAcceptResult(
            operation_id=operation_id,
            status="completed",
            action="already_completed",
        )

    effective_operation = ParentLandOperation(
        operation_id=operation_id,
        idempotency_key=recorded["idempotency_key"],
        parent_id=recorded["parent_id"],
        parent_ref=recorded["parent_ref"],
        base_branch=recorded["base_branch"],
    )
    if integration.has_landed_parent_ref(effective_operation):
        ledger.mark_parent_land_completed(operation_id)
        return ParentAcceptResult(
            operation_id=operation_id,
            status="completed",
            action="recorded_existing_land",
        )

    try:
        integration.land_parent_to_base(effective_operation)
    except Exception as error:
        ledger.mark_parent_land_failed(operation_id, str(error))
        return ParentAcceptResult(
            operation_id=operation_id,
            status="pending",
            action="land_failed",
        )

    ledger.mark_parent_land_completed(operation_id)
    return ParentAcceptResult(
        operation_id=operation_id,
        status="completed",
        action="landed_parent",
    )


def _operation_with_id(ledger: PhaseLedger, operation_id: str) -> dict:
    for operation in ledger.load_parent_accept_operations():
        if operation["operation_id"] == operation_id:
            return operation
    raise ValueError(f"Parent accept operation not found: {operation_id}")


def child_accept_conflict_fingerprint(
    operation: ChildAcceptOperation,
    *,
    conflicted_paths: tuple[str, ...],
    error_message: str,
) -> str:
    payload = {
        "parent_id": operation.parent_id,
        "child_id": operation.child_id,
        "candidate_ref": operation.candidate_ref,
        "conflicted_paths": sorted(conflicted_paths),
        "last_error_hash": hashlib.sha256(error_message.encode("utf-8")).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _parent_land_operation_with_id(ledger: PhaseLedger, operation_id: str) -> dict:
    for operation in ledger.load_parent_land_operations():
        if operation["operation_id"] == operation_id:
            return operation
    raise ValueError(f"Parent land operation not found: {operation_id}")
