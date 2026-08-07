import ast
import json
import re
import runpy
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from helpers import write_minimal_config


PLUGIN_ROOT = Path("plugins/smda-automation")
SCHEDULER_PACKAGE = Path("packages/scheduler/src/smda_scheduler")
PLUGIN_RUNTIME_LAUNCHER = PLUGIN_ROOT / "runtime" / "smda"
SANDCASTLE_RUNNER_SOURCE = Path("packages/sandcastle-runner/src/cli.ts")
PLUGIN_SANDCASTLE_RUNNER = PLUGIN_ROOT / "runtime" / "js" / "sandcastle-runner.mjs"


def _parent_phase_write_violations(source_package: Path) -> list[str]:
    if not source_package.is_dir():
        return [f"source package is missing: {source_package}"]
    paths = sorted(source_package.rglob("*.py"))
    if not paths:
        return [f"source package has no Python files: {source_package}"]

    public_writes = {
        "create_parent_run",
        "transition_parent",
        "force_parent_phase",
    }
    retired = {
        "record_parent_run",
        "record_attempt_result_and_parent_run",
        "record_attempt_result_parent_run_and_graph",
    }
    function_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    violations: list[str] = []
    definitions: dict[str, list[tuple[Path, ast.AST, ast.AST | None]]] = {
        name: [] for name in public_writes
    }
    force_references: list[tuple[Path, ast.AST]] = []
    private_calls = 0

    for path in paths:
        relative_path = path.relative_to(source_package)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }

        def ancestor(node: ast.AST, types: tuple[type[ast.AST], ...]):
            current = parents.get(node)
            while current is not None and not isinstance(current, types):
                current = parents.get(current)
            return current

        def location(node: ast.AST) -> str:
            return f"{relative_path}:{getattr(node, 'lineno', 0)}"

        for node in ast.walk(tree):
            if isinstance(node, function_types):
                owner = parents.get(node)
                if node.name in public_writes:
                    definitions[node.name].append((relative_path, node, owner))
                if node.name in retired:
                    violations.append(f"{location(node)}: retired name {node.name}")

            reference = None
            if isinstance(node, ast.Name):
                reference = node.id
            elif isinstance(node, ast.Attribute):
                reference = node.attr
            elif isinstance(node, ast.alias):
                reference = node.name.rsplit(".", 1)[-1]

            if reference in retired:
                violations.append(f"{location(node)}: retired name {reference}")
            if reference in public_writes:
                enclosing_class = ancestor(node, (ast.ClassDef,))
                enclosing_function = ancestor(node, function_types)
                if (
                    isinstance(enclosing_class, ast.ClassDef)
                    and enclosing_class.name == "PhaseLedger"
                    and (
                        not isinstance(enclosing_function, function_types)
                        or enclosing_function.name != reference
                    )
                ):
                    violations.append(
                        f"{location(node)}: unexpected PhaseLedger forwarding writer "
                        f"for {reference}"
                    )
                if reference == "force_parent_phase":
                    force_references.append((relative_path, node))

            if reference == "_transition_parent":
                enclosing_class = ancestor(node, (ast.ClassDef,))
                enclosing_function = ancestor(node, function_types)
                expected_residence = (
                    relative_path == Path("phase_ledger.py")
                    and isinstance(enclosing_class, ast.ClassDef)
                    and enclosing_class.name == "PhaseLedger"
                    and isinstance(enclosing_function, function_types)
                    and enclosing_function.name == "transition_parent"
                )
                if not expected_residence:
                    violations.append(
                        f"{location(node)}: _transition_parent reference outside "
                        "transition_parent"
                    )
                if (
                    expected_residence
                    and isinstance(parents.get(node), ast.Call)
                    and parents[node].func is node
                ):
                    private_calls += 1

            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = re.sub(r'[`"\[\]]', "", node.value)
                if not re.search(
                    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)"
                    r"\s+parent_run_state\b",
                    sql,
                    re.IGNORECASE,
                ):
                    continue
                enclosing_class = ancestor(node, (ast.ClassDef,))
                enclosing_function = ancestor(node, function_types)
                allowed_sql_residence = (
                    relative_path == Path("phase_ledger.py")
                    and isinstance(enclosing_class, ast.ClassDef)
                    and enclosing_class.name == "PhaseLedger"
                    and isinstance(enclosing_function, function_types)
                    and enclosing_function.name
                    in {"create_parent_run", "force_parent_phase", "_transition_parent"}
                )
                if not allowed_sql_residence:
                    violations.append(
                        f"{location(node)}: direct parent_run_state write outside "
                        "create_parent_run, force_parent_phase, or _transition_parent"
                    )

    for name, found in definitions.items():
        intended = [
            item
            for item in found
            if item[0] == Path("phase_ledger.py")
            and isinstance(item[2], ast.ClassDef)
            and item[2].name == "PhaseLedger"
        ]
        if len(intended) != 1:
            violations.append(
                f"{name} must have exactly one PhaseLedger definition in "
                f"phase_ledger.py; found {len(intended)}"
            )
        for relative_path, node, owner in found:
            if (
                relative_path != Path("phase_ledger.py")
                or not isinstance(owner, ast.ClassDef)
                or owner.name != "PhaseLedger"
            ):
                violations.append(
                    f"{relative_path}:{getattr(node, 'lineno', 0)}: unexpected public "
                    f"write definition {name}"
                )

    if private_calls == 0:
        violations.append(
            "PhaseLedger.transition_parent must call private _transition_parent"
        )
    if not force_references:
        violations.append("force_parent_phase must have a cli.py reference")
    for relative_path, node in force_references:
        if relative_path != Path("cli.py"):
            violations.append(
                f"{relative_path}:{getattr(node, 'lineno', 0)}: "
                "force_parent_phase reference outside cli.py"
            )

    return sorted(set(violations))


