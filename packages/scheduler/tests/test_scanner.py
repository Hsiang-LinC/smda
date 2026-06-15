from smda_scheduler.backlog import BacklogIssue, BacklogPage
from smda_scheduler.scanner import scan_dispatch_candidates


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
