from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from smda_scheduler.adapters import AdapterDescriptor
from smda_scheduler.backlog import BacklogError, BacklogIssue, BacklogPage


class GraphQLTransport(Protocol):
    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]: ...


class LinearConfigError(ValueError):
    """Raised when Linear adapter credentials or state ids are missing."""


class LinearHttpTransport:
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = "https://api.linear.app/graphql",
        timeout_seconds: float = 30.0,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._urlopen = urlopen

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._api_key,
            },
            method="POST",
        )
        with self._urlopen(request, timeout=self._timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


class LinearBacklogAdapter:
    def __init__(
        self,
        *,
        transport: GraphQLTransport,
        team_id: str,
        state_ids: dict[str, str],
        label_ids: dict[str, str] | None = None,
        project_id: str | None = None,
    ) -> None:
        self._transport = transport
        self._team_id = team_id
        self._state_ids = dict(state_ids)
        self._label_ids = dict(label_ids or {})
        self._project_id = project_id

    def descriptor(self) -> AdapterDescriptor:
        capabilities = {
            "create_child",
            "coarse_states",
            "comments",
            "hierarchy",
            "blocking_relations",
        }
        if self._label_ids:
            capabilities.add("labels")
        return AdapterDescriptor(
            id="linear",
            version="0.1.0",
            capabilities=frozenset(capabilities),
        )

    def fetch_issue(self, issue_id: str) -> BacklogIssue:
        payload = self._execute(
            FETCH_ISSUE,
            {"id": issue_id},
        )
        issue = payload.get("issue")
        if issue is None:
            raise BacklogError(f"Linear issue not found: {issue_id}")
        return _map_issue(issue)

    def set_coarse_state(self, issue_id: str, state: str) -> None:
        try:
            state_id = self._state_ids[state]
        except KeyError as error:
            raise BacklogError(f"Linear state is not configured: {state}") from error

        mutation = self._execute_success_mutation(
            UPDATE_ISSUE,
            {
                "id": issue_id,
                "input": {"stateId": state_id},
            },
            "issueUpdate",
        )
        _require_success(mutation, "issueUpdate")

    def comment(self, issue_id: str, body: str) -> None:
        mutation = self._execute_success_mutation(
            CREATE_COMMENT,
            {"input": {"issueId": issue_id, "body": body}},
            "commentCreate",
        )
        _require_success(mutation, "commentCreate")

    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ) -> BacklogIssue:
        input_payload: dict[str, Any] = {
            "teamId": self._team_id,
            "parentId": parent_id,
            "title": title,
            "description": body,
        }
        if self._project_id is not None:
            input_payload["projectId"] = self._project_id
        if labels:
            try:
                input_payload["labelIds"] = sorted(
                    self._label_ids[label] for label in labels
                )
            except KeyError as error:
                raise BacklogError(
                    f"Linear label is not configured: {error.args[0]}"
                ) from error

        mutation = self._execute_success_mutation(
            CREATE_ISSUE,
            {"input": input_payload},
            "issueCreate",
        )
        _require_success(mutation, "issueCreate")
        issue = mutation.get("issue")
        if issue is None:
            raise BacklogError("Linear issueCreate returned no issue")
        return _map_issue(issue)

    def list_issues(
        self,
        *,
        state: str,
        label: str,
        parent_id: str | None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> BacklogPage:
        filter_input: dict[str, Any] = {
            "state": {"name": {"eq": state}},
            "labels": {"name": {"eq": label}},
        }
        if self._project_id is not None:
            filter_input["project"] = {"id": {"eq": self._project_id}}
        if parent_id is not None:
            filter_input["parent"] = {"id": {"eq": parent_id}}

        payload = self._execute(
            LIST_TEAM_ISSUES,
            {
                "teamId": self._team_id,
                "first": limit,
                "after": cursor,
                "filter": filter_input,
            },
        )
        team = payload.get("team")
        if team is None:
            raise BacklogError(f"Linear team not found: {self._team_id}")
        issues = team.get("issues") or {}
        page_info = issues.get("pageInfo") or {}
        return BacklogPage(
            issues=tuple(_map_issue(issue) for issue in issues.get("nodes", [])),
            has_next_page=bool(page_info.get("hasNextPage")),
            end_cursor=page_info.get("endCursor"),
        )

    def project_hierarchy(self, parent_id: str) -> list[str]:
        payload = self._execute(
            FETCH_CHILDREN,
            {"id": parent_id},
        )
        issue = payload.get("issue")
        if issue is None:
            raise BacklogError(f"Linear issue not found: {parent_id}")
        nodes = issue.get("children", {}).get("nodes", [])
        return sorted(_issue_identifier(node) for node in nodes)

    def link_blocking(self, *, blocker_id: str, blocked_id: str) -> None:
        mutation = self._execute_success_mutation(
            CREATE_RELATION,
            {
                "input": {
                    "issueId": blocker_id,
                    "relatedIssueId": blocked_id,
                    "type": "blocks",
                }
            },
            "issueRelationCreate",
        )
        _require_success(mutation, "issueRelationCreate")

    def query_blocked_by(self, issue_id: str) -> list[str]:
        payload = self._execute(
            FETCH_RELATIONS,
            {"id": issue_id},
        )
        issue = payload.get("issue")
        if issue is None:
            raise BacklogError(f"Linear issue not found: {issue_id}")

        blockers: list[str] = []
        for relation in issue.get("relations", {}).get("nodes", []):
            if relation.get("type") != "blocks":
                continue
            source = relation.get("issue") or {}
            target = relation.get("relatedIssue") or {}
            if _matches_issue(target, issue_id):
                blockers.append(_issue_identifier(source))
        return sorted(blockers)

    def _execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._transport.execute(query, variables)
        if errors := response.get("errors"):
            messages = "; ".join(
                str(error.get("message", error)) for error in errors
            )
            raise BacklogError(messages)
        data = response.get("data")
        if data is None:
            raise BacklogError("Linear response did not include data")
        return data

    def _execute_success_mutation(
        self,
        query: str,
        variables: dict[str, Any],
        key: str,
    ) -> dict[str, Any]:
        payload = self._execute(query, variables)
        mutation = payload.get(key)
        if mutation is None:
            raise BacklogError(f"Linear response did not include {key}")
        return mutation


def build_linear_backlog_adapter(
    *,
    env: dict[str, str],
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> LinearBacklogAdapter:
    api_key = _required_env(env, "LINEAR_API_KEY")
    team_id = _required_env(env, "SMDA_LINEAR_TEAM_ID")
    state_ids = _state_ids_from_env(env)
    project_id = env.get("SMDA_LINEAR_PROJECT_ID") or None
    return LinearBacklogAdapter(
        transport=LinearHttpTransport(api_key=api_key, urlopen=urlopen),
        team_id=team_id,
        state_ids=state_ids,
        label_ids=_label_ids_from_env(env),
        project_id=project_id,
    )


def _map_issue(issue: dict[str, Any]) -> BacklogIssue:
    parent = issue.get("parent")
    labels = issue.get("labels", {}).get("nodes", [])
    return BacklogIssue(
        id=_issue_identifier(issue),
        title=issue.get("title") or "",
        state=(issue.get("state") or {}).get("name") or "",
        body=issue.get("description") or "",
        parent_id=_issue_identifier(parent) if parent else None,
        labels=frozenset(
            label["name"]
            for label in labels
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        ),
    )


def _issue_identifier(issue: dict[str, Any]) -> str:
    return issue.get("identifier") or issue["id"]


def _matches_issue(issue: dict[str, Any], issue_id: str) -> bool:
    return issue.get("identifier") == issue_id or issue.get("id") == issue_id


def _require_success(mutation: dict[str, Any], mutation_name: str) -> None:
    if not mutation.get("success"):
        raise BacklogError(f"Linear {mutation_name} did not succeed")


def _required_env(env: dict[str, str], key: str) -> str:
    try:
        value = env[key]
    except KeyError as error:
        raise LinearConfigError(f"Missing required Linear environment: {key}") from error
    if not value:
        raise LinearConfigError(f"Missing required Linear environment: {key}")
    return value


def _state_ids_from_env(env: dict[str, str]) -> dict[str, str]:
    prefix = "SMDA_LINEAR_STATE_"
    state_ids = {
        key.removeprefix(prefix).replace("_", " ").title(): value
        for key, value in env.items()
        if key.startswith(prefix) and value
    }
    if not state_ids:
        raise LinearConfigError(
            "Missing required Linear state ids: set SMDA_LINEAR_STATE_<NAME>"
        )
    return state_ids


def _label_ids_from_env(env: dict[str, str]) -> dict[str, str]:
    prefix = "SMDA_LINEAR_LABEL_"
    return {
        key.removeprefix(prefix).lower().replace("_", "-"): value
        for key, value in env.items()
        if key.startswith(prefix) and value
    }


FETCH_ISSUE = """
query SmdaFetchIssue($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    state { name }
    parent { id identifier }
  }
}
"""

UPDATE_ISSUE = """
mutation SmdaUpdateIssue($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue { id identifier }
  }
}
"""

CREATE_COMMENT = """
mutation SmdaCreateComment($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment { id }
  }
}
"""

CREATE_ISSUE = """
mutation SmdaCreateChildIssue($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      id
      identifier
      title
      description
      state { name }
      parent { id identifier }
    }
  }
}
"""

LIST_TEAM_ISSUES = """
query SmdaListTeamIssues(
  $teamId: String!,
  $filter: IssueFilter,
  $first: Int!,
  $after: String
) {
  team(id: $teamId) {
    issues(filter: $filter, first: $first, after: $after) {
      nodes {
        id
        identifier
        title
        description
        state { name }
        parent { id identifier }
        labels { nodes { name } }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

FETCH_CHILDREN = """
query SmdaFetchChildren($id: String!) {
  issue(id: $id) {
    id
    identifier
    children {
      nodes { id identifier }
    }
  }
}
"""

CREATE_RELATION = """
mutation SmdaCreateIssueRelation($input: IssueRelationCreateInput!) {
  issueRelationCreate(input: $input) {
    success
    issueRelation { id type }
  }
}
"""

FETCH_RELATIONS = """
query SmdaFetchRelations($id: String!) {
  issue(id: $id) {
    id
    identifier
    relations {
      nodes {
        type
        issue { id identifier }
        relatedIssue { id identifier }
      }
    }
  }
}
"""
