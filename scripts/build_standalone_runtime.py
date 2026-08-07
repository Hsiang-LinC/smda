from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "packages" / "scheduler" / "src"
ENTRYPOINT = SOURCE_ROOT / "smda_scheduler" / "__main__.py"


def platform_tag(system: str, machine: str) -> str:
    if system == "Darwin" and machine in {"arm64", "x86_64"}:
        return f"darwin-{machine}"
    raise ValueError(
        f"standalone builds support macOS arm64 and x86_64; found {system} {machine}"
    )


def pyinstaller_command(
    *, output_root: Path, target: str, python: str = sys.executable
) -> list[str]:
    work_root = ROOT / "build" / "pyinstaller" / target
    return [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "smda",
        "--collect-data",
        "smda_scheduler",
        "--paths",
        str(SOURCE_ROOT),
        "--distpath",
        str(output_root / target),
        "--workpath",
        str(work_root / "work"),
        "--specpath",
        str(work_root),
        str(ENTRYPOINT),
    ]


def _smoke_test(executable: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="smda-standalone-") as temporary:
        repo_root = Path(temporary)
        (repo_root / "docs" / "work-ledger").mkdir(parents=True)
        (repo_root / "AGENTS.md").write_text("# Smoke fixture\n", encoding="utf-8")
        for name in ("active.md", "completed.md", "abandoned.md"):
            (repo_root / "docs" / "work-ledger" / name).write_text(
                f"# {name}\n", encoding="utf-8"
            )
        config_path = repo_root / "smda.config.json"
        config_path.write_text(
            json.dumps(
                {
                    "config_schema_version": 1,
                    "runtime": {"version_constraint": ">=0.1.0"},
                    "adapters": {
                        "execution": {
                            "id": "sandcastle",
                            "version_constraint": ">=0.1.0",
                            "provider": "noSandbox",
                            "agent": {"provider": "codex", "model": "gpt-5"},
                        },
                        "backlog": {
                            "id": "local-ledger",
                            "version_constraint": ">=0.1.0",
                            "scope_id": "smoke",
                        },
                        "context": {
                            "id": "codex-harness",
                            "version_constraint": ">=0.1.0",
                        },
                    },
                    "schemas": {"role_schema_package_version": ">=0.1.0"},
                    "context": {
                        "bootloader_path": "AGENTS.md",
                        "spec_locations": ["docs"],
                        "quality_gates": [],
                    },
                    "policy": {
                        "issue_entry": "explicit-only",
                        "qa": {
                            "max_same_feedback_fingerprint": 2,
                            "max_total_remediation_children": 3,
                            "max_parent_qa_cycles": 2,
                        },
                    },
                    "prompts": {"overrides_dir": None},
                }
            ),
            encoding="utf-8",
        )
        cli = subprocess.run(
            [
                str(executable),
                "validate-config",
                str(config_path),
                "--repo-root",
                str(repo_root),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
        if cli.returncode or json.loads(cli.stdout).get("status") != "ok":
            raise RuntimeError(f"standalone CLI smoke check failed: {cli.stderr}")

        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
        mcp = subprocess.run(
            [str(executable), "mcp"],
            input=json.dumps(initialize) + "\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
        response = json.loads(mcp.stdout)
        if mcp.returncode or response.get("id") != 1 or "result" not in response:
            raise RuntimeError(f"standalone MCP smoke check failed: {mcp.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        target = platform_tag(platform.system(), platform.machine())
    except ValueError as error:
        parser.error(str(error))
    output_root = args.output_root.resolve()
    subprocess.run(
        pyinstaller_command(output_root=output_root, target=target), check=True
    )
    _smoke_test(output_root / target / "smda" / "smda")
    print(output_root / target / "smda")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
