from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from smda_scheduler.role_contracts import RoleContract, child_role_contract_for_phase
from smda_scheduler.workflow import (
    ChildPhase,
    GraphError,
    ParentPhase,
    RoleResult,
    TERMINAL_CHILD_PHASES,
    TRANSITIONS,
    WorkflowGraph,
    eligible_child_ids,
)

if TYPE_CHECKING:
    from smda_scheduler.backlog import BacklogIssue
    from smda_scheduler.context_packets import RepoContextPacket
    from smda_scheduler.parent_acceptance import ParentIntegration
    from smda_scheduler.phase_ledger import PhaseLedger
    from smda_scheduler.role_attempts import AgentSelection
    from smda_scheduler.runtime import (
        BacklogPublicationAdapter,
        ParentIntakeResult,
        RoleExecutionAdapter,
    )
    from smda_scheduler.workflow import QaBounds


class WorkHandlerKind(StrEnum):
    ROLE_ATTEMPT = auto()
    EFFECT = auto()
    AGGREGATE = auto()


@dataclass(frozen=True)
class StageSpec:
    phase: object
    kind: WorkHandlerKind
    role_contract: RoleContract | None = None
    # Phase 1b scaffolding: a stage's work as the wrapped existing handler.
    # Phase 1d replaces these opaque callables with generic kind interpretation.
    work: Callable[["ParentTickContext"], "ParentIntakeResult"] | None = None
    # Deterministic success edge for Effect / Aggregate stages (no verdict).
    next_phase_on_success: str | None = None


@dataclass(frozen=True)
class ParentTickContext:
    """Every argument a parent stage may need, bundled once per tick."""

    issue: "BacklogIssue"
    repo_context: "RepoContextPacket"
    repo_root: Path
    ledger: "PhaseLedger"
    execution: "RoleExecutionAdapter"
    backlog: "BacklogPublicationAdapter"
    sandbox_provider: str
    agent: "AgentSelection"
    owner: str
    child_labels: frozenset[str] = frozenset()
    integration: "ParentIntegration | None" = None
    integration_branch: str | None = None
    qa_bounds: "QaBounds | None" = None


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    phases: frozenset
    transitions: dict
    terminal_phases: frozenset
    stages: dict
    # phase -> dispatched phase (e.g. READY dispatches as IMPLEMENTING)
    dispatch_phase_overrides: dict

    def stage(self, phase) -> StageSpec:
        return self.stages[phase]


def _safe_child_contract(phase: ChildPhase) -> RoleContract | None:
    """Return the child role contract for a phase, or None when none exists.

    READY (dispatched as IMPLEMENTING) and the terminal phases have no role.
    """
    try:
        return child_role_contract_for_phase(phase)
    except (KeyError, GraphError):
        return None


def _child_stages() -> dict[ChildPhase, StageSpec]:
    # Every child phase is a single agent role attempt; READY/terminal carry no
    # contract but keep the uniform ROLE_ATTEMPT kind.
    return {
        phase: StageSpec(
            phase=phase,
            kind=WorkHandlerKind.ROLE_ATTEMPT,
            role_contract=_safe_child_contract(phase),
        )
        for phase in ChildPhase
    }


CHILD_DEFINITION = WorkflowDefinition(
    name="smda-child",
    phases=frozenset(ChildPhase),
    transitions=dict(TRANSITIONS),
    terminal_phases=TERMINAL_CHILD_PHASES,
    stages=_child_stages(),
    dispatch_phase_overrides={ChildPhase.READY: ChildPhase.IMPLEMENTING},
)


