from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.role_contracts import (
    RoleContract,
    child_role_contract_for_phase,
    roadmap_role_contract_for_phase,
)
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.workflow import ChildPhase, ParentPhase, RoadmapPhase


@dataclass(frozen=True)
class AgentSelection:
    provider: str
    model: str
    effort: str | None = None
    role_overrides: Mapping[str, "AgentSelection"] = field(default_factory=dict)

    def for_role(self, role: str) -> "AgentSelection":
        return self.role_overrides.get(role, self)


@dataclass(frozen=True)
class ChildTaskContext:
    child_id: str
    title: str
    body: str
    in_scope: tuple[str, ...] = field(default_factory=tuple)
    out_of_scope: tuple[str, ...] = field(default_factory=tuple)
    touched_surfaces: dict[str, list[str]] = field(default_factory=dict)
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)
    verification: dict[str, list[str]] = field(default_factory=dict)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    dependency_outputs: tuple[dict[str, object], ...] = field(default_factory=tuple)
    candidate_ref: str | None = None
    review_findings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParentSpecContext:
    parent_issue_id: str
    title: str
    body: str
    spec_path: str
    spec_checksum: str
    approval_evidence: str
    spec_text: str


@dataclass(frozen=True)
class ParentGraphContext:
    parent: ParentSpecContext
    graph_checksum: str
    children: tuple[dict[str, object], ...]
    dependency_edges: tuple[dict[str, object], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RoadmapSpecContext:
    roadmap_issue_id: str
    title: str
    body: str
    spec_path: str
    spec_checksum: str
    approval_evidence: str
    spec_text: str
    open_parent_snapshot: tuple[dict[str, object], ...] = field(default_factory=tuple)


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
    contract = child_role_contract_for_phase(phase)
    selected_agent = agent.for_role(contract.role.value)
    context_packet = _context_packet(
        parent_issue_id=parent_issue_id,
        child=child,
        phase=phase,
        role=contract.role.value,
        repo_context=repo_context,
    )
    return RoleAttemptRequest(
        attempt_id=attempt_id,
        role=contract.role.value,
        phase=phase,
        branch=_branch_name(parent_issue_id, child.child_id, phase),
        cwd=repo_root,
        context_packet=context_packet,
        prompt=_prompt(
            contract,
            context_packet,
            repo_context.bootloader_text,
            repo_context.skills,
        ),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=selected_agent.provider,
        agent_model=selected_agent.model,
        agent_effort=selected_agent.effort,
    )


def build_parent_graph_spec_review_request(
    *,
    attempt_id: str,
    contract: RoleContract,
    graph: ParentGraphContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    return _build_parent_graph_review_request(
        attempt_id=attempt_id,
        contract=contract,
        graph=graph,
        phase=ParentPhase.GRAPH_SPEC_REVIEWING,
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )


def build_parent_graph_execution_review_request(
    *,
    attempt_id: str,
    contract: RoleContract,
    graph: ParentGraphContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    return _build_parent_graph_review_request(
        attempt_id=attempt_id,
        contract=contract,
        graph=graph,
        phase=ParentPhase.GRAPH_EXECUTION_REVIEWING,
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )


def build_parent_qa_review_request(
    *,
    attempt_id: str,
    contract: RoleContract,
    graph: ParentGraphContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    return _build_parent_graph_review_request(
        attempt_id=attempt_id,
        contract=contract,
        graph=graph,
        phase=ParentPhase.PARENT_QA_REVIEWING,
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )


def build_parent_accept_conflict_resolver_request(
    *,
    attempt_id: str,
    contract: RoleContract,
    graph: ParentGraphContext,
    conflict_history: dict[str, object],
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    phase = ParentPhase.CHILD_ACCEPT_CONFLICT_RESOLVING
    selected_agent = agent.for_role(contract.role.value)
    context_packet = _parent_graph_context_packet(
        graph=graph,
        phase=phase,
        role=contract.role.value,
        repo_context=repo_context,
    )
    context_packet["conflict_history"] = conflict_history
    return RoleAttemptRequest(
        attempt_id=attempt_id,
        role=contract.role.value,
        phase=phase,
        branch=_parent_branch_name(graph.parent.parent_issue_id, phase),
        cwd=repo_root,
        context_packet=context_packet,
        prompt=_parent_graph_prompt(
            contract,
            context_packet,
            repo_context.bootloader_text,
            repo_context.skills,
        ),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=selected_agent.provider,
        agent_model=selected_agent.model,
        agent_effort=selected_agent.effort,
    )


def _build_parent_graph_review_request(
    *,
    attempt_id: str,
    contract: RoleContract,
    graph: ParentGraphContext,
    phase: ParentPhase,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    selected_agent = agent.for_role(contract.role.value)
    context_packet = _parent_graph_context_packet(
        graph=graph,
        phase=phase,
        role=contract.role.value,
        repo_context=repo_context,
    )
    return RoleAttemptRequest(
        attempt_id=attempt_id,
        role=contract.role.value,
        phase=phase,
        branch=_parent_branch_name(graph.parent.parent_issue_id, phase),
        cwd=repo_root,
        context_packet=context_packet,
        prompt=_parent_graph_prompt(
            contract,
            context_packet,
            repo_context.bootloader_text,
            repo_context.skills,
        ),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=selected_agent.provider,
        agent_model=selected_agent.model,
        agent_effort=selected_agent.effort,
    )


def build_parent_graph_fixer_request(
    *,
    attempt_id: str,
    contract: RoleContract,
    graph: ParentGraphContext,
    review_findings: str,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    phase = ParentPhase.GRAPH_FIXING
    selected_agent = agent.for_role(contract.role.value)
    context_packet = _parent_graph_context_packet(
        graph=graph,
        phase=phase,
        role=contract.role.value,
        repo_context=repo_context,
    )
    context_packet["review_findings"] = review_findings
    return RoleAttemptRequest(
        attempt_id=attempt_id,
        role=contract.role.value,
        phase=phase,
        branch=_parent_branch_name(graph.parent.parent_issue_id, phase),
        cwd=repo_root,
        context_packet=context_packet,
        prompt=_parent_graph_prompt(
            contract, context_packet, repo_context.bootloader_text, repo_context.skills
        ),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=selected_agent.provider,
        agent_model=selected_agent.model,
        agent_effort=selected_agent.effort,
    )


def build_parent_graph_decomposer_request(
    *,
    attempt_id: str,
    contract: RoleContract,
    parent: ParentSpecContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    phase = ParentPhase.GRAPH_DECOMPOSING
    selected_agent = agent.for_role(contract.role.value)
    context_packet = _parent_context_packet(
        parent=parent,
        phase=phase,
        role=contract.role.value,
        repo_context=repo_context,
    )
    return RoleAttemptRequest(
        attempt_id=attempt_id,
        role=contract.role.value,
        phase=phase,
        branch=_parent_branch_name(parent.parent_issue_id, phase),
        cwd=repo_root,
        context_packet=context_packet,
        prompt=_parent_prompt(
            contract,
            context_packet,
            repo_context.bootloader_text,
            repo_context.skills,
        ),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=selected_agent.provider,
        agent_model=selected_agent.model,
        agent_effort=selected_agent.effort,
    )


def build_roadmap_decomposer_request(
    *,
    attempt_id: str,
    roadmap: RoadmapSpecContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    phase = RoadmapPhase.ROADMAP_DECOMPOSING
    contract = roadmap_role_contract_for_phase(phase)
    selected_agent = agent.for_role(contract.role.value)
    context_packet = _roadmap_context_packet(
        roadmap=roadmap,
        phase=phase,
        role=contract.role.value,
        repo_context=repo_context,
    )
    return RoleAttemptRequest(
        attempt_id=attempt_id,
        role=contract.role.value,
        phase=phase,
        branch=_roadmap_branch_name(roadmap.roadmap_issue_id, phase),
        cwd=repo_root,
        context_packet=context_packet,
        prompt=_roadmap_prompt(
            contract,
            context_packet,
            repo_context.bootloader_text,
            repo_context.skills,
        ),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=selected_agent.provider,
        agent_model=selected_agent.model,
        agent_effort=selected_agent.effort,
    )


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
        "in_scope": list(child.in_scope),
        "out_of_scope": list(child.out_of_scope),
        "touched_surfaces": child.touched_surfaces,
        "acceptance_criteria": list(child.acceptance_criteria),
        "verification": child.verification,
        "dependencies": list(child.dependencies),
        "dependency_outputs": list(child.dependency_outputs),
        "candidate_ref": child.candidate_ref,
        "review_findings": list(child.review_findings),
        "phase": phase.value,
        "role": role,
        "bootloader_path": str(repo_context.bootloader_path),
        "spec_locations": [str(path) for path in repo_context.spec_locations],
        "adr_locations": [str(path) for path in repo_context.adr_locations],
        "quality_gates": list(repo_context.quality_gates),
    }


def _roadmap_context_packet(
    *,
    roadmap: RoadmapSpecContext,
    phase: RoadmapPhase,
    role: str,
    repo_context: RepoContextPacket,
) -> dict[str, Any]:
    return {
        "roadmap_issue_id": roadmap.roadmap_issue_id,
        "roadmap_title": roadmap.title,
        "roadmap_body": roadmap.body,
        "spec_path": roadmap.spec_path,
        "spec_checksum": roadmap.spec_checksum,
        "approval_evidence": roadmap.approval_evidence,
        "spec_text": roadmap.spec_text,
        "open_parent_snapshot": list(roadmap.open_parent_snapshot),
        "phase": phase.value,
        "role": role,
        "bootloader_path": str(repo_context.bootloader_path),
        "spec_locations": [str(path) for path in repo_context.spec_locations],
        "adr_locations": [str(path) for path in repo_context.adr_locations],
        "quality_gates": list(repo_context.quality_gates),
    }


def _parent_context_packet(
    *,
    parent: ParentSpecContext,
    phase: ParentPhase,
    role: str,
    repo_context: RepoContextPacket,
) -> dict[str, Any]:
    return {
        "parent_issue_id": parent.parent_issue_id,
        "parent_title": parent.title,
        "parent_body": parent.body,
        "spec_path": parent.spec_path,
        "spec_checksum": parent.spec_checksum,
        "approval_evidence": parent.approval_evidence,
        "spec_text": parent.spec_text,
        "phase": phase.value,
        "role": role,
        "bootloader_path": str(repo_context.bootloader_path),
        "spec_locations": [str(path) for path in repo_context.spec_locations],
        "adr_locations": [str(path) for path in repo_context.adr_locations],
        "quality_gates": list(repo_context.quality_gates),
    }


def _parent_graph_context_packet(
    *,
    graph: ParentGraphContext,
    phase: ParentPhase,
    role: str,
    repo_context: RepoContextPacket,
) -> dict[str, Any]:
    context_packet = _parent_context_packet(
        parent=graph.parent,
        phase=phase,
        role=role,
        repo_context=repo_context,
    )
    context_packet["graph_checksum"] = graph.graph_checksum
    context_packet["children"] = list(graph.children)
    context_packet["dependency_edges"] = list(graph.dependency_edges)
    return context_packet


def _inject_methodology(
    prompt: str,
    contract: RoleContract,
    skills: Mapping[str, str] | None,
) -> str:
    skills = skills or {}
    blocks = [
        f"\n\n## Methodology: {skill_id}\n{skills[skill_id]}"
        for skill_id in contract.methodology_skills
        if skill_id in skills
    ]
    return prompt + "".join(blocks) + (
        "\n\n## Runtime execution boundary\n"
        f"Execution owner: SMDA. Assigned role: {contract.role.value}. "
        f"Shared harness phase: {contract.harness_phase}.\n"
        "Use repo guidance and methodology within this assignment. "
        "Do not advance phases, restart the interactive pipeline, publish work "
        "items, or write tracker lifecycle state. Return the assigned role artifact; "
        "the runtime owns transitions, publication and acceptance effects. "
        "Report unresolved decisions through this role's supported result/escalation "
        "contract; do not invent approval or weaken gates.\n"
    )


def _prompt(
    contract: RoleContract,
    context_packet: dict[str, Any],
    bootloader_text: str,
    skills: Mapping[str, str] | None = None,
) -> str:
    prompt = contract.render_prompt(
        {
            "phase": str(context_packet["phase"]),
            "parent_issue_id": str(context_packet["parent_issue_id"]),
            "child_id": str(context_packet["child_id"]),
            "child_title": str(context_packet["child_title"]),
            "child_body": str(context_packet["child_body"]),
            "acceptance_criteria": _bullet_list(context_packet["acceptance_criteria"]),
            "bootloader_text": bootloader_text,
            "spec_locations": _bullet_list(context_packet["spec_locations"]),
            "adr_locations": _bullet_list(context_packet["adr_locations"]),
            "quality_gates": _bullet_list(context_packet["quality_gates"]),
            "schema_id": contract.schema_id,
        }
    )
    task_constraints = {
        key: context_packet[key]
        for key in (
            "in_scope", "out_of_scope", "touched_surfaces", "verification",
            "dependencies", "dependency_outputs", "candidate_ref", "review_findings",
        )
    }
    prompt += "\n\n## Assigned task constraints and evidence\n" + _json_block(task_constraints)
    return _inject_methodology(prompt, contract, skills)


def _parent_graph_prompt(
    contract: RoleContract,
    context_packet: dict[str, Any],
    bootloader_text: str,
    skills: Mapping[str, str] | None = None,
) -> str:
    values = _parent_prompt_values(
        context_packet,
        bootloader_text,
        schema_id=contract.schema_id,
    )
    values["graph_checksum"] = str(context_packet["graph_checksum"])
    values["children"] = _json_block(context_packet["children"])
    values["dependency_edges"] = _json_block(
        context_packet.get("dependency_edges", [])
    )
    values["review_findings"] = str(context_packet.get("review_findings", ""))
    values["conflict_history"] = _json_block(
        context_packet.get("conflict_history", {})
    )
    return _inject_methodology(contract.render_prompt(values), contract, skills)


def _parent_prompt(
    contract: RoleContract,
    context_packet: dict[str, Any],
    bootloader_text: str,
    skills: Mapping[str, str] | None = None,
) -> str:
    prompt = contract.render_prompt(
        _parent_prompt_values(
            context_packet,
            bootloader_text,
            schema_id=contract.schema_id,
        )
    )
    return _inject_methodology(prompt, contract, skills)


def _roadmap_prompt(
    contract: RoleContract,
    context_packet: dict[str, Any],
    bootloader_text: str,
    skills: Mapping[str, str] | None = None,
) -> str:
    prompt = contract.render_prompt(
        {
            "phase": str(context_packet["phase"]),
            "roadmap_issue_id": str(context_packet["roadmap_issue_id"]),
            "roadmap_title": str(context_packet["roadmap_title"]),
            "roadmap_body": str(context_packet["roadmap_body"]),
            "spec_path": str(context_packet["spec_path"]),
            "spec_checksum": str(context_packet["spec_checksum"]),
            "approval_evidence": str(context_packet["approval_evidence"]),
            "spec_text": str(context_packet["spec_text"]),
            "open_parent_snapshot": _json_block(
                context_packet.get("open_parent_snapshot", [])
            ),
            "bootloader_text": bootloader_text,
            "spec_locations": _bullet_list(context_packet["spec_locations"]),
            "adr_locations": _bullet_list(context_packet["adr_locations"]),
            "quality_gates": _bullet_list(context_packet["quality_gates"]),
            "schema_id": contract.schema_id,
        }
    )
    return _inject_methodology(prompt, contract, skills)


def _parent_prompt_values(
    context_packet: dict[str, Any],
    bootloader_text: str,
    *,
    schema_id: str,
) -> dict[str, str]:
    return {
        "phase": str(context_packet["phase"]),
        "parent_issue_id": str(context_packet["parent_issue_id"]),
        "parent_title": str(context_packet["parent_title"]),
        "parent_body": str(context_packet["parent_body"]),
        "spec_path": str(context_packet["spec_path"]),
        "spec_checksum": str(context_packet["spec_checksum"]),
        "approval_evidence": str(context_packet["approval_evidence"]),
        "spec_text": str(context_packet["spec_text"]),
        "bootloader_text": bootloader_text,
        "spec_locations": _bullet_list(context_packet["spec_locations"]),
        "adr_locations": _bullet_list(context_packet["adr_locations"]),
        "quality_gates": _bullet_list(context_packet["quality_gates"]),
        "schema_id": schema_id,
    }


def _bullet_list(values: list[str]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {value}" for value in values)


def _json_block(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _branch_name(parent_issue_id: str, child_id: str, phase: ChildPhase) -> str:
    return "/".join(
        [
            "smda",
            _slug(parent_issue_id),
            _slug(child_id),
            "candidate",
        ]
    )


def _parent_branch_name(parent_issue_id: str, phase: ParentPhase) -> str:
    return "/".join(["smda", _slug(parent_issue_id), _slug(phase.value)])


def _roadmap_branch_name(roadmap_issue_id: str, phase: RoadmapPhase) -> str:
    return "/".join(["smda-roadmap", _slug(roadmap_issue_id), _slug(phase.value)])


def _slug(value: str) -> str:
    characters = [
        character.lower() if character.isalnum() else "-"
        for character in value.strip()
    ]
    slug = "".join(characters).strip("-")
    return slug or "item"
