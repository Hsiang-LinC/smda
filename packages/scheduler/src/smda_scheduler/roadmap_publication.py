from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.workflow import GraphError, RoadmapPhase


class RoadmapPublicationBacklog(Protocol):
    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ) -> BacklogIssue: ...

    def link_blocking(self, *, blocker_id: str, blocked_id: str) -> None: ...

    def set_coarse_state(self, issue_id: str, state: str) -> None: ...


@dataclass(frozen=True)
class RoadmapPublicationResult:
    target_state: str
    comment: str


_ROADMAP_MEMBER_HELD_STATE = "Blocked"
_ROADMAP_MEMBER_DISPATCH_STATE = "Todo"


def publish_roadmap_members(
    *,
    issue: BacklogIssue,
    ledger: PhaseLedger,
    backlog: RoadmapPublicationBacklog,
    child_labels: frozenset[str] = frozenset(),
) -> RoadmapPublicationResult:
    roadmap_run = _roadmap_run_for_publication(ledger, issue.id)
    members = ledger.load_roadmap_members(issue.id)
    if not members:
        raise GraphError(f"Roadmap has no persisted members: {issue.id}")
    projections = ledger.load_roadmap_member_projections(issue.id)

    for member in members:
        node_id = str(member["node_id"])
        if node_id in projections:
            continue
        created = backlog.create_child(
            parent_id=issue.id,
            title=str(member["title"]),
            body=_roadmap_member_issue_body(
                roadmap_id=issue.id,
                spec_path=roadmap_run["spec_path"],
                member=member,
            ),
            labels=child_labels,
        )
        backlog.set_coarse_state(created.id, _ROADMAP_MEMBER_HELD_STATE)
        ledger.record_roadmap_member_projection(
            roadmap_id=issue.id,
            node_id=node_id,
            issue_id=created.id,
        )
        projections[node_id] = created.id

    parent_edges = _parent_edges_for_publication(ledger, issue.id, members, projections)
    if parent_edges:
        ledger.record_roadmap_edges(parent_edges)
    for edge in parent_edges:
        if not bool(edge["blocks_dispatch"]):
            continue
        backlog.link_blocking(
            blocker_id=str(edge["from_parent_id"]),
            blocked_id=str(edge["to_parent_id"]),
        )

    for member in members:
        member_issue_id = projections[str(member["node_id"])]
        backlog.set_coarse_state(member_issue_id, _ROADMAP_MEMBER_DISPATCH_STATE)

    next_phase = RoadmapPhase.ROADMAP_PUBLISHED.value
    return RoadmapPublicationResult(
        target_state="In Progress",
        comment=(
            f"SMDA roadmap parent issues published for {issue.id}.\n\n"
            f"Roadmap phase: `{next_phase}`\n"
            f"Published parents: {len(members)}"
        ),
    )


def _roadmap_run_for_publication(
    ledger: PhaseLedger,
    roadmap_id: str,
) -> dict[str, str]:
    parent_run = ledger.load_parent_run(roadmap_id)
    if parent_run is None:
        raise GraphError(f"Roadmap run state not found: {roadmap_id}")
    if parent_run["phase"] != RoadmapPhase.ROADMAP_PUBLICATION_READY.value:
        raise GraphError(
            "Roadmap publication requires "
            f"{RoadmapPhase.ROADMAP_PUBLICATION_READY.value}: {roadmap_id}"
        )
    return parent_run


def _parent_edges_for_publication(
    ledger: PhaseLedger,
    roadmap_id: str,
    members: list[dict[str, object]],
    projections: dict[str, str],
) -> list[dict[str, object]]:
    return [
        {
            "from_parent_id": projections[str(edge["from"])],
            "to_parent_id": projections[str(edge["to"])],
            "blocks_dispatch": bool(edge["blocks_dispatch"]),
            "reason": str(edge.get("reason", "")),
        }
        for edge in _roadmap_edges_for_publication(ledger, roadmap_id, members)
    ]


def _roadmap_edges_for_publication(
    ledger: PhaseLedger,
    roadmap_id: str,
    members: list[dict[str, object]],
) -> list[dict[str, object]]:
    edges = ledger.load_roadmap_member_edges(roadmap_id)
    if edges:
        return edges
    fallback_edges: list[dict[str, object]] = []
    for member in members:
        for dependency in _string_list(member.get("dependencies", []), "dependencies"):
            fallback_edges.append(
                {
                    "from": dependency,
                    "to": str(member["node_id"]),
                    "type": "sequencing_only",
                    "blocks_dispatch": True,
                    "reason": f"{member['node_id']} depends on {dependency}",
                }
            )
    return fallback_edges


def _roadmap_member_issue_body(
    *,
    roadmap_id: str,
    spec_path: str,
    member: dict[str, object],
) -> str:
    dependencies = _string_list(member.get("dependencies", []), "dependencies")
    return "\n".join(
        [
            "Execution: smda",
            f"Source: {spec_path}",
            f"Roadmap issue: {roadmap_id}",
            f"Roadmap node id: {member['node_id']}",
            f"Risk level: {member['risk_level']}",
            *_prefixed_lines("Roadmap dependencies", dependencies),
            "",
            str(member["body"]),
        ]
    )


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise GraphError(f"roadmap member {field_name} must be a string list")
    return value


def _prefixed_lines(prefix: str, values: list[str]) -> list[str]:
    if not values:
        return [f"{prefix}: none"]
    return [f"{prefix}: {value}" for value in values]