class WorkflowEngine:
    """Interprets a WorkflowDefinition's decisions.

    Owns only the routing decisions (dispatch phase, transition, terminal test,
    role selection, eligibility). The scheduler keeps owning claim/lease, durable
    recording, backoff, and fix-cycle escalation.
    """

    def __init__(self, definition: WorkflowDefinition) -> None:
        self._definition = definition

    @property
    def definition(self) -> WorkflowDefinition:
        return self._definition

    def dispatch_phase(self, phase):
        return self._definition.dispatch_phase_overrides.get(phase, phase)

    def next_phase(self, phase, result: RoleResult):
        key = (phase, result.verdict, result.required_next_action)
        try:
            return self._definition.transitions[key]
        except KeyError as error:
            raise GraphError(
                "No transition for "
                f"phase={phase} verdict={result.verdict} "
                f"required_next_action={result.required_next_action}"
            ) from error

    def is_terminal(self, phase) -> bool:
        return phase in self._definition.terminal_phases

    def role_contract(self, phase) -> RoleContract | None:
        return self._definition.stage(phase).role_contract

    def eligible(self, graph: WorkflowGraph, *, completed_child_ids):
        return eligible_child_ids(graph, completed_child_ids=completed_child_ids)

    def dispatch_parent_stage(self, phase, ctx: "ParentTickContext"):
        """Run the stage's work for a parent phase, or None if no stage/work.

        The caller applies the idle/blocked default when this returns None.
        """
        stage = self._definition.stages.get(phase)
        if stage is None or stage.work is None:
            return None
        return stage.work(ctx)


# --- Parent workflow definition (Phase 1b: handlers wrapped as stage work) ---
#
# Each work imports its handler lazily: runtime.py imports this module, so a
# module-load import of runtime here would be a cycle. The stage *kind* is now
# first-class data; Phase 1c replaces these wrappers with generic interpretation.

# Ledger phase marker that triggers decomposition (not a ParentPhase member).
_SPEC_FINALIZED = "SPEC_FINALIZED"


def _role_args(ctx: "ParentTickContext") -> dict:
    return dict(
        issue=ctx.issue,
        repo_context=ctx.repo_context,
        repo_root=ctx.repo_root,
        ledger=ctx.ledger,
        execution=ctx.execution,
        sandbox_provider=ctx.sandbox_provider,
        agent=ctx.agent,
        owner=ctx.owner,
    )


def _spec_finalized_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_graph_decomposition_tick

    return run_parent_graph_decomposition_tick(**_role_args(ctx))


def _graph_fixing_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_graph_fixing_tick

    return run_parent_graph_fixing_tick(**_role_args(ctx))


def _graph_spec_review_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_graph_spec_review_tick

    return run_parent_graph_spec_review_tick(**_role_args(ctx))


def _graph_execution_review_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_graph_execution_review_tick

    return run_parent_graph_execution_review_tick(**_role_args(ctx))


def _child_publication_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_child_publication_tick

    return run_parent_child_publication_tick(
        issue=ctx.issue,
        ledger=ctx.ledger,
        backlog=ctx.backlog,
        child_labels=ctx.child_labels,
    )


def _child_acceptance_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_child_acceptance_tick

    return run_parent_child_acceptance_tick(
        issue=ctx.issue,
        ledger=ctx.ledger,
        integration=ctx.integration,
        integration_branch=ctx.integration_branch,
    )


def _parent_qa_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_qa_review_tick

    return run_parent_qa_review_tick(**_role_args(ctx))


def _remediation_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_remediation_planning_tick

    return run_parent_remediation_planning_tick(
        issue=ctx.issue,
        ledger=ctx.ledger,
        backlog=ctx.backlog,
        child_labels=ctx.child_labels,
        qa_bounds=ctx.qa_bounds,
    )


def _final_accept_work(ctx: "ParentTickContext"):
    from smda_scheduler.runtime import run_parent_final_accept_tick

    return run_parent_final_accept_tick(issue=ctx.issue, ledger=ctx.ledger)


def _parent_stage(
    phase, kind: WorkHandlerKind, work, next_phase_on_success: str | None = None
) -> StageSpec:
    return StageSpec(
        phase=phase, kind=kind, work=work, next_phase_on_success=next_phase_on_success
    )


