from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from smda_scheduler.config import AgentConfig, derive_workspace_paths, load_config
from smda_scheduler.context_packets import CodexHarnessContextAdapter
from smda_scheduler.daemon import TickResult
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.parent_acceptance import ParentIntegration
from smda_scheduler.role_attempts import AgentSelection
from smda_scheduler.route_dispatch import RouteDispatcher
from smda_scheduler.runtime import RoleExecutionAdapter
from smda_scheduler.workflow import QaBounds
from smda_scheduler.workspace_tick import WorkspaceBacklog, run_workspace_tick


def build_configured_workspace_tick(
    *,
    config_path: Path,
    repo_root: Path,
    backlog: WorkspaceBacklog,
    execution: RoleExecutionAdapter,
    scan_states: Sequence[str],
    scan_label: str,
    owner: str,
    max_parallel: int = 3,
    parent_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    agent: AgentSelection | None = None,
    integration: ParentIntegration | None = None,
    integration_branch: str | None = None,
    standalone_base: str = "main",
) -> Callable[[], TickResult]:
    config = load_config(config_path, repo_root=repo_root)
    if agent is None:
        agent = _agent_selection(config.adapters.execution.agent)
    workspace = derive_workspace_paths(config)
    ledger = PhaseLedger(workspace.ledger_path)
    repo_context = CodexHarnessContextAdapter().build_repo_packet(config)
    child_labels = _child_labels(config.labels)
    qa_bounds = QaBounds(
        max_same_feedback_fingerprint=config.policy.qa.max_same_feedback_fingerprint,
        max_total_remediation_children=config.policy.qa.max_total_remediation_children,
        max_parent_qa_cycles=config.policy.qa.max_parent_qa_cycles,
    )

    route_dispatcher = RouteDispatcher(
        repo_context=repo_context,
        repo_root=config.repo_root,
        ledger=ledger,
        execution=execution,
        backlog=backlog,
        sandbox_provider=config.adapters.execution.provider,
        agent=agent,
        owner=owner,
        child_labels=child_labels,
        qa_bounds=qa_bounds,
        integration=integration,
        integration_branch=integration_branch,
        standalone_base=standalone_base,
        create_follow_up_issues_for_concerns=(
            config.policy.concerns.create_follow_up_issues
        ),
        concern_followup_labels=frozenset(config.policy.concerns.labels),
    )

    return lambda: run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=scan_states,
        label=scan_label,
        parent_id=parent_id,
        dispatch_candidate=lambda issue: TickResult(
            status="blocked",
            detail=f"SMDA routing was not configured for {issue.id}",
        ),
        issue_entry_policy=config.policy.issue_entry,
        dispatch_routed_candidate=route_dispatcher,
        max_parallel=max_parallel,
        limit=limit,
        cursor=cursor,
    )


def _child_labels(labels: dict[str, object]) -> frozenset[str]:
    actor = labels.get("actor")
    if isinstance(actor, str) and actor:
        return frozenset({actor})
    return frozenset()


def _agent_selection(config: AgentConfig) -> AgentSelection:
    return AgentSelection(
        provider=config.provider,
        model=config.model,
        effort=config.effort,
        role_overrides={
            role: _agent_selection(override)
            for role, override in config.role_overrides.items()
        },
    )
