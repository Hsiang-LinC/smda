from __future__ import annotations

from dataclasses import dataclass

from smda_scheduler.schema_artifact import RISK_LEVELS
from smda_scheduler.workflow import (
    ChildNode,
    DependencyEdge,
    GraphError,
    WorkflowGraph,
    validate_graph,
)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise GraphError(f"{field} must be a non-empty string")
    return value


def _strings(value: object, field: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise GraphError(f"{field} must be a string list")
    if required and not value:
        raise GraphError(f"{field} must not be empty")
    return tuple(value)


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GraphError(f"{field} must be an object")
    return value


@dataclass(frozen=True)
class TouchedSurfaces:
    files: tuple[str, ...]
    modules: tuple[str, ...]
    contracts: tuple[str, ...]
    docs: tuple[str, ...]
    tests: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> TouchedSurfaces:
        fields = _object(value, "touched_surfaces")
        return cls(
            **{
                field: _strings(
                    fields.get(field), f"touched_surfaces.{field}", required=True
                )
                for field in ("files", "modules", "contracts", "docs", "tests")
            }
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            field: list(getattr(self, field))
            for field in ("files", "modules", "contracts", "docs", "tests")
        }


@dataclass(frozen=True)
class Verification:
    required: tuple[str, ...]
    smoke: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> Verification:
        fields = _object(value, "verification")
        return cls(
            required=_strings(
                fields.get("required"), "verification.required", required=True
            ),
            smoke=_strings(fields.get("smoke", []), "verification.smoke"),
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {"required": list(self.required), "smoke": list(self.smoke)}


@dataclass(frozen=True)
class WorkflowGraphChild:
    node_id: str
    title: str
    body: str
    acceptance_criteria: tuple[str, ...]
    dependencies: tuple[str, ...]
    in_scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    touched_surfaces: TouchedSurfaces
    verification: Verification
    risk_level: str

    @classmethod
    def from_dict(cls, value: object) -> WorkflowGraphChild:
        fields = _object(value, "graph child")
        risk_level = _string(fields.get("risk_level"), "risk_level")
        if risk_level not in RISK_LEVELS:
            raise GraphError("risk_level must be one of: low, medium, high")
        return cls(
            node_id=_string(fields.get("node_id"), "node_id"),
            title=_string(fields.get("title"), "title"),
            body=_string(fields.get("body"), "body"),
            acceptance_criteria=_strings(
                fields.get("acceptance_criteria"),
                "acceptance_criteria",
                required=True,
            ),
            dependencies=_strings(fields.get("dependencies", []), "dependencies"),
            in_scope=_strings(fields.get("in_scope"), "in_scope", required=True),
            out_of_scope=_strings(
                fields.get("out_of_scope"), "out_of_scope", required=True
            ),
            touched_surfaces=TouchedSurfaces.from_dict(fields.get("touched_surfaces")),
            verification=Verification.from_dict(fields.get("verification")),
            risk_level=risk_level,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "body": self.body,
            "acceptance_criteria": list(self.acceptance_criteria),
            "dependencies": list(self.dependencies),
            "in_scope": list(self.in_scope),
            "out_of_scope": list(self.out_of_scope),
            "touched_surfaces": self.touched_surfaces.to_dict(),
            "verification": self.verification.to_dict(),
            "risk_level": self.risk_level,
        }


@dataclass(frozen=True)
class WorkflowGraphArtifact:
    parent_id: str
    graph_checksum: str
    children: tuple[WorkflowGraphChild, ...]
    dependency_edges: tuple[DependencyEdge, ...]

    @classmethod
    def from_dict(cls, value: object) -> WorkflowGraphArtifact:
        fields = _object(value, "workflow graph")
        raw_children = fields.get("children")
        if not isinstance(raw_children, list) or not raw_children:
            raise GraphError("children must be a non-empty list")
        children = tuple(WorkflowGraphChild.from_dict(child) for child in raw_children)
        child_ids = [child.node_id for child in children]
        if len(child_ids) != len(set(child_ids)):
            raise GraphError("graph child IDs must be unique")

        raw_edges = fields.get("dependency_edges")
        if not isinstance(raw_edges, list):
            raise GraphError("dependency_edges must be a list")
        dependency_edges = tuple(cls._edge_from_dict(edge) for edge in raw_edges)
        artifact = cls(
            parent_id=_string(fields.get("parent_id"), "parent_id"),
            graph_checksum=_string(fields.get("graph_checksum"), "graph_checksum"),
            children=children,
            dependency_edges=dependency_edges,
        )
        validate_graph(artifact.scheduling_view())
        return artifact

    @staticmethod
    def _edge_from_dict(value: object) -> DependencyEdge:
        fields = _object(value, "dependency edge")
        blocks_dispatch = fields.get("blocks_dispatch")
        if not isinstance(blocks_dispatch, bool):
            raise GraphError("dependency edge blocks_dispatch must be a boolean")
        return DependencyEdge(
            from_node_id=_string(fields.get("from"), "dependency edge from"),
            to_node_id=_string(fields.get("to"), "dependency edge to"),
            type=_string(fields.get("type"), "dependency edge type"),
            blocks_dispatch=blocks_dispatch,
            reason=_string(fields.get("reason"), "dependency edge reason"),
            required_artifacts=_strings(
                fields.get("required_artifacts"),
                "dependency edge required_artifacts",
                required=True,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "parent_id": self.parent_id,
            "graph_checksum": self.graph_checksum,
            "children": [child.to_dict() for child in self.children],
            "dependency_edges": [
                {
                    "from": edge.from_node_id,
                    "to": edge.to_node_id,
                    "type": edge.type,
                    "blocks_dispatch": edge.blocks_dispatch,
                    "reason": edge.reason,
                    "required_artifacts": list(edge.required_artifacts),
                }
                for edge in self.dependency_edges
            ],
        }

    def scheduling_view(self) -> WorkflowGraph:
        return WorkflowGraph(
            children={
                child.node_id: ChildNode(
                    id=child.node_id,
                    dependencies=frozenset(child.dependencies)
                    | frozenset(
                        edge.from_node_id
                        for edge in self.dependency_edges
                        if edge.to_node_id == child.node_id
                        and edge.blocks_dispatch
                    ),
                )
                for child in self.children
            },
            dependency_edges=self.dependency_edges,
        )
