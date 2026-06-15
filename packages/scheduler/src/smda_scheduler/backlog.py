from __future__ import annotations

from dataclasses import dataclass, field


class BacklogError(KeyError):
    """Raised when a backlog operation references missing tracker state."""


@dataclass(frozen=True)
class BacklogIssue:
    id: str
    title: str
    state: str
    body: str = ""
    parent_id: str | None = None
    labels: frozenset[str] = frozenset()
    comments: list[str] = field(default_factory=list)
