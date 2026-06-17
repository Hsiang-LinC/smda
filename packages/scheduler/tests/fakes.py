from __future__ import annotations

from dataclasses import dataclass, field, replace

from smda_scheduler.adapters import AdapterDescriptor
from smda_scheduler.backlog import BacklogIssue, BacklogError, BacklogPage


def fake_registry() -> dict[str, AdapterDescriptor]:
    return {
        "fake-execution": AdapterDescriptor(
            id="fake-execution",
            version="0.1.0",
            capabilities=frozenset(
                {"worktree_per_attempt", "structured_output_recovery", "session_resume"}
            ),
        ),
        "fake-backlog": AdapterDescriptor(
            id="fake-backlog",
            version="0.1.0",
            capabilities=frozenset({"create_child", "comments", "coarse_states"}),
        ),
        "fake-context": AdapterDescriptor(
            id="fake-context",
            version="0.1.0",
            capabilities=frozenset({"bootloader", "spec_locations", "repo_commands"}),
        ),
    }


@dataclass(frozen=True)
class FakeBacklogIssue:
    id: str
    title: str
    state: str
    body: str = ""
    parent_id: str | None = None
    labels: frozenset[str] = frozenset()
    comments: list[str] = field(default_factory=list)


class FakeBacklogAdapter:
    def __init__(self, *, issues: dict[str, FakeBacklogIssue] | None = None) -> None:
        self._issues = dict(issues or {})
        self._blocking: dict[str, set[str]] = {}
        self._next_child_number = 1

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            id="fake-backlog",
            version="0.1.0",
            capabilities=frozenset(
                {
                    "create_child",
                    "coarse_states",
                    "comments",
                    "hierarchy",
                    "blocking_relations",
                    "labels",
                }
            ),
        )

    def fetch_issue(self, issue_id: str) -> FakeBacklogIssue:
        try:
            return self._issues[issue_id]
        except KeyError as error:
            raise BacklogError(issue_id) from error

    def list_issues(
        self,
        *,
        state: str,
        label: str,
        parent_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> BacklogPage:
        issues = [
            BacklogIssue(
                id=issue.id,
                title=issue.title,
                state=issue.state,
                body=issue.body,
                parent_id=issue.parent_id,
                labels=issue.labels,
                comments=issue.comments,
            )
            for issue in self._issues.values()
            if issue.state == state
            and (not label or label in issue.labels)
            and issue.parent_id == parent_id
        ]
        return BacklogPage(issues=tuple(sorted(issues, key=lambda issue: issue.id)[:limit]))

    def set_coarse_state(self, issue_id: str, state: str) -> None:
        issue = self.fetch_issue(issue_id)
        self._issues[issue_id] = replace(issue, state=state)

    def comment(self, issue_id: str, body: str) -> None:
        issue = self.fetch_issue(issue_id)
        self._issues[issue_id] = replace(issue, comments=[*issue.comments, body])

    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ) -> FakeBacklogIssue:
        self.fetch_issue(parent_id)
        child_id = f"{parent_id}-C{self._next_child_number}"
        self._next_child_number += 1
        child = FakeBacklogIssue(
            id=child_id,
            title=title,
            body=body,
            state="Todo",
            parent_id=parent_id,
            labels=frozenset(labels or ()),
        )
        self._issues[child_id] = child
        return child

    def project_hierarchy(self, parent_id: str) -> list[str]:
        self.fetch_issue(parent_id)
        return sorted(
            issue.id for issue in self._issues.values() if issue.parent_id == parent_id
        )

    def link_blocking(self, *, blocker_id: str, blocked_id: str) -> None:
        self.fetch_issue(blocker_id)
        self.fetch_issue(blocked_id)
        self._blocking.setdefault(blocked_id, set()).add(blocker_id)

    def query_blocked_by(self, issue_id: str) -> list[str]:
        self.fetch_issue(issue_id)
        return sorted(self._blocking.get(issue_id, set()))
