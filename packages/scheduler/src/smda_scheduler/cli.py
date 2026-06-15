from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from smda_scheduler.adapters import (
    AdapterDescriptor,
    AdapterResolutionError,
    CapabilityError,
)
from smda_scheduler.boot import boot_workspace
from smda_scheduler.config import ConfigError, derive_workspace_paths, load_config
from smda_scheduler.context_packets import (
    CodexHarnessContextAdapter,
    ContextDiscoveryError,
)
from smda_scheduler.daemon import Tick, run_daemon
from smda_scheduler.linear_backlog import LinearConfigError, build_linear_backlog_adapter
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.runtime_factory import build_configured_workspace_tick
from smda_scheduler.sandcastle_execution import SandcastleExecutionAdapter
from smda_scheduler.scheduling import reconcile_expired_claims


DaemonTickBuilder = Callable[
    ...,
    Tick,
]


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
    daemon_tick_builder: DaemonTickBuilder | None = None,
) -> CliResult:
    parser = _build_parser()
    args = parser.parse_args(list(argv))

    if args.command == "validate-config":
        return _validate_config(
            args.config_path,
            repo_root=args.repo_root,
            registry=registry,
        )
    if args.command == "validate-context":
        return _validate_context(args.config_path, repo_root=args.repo_root)
    if args.command == "status":
        return _status(args.config_path, repo_root=args.repo_root)
    if args.command == "validate-state":
        return _validate_state(args.config_path, repo_root=args.repo_root)
    if args.command == "pause":
        return _set_pause(
            args.config_path,
            repo_root=args.repo_root,
            parent_id=args.parent,
            paused=True,
        )
    if args.command == "resume":
        return _set_pause(
            args.config_path,
            repo_root=args.repo_root,
            parent_id=args.parent,
            paused=False,
        )
    if args.command == "reconcile-claims":
        return _reconcile_claims(args.config_path, repo_root=args.repo_root)
    if args.command == "daemon":
        return _run_daemon_command(
            config_path=args.config_path,
            repo_root=args.repo_root,
            scan_state=args.state,
            scan_label=args.label,
            owner=args.owner,
            max_ticks=args.max_ticks,
            interval_seconds=args.interval_seconds,
            daemon_tick=daemon_tick,
            daemon_tick_builder=daemon_tick_builder,
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
    config_path: Path | None,
    repo_root: Path | None,
    scan_state: str,
    scan_label: str,
    owner: str,
    max_ticks: int,
    interval_seconds: float,
    daemon_tick: Tick | None,
    daemon_tick_builder: DaemonTickBuilder | None,
) -> CliResult:
    if daemon_tick is None:
        if config_path is not None and repo_root is not None:
            builder = daemon_tick_builder or _build_live_daemon_tick
            try:
                daemon_tick = builder(
                    config_path=config_path,
                    repo_root=repo_root,
                    scan_state=scan_state,
                    scan_label=scan_label,
                    owner=owner,
                )
            except (ConfigError, LinearConfigError, ContextDiscoveryError) as error:
                return CliResult(
                    exit_code=1,
                    stdout="",
                    stderr=json.dumps(
                        {
                            "status": "daemon_not_configured",
                            "error_message": str(error),
                        }
                    ),
                )
        else:
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


