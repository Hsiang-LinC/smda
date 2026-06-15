from pathlib import Path

import pytest

from helpers import write_minimal_config
from smda_scheduler.config import load_config
from smda_scheduler.context_packets import (
    CodexHarnessContextAdapter,
    ContextDiscoveryError,
)


def test_codex_harness_context_adapter_builds_repo_packet(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# Agent boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "spec.md").write_text("# Spec\n", encoding="utf-8")

    config = load_config(config_path, repo_root=tmp_path)
    packet = CodexHarnessContextAdapter().build_repo_packet(config)

    assert packet.bootloader_path == tmp_path / "AGENTS.md"
    assert packet.bootloader_text == "# Agent boot\n"
    assert packet.spec_locations == (tmp_path / "docs",)
    assert packet.adr_locations == ()
    assert packet.quality_gates == ("pytest",)


def test_codex_harness_context_adapter_declares_capabilities():
    descriptor = CodexHarnessContextAdapter().descriptor()

    assert descriptor.id == "codex-harness"
    assert descriptor.capabilities >= frozenset(
        {"bootloader", "spec_locations", "repo_commands"}
    )


def test_codex_harness_context_adapter_rejects_missing_required_paths(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    config = load_config(config_path, repo_root=tmp_path)

    with pytest.raises(ContextDiscoveryError, match="bootloader"):
        CodexHarnessContextAdapter().build_repo_packet(config)


def test_codex_harness_context_adapter_rejects_path_escape(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# Agent boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    config = load_config(config_path, repo_root=tmp_path)
    escaped = config.__class__(
        config_schema_version=config.config_schema_version,
        repo_root=config.repo_root,
        runtime=config.runtime,
        adapters=config.adapters,
        schemas=config.schemas,
        context=config.context.__class__(
            bootloader_path="../AGENTS.md",
            spec_locations=config.context.spec_locations,
            quality_gates=config.context.quality_gates,
            adr_locations=config.context.adr_locations,
        ),
        policy=config.policy,
        prompts=config.prompts,
        labels=config.labels,
    )

    with pytest.raises(ContextDiscoveryError, match="escapes repo root"):
        CodexHarnessContextAdapter().build_repo_packet(escaped)
