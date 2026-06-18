from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from smda_scheduler.backlog import BacklogIssue, BacklogPage


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


def scan_dispatch_candidates_multi(
    backlog: CandidateBacklog,
    *,
    states: Sequence[str],
    label: str,
    parent_id: str | None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[tuple[str, BacklogIssue]]:
    candidates: list[tuple[str, BacklogIssue]] = []
    for state in states:
        page = backlog.list_issues(
            state=state,
            label=label,
            parent_id=parent_id,
            limit=limit,
            cursor=cursor,
        )
        candidates.extend((state, issue) for issue in page.issues)
    return candidates
