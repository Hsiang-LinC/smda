from __future__ import annotations

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


class ParentIntegration(Protocol):
    def has_accepted_child_ref(self, operation: ChildAcceptOperation) -> bool: ...

    def apply_child_candidate(self, operation: ChildAcceptOperation) -> None: ...


@dataclass(frozen=True)
class ParentAcceptResult:
    operation_id: str
    status: str
    action: str


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
    if integration.has_accepted_child_ref(effective_operation):
        ledger.mark_parent_accept_completed(operation_id)
        return ParentAcceptResult(
            operation_id=operation_id,
            status="completed",
            action="recorded_existing_accept",
        )

    try:
        integration.apply_child_candidate(effective_operation)
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


def _operation_with_id(ledger: PhaseLedger, operation_id: str) -> dict:
    for operation in ledger.load_parent_accept_operations():
        if operation["operation_id"] == operation_id:
            return operation
    raise ValueError(f"Parent accept operation not found: {operation_id}")
