from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smda_scheduler.adapters import (
    AdapterDescriptor,
    AdapterResolutionError,
    NegotiationResult,
    WorkflowRequirements,
    negotiate_capabilities,
)
from smda_scheduler.config import WorkspacePaths, derive_workspace_paths, load_config


@dataclass(frozen=True)
class BootResult:
    workspace: WorkspacePaths
    adapters: dict[str, AdapterDescriptor]
    negotiation: dict[str, NegotiationResult]


WORKFLOW_REQUIREMENTS: dict[str, WorkflowRequirements] = {
    "execution": WorkflowRequirements(
        required=frozenset({"worktree_per_attempt", "structured_output_recovery"}),
        optional_fallbacks={"session_resume": "start_new_session"},
    ),
    "backlog": WorkflowRequirements(
        required=frozenset({"create_child", "comments", "coarse_states"}),
        optional_fallbacks={
            "blocking_relations": "gate_on_smda_graph_only",
            "hierarchy": "flat_issues_with_parent_label",
        },
    ),
    "context": WorkflowRequirements(
        required=frozenset({"bootloader", "spec_locations"}),
        optional_fallbacks={"repo_commands": "use_configured_quality_gates_only"},
    ),
}


def boot_workspace(
    config_path: Path,
    *,
    repo_root: Path,
    registry: dict[str, AdapterDescriptor] | None = None,
) -> BootResult:
    config = load_config(config_path, repo_root=repo_root)
    adapter_registry = registry or {}
    selected = {
        "execution": _resolve_adapter(adapter_registry, config.adapters.execution.id),
        "backlog": _resolve_adapter(adapter_registry, config.adapters.backlog.id),
        "context": _resolve_adapter(adapter_registry, config.adapters.context.id),
    }
    negotiation = {
        role: negotiate_capabilities(adapter, WORKFLOW_REQUIREMENTS[role])
        for role, adapter in selected.items()
    }
    return BootResult(
        workspace=derive_workspace_paths(config),
        adapters=selected,
        negotiation=negotiation,
    )


def _resolve_adapter(
    registry: dict[str, AdapterDescriptor],
    adapter_id: str,
) -> AdapterDescriptor:
    try:
        return registry[adapter_id]
    except KeyError as error:
        raise AdapterResolutionError(
            f"Configured adapter is unavailable: {adapter_id}"
        ) from error
