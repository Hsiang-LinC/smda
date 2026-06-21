import json
import tomllib
from pathlib import Path


PLUGIN_ROOT = Path("plugins/smda-automation")


def test_pyproject_exposes_smda_scheduler_console_script():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["smda-scheduler"] == (
        "smda_scheduler.cli:main"
    )


def test_pyproject_declares_scheduler_src_layout():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["package-dir"] == {
        "": "packages/scheduler/src"
    }
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == [
        "packages/scheduler/src"
    ]


def test_smda_plugin_ships_only_smda_setup_skill():
    skills = sorted(
        path.name for path in (PLUGIN_ROOT / "skills").iterdir() if path.is_dir()
    )

    assert skills == ["setup-smda-automation"]


def test_plugin_manifests_describe_smda_tier3_only():
    for manifest_path in (
        PLUGIN_ROOT / ".codex-plugin" / "plugin.json",
        PLUGIN_ROOT / ".claude-plugin" / "plugin.json",
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        interface = manifest.get("interface", {})
        searchable_text = "\n".join(
            [
                manifest.get("description", ""),
                interface.get("shortDescription", ""),
                interface.get("longDescription", ""),
                *interface.get("defaultPrompt", []),
            ]
        )

        assert "Two setup skills" not in searchable_text
        assert "setup-codex-development-harness builds" not in searchable_text
        assert "Tier-3 config" in searchable_text


def test_setup_smda_requires_external_harness_and_documents_routing():
    skill_text = (PLUGIN_ROOT / "skills" / "setup-smda-automation" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    adapters_text = (
        PLUGIN_ROOT / "skills" / "setup-smda-automation" / "adapters.md"
    ).read_text(encoding="utf-8")
    methodology_text = (
        PLUGIN_ROOT / "skills" / "setup-smda-automation" / "methodology.md"
    ).read_text(encoding="utf-8")

    assert "engineering:setup-codex-development-harness" in skill_text
    assert "equivalent harness" in skill_text
    for route in (
        "Execution: smda",
        "Execution: smda-task",
        "Execution: smda-roadmap",
        "Execution: smda-child",
        "Execution: manual",
    ):
        assert route in adapters_text
    assert "| AFK |" in methodology_text
    assert "| HITL |" in methodology_text
    assert "| `Execution:` |" in methodology_text
    assert "| `Agent Review` |" in methodology_text
    assert "| `Human Review` |" in methodology_text


def test_setup_smda_docs_do_not_generate_legacy_agent_config():
    setup_dir = PLUGIN_ROOT / "skills" / "setup-smda-automation"

    for path in setup_dir.rglob("*.md"):
        assert "docs/agents/" not in path.read_text(encoding="utf-8")
