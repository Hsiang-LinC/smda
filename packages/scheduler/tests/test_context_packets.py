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


def _declared_skills() -> list[str]:
    import json  # noqa: F401  (kept local to avoid touching the import block)
    from smda_scheduler.role_contracts import (
        CHILD_ROLE_BY_PHASE,
        PARENT_ROLE_BY_PHASE,
    )

    return sorted(
        {
            skill_id
            for contract in (
                *CHILD_ROLE_BY_PHASE.values(),
                *PARENT_ROLE_BY_PHASE.values(),
            )
            for skill_id in contract.methodology_skills
        }
    )


def _config_with_skills_dir(tmp_path: Path) -> Path:
    import json

    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    data = json.loads(config_path.read_text())
    data["context"]["skills_dir"] = "skills"
    config_path.write_text(json.dumps(data))
    return config_path


def _write_skills(tmp_path: Path, skill_ids: list[str]) -> None:
    for skill_id in skill_ids:
        path = tmp_path / "skills" / skill_id / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: {skill_id}\n---\n# {skill_id}\nMethodology for {skill_id}.\n",
            encoding="utf-8",
        )


def test_skills_loaded_when_skills_dir_configured(tmp_path: Path):
    config_path = _config_with_skills_dir(tmp_path)
    _write_skills(tmp_path, _declared_skills())

    config = load_config(config_path, repo_root=tmp_path)
    packet = CodexHarnessContextAdapter().build_repo_packet(config)

    assert set(packet.skills) == set(_declared_skills())
    assert "Methodology for tdd." in packet.skills["tdd"]


def test_missing_declared_skill_fails_closed(tmp_path: Path):
    config_path = _config_with_skills_dir(tmp_path)
    _write_skills(tmp_path, [s for s in _declared_skills() if s != "tdd"])

    config = load_config(config_path, repo_root=tmp_path)
    with pytest.raises(ContextDiscoveryError, match="tdd"):
        CodexHarnessContextAdapter().build_repo_packet(config)


def test_no_skills_dir_means_empty_skills(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()

    config = load_config(config_path, repo_root=tmp_path)
    packet = CodexHarnessContextAdapter().build_repo_packet(config)

    assert packet.skills == {}
