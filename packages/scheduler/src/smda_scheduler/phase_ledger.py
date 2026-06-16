from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from smda_scheduler.scheduling import ChildRunState, Claim, SchedulerState
from smda_scheduler.sandcastle_execution import AttemptPhase
from smda_scheduler.workflow import ChildPhase, GraphError


class PhaseLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_scheduler_state(self) -> SchedulerState:
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
        phase: AttemptPhase | str,
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

    def record_attempt_result_and_parent_run(
        self,
        *,
        attempt_id: str,
        status: str,
        result_json: dict[str, Any] | None,
        error_message: str | None,
        parent_id: str,
        phase: str,
        spec_path: str,
        spec_checksum: str,
        approval_evidence: str,
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
            self._record_parent_run(
                connection,
                parent_id=parent_id,
                phase=phase,
                spec_path=spec_path,
                spec_checksum=spec_checksum,
                approval_evidence=approval_evidence,
            )

    def record_attempt_result_parent_run_and_graph(
        self,
        *,
        attempt_id: str,
        status: str,
        result_json: dict[str, Any] | None,
        error_message: str | None,
        parent_id: str,
        phase: str,
        spec_path: str,
        spec_checksum: str,
        approval_evidence: str,
        graph_checksum: str,
        children: list[dict[str, Any]],
        dependency_edges: list[dict[str, Any]] | None = None,
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
            self._record_parent_run(
                connection,
                parent_id=parent_id,
                phase=phase,
                spec_path=spec_path,
                spec_checksum=spec_checksum,
                approval_evidence=approval_evidence,
            )
            self._record_graph(
                connection,
                parent_id=parent_id,
                graph_checksum=graph_checksum,
                children=children,
                dependency_edges=dependency_edges,
            )

    def load_attempts(self) -> list[dict[str, Any]]:
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

    def record_graph(
        self,
        *,
        parent_id: str,
        graph_checksum: str,
        children: list[dict[str, Any]],
        dependency_edges: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._record_graph(
                connection,
                parent_id=parent_id,
                graph_checksum=graph_checksum,
                children=children,
                dependency_edges=dependency_edges,
            )

    def load_graph(self, parent_id: str) -> dict[str, Any]:
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
                ORDER BY node_id
                """,
                (parent_id,),
            ).fetchall()
        return {
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
        }

    def record_child_issue_projection(
        self,
        *,
        parent_id: str,
        node_id: str,
        issue_id: str,
    ) -> None:
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

    def record_parent_run(
        self,
        *,
        parent_id: str,
        phase: str,
        spec_path: str,
        spec_checksum: str,
        approval_evidence: str,
    ) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._record_parent_run(
                connection,
                parent_id=parent_id,
                phase=phase,
                spec_path=spec_path,
                spec_checksum=spec_checksum,
                approval_evidence=approval_evidence,
            )

    def load_parent_runs(self) -> list[dict[str, str]]:
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

    def _record_parent_run(
        self,
        connection: sqlite3.Connection,
        *,
        parent_id: str,
        phase: str,
        spec_path: str,
        spec_checksum: str,
        approval_evidence: str,
    ) -> None:
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
            ON CONFLICT(parent_id) DO UPDATE SET
                phase = excluded.phase,
                spec_path = excluded.spec_path,
                spec_checksum = excluded.spec_checksum,
                approval_evidence = excluded.approval_evidence
            """,
            (
                parent_id,
                phase,
                spec_path,
                spec_checksum,
                approval_evidence,
            ),
        )

    def _record_graph(
        self,
        connection: sqlite3.Connection,
        *,
        parent_id: str,
        graph_checksum: str,
        children: list[dict[str, Any]],
        dependency_edges: list[dict[str, Any]] | None = None,
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
                parent_id,
                graph_checksum,
                json.dumps(dependency_edges or [], sort_keys=True),
            ),
        )
        connection.execute(
            "DELETE FROM smda_graph_child WHERE parent_id = ?",
            (parent_id,),
        )
        for child in children:
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
                    parent_id,
                    str(child["node_id"]),
                    str(child["title"]),
                    str(child["body"]),
                    json.dumps(child.get("acceptance_criteria", []), sort_keys=True),
                    json.dumps(child.get("dependencies", []), sort_keys=True),
                    json.dumps(child.get("in_scope", []), sort_keys=True),
                    json.dumps(child.get("out_of_scope", []), sort_keys=True),
                    json.dumps(child.get("touched_surfaces", {}), sort_keys=True),
                    json.dumps(child.get("verification", {}), sort_keys=True),
                    str(child.get("risk_level", "")),
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


def _phase_value(phase: AttemptPhase | str) -> str:
    return phase.value if hasattr(phase, "value") else str(phase)
