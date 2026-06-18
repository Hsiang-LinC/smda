from collections.abc import Sequence

from smda_scheduler.backlog import BacklogIssue, BacklogPage
from smda_scheduler.scanner import scan_dispatch_candidates, scan_dispatch_candidates_multi


class RecordingBacklog:
    def __init__(self, page: BacklogPage) -> None:
        self.page = page
        self.calls: list[dict] = []

    def list_issues(
        self,
        *,
        state: str,
        label: str,
        parent_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> BacklogPage:
        self.calls.append(
            {
                "state": state,
                "label": label,
                "parent_id": parent_id,
                "limit": limit,
                "cursor": cursor,
            }
        )
        return self.page


def test_scan_dispatch_candidates_lists_backlog_candidates():
    backlog = RecordingBacklog(
        BacklogPage(
            issues=(
                BacklogIssue(
                    id="DANNY-66",
                    title="SMDA parent",
                    state="Todo",
                    labels=frozenset({"smda"}),
                ),
            ),
            has_next_page=True,
            end_cursor="cursor-1",
        )
    )

    result = scan_dispatch_candidates(
        backlog,
        state="Todo",
        label="smda",
        parent_id=None,
        limit=25,
        cursor=None,
    )

    assert result.issues[0].id == "DANNY-66"
    assert result.has_next_page is True
    assert result.end_cursor == "cursor-1"
    assert backlog.calls == [
        {
            "state": "Todo",
            "label": "smda",
            "parent_id": None,
            "limit": 25,
            "cursor": None,
        }
    ]


class MultiStateBacklog:
    def __init__(self, pages: dict[str, BacklogPage]) -> None:
        self.pages = pages
        self.states_scanned: list[str] = []

    def list_issues(self, *, state, label, parent_id, limit, cursor) -> BacklogPage:
        self.states_scanned.append(state)
        return self.pages.get(state, BacklogPage(issues=()))


def _issue(issue_id: str, state: str) -> BacklogIssue:
    return BacklogIssue(id=issue_id, title=issue_id, state=state, labels=frozenset({"agent"}))


def test_scan_multi_preserves_state_order_and_tags_source():
    backlog = MultiStateBacklog(
        {
            "In Progress": BacklogPage(issues=(_issue("DANNY-2", "In Progress"),)),
            "Todo": BacklogPage(issues=(_issue("DANNY-1", "Todo"),)),
        }
    )

    result = scan_dispatch_candidates_multi(
        backlog,
        states=["In Progress", "Todo"],
        label="agent",
        parent_id=None,
    )

    assert backlog.states_scanned == ["In Progress", "Todo"]
    assert result == [("In Progress", backlog.pages["In Progress"].issues[0]),
                      ("Todo", backlog.pages["Todo"].issues[0])]
