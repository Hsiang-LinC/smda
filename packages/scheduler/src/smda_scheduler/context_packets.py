from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smda_scheduler.adapters import AdapterDescriptor
from smda_scheduler.config import SmdaConfig


class ContextDiscoveryError(ValueError):
    """Raised when repo context cannot be safely discovered."""


@dataclass(frozen=True)
class RepoContextPacket:
    bootloader_path: Path
    bootloader_text: str
    spec_locations: tuple[Path, ...]
    adr_locations: tuple[Path, ...]
    quality_gates: tuple[str, ...]


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
        )


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