# Verdict-keyed parent success transitions (RoleAttempt). Mirrors the child
# TRANSITIONS table. Failure routing (bounded fixer / remediation / human-review
# escalation) stays dynamic in the handlers.
_P = ParentPhase
PARENT_TRANSITIONS: dict[tuple[str, str, str], str] = {
    (_SPEC_FINALIZED, "DONE", "submit_for_graph_review"): _P.GRAPH_SPEC_REVIEWING.value,
    (
        _P.GRAPH_FIXING.value,
        "DONE",
        "submit_for_graph_review",
    ): _P.GRAPH_SPEC_REVIEWING.value,
    **{
        (_P.GRAPH_SPEC_REVIEWING.value, verdict, "submit_for_graph_execution_review"): (
            _P.GRAPH_EXECUTION_REVIEWING.value
        )
        for verdict in ("PASS", "DONE_WITH_CONCERNS")
    },
    **{
        (_P.GRAPH_EXECUTION_REVIEWING.value, verdict, "publish_child_issues"): (
            _P.CHILD_PUBLICATION_READY.value
        )
        for verdict in ("PASS", "DONE_WITH_CONCERNS")
    },
    **{
        (_P.PARENT_QA_READY.value, verdict, "accept_parent"): _P.FINAL_ACCEPT_READY.value
        for verdict in ("PASS", "DONE_WITH_CONCERNS")
    },
    (
        _P.PARENT_QA_READY.value,
        "FAIL",
        "plan_remediation",
    ): _P.REMEDIATION_PLANNING.value,
}


_PARENT_STAGES: dict[str, StageSpec] = {
    _SPEC_FINALIZED: _parent_stage(
        _SPEC_FINALIZED, WorkHandlerKind.ROLE_ATTEMPT, _spec_finalized_work
    ),
    ParentPhase.GRAPH_FIXING.value: _parent_stage(
        ParentPhase.GRAPH_FIXING, WorkHandlerKind.ROLE_ATTEMPT, _graph_fixing_work
    ),
    ParentPhase.GRAPH_SPEC_REVIEWING.value: _parent_stage(
        ParentPhase.GRAPH_SPEC_REVIEWING,
        WorkHandlerKind.ROLE_ATTEMPT,
        _graph_spec_review_work,
    ),
    ParentPhase.GRAPH_EXECUTION_REVIEWING.value: _parent_stage(
        ParentPhase.GRAPH_EXECUTION_REVIEWING,
        WorkHandlerKind.ROLE_ATTEMPT,
        _graph_execution_review_work,
    ),
    ParentPhase.CHILD_PUBLICATION_READY.value: _parent_stage(
        ParentPhase.CHILD_PUBLICATION_READY,
        WorkHandlerKind.EFFECT,
        _child_publication_work,
        next_phase_on_success=ParentPhase.CHILDREN_PUBLISHED.value,
    ),
    ParentPhase.CHILDREN_PUBLISHED.value: _parent_stage(
        ParentPhase.CHILDREN_PUBLISHED,
        WorkHandlerKind.AGGREGATE,
        _child_acceptance_work,
        next_phase_on_success=ParentPhase.PARENT_QA_READY.value,
    ),
    ParentPhase.PARENT_QA_READY.value: _parent_stage(
        ParentPhase.PARENT_QA_READY, WorkHandlerKind.ROLE_ATTEMPT, _parent_qa_work
    ),
    ParentPhase.REMEDIATION_PLANNING.value: _parent_stage(
        ParentPhase.REMEDIATION_PLANNING,
        WorkHandlerKind.EFFECT,
        _remediation_work,
        next_phase_on_success=ParentPhase.CHILDREN_PUBLISHED.value,
    ),
    ParentPhase.FINAL_ACCEPT_READY.value: _parent_stage(
        ParentPhase.FINAL_ACCEPT_READY,
        WorkHandlerKind.EFFECT,
        _final_accept_work,
        next_phase_on_success=ParentPhase.FINAL_ACCEPTED.value,
    ),
}


PARENT_DEFINITION = WorkflowDefinition(
    name="smda",
    phases=frozenset(ParentPhase),
    transitions=PARENT_TRANSITIONS,
    terminal_phases=frozenset(
        {ParentPhase.FINAL_ACCEPTED, ParentPhase.HUMAN_REVIEW_REQUIRED}
    ),
    stages=_PARENT_STAGES,
    dispatch_phase_overrides={},
)
