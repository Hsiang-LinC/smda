from pathlib import Path

import pytest

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.role_attempts import AgentSelection, ChildTaskContext
from smda_scheduler.runtime import RoleExecutionAdapter, run_child_workflow_tick
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.scheduling import AttemptOutcome
from smda_scheduler.workflow import ChildNode, ChildPhase, GraphError, RoleResult, WorkflowGraph


class RecordingExecutionAdapter(RoleExecutionAdapter):
    def __init__(self, outcome: AttemptOutcome):
        self.outcome = outcome
        self.requests: list[RoleAttemptRequest] = []

    def run_role_attempt(self, request: RoleAttemptRequest) -> AttemptOutcome:
        self.requests.append(request)
        return self.outcome


def test_run_child_workflow_tick_dispatches_typed_role_attempt(tmp_path: Path):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=("pytest",),
    )
    execution = RecordingExecutionAdapter(
        AttemptOutcome(
            status="succeeded",
            role_result=RoleResult(
                verdict="DONE",
                required_next_action="submit_for_spec_review",
            ),
        )
    )
    ledger = PhaseLedger(tmp_path / ".smda" / "state" / "ledger.sqlite")

    state = run_child_workflow_tick(
        graph=WorkflowGraph(children={"child-001": ChildNode(id="child-001")}),
        child_tasks={
            "child-001": ChildTaskContext(
                child_id="child-001",
                title="Implement runtime wiring",
                body="Dispatch through Sandcastle.",
            )
        },
        parent_issue_id="DANNY-66",
        repo_context=repo_context,
        repo_root=tmp_path,
        ledger=ledger,
        execution=execution,
        sandbox_provider="noSandbox",
        agent=AgentSelection(provider="codex", model="gpt-5"),
        now=10.0,
        owner="daemon-1",
    )

    assert state.children["child-001"].phase == ChildPhase.SPEC_REVIEWING
    assert len(execution.requests) == 1
    request = execution.requests[0]
    assert request.attempt_id == "child-001-IMPLEMENTING-1"
    assert request.role == "implementer"
    assert request.context_packet["child_id"] == "child-001"
    assert ledger.load_attempts()[0]["status"] == "succeeded"


def test_run_child_workflow_tick_requires_child_task_context(tmp_path: Path):
    bootloader = tmp_path / "AGENTS.md"
    docs = tmp_path / "docs"
    bootloader.write_text("# Boot\n", encoding="utf-8")
    docs.mkdir()
    repo_context = RepoContextPacket(
        bootloader_path=bootloader,
        bootloader_text="# Boot\n",
        spec_locations=(docs,),
        adr_locations=(),
        quality_gates=(),
    )

    with pytest.raises(GraphError, match="Missing child task context"):
        run_child_workflow_tick(
            graph=WorkflowGraph(children={"child-001": ChildNode(id="child-001")}),
            child_tasks={},
            parent_issue_id="DANNY-66",
            repo_context=repo_context,
            repo_root=tmp_path,
            ledger=PhaseLedger(tmp_path / "ledger.sqlite"),
            execution=RecordingExecutionAdapter(AttemptOutcome(status="execution_failed")),
            sandbox_provider="noSandbox",
            agent=AgentSelection(provider="codex", model="gpt-5"),
            now=10.0,
            owner="daemon-1",
        )
