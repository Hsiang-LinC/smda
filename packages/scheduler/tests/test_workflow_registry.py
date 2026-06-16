import pytest

from smda_scheduler.execution_modes import ExecutionMode
from smda_scheduler.workflow_engine import CHILD_DEFINITION
from smda_scheduler.workflow_registry import (
    WorkflowRegistryError,
    definition_for_mode,
)


def test_registry_resolves_smda_child_to_child_definition():
    assert definition_for_mode(ExecutionMode.SMDA_CHILD) is CHILD_DEFINITION


def test_registry_unknown_mode_raises():
    # smda (parent) is not registered in Phase 1a — documents the boundary.
    with pytest.raises(WorkflowRegistryError):
        definition_for_mode(ExecutionMode.SMDA)
