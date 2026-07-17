from copy import deepcopy

import pytest

from smda_scheduler.workflow import GraphError
from smda_scheduler.workflow_graph import WorkflowGraphArtifact


def complete_graph_dict():
    return {
        "parent_id": "DANNY-66",
        "graph_checksum": "sha256:graph-v1",
        "children": [
            {
                "node_id": "child-001",
                "title": "Add durable transition",
                "body": "Move Parent transition truth into the Runtime Ledger.",
                "acceptance_criteria": ["stale transitions fail"],
                "dependencies": [],
                "in_scope": ["Parent persistence"],
                "out_of_scope": ["Request Intake"],
                "touched_surfaces": {
                    "files": [
                        "packages/scheduler/src/smda_scheduler/phase_ledger.py"
                    ],
                    "modules": ["smda_scheduler.phase_ledger"],
                    "contracts": ["Parent Transition"],
                    "docs": ["docs/adr/0010-expected-phase-parent-transitions.md"],
                    "tests": ["packages/scheduler/tests/test_phase_ledger.py"],
                },
                "verification": {
                    "required": ["pytest test_phase_ledger.py"],
                    "smoke": [],
                },
                "risk_level": "medium",
            }
        ],
        "dependency_edges": [],
    }


def test_complete_workflow_graph_round_trips_without_losing_fields():
    graph = WorkflowGraphArtifact.from_dict(complete_graph_dict())
    assert graph.to_dict() == complete_graph_dict()
    assert graph.scheduling_view().children["child-001"].dependencies == frozenset()


def test_complete_workflow_graph_rejects_unknown_risk():
    value = complete_graph_dict()
    value["children"][0]["risk_level"] = "extreme"

    with pytest.raises(GraphError, match="risk_level"):
        WorkflowGraphArtifact.from_dict(value)


def test_complete_workflow_graph_rejects_incomplete_touched_surfaces():
    value = complete_graph_dict()
    del value["children"][0]["touched_surfaces"]["tests"]

    with pytest.raises(GraphError, match="touched_surfaces.tests"):
        WorkflowGraphArtifact.from_dict(value)


def test_complete_workflow_graph_rejects_incomplete_verification():
    value = complete_graph_dict()
    del value["children"][0]["verification"]["required"]

    with pytest.raises(GraphError, match="verification.required"):
        WorkflowGraphArtifact.from_dict(value)


def test_complete_workflow_graph_rejects_unknown_dependency():
    value = complete_graph_dict()
    value["children"][0]["dependencies"] = ["missing-child"]

    with pytest.raises(GraphError, match="unknown dependency"):
        WorkflowGraphArtifact.from_dict(value)


def test_complete_workflow_graph_rejects_edge_without_required_artifacts():
    value = complete_graph_dict()
    second_child = deepcopy(value["children"][0])
    second_child["node_id"] = "child-002"
    value["children"].append(second_child)
    value["dependency_edges"] = [
        {
            "from": "child-001",
            "to": "child-002",
            "type": "code_dependency",
            "blocks_dispatch": True,
            "reason": "child-002 consumes child-001",
            "required_artifacts": [],
        }
    ]

    with pytest.raises(GraphError, match="required_artifacts"):
        WorkflowGraphArtifact.from_dict(value)
