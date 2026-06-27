from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from smda_scheduler.role_contracts import (
    RoleContract,
    child_role_contract_for_phase,
    roadmap_role_contract_for_phase,
)
from smda_scheduler.workflow import (
    ChildPhase,
    GraphError,
    ParentPhase,
    RoadmapPhase,
    RoleResult,
    TASK_TRANSITIONS,
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
        RoleExecutionAdapter,
    )
    from smda_scheduler.workflow import QaBounds


class WorkHandlerKind(StrEnum):
    ROLE_ATTEMPT = auto()
    EFFECT = auto()
    AGGREGATE = auto()


@dataclass(frozen=True)
class StageSpec:
    """Pure data describing one stage (ADR-0006).

    The engine interprets `kind` to dispatch (a generic role-attempt runner or
    a phase-resolved effect handler in runtime) — there is no per-stage work
    callable. `role_contract` documents the RoleAttempt; `next_phase_on_success`
    is the deterministic success edge for Effect / Aggregate stages (no verdict).
    """

    phase: object
    kind: WorkHandlerKind
    role_contract: RoleContract | None = None
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
    standalone_base: str = "main"
    qa_bounds: "QaBounds | None" = None
    create_follow_up_issues_for_concerns: bool = False
    concern_followup_labels: frozenset[str] = frozenset()


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


def _task_stages() -> dict[ChildPhase, StageSpec]:
    stages = _child_stages()
    for skipped_phase in (ChildPhase.SPEC_REVIEWING, ChildPhase.FIXING_SPEC):
        stages[skipped_phase] = StageSpec(
            phase=skipped_phase,
            kind=WorkHandlerKind.ROLE_ATTEMPT,
        )
    return stages


CHILD_DEFINITION = WorkflowDefinition(
    name="smda-child",
    phases=frozenset(ChildPhase),
    transitions=dict(TRANSITIONS),
    terminal_phases=TERMINAL_CHILD_PHASES,
    stages=_child_stages(),
    dispatch_phase_overrides={ChildPhase.READY: ChildPhase.IMPLEMENTING},
)


TASK_DEFINITION = WorkflowDefinition(
    name="smda-task",
    phases=frozenset(ChildPhase),
    transitions=dict(TASK_TRANSITIONS),
    terminal_phases=TERMINAL_CHILD_PHASES,
    stages=_task_stages(),
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
        """Interpret a parent/roadmap stage by its WorkHandlerKind (ADR-0006).

        ROLE_ATTEMPT stages run through the generic role-attempt dispatcher;
        EFFECT / AGGREGATE stages resolve their handler by phase. Each kind
        reaches runtime via a single call-time import, keeping the
        runtime -> workflow_engine cycle broken. Returns None when the phase
        has no stage; the caller applies the idle default.
        """
        stage = self._definition.stages.get(phase)
        if stage is None:
            return None
        if stage.kind is WorkHandlerKind.ROLE_ATTEMPT:
            from smda_scheduler.runtime import dispatch_role_attempt_stage

            return dispatch_role_attempt_stage(stage.phase, ctx)
        from smda_scheduler.runtime import resolve_parent_effect

        return resolve_parent_effect(stage.phase)(ctx)


# --- Parent workflow definition (ADR-0006: pure-data stages, kind dispatch) ---
#
# Stages carry no work callable: dispatch_parent_stage interprets `kind` and
# reaches the handlers in runtime (generic role-attempt runner / phase-resolved
# effect handler) via a call-time import, keeping the runtime -> workflow_engine
# cycle broken.

# Ledger phase marker that triggers decomposition (not a ParentPhase member).
_SPEC_FINALIZED = "SPEC_FINALIZED"


def _parent_stage(
    phase, kind: WorkHandlerKind, next_phase_on_success: str | None = None
) -> StageSpec:
    return StageSpec(
        phase=phase, kind=kind, next_phase_on_success=next_phase_on_success
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
        _P.CHILD_ACCEPT_CONFLICT_RESOLVING.value,
        "DONE",
        "retry_child_acceptance",
    ): _P.CHILDREN_PUBLISHED.value,
    (
        _P.PARENT_QA_READY.value,
        "FAIL",
        "plan_remediation",
    ): _P.REMEDIATION_PLANNING.value,
}


