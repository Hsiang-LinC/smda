from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from smda_scheduler.adapters import (
    AdapterDescriptor,
    AdapterResolutionError,
    CapabilityError,
)
from smda_scheduler.boot import boot_workspace
from smda_scheduler.config import ConfigError
from smda_scheduler.daemon import Tick, run_daemon


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str


def run_cli(
    argv: Sequence[str],
    *,
    registry: dict[str, AdapterDescriptor] | None = None,
    daemon_tick: Tick | None = None,
) -> CliResult:
    parser = _build_parser()
    args = parser.parse_args(list(argv))

    if args.command == "validate-config":
        return _validate_config(
            args.config_path,
            repo_root=args.repo_root,
            registry=registry,
        )
    if args.command == "daemon":
        return _run_daemon_command(
            max_ticks=args.max_ticks,
            interval_seconds=args.interval_seconds,
            daemon_tick=daemon_tick,
        )

    return CliResult(
        exit_code=1,
        stdout="",
        stderr=json.dumps(
            {"status": "agent_protocol_failed", "error_message": "Unknown command"}
        ),
    )


def _run_daemon_command(
    *,
    max_ticks: int,
    interval_seconds: float,
    daemon_tick: Tick | None,
) -> CliResult:
    if daemon_tick is None:
        return CliResult(
            exit_code=1,
            stdout="",
            stderr=json.dumps(
                {
                    "status": "daemon_not_configured",
                    "error_message": "No daemon tick function is wired",
                }
            ),
        )

    result = run_daemon(
        daemon_tick,
        max_ticks=max_ticks,
        interval_seconds=interval_seconds,
    )
    return CliResult(
        exit_code=0 if result.status == "stopped" else 1,
        stdout=json.dumps(asdict(result)),
        stderr="",
    )


def main(argv: Sequence[str] | None = None) -> int:
    result = run_cli(argv if argv is not None else sys.argv[1:])
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.exit_code


def _validate_config(
    config_path: Path,
    *,
    repo_root: Path,
    registry: dict[str, AdapterDescriptor] | None,
) -> CliResult:
    try:
        boot = boot_workspace(config_path, repo_root=repo_root, registry=registry)
    except ConfigError as error:
        return CliResult(
            exit_code=1,
            stdout="",
            stderr=json.dumps(
                {
                    "status": "config_invalid",
                    "error_message": str(error),
                }
            ),
        )
    except (AdapterResolutionError, CapabilityError) as error:
        return CliResult(
            exit_code=1,
            stdout="",
            stderr=json.dumps(
                {
                    "status": "adapter_unavailable",
                    "error_message": str(error),
                }
            ),
        )

    return CliResult(
        exit_code=0,
        stdout=json.dumps(
            {
                "status": "ok",
                "workspace_id": boot.workspace.workspace_id,
                "ledger_path": str(boot.workspace.ledger_path),
                "artifact_dir": str(boot.workspace.artifact_dir),
            }
        ),
        stderr="",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smda-scheduler")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config")
    validate.add_argument("config_path", type=Path)
    validate.add_argument("--repo-root", type=Path, required=True)
    daemon = subparsers.add_parser("daemon")
    daemon.add_argument("--max-ticks", type=int, default=1)
    daemon.add_argument("--interval-seconds", type=float, default=30.0)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