_VALID_PARENT_PHASE_WRITES = '''
class PhaseLedger:
    def create_parent_run(self, connection):
        connection.execute("INSERT INTO parent_run_state (phase) VALUES (?)")

    def transition_parent(self, connection):
        self._transition_parent(connection)

    def force_parent_phase(self, connection):
        connection.execute("UPDATE parent_run_state SET phase = ?")

    def _transition_parent(self, connection):
        connection.execute("UPDATE parent_run_state SET phase = ?")
'''


def _write_parent_phase_guard_fixture(
    source_package: Path,
    *,
    phase_ledger_suffix: str = "",
    runtime_source: str = "",
) -> None:
    source_package.mkdir(parents=True)
    (source_package / "phase_ledger.py").write_text(
        _VALID_PARENT_PHASE_WRITES + phase_ledger_suffix,
        encoding="utf-8",
    )
    (source_package / "cli.py").write_text(
        "def force(ledger):\n    ledger.force_parent_phase()\n",
        encoding="utf-8",
    )
    if runtime_source:
        (source_package / "runtime.py").write_text(runtime_source, encoding="utf-8")


def test_parent_phase_write_guard_rejects_missing_and_empty_packages(tmp_path: Path):
    missing = tmp_path / "missing"
    empty = tmp_path / "empty"
    empty.mkdir()

    assert _parent_phase_write_violations(missing) == [
        f"source package is missing: {missing}"
    ]
    assert _parent_phase_write_violations(empty) == [
        f"source package has no Python files: {empty}"
    ]


def test_parent_phase_write_guard_rejects_retired_aliases(tmp_path: Path):
    source_package = tmp_path / "smda_scheduler"
    _write_parent_phase_guard_fixture(
        source_package,
        runtime_source="def bypass(ledger):\n    legacy = ledger.record_parent_run\n",
    )

    violations = _parent_phase_write_violations(source_package)

    assert any("retired name record_parent_run" in item for item in violations)


def test_parent_phase_write_guard_requires_each_public_definition(tmp_path: Path):
    source_package = tmp_path / "smda_scheduler"
    _write_parent_phase_guard_fixture(source_package)
    phase_ledger = source_package / "phase_ledger.py"
    phase_ledger.write_text(
        phase_ledger.read_text(encoding="utf-8").replace(
            "def create_parent_run", "def missing_create_parent_run"
        ),
        encoding="utf-8",
    )

    violations = _parent_phase_write_violations(source_package)

    assert any(
        "create_parent_run must have exactly one PhaseLedger definition" in item
        for item in violations
    )


def test_parent_phase_write_guard_rejects_duplicate_public_definition(tmp_path: Path):
    source_package = tmp_path / "smda_scheduler"
    _write_parent_phase_guard_fixture(
        source_package,
        phase_ledger_suffix='''
    def create_parent_run(self, connection):
        pass
''',
    )

    violations = _parent_phase_write_violations(source_package)

    assert any(
        "create_parent_run must have exactly one PhaseLedger definition" in item
        for item in violations
    )