_PARENT_STAGES: dict[str, StageSpec] = {
    _SPEC_FINALIZED: _parent_stage(_SPEC_FINALIZED, WorkHandlerKind.ROLE_ATTEMPT),
    ParentPhase.GRAPH_FIXING.value: _parent_stage(
        ParentPhase.GRAPH_FIXING, WorkHandlerKind.ROLE_ATTEMPT
    ),
    ParentPhase.GRAPH_SPEC_REVIEWING.value: _parent_stage(
        ParentPhase.GRAPH_SPEC_REVIEWING, WorkHandlerKind.ROLE_ATTEMPT
    ),
    ParentPhase.GRAPH_EXECUTION_REVIEWING.value: _parent_stage(
        ParentPhase.GRAPH_EXECUTION_REVIEWING, WorkHandlerKind.ROLE_ATTEMPT
    ),
    ParentPhase.CHILD_PUBLICATION_READY.value: _parent_stage(
        ParentPhase.CHILD_PUBLICATION_READY,
        WorkHandlerKind.EFFECT,
        next_phase_on_success=ParentPhase.CHILDREN_PUBLISHED.value,
    ),
    ParentPhase.CHILDREN_PUBLISHED.value: _parent_stage(
        ParentPhase.CHILDREN_PUBLISHED,
        WorkHandlerKind.AGGREGATE,
        next_phase_on_success=ParentPhase.PARENT_QA_READY.value,
    ),
    ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING.value: _parent_stage(
        ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING,
        WorkHandlerKind.ROLE_ATTEMPT,
    ),
    ParentPhase.PARENT_QA_READY.value: _parent_stage(
        ParentPhase.PARENT_QA_READY, WorkHandlerKind.ROLE_ATTEMPT
    ),
    ParentPhase.REMEDIATION_PLANNING.value: _parent_stage(
        ParentPhase.REMEDIATION_PLANNING,
        WorkHandlerKind.EFFECT,
        next_phase_on_success=ParentPhase.CHILDREN_PUBLISHED.value,
    ),
    ParentPhase.FINAL_ACCEPT_READY.value: _parent_stage(
        ParentPhase.FINAL_ACCEPT_READY,
        WorkHandlerKind.EFFECT,
        next_phase_on_success=ParentPhase.FINAL_ACCEPTED.value,
    ),
    ParentPhase.LANDING_CONFLICT_REBASING.value: _parent_stage(
        ParentPhase.LANDING_CONFLICT_REBASING, WorkHandlerKind.EFFECT
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


_R = RoadmapPhase
ROADMAP_TRANSITIONS: dict[tuple[RoadmapPhase, str, str], str] = {
    (
        _R.ROADMAP_DECOMPOSING,
        "DONE",
        "publish_roadmap_parents",
    ): _R.ROADMAP_PUBLICATION_READY.value,
}

_ROADMAP_STAGES: dict[RoadmapPhase, StageSpec] = {
    _R.ROADMAP_DECOMPOSING: StageSpec(
        phase=_R.ROADMAP_DECOMPOSING,
        kind=WorkHandlerKind.ROLE_ATTEMPT,
        role_contract=roadmap_role_contract_for_phase(_R.ROADMAP_DECOMPOSING),
    ),
    _R.ROADMAP_PUBLICATION_READY: StageSpec(
        phase=_R.ROADMAP_PUBLICATION_READY,
        kind=WorkHandlerKind.EFFECT,
        next_phase_on_success=_R.ROADMAP_PUBLISHED.value,
    ),
    # Parent-tier Aggregate: poll member FINAL_ACCEPTED, land roadmap -> main once.
    _R.ROADMAP_PUBLISHED: StageSpec(
        phase=_R.ROADMAP_PUBLISHED,
        kind=WorkHandlerKind.AGGREGATE,
        next_phase_on_success=_R.ROADMAP_COMPLETED.value,
    ),
    # ROADMAP_COMPLETED and HUMAN_REVIEW_REQUIRED are terminal: no stage entry,
    # so dispatch returns None (idle), matching their prior work=None behaviour.
}

ROADMAP_DEFINITION = WorkflowDefinition(
    name="smda-roadmap",
    phases=frozenset(RoadmapPhase),
    transitions=ROADMAP_TRANSITIONS,
    terminal_phases=frozenset(
        {RoadmapPhase.ROADMAP_COMPLETED, RoadmapPhase.HUMAN_REVIEW_REQUIRED}
    ),
    stages=_ROADMAP_STAGES,
    dispatch_phase_overrides={},
)
