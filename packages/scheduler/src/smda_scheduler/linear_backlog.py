from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from smda_scheduler.adapters import AdapterDescriptor
from smda_scheduler.backlog import BacklogError, BacklogIssue


class GraphQLTransport(Protocol):
    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]: ...


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
    ) -> None:
        self._transport = transport
        self._team_id = team_id
        self._state_ids = dict(state_ids)

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            id="linear",
            version="0.1.0",
            capabilities=frozenset(
                {
                    "create_child",
                    "coarse_states",
                    "comments",
                    "hierarchy",
                    "blocking_relations",
                }
            ),
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
        if labels:
            raise BacklogError("Linear label projection is not implemented")

        mutation = self._execute_success_mutation(
            CREATE_ISSUE,
            {
                "input": {
                    "teamId": self._team_id,
                    "parentId": parent_id,
                    "title": title,
                    "description": body,
                }
            },
            "issueCreate",
        )
        _require_success(mutation, "issueCreate")
        issue = mutation.get("issue")
        if issue is None:
            raise BacklogError("Linear issueCreate returned no issue")
        return _map_issue(issue)

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


def _map_issue(issue: dict[str, Any]) -> BacklogIssue:
    parent = issue.get("parent")
    return BacklogIssue(
        id=_issue_identifier(issue),
        title=issue.get("title") or "",
        state=(issue.get("state") or {}).get("name") or "",
        body=issue.get("description") or "",
        parent_id=_issue_identifier(parent) if parent else None,
    )


def _issue_identifier(issue: dict[str, Any]) -> str:
    return issue.get("identifier") or issue["id"]


def _matches_issue(issue: dict[str, Any], issue_id: str) -> bool:
    return issue.get("identifier") == issue_id or issue.get("id") == issue_id


def _require_success(mutation: dict[str, Any], mutation_name: str) -> None:
    if not mutation.get("success"):
        raise BacklogError(f"Linear {mutation_name} did not succeed")


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
