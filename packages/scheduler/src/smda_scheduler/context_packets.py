from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from smda_scheduler.harness_acceptance import AcceptancePolicy, AcceptanceError
from smda_scheduler.adapters import AdapterDescriptor
from smda_scheduler.config import SmdaConfig
from smda_scheduler.role_contracts import (
    CHILD_ROLE_BY_PHASE,
    PARENT_ROLE_BY_PHASE,
    ROADMAP_ROLE_BY_PHASE,
    harness_role_bindings,
)
from smda_scheduler.skill_loader import SkillNotFoundError, load_skill_methodology


class ContextDiscoveryError(ValueError):
    """Raised when repo context cannot be safely discovered."""


@dataclass(frozen=True)
class RepoContextPacket:
    bootloader_path: Path
    bootloader_text: str
    spec_locations: tuple[Path, ...]
    adr_locations: tuple[Path, ...]
    quality_gates: tuple[str, ...]
    # skill_id -> methodology body (ADR-0004). Empty when no skills_dir configured.
    skills: Mapping[str, str] = field(default_factory=dict)
    harness_contract_path: Path | None = None
    blocking_labels: frozenset[str] = frozenset()
    acceptance_policy: AcceptancePolicy | None = None
    harness_contract_checksum: str | None = None


class CodexHarnessContextAdapter:
    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            id="codex-harness",
            version="0.1.0",
            capabilities=frozenset(
                {
                    "bootloader",
                    "spec_locations",
                    "repo_commands",
                    "roadmap",
                    "adr",
                    "quality_gates",
                }
            ),
        )

    def build_repo_packet(self, config: SmdaConfig) -> RepoContextPacket:
        bootloader_path = _required_path(
            config.repo_root,
            config.context.bootloader_path,
            label="bootloader",
        )
        spec_locations = tuple(
            _required_path(config.repo_root, location, label="spec location")
            for location in config.context.spec_locations
        )
        adr_locations = _existing_optional_paths(
            config.repo_root,
            config.context.adr_locations,
            label="ADR location",
        )

        skills = _load_declared_skills(config)
        contract_path, blocking_labels, acceptance, checksum = _load_harness_contract(config)
        return RepoContextPacket(
            bootloader_path=bootloader_path,
            bootloader_text=bootloader_path.read_text(encoding="utf-8"),
            spec_locations=spec_locations,
            adr_locations=adr_locations,
            quality_gates=tuple(config.context.quality_gates),
            skills=skills,
            harness_contract_path=contract_path,
            blocking_labels=blocking_labels,
            acceptance_policy=acceptance,
            harness_contract_checksum=checksum,
        )


def _load_harness_contract(config: SmdaConfig) -> tuple[Path | None, frozenset[str], AcceptancePolicy | None, str | None]:
    value = config.context.harness_contract_path
    if value is None:
        return None, frozenset(), None, None
    if not isinstance(value, str) or not value.strip():
        raise ContextDiscoveryError(
            "harness_contract_path must be a nonempty repo-relative path"
        )
    if Path(value).is_absolute():
        raise ContextDiscoveryError("harness_contract_path must be repo-relative")
    path = _required_path(config.repo_root, value, label="harness contract")
    if not config.context.skills_dir:
        raise ContextDiscoveryError("Harness contract requires context.skills_dir")
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as error:
        raise ContextDiscoveryError(f"Cannot read harness contract: {error}") from error
    expected_keys = {"schema_version", "execution_owner", "roles", "blocking_labels", "acceptance"}
    if not isinstance(data, dict) or set(data) != expected_keys:
        raise ContextDiscoveryError(
            "Harness contract must contain exactly schema_version, execution_owner, "
            "roles, blocking_labels, acceptance; unsupported policies cannot be enforced"
        )
    if type(data["schema_version"]) is not int or data["schema_version"] != 2:
        raise ContextDiscoveryError("Unsupported harness contract schema_version")
    if data["execution_owner"] != "smda":
        raise ContextDiscoveryError("Harness execution_owner must be smda")
    expected_roles = harness_role_bindings()
    if data["roles"] != expected_roles:
        raise ContextDiscoveryError(
            "Harness role phase/skill bindings do not match the runtime role registry"
        )
    labels = data["blocking_labels"]
    if not isinstance(labels, list) or any(
        not isinstance(v, str) or not v.strip() or v != v.strip() for v in labels
    ):
        raise ContextDiscoveryError(
            "Harness blocking_labels must be a list of nonempty trimmed strings"
        )
    if len(set(labels)) != len(labels):
        raise ContextDiscoveryError("Harness blocking_labels must not contain duplicates")
    try:
        acceptance = AcceptancePolicy.from_dict(data["acceptance"])
    except AcceptanceError as error:
        raise ContextDiscoveryError(str(error)) from error
    return path, frozenset(labels), acceptance, hashlib.sha256(raw).hexdigest()


def _load_declared_skills(config: SmdaConfig) -> dict[str, str]:
    """Load every skill any role declares from the configured skills_dir.

    Returns {} when no skills_dir is set (injection disabled, prompts unchanged).
    Fails closed: a declared-but-missing skill is a context error.
    """
    if not config.context.skills_dir:
        return {}
    skills_dir = _required_path(
        config.repo_root, config.context.skills_dir, label="skills dir"
    )
    declared = {
        skill_id
        for contract in (
            *CHILD_ROLE_BY_PHASE.values(),
            *PARENT_ROLE_BY_PHASE.values(),
            *ROADMAP_ROLE_BY_PHASE.values(),
        )
        for skill_id in contract.methodology_skills
    }
    skills: dict[str, str] = {}
    for skill_id in sorted(declared):
        try:
            skills[skill_id] = load_skill_methodology(skills_dir, skill_id)
            if not skills[skill_id]:
                raise ContextDiscoveryError(f"Empty methodology skill: {skill_id}")
        except SkillNotFoundError as error:
            raise ContextDiscoveryError(
                f"Declared methodology skill not found in {config.context.skills_dir}: "
                f"{skill_id}"
            ) from error
    return skills


def _required_path(repo_root: Path, value: str, *, label: str) -> Path:
    path = _resolve_repo_path(repo_root, value, label=label)
    if not path.exists():
        raise ContextDiscoveryError(f"Missing {label}: {value}")
    return path


def _optional_path(repo_root: Path, value: str, *, label: str) -> Path | None:
    path = _resolve_repo_path(repo_root, value, label=label)
    if not path.exists():
        return None
    return path


def _existing_optional_paths(
    repo_root: Path,
    values: list[str],
    *,
    label: str,
) -> tuple[Path, ...]:
    paths: list[Path] = []
    for value in values:
        path = _optional_path(repo_root, value, label=label)
        if path is not None:
            paths.append(path)
    return tuple(paths)


def _resolve_repo_path(repo_root: Path, value: str, *, label: str) -> Path:
    path = (repo_root / value).resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as error:
        raise ContextDiscoveryError(f"{label} escapes repo root: {value}") from error
    return path
