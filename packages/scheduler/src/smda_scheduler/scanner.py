from __future__ import annotations

from typing import Protocol

from smda_scheduler.backlog import BacklogPage


class CandidateBacklog(Protocol):
    def list_issues(
        self,
        *,
        state: str,
        label: str,
        parent_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> BacklogPage: ...


def scan_dispatch_candidates(
    backlog: CandidateBacklog,
    *,
    state: str,
    label: str,
    parent_id: str | None,
    limit: int = 50,
    cursor: str | None = None,
) -> BacklogPage:
    return backlog.list_issues(
        state=state,
        label=label,
        parent_id=parent_id,
        limit=limit,
        cursor=cursor,
    )
