from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.workflow import ChildPhase, GraphError


@dataclass(frozen=True)
class AgentSelection:
    provider: str
    model: str


@dataclass(frozen=True)
class ChildTaskContext:
    child_id: str
    title: str
    body: str
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)


ROLE_BY_PHASE: dict[ChildPhase, str] = {
    ChildPhase.IMPLEMENTING: "implementer",
    ChildPhase.SPEC_REVIEWING: "spec_reviewer",
    ChildPhase.FIXING_SPEC: "fixer",
    ChildPhase.QUALITY_REVIEWING: "quality_reviewer",
}


def build_child_role_attempt_request(
    *,
    attempt_id: str,
    parent_issue_id: str,
    child: ChildTaskContext,
    phase: ChildPhase,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    role = _role_for_phase(phase)
    context_packet = _context_packet(
        parent_issue_id=parent_issue_id,
        child=child,
        phase=phase,
        role=role,
        repo_context=repo_context,
    )
    return RoleAttemptRequest(
        attempt_id=attempt_id,
        role=role,
        phase=phase,
        branch=_branch_name(parent_issue_id, child.child_id, phase),
        cwd=repo_root,
        context_packet=context_packet,
        prompt=_prompt(context_packet, repo_context.bootloader_text),
        output_tag="smda_role_result",
        schema_id="smda.role-result.v1",
        sandbox_provider=sandbox_provider,
        agent_provider=agent.provider,
        agent_model=agent.model,
    )


def _role_for_phase(phase: ChildPhase) -> str:
    try:
        return ROLE_BY_PHASE[phase]
    except KeyError as error:
        raise GraphError(f"No child role mapped for phase: {phase}") from error


def _context_packet(
    *,
    parent_issue_id: str,
    child: ChildTaskContext,
    phase: ChildPhase,
    role: str,
    repo_context: RepoContextPacket,
) -> dict[str, Any]:
    return {
        "parent_issue_id": parent_issue_id,
        "child_id": child.child_id,
        "child_title": child.title,
        "child_body": child.body,
        "acceptance_criteria": list(child.acceptance_criteria),
        "phase": phase.value,
        "role": role,
        "bootloader_path": str(repo_context.bootloader_path),
        "spec_locations": [str(path) for path in repo_context.spec_locations],
        "adr_locations": [str(path) for path in repo_context.adr_locations],
        "quality_gates": list(repo_context.quality_gates),
    }


def _prompt(context_packet: dict[str, Any], bootloader_text: str) -> str:
    quality_gates = _bullet_list(context_packet["quality_gates"])
    acceptance = _bullet_list(context_packet["acceptance_criteria"])
    spec_locations = _bullet_list(context_packet["spec_locations"])
    adr_locations = _bullet_list(context_packet["adr_locations"])
    return "\n".join(
        [
            f"Role: {context_packet['role']}",
            f"Phase: {context_packet['phase']}",
            f"Parent issue: {context_packet['parent_issue_id']}",
            f"Child: {context_packet['child_id']} - {context_packet['child_title']}",
            "",
            "Child body:",
            str(context_packet["child_body"]),
            "",
            "Acceptance criteria:",
            acceptance,
            "",
            "Repo bootloader:",
            bootloader_text,
            "",
            "Spec locations:",
            spec_locations,
            "",
            "ADR locations:",
            adr_locations,
            "",
            "Quality gates:",
            quality_gates,
            "",
            "Return the required structured role result.",
        ]
    )


def _bullet_list(values: list[str]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {value}" for value in values)


def _branch_name(parent_issue_id: str, child_id: str, phase: ChildPhase) -> str:
    return "/".join(
        [
            "smda",
            _slug(parent_issue_id),
            _slug(child_id),
            phase.value.lower(),
        ]
    )


def _slug(value: str) -> str:
    characters = [
        character.lower() if character.isalnum() else "-"
        for character in value.strip()
    ]
    slug = "".join(characters).strip("-")
    return slug or "item"
