from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from smda_scheduler.adapters import AdapterDescriptor
from smda_scheduler.config import SmdaConfig
from smda_scheduler.role_contracts import (
    CHILD_ROLE_BY_PHASE,
    PARENT_ROLE_BY_PHASE,
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

        return RepoContextPacket(
            bootloader_path=bootloader_path,
            bootloader_text=bootloader_path.read_text(encoding="utf-8"),
            spec_locations=spec_locations,
            adr_locations=adr_locations,
            quality_gates=tuple(config.context.quality_gates),
            skills=_load_declared_skills(config),
        )


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
        for contract in (*CHILD_ROLE_BY_PHASE.values(), *PARENT_ROLE_BY_PHASE.values())
        for skill_id in contract.methodology_skills
    }
    skills: dict[str, str] = {}
    for skill_id in sorted(declared):
        try:
            skills[skill_id] = load_skill_methodology(skills_dir, skill_id)
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
