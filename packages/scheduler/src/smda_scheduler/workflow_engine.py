from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto

from smda_scheduler.role_contracts import RoleContract, child_role_contract_for_phase
from smda_scheduler.workflow import (
    ChildPhase,
    GraphError,
    RoleResult,
    TERMINAL_CHILD_PHASES,
    TRANSITIONS,
    WorkflowGraph,
    eligible_child_ids,
)


class WorkHandlerKind(StrEnum):
    ROLE_ATTEMPT = auto()
    EFFECT = auto()
    AGGREGATE = auto()


@dataclass(frozen=True)
class StageSpec:
    phase: object
    kind: WorkHandlerKind
    role_contract: RoleContract | None = None


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
