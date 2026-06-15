from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smda_scheduler.context_packets import RepoContextPacket
from smda_scheduler.role_contracts import (
    RoleContract,
    child_role_contract_for_phase,
    parent_role_contract_for_phase,
)
from smda_scheduler.sandcastle_execution import RoleAttemptRequest
from smda_scheduler.workflow import ChildPhase, ParentPhase


@dataclass(frozen=True)
class AgentSelection:
    provider: str
    model: str


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
        prompt=_prompt(contract, context_packet, repo_context.bootloader_text),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=agent.provider,
        agent_model=agent.model,
    )


def build_parent_graph_spec_review_request(
    *,
    attempt_id: str,
    graph: ParentGraphContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    return _build_parent_graph_review_request(
        attempt_id=attempt_id,
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
    graph: ParentGraphContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    return _build_parent_graph_review_request(
        attempt_id=attempt_id,
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
    graph: ParentGraphContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    return _build_parent_graph_review_request(
        attempt_id=attempt_id,
        graph=graph,
        phase=ParentPhase.PARENT_QA_REVIEWING,
        repo_context=repo_context,
        repo_root=repo_root,
        sandbox_provider=sandbox_provider,
        agent=agent,
    )


def _build_parent_graph_review_request(
    *,
    attempt_id: str,
    graph: ParentGraphContext,
    phase: ParentPhase,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    contract = parent_role_contract_for_phase(phase)
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
        ),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=agent.provider,
        agent_model=agent.model,
    )


def build_parent_graph_decomposer_request(
    *,
    attempt_id: str,
    parent: ParentSpecContext,
    repo_context: RepoContextPacket,
    repo_root: Path,
    sandbox_provider: str,
    agent: AgentSelection,
) -> RoleAttemptRequest:
    phase = ParentPhase.GRAPH_DECOMPOSING
    contract = parent_role_contract_for_phase(phase)
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
        prompt=_parent_prompt(contract, context_packet, repo_context.bootloader_text),
        output_tag=contract.output_tag,
        schema_id=contract.schema_id,
        sandbox_provider=sandbox_provider,
        agent_provider=agent.provider,
        agent_model=agent.model,
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


def _prompt(
    contract: RoleContract,
    context_packet: dict[str, Any],
    bootloader_text: str,
) -> str:
    return contract.render_prompt(
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


def _parent_graph_prompt(
    contract: RoleContract,
    context_packet: dict[str, Any],
    bootloader_text: str,
) -> str:
    values = _parent_prompt_values(
        context_packet,
        bootloader_text,
        schema_id=contract.schema_id,
    )
    values["graph_checksum"] = str(context_packet["graph_checksum"])
    values["children"] = _json_block(context_packet["children"])
    return contract.render_prompt(values)


def _parent_prompt(
    contract: RoleContract,
    context_packet: dict[str, Any],
    bootloader_text: str,
) -> str:
    return contract.render_prompt(
        _parent_prompt_values(
            context_packet,
            bootloader_text,
            schema_id=contract.schema_id,
        )
    )


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
            phase.value.lower(),
        ]
    )


def _parent_branch_name(parent_issue_id: str, phase: ParentPhase) -> str:
    return "/".join(["smda", _slug(parent_issue_id), _slug(phase.value)])


def _slug(value: str) -> str:
    characters = [
        character.lower() if character.isalnum() else "-"
        for character in value.strip()
    ]
    slug = "".join(characters).strip("-")
    return slug or "item"
