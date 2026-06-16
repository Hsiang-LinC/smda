from __future__ import annotations

from smda_scheduler.execution_modes import ExecutionMode
from smda_scheduler.workflow_engine import (
    CHILD_DEFINITION,
    PARENT_DEFINITION,
    ROADMAP_DEFINITION,
    WorkflowDefinition,
)


class WorkflowRegistryError(KeyError):
    """Raised when no workflow definition is registered for a mode."""


# Mode -> Workflow Definition. Task / review register in later phases; the
# unknown-mode boundary is intentional.
_REGISTRY: dict[ExecutionMode, WorkflowDefinition] = {
    ExecutionMode.SMDA: PARENT_DEFINITION,
    ExecutionMode.SMDA_CHILD: CHILD_DEFINITION,
    ExecutionMode.SMDA_ROADMAP: ROADMAP_DEFINITION,
}


def definition_for_mode(mode: ExecutionMode) -> WorkflowDefinition:
    try:
        return _REGISTRY[mode]
    except KeyError as error:
        raise WorkflowRegistryError(
            f"No workflow definition registered for mode: {mode}"
        ) from error
