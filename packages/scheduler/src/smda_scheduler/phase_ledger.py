from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from smda_scheduler.scheduling import ChildRunState, Claim, SchedulerState
from smda_scheduler.workflow import ChildPhase


class PhaseLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_scheduler_state(self) -> SchedulerState:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT child_id, phase, attempts, claim_owner,
                       claim_lease_expires_at, next_not_before
                FROM child_run_state
                ORDER BY child_id
                """
            ).fetchall()

        children = {
            child_id: ChildRunState(
                phase=ChildPhase(phase),
                attempts=attempts,
                claim=(
                    Claim(owner=claim_owner, lease_expires_at=claim_lease_expires_at)
                    if claim_owner is not None
                    else None
                ),
                next_not_before=next_not_before,
            )
            for (
                child_id,
                phase,
                attempts,
                claim_owner,
                claim_lease_expires_at,
                next_not_before,
            ) in rows
        }
        return SchedulerState(children=children)

    def save_scheduler_state(self, state: SchedulerState) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._save_scheduler_state(connection, state)

    def record_attempt_request(
        self,
        *,
        attempt_id: str,
        child_id: str,
        phase: ChildPhase,
        idempotency_key: str,
        request_json: dict[str, Any],
    ) -> str:
        self._ensure_schema()
        encoded_request = json.dumps(request_json, sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT attempt_id FROM attempt_ledger WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return str(existing[0])
            connection.execute(
                """
                INSERT INTO attempt_ledger (
                    attempt_id,
                    child_id,
                    phase,
                    idempotency_key,
                    status,
                    request_json,
                    result_json,
                    error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    child_id,
                    phase.value,
                    idempotency_key,
                    "dispatched",
                    encoded_request,
                    None,
                    None,
                ),
            )
        return attempt_id

    def record_attempt_result(
        self,
        *,
        attempt_id: str,
        status: str,
        result_json: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._record_attempt_result(
                connection,
                attempt_id=attempt_id,
                status=status,
                result_json=result_json,
                error_message=error_message,
            )

    def record_attempt_result_and_state(
        self,
        *,
        attempt_id: str,
        status: str,
        result_json: dict[str, Any] | None,
        error_message: str | None,
        state: SchedulerState,
    ) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._record_attempt_result(
                connection,
                attempt_id=attempt_id,
                status=status,
                result_json=result_json,
                error_message=error_message,
            )
            self._save_scheduler_state(connection, state)

    def load_attempts(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, child_id, phase, idempotency_key, status,
                       request_json, result_json, error_message
                FROM attempt_ledger
                ORDER BY attempt_id
                """
            ).fetchall()
        return [
            {
                "attempt_id": attempt_id,
                "child_id": child_id,
                "phase": phase,
                "idempotency_key": idempotency_key,
                "status": status,
                "request_json": json.loads(request_json),
                "result_json": json.loads(result_json) if result_json else None,
                "error_message": error_message,
            }
            for (
                attempt_id,
                child_id,
                phase,
                idempotency_key,
                status,
                request_json,
                result_json,
                error_message,
            ) in rows
        ]

    def record_tracker_effect(
        self,
        *,
        effect_id: str,
        idempotency_key: str,
        effect_type: str,
        target_id: str,
        payload: dict[str, Any],
    ) -> str:
        self._ensure_schema()
        encoded_payload = json.dumps(payload, sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT effect_id FROM tracker_effect_ledger WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return str(existing[0])
            connection.execute(
                """
                INSERT INTO tracker_effect_ledger (
                    effect_id,
                    idempotency_key,
                    effect_type,
                    target_id,
                    payload_json,
                    status,
                    last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    effect_id,
                    idempotency_key,
                    effect_type,
                    target_id,
                    encoded_payload,
                    "pending",
                    None,
                ),
            )
        return effect_id

    def mark_tracker_effect_sent(self, effect_id: str) -> None:
        self._update_tracker_effect_status(
            effect_id,
            status="sent",
            last_error=None,
        )

    def mark_tracker_effect_failed(self, effect_id: str, error_message: str) -> None:
        self._update_tracker_effect_status(
            effect_id,
            status="pending",
            last_error=error_message,
        )

    def load_pending_tracker_effects(self) -> list[dict[str, Any]]:
        return [
            effect
            for effect in self.load_tracker_effects()
            if effect["status"] == "pending"
        ]

    def load_tracker_effects(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT effect_id, idempotency_key, effect_type, target_id,
                       payload_json, status, last_error
                FROM tracker_effect_ledger
                ORDER BY effect_id
                """
            ).fetchall()
        return [
            {
                "effect_id": effect_id,
                "idempotency_key": idempotency_key,
                "effect_type": effect_type,
                "target_id": target_id,
                "payload": json.loads(payload_json),
                "status": status,
                "last_error": last_error,
            }
            for (
                effect_id,
                idempotency_key,
                effect_type,
                target_id,
                payload_json,
                status,
                last_error,
            ) in rows
        ]

    def record_parent_accept_operation(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        parent_id: str,
        child_id: str,
        candidate_ref: str,
        integration_branch: str,
    ) -> str:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT operation_id
                FROM parent_accept_ledger
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return str(existing[0])
            connection.execute(
                """
                INSERT INTO parent_accept_ledger (
                    operation_id,
                    idempotency_key,
                    parent_id,
                    child_id,
                    candidate_ref,
                    integration_branch,
                    status,
                    last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    idempotency_key,
                    parent_id,
                    child_id,
                    candidate_ref,
                    integration_branch,
                    "pending",
                    None,
                ),
            )
        return operation_id

    def mark_parent_accept_completed(self, operation_id: str) -> None:
        self._update_parent_accept_status(
            operation_id,
            status="completed",
            last_error=None,
        )

    def mark_parent_accept_failed(
        self,
        operation_id: str,
        error_message: str,
    ) -> None:
        self._update_parent_accept_status(
            operation_id,
            status="pending",
            last_error=error_message,
        )

    def load_parent_accept_operations(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT operation_id, idempotency_key, parent_id, child_id,
                       candidate_ref, integration_branch, status, last_error
                FROM parent_accept_ledger
                ORDER BY operation_id
                """
            ).fetchall()
        return [
            {
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "parent_id": parent_id,
                "child_id": child_id,
                "candidate_ref": candidate_ref,
                "integration_branch": integration_branch,
                "status": status,
                "last_error": last_error,
            }
            for (
                operation_id,
                idempotency_key,
                parent_id,
                child_id,
                candidate_ref,
                integration_branch,
                status,
                last_error,
            ) in rows
        ]

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS child_run_state (
                    child_id TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    claim_owner TEXT,
                    claim_lease_expires_at REAL,
                    next_not_before REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attempt_ledger (
                    attempt_id TEXT PRIMARY KEY,
                    child_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tracker_effect_ledger (
                    effect_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    effect_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parent_accept_ledger (
                    operation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    parent_id TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    candidate_ref TEXT NOT NULL,
                    integration_branch TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )

    def _record_attempt_result(
        self,
        connection: sqlite3.Connection,
        *,
        attempt_id: str,
        status: str,
        result_json: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        result = json.dumps(result_json, sort_keys=True) if result_json else None
        connection.execute(
            """
            UPDATE attempt_ledger
            SET status = ?, result_json = ?, error_message = ?
            WHERE attempt_id = ?
            """,
            (status, result, error_message, attempt_id),
        )

    def _save_scheduler_state(
        self,
        connection: sqlite3.Connection,
        state: SchedulerState,
    ) -> None:
        connection.execute("DELETE FROM child_run_state")
        connection.executemany(
            """
            INSERT INTO child_run_state (
                child_id,
                phase,
                attempts,
                claim_owner,
                claim_lease_expires_at,
                next_not_before
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    child_id,
                    child.phase.value,
                    child.attempts,
                    child.claim.owner if child.claim is not None else None,
                    (
                        child.claim.lease_expires_at
                        if child.claim is not None
                        else None
                    ),
                    child.next_not_before,
                )
                for child_id, child in sorted(state.children.items())
            ],
        )

    def _update_tracker_effect_status(
        self,
        effect_id: str,
        *,
        status: str,
        last_error: str | None,
    ) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE tracker_effect_ledger
                SET status = ?, last_error = ?
                WHERE effect_id = ?
                """,
                (status, last_error, effect_id),
            )

    def _update_parent_accept_status(
        self,
        operation_id: str,
        *,
        status: str,
        last_error: str | None,
    ) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE parent_accept_ledger
                SET status = ?, last_error = ?
                WHERE operation_id = ?
                """,
                (status, last_error, operation_id),
            )