def test_parent_phase_write_guard_rejects_forwarding_and_private_calls(
    tmp_path: Path,
):
    source_package = tmp_path / "smda_scheduler"
    _write_parent_phase_guard_fixture(
        source_package,
        phase_ledger_suffix='''
    def forward(self):
        self.transition_parent(None)

    def bypass(self):
        self._transition_parent(None)
''',
    )

    violations = _parent_phase_write_violations(source_package)

    assert any(
        "unexpected PhaseLedger forwarding writer" in item for item in violations
    )
    assert any(
        "_transition_parent reference outside transition_parent" in item
        for item in violations
    )


def test_parent_phase_write_guard_rejects_direct_sql_writer(tmp_path: Path):
    source_package = tmp_path / "smda_scheduler"
    _write_parent_phase_guard_fixture(
        source_package,
        runtime_source='''
def bypass(connection):
    connection.execute("DELETE FROM parent_run_state WHERE parent_id = ?")
''',
    )

    violations = _parent_phase_write_violations(source_package)

    assert any("direct parent_run_state write" in item for item in violations)


def test_parent_phase_write_guard_rejects_non_cli_force_alias(tmp_path: Path):
    source_package = tmp_path / "smda_scheduler"
    _write_parent_phase_guard_fixture(
        source_package,
        runtime_source="def bypass(ledger):\n    force = ledger.force_parent_phase\n",
    )

    violations = _parent_phase_write_violations(source_package)

    assert any(
        "force_parent_phase reference outside cli.py" in item for item in violations
    )


def test_parent_phase_write_guard_requires_cli_force_reference(tmp_path: Path):
    source_package = tmp_path / "smda_scheduler"
    _write_parent_phase_guard_fixture(source_package)
    (source_package / "cli.py").write_text("def noop():\n    pass\n", encoding="utf-8")

    violations = _parent_phase_write_violations(source_package)

    assert "force_parent_phase must have a cli.py reference" in violations


def test_parent_roadmap_production_writes_use_deep_interface():
    assert _parent_phase_write_violations(SCHEDULER_PACKAGE) == []


def _package_files(root: Path) -> list[Path]:
    return sorted(
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )


def _write_clean_local_ledger_fixture(repo_root: Path) -> Path:
    (repo_root / "docs" / "work-ledger").mkdir(parents=True)
    (repo_root / "AGENTS.md").write_text("# Clean fixture\n", encoding="utf-8")
    (repo_root / "docs" / "work-ledger" / "active.md").write_text(
        "# Active Work\n", encoding="utf-8"
    )
    (repo_root / "docs" / "work-ledger" / "completed.md").write_text(
        "# Completed Work\n", encoding="utf-8"
    )
    (repo_root / "docs" / "work-ledger" / "abandoned.md").write_text(
        "# Abandoned Work\n", encoding="utf-8"
    )
    config_path = repo_root / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="local-ledger",
        context_id="codex-harness",
    )
    return config_path


def test_pyproject_exposes_smda_scheduler_console_script():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["smda"] == "smda_scheduler.cli:main"
    assert pyproject["project"]["scripts"]["smda-scheduler"] == (
        "smda_scheduler.cli:main"
    )


def test_scheduler_module_entrypoint_validates_a_clean_workspace(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = _write_clean_local_ledger_fixture(repo_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "smda_scheduler",
            "validate-config",
            str(config_path),
            "--repo-root",
            str(repo_root),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PYTHONPATH": str(SCHEDULER_PACKAGE.parent.resolve())},
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == b""
    assert json.loads(result.stdout)["status"] == "ok"


def test_pyproject_declares_scheduler_src_layout():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["package-dir"] == {
        "": "packages/scheduler/src"
    }
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == [
        "packages/scheduler/src"
    ]


def test_standalone_build_accepts_only_native_macos_targets():
    platform_tag = runpy.run_path("scripts/build_standalone_runtime.py")[
        "platform_tag"
    ]

    assert platform_tag("Darwin", "arm64") == "darwin-arm64"
    assert platform_tag("Darwin", "x86_64") == "darwin-x86_64"

    for system, machine in (("Linux", "x86_64"), ("Darwin", "i386")):
        try:
            platform_tag(system, machine)
        except ValueError as error:
            assert "macOS arm64 and x86_64" in str(error)
        else:
            raise AssertionError(f"accepted unsupported platform: {system} {machine}")


def test_standalone_build_command_creates_onedir_with_package_data(tmp_path: Path):
    pyinstaller_command = runpy.run_path("scripts/build_standalone_runtime.py")[
        "pyinstaller_command"
    ]

    command = pyinstaller_command(
        output_root=tmp_path / "artifacts",
        target="darwin-x86_64",
        python="/build/python",
    )

    assert command[:3] == ["/build/python", "-m", "PyInstaller"]
    assert "--onedir" in command
    assert command[command.index("--collect-data") + 1] == "smda_scheduler"
    assert command[command.index("--distpath") + 1] == str(
        tmp_path / "artifacts" / "darwin-x86_64"
    )
    assert command[-1].endswith("smda_scheduler/__main__.py")


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
                "command": "sh",
                "args": ["./runtime/smda", "mcp"],
                "cwd": ".",
            }
        }
    }


