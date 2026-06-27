import json
import subprocess
import tomllib
from pathlib import Path


PLUGIN_ROOT = Path("plugins/smda-automation")
SCHEDULER_PACKAGE = Path("packages/scheduler/src/smda_scheduler")
PLUGIN_RUNTIME_PACKAGE = PLUGIN_ROOT / "runtime" / "python" / "smda_scheduler"
SANDCASTLE_RUNNER_SOURCE = Path("packages/sandcastle-runner/src/cli.ts")
PLUGIN_SANDCASTLE_RUNNER = PLUGIN_ROOT / "runtime" / "js" / "sandcastle-runner.mjs"


def _package_files(root: Path) -> list[Path]:
    return sorted(
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )


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


def test_codex_plugin_bundles_product_owned_mcp_server():
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    mcp_config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))

    assert manifest["mcpServers"] == "./.mcp.json"
    assert "MCP" in manifest["description"]
    assert "MCP" in manifest["interface"]["longDescription"]
    assert mcp_config == {
        "mcpServers": {
            "smda": {
                "command": "python3",
                "args": ["./runtime/smda-scheduler-mcp.py"],
                "cwd": ".",
            }
        }
    }


def test_smda_plugin_bundles_scheduler_runtime_copy_in_sync():
    source_files = _package_files(SCHEDULER_PACKAGE)
    bundled_files = _package_files(PLUGIN_RUNTIME_PACKAGE)

    assert bundled_files == source_files
    for relative_path in source_files:
        assert (PLUGIN_RUNTIME_PACKAGE / relative_path).read_bytes() == (
            SCHEDULER_PACKAGE / relative_path
        ).read_bytes()


def test_smda_plugin_runtime_wrapper_starts_from_plugin_bundle():
    result = subprocess.run(
        ["python3", "-B", "runtime/smda-scheduler-mcp.py"],
        cwd=PLUGIN_ROOT,
        input=b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == b""


def test_smda_plugin_bundles_sandcastle_runner_artifact_in_sync(tmp_path: Path):
    rebuilt_runner = tmp_path / "sandcastle-runner.mjs"
    subprocess.run(
        [
            "node_modules/.bin/esbuild",
            str(SANDCASTLE_RUNNER_SOURCE),
            "--bundle",
            "--platform=node",
            "--format=esm",
            "--target=node20",
            f"--outfile={rebuilt_runner}",
        ],
        check=True,
    )

    assert PLUGIN_SANDCASTLE_RUNNER.read_bytes() == rebuilt_runner.read_bytes()


def test_smda_plugin_sandcastle_runner_starts_from_plugin_bundle(tmp_path: Path):
    result_file = tmp_path / "result.json"
    result = subprocess.run(
        ["node", str(PLUGIN_SANDCASTLE_RUNNER), "--result-file", str(result_file)],
        input=b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == b""
    assert json.loads(result_file.read_text(encoding="utf-8")) == {
        "status": "agent_protocol_failed",
        "error_message": "Invalid JSON IPC request",
    }


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


def test_setup_smda_docs_describe_product_owned_mcp_surface():
    daemon_ops = (
        PLUGIN_ROOT / "skills" / "setup-smda-automation" / "daemon-operations.md"
    ).read_text(encoding="utf-8")

    assert "python3 ./runtime/smda-scheduler-mcp.py" in daemon_ops
    for tool in (
        "smda_status",
        "smda_pause",
        "smda_resume",
        "smda_reconcile_claims",
        "smda_force_phase",
    ):
        assert tool in daemon_ops
    assert "smda_daemon" not in daemon_ops
    assert "plugin bundles the SMDA Scheduler runtime" in daemon_ops
    assert ".mcp.json` pointer written by setup" not in daemon_ops


def test_setup_smda_docs_surface_backlog_adapter_choice():
    setup_dir = PLUGIN_ROOT / "skills" / "setup-smda-automation"
    skill_text = (setup_dir / "SKILL.md").read_text(encoding="utf-8")
    adapters_text = (setup_dir / "adapters.md").read_text(encoding="utf-8")
    fixtures_text = (setup_dir / "fixtures" / "README.md").read_text(
        encoding="utf-8"
    )
    combined = "\n".join([skill_text, adapters_text, fixtures_text])

    assert "Backlog adapter choice" in skill_text
    assert "adapters.backlog.id: linear" in combined
    assert "adapters.backlog.id: local-ledger" in combined
    for key in ("active_path", "completed_path", "abandoned_path"):
        assert key in combined
    assert "unsupported tracker" in combined.lower()
    assert "do not generate adapter code" in combined
