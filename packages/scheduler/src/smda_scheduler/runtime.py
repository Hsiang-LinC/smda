from __future__ import annotations

from pathlib import Path
from typing import Protocol

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.role_attempts import (
    AgentSelection,
    ChildTaskContext,
    build_child_role_attempt_request,
)
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.scheduling import (
    AttemptDispatch,
    AttemptOutcome,
    SchedulerState,
    run_once_durable,
)
from smda_scheduler.workflow import GraphError, WorkflowGraph


class RoleExecutionAdapter(Protocol):
    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome: ...


def run_child_workflow_tick(
    *,
    graph: WorkflowGraph,
    child_tasks: dict[str, ChildTaskContext],
    parent_issue_id: str,
    repo_context: RepoContextPacket,
    repo_root: Path,
    ledger: PhaseLedger,
    execution: RoleExecutionAdapter,
    sandbox_provider: str,
    agent: AgentSelection,
    now: float,
    owner: str,
) -> SchedulerState:
    def executor(dispatch: AttemptDispatch) -> AttemptOutcome:
        try:
            child = child_tasks[dispatch.child_id]
        except KeyError as error:
            raise GraphError(
                f"Missing child task context: {dispatch.child_id}"
            ) from error

        request = build_child_role_attempt_request(
            attempt_id=dispatch.attempt_id,
            parent_issue_id=parent_issue_id,
            child=child,
            phase=dispatch.phase,
            repo_context=repo_context,
            repo_root=repo_root,
            sandbox_provider=sandbox_provider,
            agent=agent,
        )
        return execution.run_role_attempt(request)

    return run_once_durable(
        graph,
        ledger,
        executor=executor,
        now=now,
        owner=owner,
    )
