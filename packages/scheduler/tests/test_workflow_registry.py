import pytest

from smda_scheduler.execution_modes import ExecutionMode
from smda_scheduler.workflow_engine import CHILD_DEFINITION, PARENT_DEFINITION
from smda_scheduler.workflow_engine import ROADMAP_DEFINITION
from smda_scheduler.workflow_registry import (
    WorkflowRegistryError,
    definition_for_mode,
)


def test_registry_resolves_smda_child_to_child_definition():
    assert definition_for_mode(ExecutionMode.SMDA_CHILD) is CHILD_DEFINITION


def test_registry_resolves_smda_to_parent_definition():
    assert definition_for_mode(ExecutionMode.SMDA) is PARENT_DEFINITION


def test_registry_resolves_smda_roadmap_to_roadmap_definition():
    assert definition_for_mode(ExecutionMode.SMDA_ROADMAP) is ROADMAP_DEFINITION


def test_registry_unknown_mode_raises():
    # smda-task is not registered until Phase 5 — documents the boundary.
    with pytest.raises(WorkflowRegistryError):
        definition_for_mode(ExecutionMode.SMDA_TASK)