def _build_live_daemon_tick(
    *,
    config_path: Path,
    repo_root: Path,
    scan_state: str,
    scan_label: str,
    owner: str,
) -> Tick:
    config = load_config(config_path, repo_root=repo_root)
    if config.adapters.backlog.id != "linear":
        raise ConfigError(f"Unsupported backlog adapter: {config.adapters.backlog.id}")
    if config.adapters.execution.id != "sandcastle":
        raise ConfigError(
            f"Unsupported execution adapter: {config.adapters.execution.id}"
        )

    product_root = Path(__file__).resolve().parents[4]
    return build_configured_workspace_tick(
        config_path=config_path,
        repo_root=repo_root,
        backlog=build_linear_backlog_adapter(env=dict(os.environ)),
        execution=SandcastleExecutionAdapter(process_cwd=product_root),
        scan_state=scan_state,
        scan_label=scan_label,
        owner=owner,
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


def _validate_context(config_path: Path, *, repo_root: Path) -> CliResult:
    try:
        config = load_config(config_path, repo_root=repo_root)
        packet = CodexHarnessContextAdapter().build_repo_packet(config)
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
    except ContextDiscoveryError as error:
        return CliResult(
            exit_code=1,
            stdout="",
            stderr=json.dumps(
                {
                    "status": "context_invalid",
                    "error_message": str(error),
                }
            ),
        )

    return CliResult(
        exit_code=0,
        stdout=json.dumps(
            {
                "status": "ok",
                "bootloader_path": str(packet.bootloader_path),
                "spec_locations": [str(path) for path in packet.spec_locations],
                "adr_locations": [str(path) for path in packet.adr_locations],
                "quality_gates": list(packet.quality_gates),
            }
        ),
        stderr="",
    )


def _status(config_path: Path, *, repo_root: Path) -> CliResult:
    try:
        workspace, ledger = _workspace_ledger(config_path, repo_root=repo_root)
        scheduler_state = ledger.load_scheduler_state()
        payload = {
            "status": "ok",
            "workspace_id": workspace.workspace_id,
            "ledger_path": str(workspace.ledger_path),
            "parent_runs": ledger.load_parent_runs(),
            "child_runs": [
                {
                    "child_id": child_id,
                    "phase": child.phase.value,
                    "attempts": child.attempts,
                    "claim_owner": child.claim.owner if child.claim else None,
                    "next_not_before": child.next_not_before,
                }
                for child_id, child in sorted(scheduler_state.children.items())
            ],
            "paused_parent_ids": ledger.load_paused_parent_ids(),
        }
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

    return CliResult(exit_code=0, stdout=json.dumps(payload), stderr="")


def _validate_state(config_path: Path, *, repo_root: Path) -> CliResult:
    status = _status(config_path, repo_root=repo_root)
    if status.exit_code != 0:
        return status
    payload = json.loads(status.stdout)
    return CliResult(
        exit_code=0,
        stdout=json.dumps(
            {
                "status": "ok",
                "workspace_id": payload["workspace_id"],
                "ledger_path": payload["ledger_path"],
            }
        ),
        stderr="",
    )


def _set_pause(
    config_path: Path,
    *,
    repo_root: Path,
    parent_id: str,
    paused: bool,
) -> CliResult:
    try:
        _, ledger = _workspace_ledger(config_path, repo_root=repo_root)
        ledger.set_parent_pause(parent_id, paused=paused)
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
    return CliResult(
        exit_code=0,
        stdout=json.dumps(
            {
                "status": "ok",
                "parent_id": parent_id,
                "paused": paused,
            }
        ),
        stderr="",
    )


def _reconcile_claims(config_path: Path, *, repo_root: Path) -> CliResult:
    try:
        _, ledger = _workspace_ledger(config_path, repo_root=repo_root)
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

    now = time.time()
    state = ledger.load_scheduler_state()
    reset_child_ids = sorted(
        child_id
        for child_id, child in state.children.items()
        if child.claim is not None and child.claim.lease_expires_at <= now
    )
    if reset_child_ids:
        ledger.save_scheduler_state(reconcile_expired_claims(state, now=now))

    return CliResult(
        exit_code=0,
        stdout=json.dumps({"status": "ok", "reset_child_ids": reset_child_ids}),
        stderr="",
    )


def _workspace_ledger(config_path: Path, *, repo_root: Path):
    config = load_config(config_path, repo_root=repo_root)
    workspace = derive_workspace_paths(config)
    return workspace, PhaseLedger(workspace.ledger_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smda-scheduler")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config")
    validate.add_argument("config_path", type=Path)
    validate.add_argument("--repo-root", type=Path, required=True)
    validate_context = subparsers.add_parser("validate-context")
    validate_context.add_argument("config_path", type=Path)
    validate_context.add_argument("--repo-root", type=Path, required=True)
    status = subparsers.add_parser("status")
    status.add_argument("config_path", type=Path)
    status.add_argument("--repo-root", type=Path, required=True)
    validate_state = subparsers.add_parser("validate-state")
    validate_state.add_argument("config_path", type=Path)
    validate_state.add_argument("--repo-root", type=Path, required=True)
    pause = subparsers.add_parser("pause")
    pause.add_argument("config_path", type=Path)
    pause.add_argument("--repo-root", type=Path, required=True)
    pause.add_argument("--parent", required=True)
    resume = subparsers.add_parser("resume")
    resume.add_argument("config_path", type=Path)
    resume.add_argument("--repo-root", type=Path, required=True)
    resume.add_argument("--parent", required=True)
    reconcile_claims = subparsers.add_parser("reconcile-claims")
    reconcile_claims.add_argument("config_path", type=Path)
    reconcile_claims.add_argument("--repo-root", type=Path, required=True)
    daemon = subparsers.add_parser("daemon")
    daemon.add_argument("config_path", type=Path, nargs="?")
    daemon.add_argument("--repo-root", type=Path)
    daemon.add_argument("--state", default="Todo")
    daemon.add_argument("--label", default="agent")
    daemon.add_argument("--owner", default="smda-daemon")
    daemon.add_argument("--max-ticks", type=int, default=1)
    daemon.add_argument("--interval-seconds", type=float, default=30.0)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
