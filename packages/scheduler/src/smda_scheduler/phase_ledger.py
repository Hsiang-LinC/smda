from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smda_scheduler.scheduling import ChildRunState, Claim, SchedulerState
from smda_scheduler.sandcastle_execution import AttemptPhase
from smda_scheduler.workflow import (
    ChildPhase,
    GraphError,
    ParentPhase,
    RoadmapPhase,
)
from smda_scheduler.workflow_graph import WorkflowGraphArtifact


class ParentRunExists(RuntimeError):
    pass


class StaleParentTransition(RuntimeError):
    pass


class ParentAttemptResultRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class AttemptResultUpdate:
    attempt_id: str
    expected_dispatched_phase: AttemptPhase | RoadmapPhase | str
    status: str
    result_json: dict[str, Any] | None
    error_message: str | None


@dataclass(frozen=True)
class BacklogEffect:
    effect_id: str
    idempotency_key: str
    effect_type: str
    target_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RoadmapMembersUpdate:
    members: tuple[dict[str, Any], ...]
    member_edges: tuple[dict[str, Any], ...]


class PhaseLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")

    def load_scheduler_state(self) -> SchedulerState:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT child_id, phase, attempts, claim_owner,
                           claim_lease_expires_at, next_not_before, review_fix_cycles
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
                    review_fix_cycles=review_fix_cycles,
                )
                for (
                    child_id,
                    phase,
                    attempts,
                    claim_owner,
                    claim_lease_expires_at,
                    next_not_before,
                    review_fix_cycles,
                ) in rows
            }
            return SchedulerState(children=children)

    def save_scheduler_state(self, state: SchedulerState) -> None:
        with self._lock:
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
        with self._lock:
            return self.record_role_attempt_request(
                attempt_id=attempt_id,
                target_kind="child",
                target_id=child_id,
                phase=phase,
                idempotency_key=idempotency_key,
                request_json=request_json,
            )

    def record_role_attempt_request(
        self,
        *,
        attempt_id: str,
        target_kind: str,
        target_id: str,
        phase: AttemptPhase | RoadmapPhase | str,
        idempotency_key: str,
        request_json: dict[str, Any],
    ) -> str:
        with self._lock:
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
                        target_kind,
                        target_id,
                        phase,
                        idempotency_key,
                        status,
                        request_json,
                        result_json,
                        error_message
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        target_id,
                        target_kind,
                        target_id,
                        _phase_value(phase),
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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT attempt_id, child_id, phase, idempotency_key, status,
                           request_json, result_json, error_message,
                           target_kind, target_id
                    FROM attempt_ledger
                    ORDER BY attempt_id
                    """
                ).fetchall()
            return [
                {
                    "attempt_id": attempt_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
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
                    target_kind,
                    target_id,
                ) in rows
            ]

    def next_attempt_number(
        self,
        *,
        target_kind: str,
        target_id: str,
        phase: AttemptPhase | RoadmapPhase | str,
    ) -> int:
        sequences = (
            _attempt_sequence(attempt)
            for attempt in self._ordered_attempts(
                target_kind=target_kind,
                target_id=target_id,
                phases=(phase,),
            )
        )
        return (
            max(
                (sequence for sequence in sequences if sequence is not None),
                default=0,
            )
            + 1
        )

    def latest_review_findings(
        self,
        *,
        target_kind: str,
        target_id: str,
        phases: tuple[AttemptPhase | RoadmapPhase | str, ...],
    ) -> str | None:
        for attempt in reversed(
            self._ordered_attempts(
                target_kind=target_kind,
                target_id=target_id,
                phases=phases,
            )
        ):
            if attempt["status"] != "succeeded":
                continue
            result = attempt["result_json"]
            if isinstance(result, dict):
                report = result.get("report")
                if isinstance(report, str) and report.strip():
                    return report.strip()
        return None

    def latest_quality_candidate_ref(self, child_id: str) -> str | None:
        for attempt in reversed(
            self._ordered_attempts(
                target_kind="child",
                target_id=child_id,
                phases=(ChildPhase.QUALITY_REVIEWING,),
            )
        ):
            if attempt["status"] != "succeeded":
                continue
            result = attempt["result_json"]
            if not isinstance(result, dict):
                return None
            branch = result.get("branch")
            if isinstance(branch, str) and branch:
                return branch
            commits = result.get("commits")
            if isinstance(commits, list) and commits and isinstance(commits[-1], str):
                return commits[-1]
            return None
        return None

    def latest_child_report(self, child_id: str) -> str | None:
        attempts = self._ordered_attempts(
            target_kind="child",
            target_id=child_id,
            phases=tuple(ChildPhase),
        )
        if not attempts:
            return None
        attempt = attempts[-1]
        result = attempt["result_json"]
        if isinstance(result, dict):
            report = result.get("report")
            if isinstance(report, str) and report.strip():
                return report.strip()
        error_message = attempt["error_message"]
        return str(error_message) if error_message else None

    def child_parent_ids(self, child_id: str) -> tuple[str, ...]:
        parent_ids: list[str] = []
        for attempt in self._ordered_attempts(
            target_kind="child",
            target_id=child_id,
            phases=tuple(ChildPhase),
        ):
            request = attempt["request_json"]
            context_packet = (
                request.get("context_packet", {}) if isinstance(request, dict) else {}
            )
            parent_id = (
                context_packet.get("parent_issue_id")
                if isinstance(context_packet, dict)
                else None
            )
            if parent_id is not None and str(parent_id) not in parent_ids:
                parent_ids.append(str(parent_id))
        return tuple(parent_ids)

    def latest_parent_qa_attempt(self, parent_id: str) -> dict[str, Any] | None:
        attempts = self._ordered_attempts(
            target_kind="parent", target_id=parent_id,
            phases=(ParentPhase.PARENT_QA_REVIEWING,),
        )
        return attempts[-1] if attempts else None

    def parent_qa_results(self, parent_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for attempt in self._ordered_attempts(
            target_kind="parent",
            target_id=parent_id,
            phases=(ParentPhase.PARENT_QA_REVIEWING,),
        ):
            result = attempt["result_json"]
            if attempt["status"] == "succeeded" and isinstance(result, dict):
                results.append(result)
        return results

    def conflict_attempt_history(self, parent_id: str) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for attempt in self._ordered_attempts(
            target_kind="parent",
            target_id=parent_id,
            phases=(ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING,),
        ):
            request = attempt["request_json"]
            context_packet = (
                request.get("context_packet", {}) if isinstance(request, dict) else {}
            )
            conflict = (
                context_packet.get("conflict_history", {})
                if isinstance(context_packet, dict)
                else {}
            )
            result = attempt["result_json"]
            history.append(
                {
                    "attempt_id": attempt["attempt_id"],
                    "operation_id": (
                        conflict.get("operation_id")
                        if isinstance(conflict, dict)
                        else None
                    ),
                    "status": attempt["status"],
                    "verdict": result.get("verdict") if isinstance(result, dict) else None,
                    "required_next_action": (
                        result.get("required_next_action")
                        if isinstance(result, dict)
                        else None
                    ),
                    "report": result.get("report", "") if isinstance(result, dict) else "",
                }
            )
        return history

    def _ordered_attempts(
        self,
        *,
        target_kind: str,
        target_id: str,
        phases: tuple[AttemptPhase | RoadmapPhase | str, ...],
    ) -> list[dict[str, Any]]:
        if not phases:
            return []
        with self._lock:
            self._ensure_schema()
            phase_values = tuple(_phase_value(phase) for phase in phases)
            placeholders = ", ".join("?" for _ in phase_values)
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    f"""
                    SELECT attempt_id, phase, idempotency_key, status,
                           request_json, result_json, error_message
                    FROM attempt_ledger
                    WHERE target_kind = ?
                      AND target_id = ?
                      AND phase IN ({placeholders})
                    ORDER BY rowid
                    """,
                    (target_kind, target_id, *phase_values),
                ).fetchall()
            attempts = [
                {
                    "attempt_id": attempt_id,
                    "phase": phase,
                    "idempotency_key": idempotency_key,
                    "status": status,
                    "request_json": json.loads(request_json),
                    "result_json": json.loads(result_json) if result_json else None,
                    "error_message": error_message,
                }
                for (
                    attempt_id,
                    phase,
                    idempotency_key,
                    status,
                    request_json,
                    result_json,
                    error_message,
                ) in rows
            ]
        phase_groups: dict[str, list[dict[str, Any]]] = {}
        for attempt in attempts:
            phase_groups.setdefault(attempt["phase"], []).append(attempt)
        for phase, phase_attempts in phase_groups.items():
            ordered = sorted(
                enumerate(phase_attempts),
                key=lambda indexed_attempt: _attempt_order_key(
                    indexed_attempt[1],
                    fallback_index=indexed_attempt[0],
                ),
            )
            phase_groups[phase] = [attempt for _, attempt in ordered]

        phase_indexes = {phase: 0 for phase in phase_groups}
        ordered_attempts = []
        for attempt in attempts:
            phase = attempt["phase"]
            ordered_attempts.append(phase_groups[phase][phase_indexes[phase]])
            phase_indexes[phase] += 1
        return ordered_attempts

    def record_graph(self, graph: WorkflowGraphArtifact) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._record_graph(connection, graph)

    def load_graph(self, parent_id: str) -> WorkflowGraphArtifact:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                graph_row = connection.execute(
                    """
                    SELECT graph_checksum, dependency_edges_json
                    FROM smda_graph
                    WHERE parent_id = ?
                    """,
                    (parent_id,),
                ).fetchone()
                if graph_row is None:
                    raise KeyError(f"SMDA graph not found: {parent_id}")
                child_rows = connection.execute(
                    """
                    SELECT node_id, title, body, acceptance_criteria_json,
                           dependencies_json, in_scope_json, out_of_scope_json,
                           touched_surfaces_json, verification_json, risk_level
                    FROM smda_graph_child
                    WHERE parent_id = ?
                    ORDER BY rowid
                    """,
                    (parent_id,),
                ).fetchall()
            return WorkflowGraphArtifact.from_dict({
                "parent_id": parent_id,
                "graph_checksum": str(graph_row[0]),
                "dependency_edges": json.loads(graph_row[1]),
                "children": [
                    {
                        "node_id": node_id,
                        "title": title,
                        "body": body,
                        "acceptance_criteria": json.loads(acceptance_criteria_json),
                        "dependencies": json.loads(dependencies_json),
                        "in_scope": json.loads(in_scope_json),
                        "out_of_scope": json.loads(out_of_scope_json),
                        "touched_surfaces": json.loads(touched_surfaces_json),
                        "verification": json.loads(verification_json),
                        "risk_level": risk_level,
                    }
                    for (
                        node_id,
                        title,
                        body,
                        acceptance_criteria_json,
                        dependencies_json,
                        in_scope_json,
                        out_of_scope_json,
                        touched_surfaces_json,
                        verification_json,
                        risk_level,
                    ) in child_rows
                ],
            })

    def record_child_issue_projection(
        self,
        *,
        parent_id: str,
        node_id: str,
        issue_id: str,
    ) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO child_issue_projection (parent_id, node_id, issue_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(parent_id, node_id) DO UPDATE SET
                        issue_id = excluded.issue_id
                    """,
                    (parent_id, node_id, issue_id),
                )

    def load_child_issue_projections(self, parent_id: str) -> dict[str, str]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT node_id, issue_id
                    FROM child_issue_projection
                    WHERE parent_id = ?
                    ORDER BY node_id
                    """,
                    (parent_id,),
                ).fetchall()
            return {str(node_id): str(issue_id) for node_id, issue_id in rows}

    def set_parent_pause(self, parent_id: str, *, paused: bool) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if paused:
                    connection.execute(
                        """
                        INSERT INTO parent_pause (parent_id, paused)
                        VALUES (?, 1)
                        ON CONFLICT(parent_id) DO UPDATE SET paused = 1
                        """,
                        (parent_id,),
                    )
                else:
                    connection.execute(
                        "DELETE FROM parent_pause WHERE parent_id = ?",
                        (parent_id,),
                    )

    def is_parent_paused(self, parent_id: str) -> bool:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT paused
                    FROM parent_pause
                    WHERE parent_id = ?
                    """,
                    (parent_id,),
                ).fetchone()
            return bool(row and row[0])

    def load_paused_parent_ids(self) -> list[str]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT parent_id
                    FROM parent_pause
                    WHERE paused = 1
                    ORDER BY parent_id
                    """
                ).fetchall()
            return [str(parent_id) for (parent_id,) in rows]

    def record_tracker_effect(
        self,
        *,
        effect_id: str,
        idempotency_key: str,
        effect_type: str,
        target_id: str,
        payload: dict[str, Any],
    ) -> str:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT effect_id FROM tracker_effect_ledger WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return str(existing[0])
                self._record_tracker_effect(
                    connection,
                    BacklogEffect(
                        effect_id=effect_id,
                        idempotency_key=idempotency_key,
                        effect_type=effect_type,
                        target_id=target_id,
                        payload=payload,
                    ),
                )
            return effect_id

    def mark_tracker_effect_sent(self, effect_id: str) -> None:
        with self._lock:
            self._update_tracker_effect_status(
                effect_id,
                status="sent",
                last_error=None,
            )

    def mark_tracker_effect_failed(self, effect_id: str, error_message: str) -> None:
        with self._lock:
            self._update_tracker_effect_status(
                effect_id,
                status="pending",
                last_error=error_message,
            )

    def load_pending_tracker_effects(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                effect
                for effect in self.load_tracker_effects()
                if effect["status"] == "pending"
            ]

    def load_tracker_effects(self) -> list[dict[str, Any]]:
        with self._lock:
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
        with self._lock:
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
                        last_error,
                        conflicted_paths_json,
                        conflict_fingerprint,
                        resolver_attempts
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        "[]",
                        "",
                        0,
                    ),
                )
            return operation_id

    def mark_parent_accept_completed(self, operation_id: str) -> None:
        with self._lock:
            self._update_parent_accept_status(
                operation_id,
                status="completed",
                last_error=None,
            )

    def mark_parent_accept_failed(
        self,
        operation_id: str,
        error_message: str,
        *,
        conflicted_paths: tuple[str, ...] = (),
        conflict_fingerprint: str = "",
    ) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT conflict_fingerprint
                    FROM parent_accept_ledger
                    WHERE operation_id = ?
                    """,
                    (operation_id,),
                ).fetchone()
                if row is not None and str(row[0]) == conflict_fingerprint:
                    connection.execute(
                        """
                        UPDATE parent_accept_ledger
                        SET status = ?,
                            last_error = ?,
                            conflicted_paths_json = ?,
                            conflict_fingerprint = ?
                        WHERE operation_id = ?
                        """,
                        (
                            "pending",
                            error_message,
                            json.dumps(list(conflicted_paths), sort_keys=True),
                            conflict_fingerprint,
                            operation_id,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE parent_accept_ledger
                        SET status = ?,
                            last_error = ?,
                            conflicted_paths_json = ?,
                            conflict_fingerprint = ?,
                            resolver_attempts = 0
                        WHERE operation_id = ?
                        """,
                        (
                            "pending",
                            error_message,
                            json.dumps(list(conflicted_paths), sort_keys=True),
                            conflict_fingerprint,
                            operation_id,
                        ),
                    )

    def increment_parent_accept_resolver_attempts(
        self,
        operation_id: str,
    ) -> int:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE parent_accept_ledger
                    SET resolver_attempts = resolver_attempts + 1
                    WHERE operation_id = ?
                    """,
                    (operation_id,),
                )
                row = connection.execute(
                    """
                    SELECT resolver_attempts
                    FROM parent_accept_ledger
                    WHERE operation_id = ?
                    """,
                    (operation_id,),
                ).fetchone()
            if row is None:
                raise ValueError(f"Parent accept operation not found: {operation_id}")
            return int(row[0])

    def load_parent_accept_operations(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT operation_id, idempotency_key, parent_id, child_id,
                           candidate_ref, integration_branch, status, last_error,
                           conflicted_paths_json, conflict_fingerprint,
                           resolver_attempts
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
                    "conflicted_paths": tuple(json.loads(conflicted_paths_json)),
                    "conflict_fingerprint": conflict_fingerprint,
                    "resolver_attempts": resolver_attempts,
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
                    conflicted_paths_json,
                    conflict_fingerprint,
                    resolver_attempts,
                ) in rows
            ]

    def record_parent_land_operation(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        parent_id: str,
        parent_ref: str,
        base_branch: str,
    ) -> str:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT operation_id
                    FROM parent_land_ledger
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return str(existing[0])
                connection.execute(
                    """
                    INSERT INTO parent_land_ledger (
                        operation_id,
                        idempotency_key,
                        parent_id,
                        parent_ref,
                        base_branch,
                        status,
                        last_error
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        idempotency_key,
                        parent_id,
                        parent_ref,
                        base_branch,
                        "pending",
                        None,
                    ),
                )
            return operation_id

    def mark_parent_land_completed(self, operation_id: str) -> None:
        with self._lock:
            self._update_parent_land_status(
                operation_id,
                status="completed",
                last_error=None,
            )

    def mark_parent_land_failed(
        self,
        operation_id: str,
        error_message: str,
    ) -> None:
        with self._lock:
            self._update_parent_land_status(
                operation_id,
                status="pending",
                last_error=error_message,
            )

    def load_parent_land_operations(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT operation_id, idempotency_key, parent_id, parent_ref,
                           base_branch, status, last_error
                    FROM parent_land_ledger
                    ORDER BY operation_id
                    """
                ).fetchall()
            return [
                {
                    "operation_id": operation_id,
                    "idempotency_key": idempotency_key,
                    "parent_id": parent_id,
                    "parent_ref": parent_ref,
                    "base_branch": base_branch,
                    "status": status,
                    "last_error": last_error,
                }
                for (
                    operation_id,
                    idempotency_key,
                    parent_id,
                    parent_ref,
                    base_branch,
                    status,
                    last_error,
                ) in rows
            ]

    def create_parent_run(
        self,
        *,
        parent_id: str,
        initial_phase: str,
        spec_path: str,
        spec_checksum: str,
        approval_evidence: str,
        effects: tuple[BacklogEffect, ...] = (),
    ) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        INSERT INTO parent_run_state (
                            parent_id,
                            phase,
                            spec_path,
                            spec_checksum,
                            approval_evidence
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            parent_id,
                            initial_phase,
                            spec_path,
                            spec_checksum,
                            approval_evidence,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    if error.sqlite_errorcode in (
                        sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,
                        sqlite3.SQLITE_CONSTRAINT_UNIQUE,
                    ):
                        raise ParentRunExists(parent_id) from error
                    raise
                for effect in effects:
                    self._record_tracker_effect(connection, effect)

    def load_parent_run(self, parent_id: str) -> dict[str, str] | None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT parent_id, phase, spec_path, spec_checksum,
                           approval_evidence
                    FROM parent_run_state
                    WHERE parent_id = ?
                    """,
                    (parent_id,),
                ).fetchone()
            if row is None:
                return None
            parent_id, phase, spec_path, spec_checksum, approval_evidence = row
            return {
                "parent_id": str(parent_id),
                "phase": str(phase),
                "spec_path": str(spec_path),
                "spec_checksum": str(spec_checksum),
                "approval_evidence": str(approval_evidence),
            }

    def transition_parent(
        self,
        *,
        parent_id: str,
        expected_phase: str,
        next_phase: str,
        attempt_result: AttemptResultUpdate | None = None,
        graph: WorkflowGraphArtifact | None = None,
        roadmap_members: RoadmapMembersUpdate | None = None,
        effects: tuple[BacklogEffect, ...] = (),
    ) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if graph is not None and graph.parent_id != parent_id:
                    raise GraphError(
                        f"graph parent {graph.parent_id} does not match transition "
                        f"parent {parent_id}"
                    )
                self._transition_parent(
                    connection,
                    parent_id=parent_id,
                    expected_phase=expected_phase,
                    next_phase=next_phase,
                )
                if attempt_result is not None:
                    self._record_parent_attempt_result(
                        connection,
                        parent_id=parent_id,
                        attempt_id=attempt_result.attempt_id,
                        expected_dispatched_phase=(
                            attempt_result.expected_dispatched_phase
                        ),
                        status=attempt_result.status,
                        result_json=attempt_result.result_json,
                        error_message=attempt_result.error_message,
                    )
                if graph is not None:
                    self._record_graph(connection, graph)
                if roadmap_members is not None:
                    self._record_roadmap_members(
                        connection,
                        roadmap_id=parent_id,
                        update=roadmap_members,
                    )
                for effect in effects:
                    self._record_tracker_effect(connection, effect)

    def force_parent_phase(self, *, parent_id: str, phase: str) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE parent_run_state SET phase = ? WHERE parent_id = ?",
                    (phase, parent_id),
                )

    def load_parent_runs(self) -> list[dict[str, str]]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT parent_id, phase, spec_path, spec_checksum,
                           approval_evidence
                    FROM parent_run_state
                    ORDER BY parent_id
                    """
                ).fetchall()
            return [
                {
                    "parent_id": parent_id,
                    "phase": phase,
                    "spec_path": spec_path,
                    "spec_checksum": spec_checksum,
                    "approval_evidence": approval_evidence,
                }
                for (
                    parent_id,
                    phase,
                    spec_path,
                    spec_checksum,
                    approval_evidence,
                ) in rows
            ]

    def record_roadmap_edges(self, edges: list[dict[str, Any]]) -> None:
        """Persist parent->parent roadmap dependency edges (cycle-checked).

        An edge {from_parent_id, to_parent_id, blocks_dispatch, reason} means
        to_parent depends on from_parent. Rejects a cycle across the full
        blocking edge set so a bad decomposition fails at write time.
        """
        with self._lock:
            _reject_roadmap_cycle(edges)
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                for edge in edges:
                    connection.execute(
                        """
                        INSERT INTO smda_roadmap_edge (
                            from_parent_id,
                            to_parent_id,
                            blocks_dispatch,
                            reason
                        )
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(from_parent_id, to_parent_id) DO UPDATE SET
                            blocks_dispatch = excluded.blocks_dispatch,
                            reason = excluded.reason
                        """,
                        (
                            str(edge["from_parent_id"]),
                            str(edge["to_parent_id"]),
                            1 if bool(edge.get("blocks_dispatch")) else 0,
                            str(edge.get("reason", "")),
                        ),
                    )

    def load_roadmap_blockers(self, parent_id: str) -> tuple[str, ...]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT from_parent_id
                    FROM smda_roadmap_edge
                    WHERE to_parent_id = ? AND blocks_dispatch = 1
                    ORDER BY from_parent_id
                    """,
                    (parent_id,),
                ).fetchall()
            return tuple(str(from_parent_id) for (from_parent_id,) in rows)

    def record_roadmap_members(
        self,
        roadmap_id: str,
        members: list[dict[str, Any]],
        roadmap_edges: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._record_roadmap_members(
                    connection,
                    roadmap_id=roadmap_id,
                    update=RoadmapMembersUpdate(
                        members=tuple(members),
                        member_edges=tuple(roadmap_edges or ()),
                    ),
                )

    def load_roadmap_members(self, roadmap_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT node_id, title, body, risk_level, dependencies_json
                    FROM roadmap_member
                    WHERE roadmap_id = ?
                    ORDER BY node_id
                    """,
                    (roadmap_id,),
                ).fetchall()
            return [
                {
                    "node_id": node_id,
                    "title": title,
                    "body": body,
                    "risk_level": risk_level,
                    "dependencies": json.loads(dependencies_json),
                }
                for node_id, title, body, risk_level, dependencies_json in rows
            ]

    def load_roadmap_member_edges(self, roadmap_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT from_node_id, to_node_id, edge_type, blocks_dispatch, reason
                    FROM roadmap_member_edge
                    WHERE roadmap_id = ?
                    ORDER BY from_node_id, to_node_id
                    """,
                    (roadmap_id,),
                ).fetchall()
            return [
                {
                    "from": from_node_id,
                    "to": to_node_id,
                    "type": edge_type,
                    "blocks_dispatch": bool(blocks_dispatch),
                    "reason": reason,
                }
                for from_node_id, to_node_id, edge_type, blocks_dispatch, reason in rows
            ]

    def record_roadmap_member_projection(
        self,
        *,
        roadmap_id: str,
        node_id: str,
        issue_id: str,
    ) -> None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO roadmap_member_projection (roadmap_id, node_id, issue_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(roadmap_id, node_id) DO UPDATE SET
                        issue_id = excluded.issue_id
                    """,
                    (roadmap_id, node_id, issue_id),
                )

    def load_roadmap_member_projections(self, roadmap_id: str) -> dict[str, str]:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT node_id, issue_id
                    FROM roadmap_member_projection
                    WHERE roadmap_id = ?
                    ORDER BY node_id
                    """,
                    (roadmap_id,),
                ).fetchall()
            return {str(node_id): str(issue_id) for node_id, issue_id in rows}

    def load_roadmap_for_member(self, parent_issue_id: str) -> dict[str, str] | None:
        with self._lock:
            self._ensure_schema()
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT roadmap_id, node_id
                    FROM roadmap_member_projection
                    WHERE issue_id = ?
                    ORDER BY roadmap_id, node_id
                    LIMIT 1
                    """,
                    (parent_issue_id,),
                ).fetchone()
            if row is None:
                return None
            roadmap_id, node_id = row
            return {"roadmap_id": str(roadmap_id), "node_id": str(node_id)}

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parent_run_state (
                    parent_id TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    spec_path TEXT NOT NULL,
                    spec_checksum TEXT NOT NULL,
                    approval_evidence TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS child_run_state (
                    child_id TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    claim_owner TEXT,
                    claim_lease_expires_at REAL,
                    next_not_before REAL NOT NULL,
                    review_fix_cycles INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            child_state_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(child_run_state)")
            }
            if "review_fix_cycles" not in child_state_columns:
                connection.execute(
                    "ALTER TABLE child_run_state "
                    "ADD COLUMN review_fix_cycles INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS smda_graph (
                    parent_id TEXT PRIMARY KEY,
                    graph_checksum TEXT NOT NULL,
                    dependency_edges_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            self._ensure_columns(
                connection,
                table="smda_graph",
                columns={
                    "dependency_edges_json": "TEXT NOT NULL DEFAULT '[]'",
                },
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS smda_graph_child (
                    parent_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    acceptance_criteria_json TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    in_scope_json TEXT NOT NULL DEFAULT '[]',
                    out_of_scope_json TEXT NOT NULL DEFAULT '[]',
                    touched_surfaces_json TEXT NOT NULL DEFAULT '{}',
                    verification_json TEXT NOT NULL DEFAULT '{}',
                    risk_level TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (parent_id, node_id),
                    FOREIGN KEY(parent_id) REFERENCES smda_graph(parent_id)
                )
                """
            )
            self._ensure_columns(
                connection,
                table="smda_graph_child",
                columns={
                    "in_scope_json": "TEXT NOT NULL DEFAULT '[]'",
                    "out_of_scope_json": "TEXT NOT NULL DEFAULT '[]'",
                    "touched_surfaces_json": "TEXT NOT NULL DEFAULT '{}'",
                    "verification_json": "TEXT NOT NULL DEFAULT '{}'",
                    "risk_level": "TEXT NOT NULL DEFAULT ''",
                },
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS child_issue_projection (
                    parent_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    issue_id TEXT NOT NULL,
                    PRIMARY KEY (parent_id, node_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parent_pause (
                    parent_id TEXT PRIMARY KEY,
                    paused INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attempt_ledger (
                    attempt_id TEXT PRIMARY KEY,
                    child_id TEXT NOT NULL,
                    target_kind TEXT NOT NULL DEFAULT 'child',
                    target_id TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(attempt_ledger)")
            }
            if "target_kind" not in columns:
                connection.execute(
                    "ALTER TABLE attempt_ledger "
                    "ADD COLUMN target_kind TEXT NOT NULL DEFAULT 'child'"
                )
            if "target_id" not in columns:
                connection.execute(
                    "ALTER TABLE attempt_ledger "
                    "ADD COLUMN target_id TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "UPDATE attempt_ledger SET target_id = child_id "
                    "WHERE target_id = ''"
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
                    last_error TEXT,
                    conflicted_paths_json TEXT NOT NULL DEFAULT '[]',
                    conflict_fingerprint TEXT NOT NULL DEFAULT '',
                    resolver_attempts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._ensure_columns(
                connection,
                table="parent_accept_ledger",
                columns={
                    "conflicted_paths_json": "TEXT NOT NULL DEFAULT '[]'",
                    "conflict_fingerprint": "TEXT NOT NULL DEFAULT ''",
                    "resolver_attempts": "INTEGER NOT NULL DEFAULT 0",
                },
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parent_land_ledger (
                    operation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    parent_id TEXT NOT NULL,
                    parent_ref TEXT NOT NULL,
                    base_branch TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS smda_roadmap_edge (
                    from_parent_id TEXT NOT NULL,
                    to_parent_id TEXT NOT NULL,
                    blocks_dispatch INTEGER NOT NULL DEFAULT 1,
                    reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (from_parent_id, to_parent_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS roadmap_member (
                    roadmap_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    risk_level TEXT NOT NULL DEFAULT '',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (roadmap_id, node_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS roadmap_member_edge (
                    roadmap_id TEXT NOT NULL,
                    from_node_id TEXT NOT NULL,
                    to_node_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL DEFAULT '',
                    blocks_dispatch INTEGER NOT NULL DEFAULT 1,
                    reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (roadmap_id, from_node_id, to_node_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS roadmap_member_projection (
                    roadmap_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    issue_id TEXT NOT NULL,
                    PRIMARY KEY (roadmap_id, node_id)
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

    def _record_parent_attempt_result(
        self,
        connection: sqlite3.Connection,
        *,
        parent_id: str,
        attempt_id: str,
        expected_dispatched_phase: AttemptPhase | RoadmapPhase | str,
        status: str,
        result_json: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        result = json.dumps(result_json, sort_keys=True) if result_json else None
        changed = connection.execute(
            """
            UPDATE attempt_ledger
            SET status = ?, result_json = ?, error_message = ?
            WHERE attempt_id = ?
              AND target_id = ?
              AND target_kind IN ('parent', 'roadmap')
              AND status = 'dispatched'
              AND phase = ?
            """,
            (
                status,
                result,
                error_message,
                attempt_id,
                parent_id,
                _phase_value(expected_dispatched_phase),
            ),
        )
        if changed.rowcount != 1:
            attempt = connection.execute(
                """
                SELECT target_kind, target_id, status, phase
                FROM attempt_ledger
                WHERE attempt_id = ?
                """,
                (attempt_id,),
            ).fetchone()
            expected_phase = _phase_value(expected_dispatched_phase)
            if attempt is None:
                reason = "attempt does not exist"
            elif attempt[0] not in ("parent", "roadmap"):
                reason = f"target kind is {attempt[0]}, expected parent or roadmap"
            elif attempt[1] != parent_id:
                reason = f"target is {attempt[1]}, expected {parent_id}"
            elif attempt[2] != "dispatched":
                reason = f"status is {attempt[2]}, expected dispatched"
            else:
                reason = (
                    f"dispatched phase is {attempt[3]}, expected {expected_phase}"
                )
            raise ParentAttemptResultRejected(
                f"parent {parent_id} attempt result update rejected for "
                f"{attempt_id}: {reason}"
            )

    def _record_roadmap_members(
        self,
        connection: sqlite3.Connection,
        *,
        roadmap_id: str,
        update: RoadmapMembersUpdate,
    ) -> None:
        connection.execute(
            "DELETE FROM roadmap_member WHERE roadmap_id = ?",
            (roadmap_id,),
        )
        for member in update.members:
            connection.execute(
                """
                INSERT INTO roadmap_member (
                    roadmap_id,
                    node_id,
                    title,
                    body,
                    risk_level,
                    dependencies_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    roadmap_id,
                    str(member["node_id"]),
                    str(member["title"]),
                    str(member["body"]),
                    str(member.get("risk_level", "")),
                    json.dumps(member.get("dependencies", []), sort_keys=True),
                ),
            )
        connection.execute(
            "DELETE FROM roadmap_member_edge WHERE roadmap_id = ?",
            (roadmap_id,),
        )
        for edge in update.member_edges:
            connection.execute(
                """
                INSERT INTO roadmap_member_edge (
                    roadmap_id,
                    from_node_id,
                    to_node_id,
                    edge_type,
                    blocks_dispatch,
                    reason
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    roadmap_id,
                    str(edge["from"]),
                    str(edge["to"]),
                    str(edge.get("type", "")),
                    1 if bool(edge.get("blocks_dispatch")) else 0,
                    str(edge.get("reason", "")),
                ),
            )

    def _record_tracker_effect(
        self,
        connection: sqlite3.Connection,
        effect: BacklogEffect,
    ) -> None:
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
                effect.effect_id,
                effect.idempotency_key,
                effect.effect_type,
                effect.target_id,
                json.dumps(effect.payload, sort_keys=True),
                "pending",
                None,
            ),
        )

    def _transition_parent(
        self,
        connection: sqlite3.Connection,
        *,
        parent_id: str,
        expected_phase: str,
        next_phase: str,
    ) -> None:
        changed = connection.execute(
            """
            UPDATE parent_run_state
            SET phase = ?
            WHERE parent_id = ? AND phase = ?
            """,
            (next_phase, parent_id, expected_phase),
        )
        if changed.rowcount != 1:
            raise StaleParentTransition(
                f"parent {parent_id} is not in expected phase {expected_phase}"
            )

    def _record_graph(
        self,
        connection: sqlite3.Connection,
        graph: WorkflowGraphArtifact,
    ) -> None:
        connection.execute(
            """
            INSERT INTO smda_graph (
                parent_id,
                graph_checksum,
                dependency_edges_json
            )
            VALUES (?, ?, ?)
            ON CONFLICT(parent_id) DO UPDATE SET
                graph_checksum = excluded.graph_checksum,
                dependency_edges_json = excluded.dependency_edges_json
            """,
            (
                graph.parent_id,
                graph.graph_checksum,
                json.dumps(graph.to_dict()["dependency_edges"], sort_keys=True),
            ),
        )
        connection.execute(
            "DELETE FROM smda_graph_child WHERE parent_id = ?",
            (graph.parent_id,),
        )
        for child in graph.children:
            connection.execute(
                """
                INSERT INTO smda_graph_child (
                    parent_id,
                    node_id,
                    title,
                    body,
                    acceptance_criteria_json,
                    dependencies_json,
                    in_scope_json,
                    out_of_scope_json,
                    touched_surfaces_json,
                    verification_json,
                    risk_level
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    graph.parent_id,
                    child.node_id,
                    child.title,
                    child.body,
                    json.dumps(child.acceptance_criteria, sort_keys=True),
                    json.dumps(child.dependencies, sort_keys=True),
                    json.dumps(child.in_scope, sort_keys=True),
                    json.dumps(child.out_of_scope, sort_keys=True),
                    json.dumps(child.touched_surfaces.to_dict(), sort_keys=True),
                    json.dumps(child.verification.to_dict(), sort_keys=True),
                    child.risk_level,
                ),
            )

    @staticmethod
    def _ensure_columns(
        connection: sqlite3.Connection,
        *,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column in existing:
                continue
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
                next_not_before,
                review_fix_cycles
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
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
                    child.review_fix_cycles,
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

    def _update_parent_land_status(
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
                UPDATE parent_land_ledger
                SET status = ?, last_error = ?
                WHERE operation_id = ?
                """,
                (status, last_error, operation_id),
            )


def _reject_roadmap_cycle(edges: list[dict[str, Any]]) -> None:
    """Raise GraphError if the blocking roadmap edges form a dependency cycle."""
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if not bool(edge.get("blocks_dispatch")):
            continue
        from_parent = str(edge["from_parent_id"])
        to_parent = str(edge["to_parent_id"])
        adjacency.setdefault(from_parent, []).append(to_parent)
        adjacency.setdefault(to_parent, [])

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(parent_id: str) -> None:
        if parent_id in visited:
            return
        if parent_id in visiting:
            raise GraphError(f"Roadmap dependency cycle detected at parent: {parent_id}")
        visiting.add(parent_id)
        for downstream in adjacency.get(parent_id, ()):
            visit(downstream)
        visiting.remove(parent_id)
        visited.add(parent_id)

    for parent_id in adjacency:
        visit(parent_id)


def _phase_value(phase: AttemptPhase | RoadmapPhase | str) -> str:
    return phase.value if hasattr(phase, "value") else str(phase)


def _attempt_order_key(attempt: dict[str, Any], *, fallback_index: int) -> tuple[int, int]:
    sequence = _attempt_sequence(attempt)
    if sequence is None:
        return (0, fallback_index)
    return (1, sequence)


def _attempt_sequence(attempt: dict[str, Any]) -> int | None:
    for key in ("idempotency_key", "attempt_id"):
        value = attempt.get(key)
        if not isinstance(value, str):
            continue
        match = re.search(r"(?P<sequence>\d+)$", value)
        if match is not None:
            return int(match.group("sequence"))
    return None
