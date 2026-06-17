import pytest

from smda_scheduler.backlog import BacklogError, BacklogIssue
from smda_scheduler.linear_backlog import (
    LinearBacklogAdapter,
    LinearConfigError,
    LinearHttpTransport,
    build_linear_backlog_adapter,
)


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


def test_linear_backlog_descriptor_declares_labels_when_configured():
    adapter = LinearBacklogAdapter(
        transport=RecordingTransport([]),
        team_id="team-1",
        state_ids={},
        label_ids={"agent": "label-agent"},
    )

    assert "labels" in adapter.descriptor().capabilities


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


def test_linear_backlog_creates_child_issue_with_configured_labels():
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
                            "labels": {"nodes": [{"name": "agent"}]},
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
        label_ids={"agent": "label-agent"},
    )

    child = adapter.create_child(
        parent_id="LIN-1",
        title="Child",
        body="Context packet",
        labels={"agent"},
    )

    assert child.labels == frozenset({"agent"})
    assert transport.calls[0][1] == {
        "input": {
            "teamId": "team-1",
            "parentId": "LIN-1",
            "title": "Child",
            "description": "Context packet",
            "labelIds": ["label-agent"],
        }
    }


def test_linear_backlog_preserves_child_body_and_projects_label_ids():
    full_body = "\n".join(
        [
            "Execution: smda-child",
            "Parent issue: LIN-1",
            "Graph checksum: sha256:graph",
            "Node id: child-001",
            "In scope: scheduler runtime",
            "Verification required: pytest",
        ]
    )
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
                            "description": full_body,
                            "state": {"name": "Todo"},
                            "parent": {"identifier": "LIN-1"},
                            "labels": {"nodes": [{"name": "agent"}]},
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
        label_ids={"agent": "label-agent"},
    )

    child = adapter.create_child(
        parent_id="LIN-1",
        title="Child",
        body=full_body,
        labels={"agent"},
    )

    assert child.body == full_body
    assert transport.calls[0][1]["input"]["description"] == full_body
    assert transport.calls[0][1]["input"]["labelIds"] == ["label-agent"]


def test_linear_backlog_rejects_unconfigured_child_label():
    adapter = LinearBacklogAdapter(
        transport=RecordingTransport([]),
        team_id="team-1",
        state_ids={},
        label_ids={},
    )

    with pytest.raises(BacklogError, match="Linear label is not configured"):
        adapter.create_child(
            parent_id="LIN-1",
            title="Child",
            body="Context packet",
            labels={"agent"},
        )


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


def test_linear_backlog_lists_filtered_issues_with_pagination():
    transport = RecordingTransport(
        [
            {
                "data": {
                    "team": {
                        "issues": {
                            "nodes": [
                                {
                                    "id": "uuid-66",
                                    "identifier": "DANNY-66",
                                    "title": "SMDA parent",
                                    "description": "Run SMDA",
                                    "state": {"name": "Todo"},
                                    "parent": None,
                                    "labels": {"nodes": [{"name": "smda"}]},
                                }
                            ],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": "cursor-1",
                            },
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

    page = adapter.list_issues(
        state="Todo",
        label="smda",
        parent_id=None,
        limit=25,
        cursor=None,
    )

    assert page.issues[0] == BacklogIssue(
        id="DANNY-66",
        title="SMDA parent",
        state="Todo",
        body="Run SMDA",
        labels=frozenset({"smda"}),
    )
    assert page.has_next_page is True
    assert page.end_cursor == "cursor-1"
    assert transport.calls[0][1] == {
        "teamId": "team-1",
        "first": 25,
        "after": None,
        "filter": {
            "state": {"name": {"eq": "Todo"}},
            "labels": {"name": {"eq": "smda"}},
        },
    }


def test_linear_backlog_list_issues_scopes_to_project_when_configured():
    transport = RecordingTransport(
        [{"data": {"team": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
        project_id="proj-A",
    )

    adapter.list_issues(state="Todo", label="agent", parent_id=None, limit=25, cursor=None)

    assert transport.calls[0][1]["filter"] == {
        "state": {"name": {"eq": "Todo"}},
        "labels": {"name": {"eq": "agent"}},
        "project": {"id": {"eq": "proj-A"}},
    }


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


def test_build_linear_backlog_adapter_requires_environment():
    try:
        build_linear_backlog_adapter(env={})
    except LinearConfigError as error:
        assert "LINEAR_API_KEY" in str(error)
    else:
        raise AssertionError("Expected LinearConfigError")


def test_build_linear_backlog_adapter_uses_environment_configuration():
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHttpResponse(
            b'{"data": {"issueUpdate": {"success": true, "issue": {"identifier": "DANNY-66"}}}}'
        )

    adapter = build_linear_backlog_adapter(
        env={
            "LINEAR_API_KEY": "lin_api_test",
            "SMDA_LINEAR_TEAM_ID": "team-1",
            "SMDA_LINEAR_STATE_TODO": "state-todo",
        },
        urlopen=urlopen,
    )

    adapter.set_coarse_state("DANNY-66", "Todo")

    request, timeout = requests[0]
    assert timeout == 30.0
    assert request.headers["Authorization"] == "lin_api_test"
    assert b'"stateId": "state-todo"' in request.data


def test_build_linear_backlog_adapter_uses_environment_label_configuration():
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHttpResponse(
            b'{"data": {"issueCreate": {"success": true, "issue": {"identifier": "DANNY-101", "title": "Child", "description": "Body", "state": {"name": "Todo"}, "parent": {"identifier": "DANNY-66"}}}}}'
        )

    adapter = build_linear_backlog_adapter(
        env={
            "LINEAR_API_KEY": "lin_api_test",
            "SMDA_LINEAR_TEAM_ID": "team-1",
            "SMDA_LINEAR_STATE_TODO": "state-todo",
            "SMDA_LINEAR_LABEL_AGENT": "label-agent",
        },
        urlopen=urlopen,
    )

    adapter.create_child(
        parent_id="DANNY-66",
        title="Child",
        body="Body",
        labels={"agent"},
    )

    request, _timeout = requests[0]
    assert b'"labelIds": ["label-agent"]' in request.data
