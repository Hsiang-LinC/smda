import pytest

from smda_scheduler.backlog import BacklogError, BacklogIssue
from smda_scheduler.linear_backlog import LinearBacklogAdapter, LinearHttpTransport


class RecordingTransport:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def execute(self, query: str, variables: dict) -> dict:
        self.calls.append((query, variables))
        return self.responses.pop(0)


class FakeHttpResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self) -> bytes:
        return self.body


def test_linear_backlog_descriptor_declares_mvp_capabilities():
    adapter = LinearBacklogAdapter(
        transport=RecordingTransport([]),
        team_id="team-1",
        state_ids={},
    )

    descriptor = adapter.descriptor()

    assert descriptor.id == "linear"
    assert descriptor.capabilities >= frozenset(
        {
            "create_child",
            "coarse_states",
            "comments",
            "hierarchy",
            "blocking_relations",
        }
    )
    assert "labels" not in descriptor.capabilities


def test_linear_backlog_fetch_issue_maps_issue_fields():
    transport = RecordingTransport(
        [
            {
                "data": {
                    "issue": {
                        "id": "uuid-1",
                        "identifier": "LIN-1",
                        "title": "Parent spec",
                        "description": "Body",
                        "state": {"name": "Todo"},
                        "parent": {"identifier": "LIN-0"},
                    }
                }
            }
        ]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
    )

    issue = adapter.fetch_issue("LIN-1")

    assert issue == BacklogIssue(
        id="LIN-1",
        title="Parent spec",
        state="Todo",
        body="Body",
        parent_id="LIN-0",
    )
    assert transport.calls[0][1] == {"id": "LIN-1"}


def test_linear_backlog_updates_coarse_state_with_configured_state_id():
    transport = RecordingTransport(
        [{"data": {"issueUpdate": {"success": True, "issue": {"identifier": "LIN-1"}}}}]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={"In Progress": "state-progress"},
    )

    adapter.set_coarse_state("LIN-1", "In Progress")

    assert transport.calls[0][1] == {
        "id": "LIN-1",
        "input": {"stateId": "state-progress"},
    }


def test_linear_backlog_creates_comment():
    transport = RecordingTransport(
        [{"data": {"commentCreate": {"success": True, "comment": {"id": "comment-1"}}}}]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
    )

    adapter.comment("LIN-1", "Started by SMDA")

    assert transport.calls[0][1] == {
        "input": {"issueId": "LIN-1", "body": "Started by SMDA"}
    }


def test_linear_backlog_creates_child_issue_with_parent():
    transport = RecordingTransport(
        [
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "uuid-2",
                            "identifier": "LIN-2",
                            "title": "Child",
                            "description": "Context packet",
                            "state": {"name": "Todo"},
                            "parent": {"identifier": "LIN-1"},
                        },
                    }
                }
            }
        ]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
    )

    child = adapter.create_child(parent_id="LIN-1", title="Child", body="Context packet")

    assert child.id == "LIN-2"
    assert child.parent_id == "LIN-1"
    assert transport.calls[0][1] == {
        "input": {
            "teamId": "team-1",
            "parentId": "LIN-1",
            "title": "Child",
            "description": "Context packet",
        }
    }


def test_linear_backlog_projects_hierarchy_from_children_connection():
    transport = RecordingTransport(
        [
            {
                "data": {
                    "issue": {
                        "children": {
                            "nodes": [
                                {"identifier": "LIN-3"},
                                {"identifier": "LIN-2"},
                            ]
                        }
                    }
                }
            }
        ]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
    )

    assert adapter.project_hierarchy("LIN-1") == ["LIN-2", "LIN-3"]


def test_linear_backlog_links_blocking_relation():
    transport = RecordingTransport(
        [
            {
                "data": {
                    "issueRelationCreate": {
                        "success": True,
                        "issueRelation": {"id": "relation-1", "type": "blocks"},
                    }
                }
            }
        ]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
    )

    adapter.link_blocking(blocker_id="LIN-1", blocked_id="LIN-2")

    assert transport.calls[0][1] == {
        "input": {
            "issueId": "LIN-1",
            "relatedIssueId": "LIN-2",
            "type": "blocks",
        }
    }


def test_linear_backlog_projects_blockers_from_relations():
    transport = RecordingTransport(
        [
            {
                "data": {
                    "issue": {
                        "relations": {
                            "nodes": [
                                {
                                    "type": "blocks",
                                    "issue": {"identifier": "LIN-1"},
                                    "relatedIssue": {"identifier": "LIN-2"},
                                },
                                {
                                    "type": "related",
                                    "issue": {"identifier": "LIN-9"},
                                    "relatedIssue": {"identifier": "LIN-2"},
                                },
                            ]
                        }
                    }
                }
            }
        ]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
    )

    assert adapter.query_blocked_by("LIN-2") == ["LIN-1"]


def test_linear_backlog_raises_named_error_on_graphql_errors():
    transport = RecordingTransport([{"errors": [{"message": "No issue found"}]}])
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
    )

    with pytest.raises(BacklogError, match="No issue found"):
        adapter.fetch_issue("LIN-404")


def test_linear_http_transport_posts_graphql_with_personal_api_key():
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeHttpResponse(b'{"data": {"viewer": {"id": "me"}}}')

    transport = LinearHttpTransport(
        api_key="lin_api_test",
        urlopen=urlopen,
        timeout_seconds=12.0,
    )

    response = transport.execute("query Me { viewer { id } }", {"first": 1})

    assert response == {"data": {"viewer": {"id": "me"}}}
    request, timeout = calls[0]
    assert request.full_url == "https://api.linear.app/graphql"
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["Authorization"] == "lin_api_test"
    assert request.data == b'{"query": "query Me { viewer { id } }", "variables": {"first": 1}}'