def _run_runtime_launcher(
    tmp_path: Path,
    *,
    system: str,
    machine: str,
    bundle_arch: str | None,
    args: tuple[str, ...] = ("status", "config.json"),
) -> subprocess.CompletedProcess[bytes]:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True)
    shutil.copy2(PLUGIN_RUNTIME_LAUNCHER, runtime_dir / "smda")

    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    uname = command_dir / "uname"
    uname.write_text(
        "#!/bin/sh\n"
        f'[ "$1" = "-s" ] && {{ echo "{system}"; exit; }}\n'
        f'echo "{machine}"\n',
        encoding="utf-8",
    )
    uname.chmod(0o755)

    if bundle_arch is not None:
        executable = runtime_dir / "bin" / f"darwin-{bundle_arch}" / "smda" / "smda"
        executable.parent.mkdir(parents=True)
        executable.write_text(
            '#!/bin/sh\nprintf \'%s\\n\' "$@"\n', encoding="utf-8"
        )
        executable.chmod(0o755)

    return subprocess.run(
        ["/bin/sh", str(runtime_dir / "smda"), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": str(command_dir)},
        check=False,
    )


def test_smda_plugin_runtime_selects_native_architecture_without_python(
    tmp_path: Path,
):
    for machine in ("arm64", "x86_64"):
        result = _run_runtime_launcher(
            tmp_path / machine,
            system="Darwin",
            machine=machine,
            bundle_arch=machine,
        )

        assert result.returncode == 0
        assert result.stdout == b"status\nconfig.json\n"
        assert result.stderr == b""


def test_smda_plugin_runtime_rejects_unsupported_platform(tmp_path: Path):
    result = _run_runtime_launcher(
        tmp_path,
        system="Linux",
        machine="x86_64",
        bundle_arch=None,
    )

    assert result.returncode == 1
    assert b"supports macOS arm64 and x86_64" in result.stderr


def test_smda_plugin_runtime_reports_missing_native_bundle(tmp_path: Path):
    result = _run_runtime_launcher(
        tmp_path,
        system="Darwin",
        machine="arm64",
        bundle_arch=None,
    )

    assert result.returncode == 1
    assert b"missing bundled runtime" in result.stderr


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


def test_smda_plugin_runtime_validates_clean_local_ledger_fixture(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = _write_clean_local_ledger_fixture(repo_root)

    for forbidden in (
        repo_root / "runtime",
        repo_root / "packages" / "scheduler",
        repo_root / "packages" / "sandcastle-runner",
        repo_root / "node_modules",
    ):
        assert not forbidden.exists()

    cli = [sys.executable, "-m", "smda_scheduler"]
    environment = {"PYTHONPATH": str(SCHEDULER_PACKAGE.parent.resolve())}
    config_result = subprocess.run(
        [*cli, "validate-config", str(config_path), "--repo-root", str(repo_root)],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    context_result = subprocess.run(
        [*cli, "validate-context", str(config_path), "--repo-root", str(repo_root)],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )

    assert config_result.returncode == 0
    assert config_result.stderr == b""
    config_payload = json.loads(config_result.stdout)
    assert config_payload["status"] == "ok"
    assert config_payload["ledger_path"].startswith(str(repo_root / ".smda"))

    assert context_result.returncode == 0
    assert context_result.stderr == b""
    assert json.loads(context_result.stdout) == {
        "status": "ok",
        "bootloader_path": str(repo_root / "AGENTS.md"),
        "spec_locations": [str(repo_root / "docs")],
        "adr_locations": [],
        "quality_gates": ["pytest"],
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

    assert "./runtime/smda status" in daemon_ops
    assert "./runtime/smda mcp" in daemon_ops
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
