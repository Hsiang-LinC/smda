from __future__ import annotations

import sqlite3
from pathlib import Path

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
