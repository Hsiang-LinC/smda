import json
import fcntl
from pathlib import Path

from fakes import fake_registry
from smda_scheduler.daemon import TickResult
from smda_scheduler.cli import run_cli
from smda_scheduler.config import derive_workspace_paths, load_config
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.scheduling import Claim, ChildRunState, SchedulerState
from smda_scheduler.workflow import ChildPhase
from helpers import write_minimal_config


def test_validate_config_cli_returns_workspace_summary_with_injected_registry(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path)

    result = run_cli(
        ["validate-config", str(config_path), "--repo-root", str(tmp_path)],
        registry=fake_registry(),
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert len(payload["workspace_id"]) == 16
    assert payload["ledger_path"].endswith("ledger.sqlite")
    assert result.stderr == ""


def test_validate_config_cli_reports_missing_adapter(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path)

    result = run_cli(
        ["validate-config", str(config_path), "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["status"] == "adapter_unavailable"
    assert "fake-execution" in payload["error_message"]


def test_validate_config_cli_uses_product_adapter_registry(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )

    result = run_cli(
        ["validate-config", str(config_path), "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "ok"
    assert result.stderr == ""


def test_validate_config_cli_reports_boot_errors(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path, schema_version=999)

    result = run_cli(
        ["validate-config", str(config_path), "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["status"] == "config_invalid"
    assert "config_schema_version" in payload["error_message"]


def test_validate_context_cli_returns_context_summary(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    (tmp_path / "AGENTS.md").write_text("# Agent boot\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()

    result = run_cli(
        ["validate-context", str(config_path), "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "status": "ok",
        "bootloader_path": str(tmp_path / "AGENTS.md"),
        "spec_locations": [str(tmp_path / "docs")],
        "adr_locations": [],
        "quality_gates": ["pytest"],
    }


def test_validate_context_cli_reports_missing_context(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )

    result = run_cli(
        ["validate-context", str(config_path), "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["status"] == "context_invalid"
    assert "bootloader" in payload["error_message"]


def test_status_cli_returns_ledger_summary(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    config = load_config(config_path, repo_root=tmp_path)
    ledger = PhaseLedger(derive_workspace_paths(config).ledger_path)
    ledger.record_tracker_effect(
        effect_id="effect-pending",
        idempotency_key="effect-pending",
        effect_type="comment",
        target_id="DANNY-1",
        payload={"body": "pending write"},
    )
    failed_effect = ledger.record_tracker_effect(
        effect_id="effect-failed",
        idempotency_key="effect-failed",
        effect_type="set_state",
        target_id="DANNY-2",
        payload={"state": "Agent Review"},
    )
    ledger.mark_tracker_effect_failed(failed_effect, "Linear timeout")
    sent_effect = ledger.record_tracker_effect(
        effect_id="effect-sent",
        idempotency_key="effect-sent",
        effect_type="comment",
        target_id="DANNY-3",
        payload={"body": "sent write"},
    )
    ledger.mark_tracker_effect_sent(sent_effect)

    result = run_cli(["status", str(config_path), "--repo-root", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["ledger_path"].endswith("ledger.sqlite")
    assert payload["parent_runs"] == []
    assert payload["child_runs"] == []
    assert payload["paused_parent_ids"] == []
    assert payload["tracker_effects"] == {
        "total": 3,
        "pending": 2,
        "sent": 1,
        "failed": 0,
        "pending_with_errors": 1,
        "pending_by_type": {"comment": 1, "set_state": 1},
        "recent_errors": [
            {
                "effect_id": "effect-failed",
                "effect_type": "set_state",
                "target_id": "DANNY-2",
                "last_error": "Linear timeout",
            }
        ],
    }


def test_validate_state_cli_returns_ok_for_readable_ledger(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )

    result = run_cli(["validate-state", str(config_path), "--repo-root", str(tmp_path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "ok"
    assert result.stderr == ""


def test_pause_and_resume_cli_updates_parent_pause_record(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )

    paused = run_cli(
        [
            "pause",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--parent",
            "DANNY-66",
        ]
    )
    status = run_cli(["status", str(config_path), "--repo-root", str(tmp_path)])
    resumed = run_cli(
        [
            "resume",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--parent",
            "DANNY-66",
        ]
    )
    final_status = run_cli(["status", str(config_path), "--repo-root", str(tmp_path)])

    assert paused.exit_code == 0
    assert json.loads(paused.stdout) == {
        "status": "ok",
        "parent_id": "DANNY-66",
        "paused": True,
    }
    assert json.loads(status.stdout)["paused_parent_ids"] == ["DANNY-66"]
    assert resumed.exit_code == 0
    assert json.loads(resumed.stdout) == {
        "status": "ok",
        "parent_id": "DANNY-66",
        "paused": False,
    }
    assert json.loads(final_status.stdout)["paused_parent_ids"] == []


def test_reconcile_claims_cli_resets_expired_claims(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    ledger = PhaseLedger(workspace.ledger_path)
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "DANNY-70": ChildRunState(
                    phase=ChildPhase.IMPLEMENTING,
                    attempts=1,
                    claim=Claim(owner="dead-worker", lease_expires_at=1.0),
                ),
                "DANNY-71": ChildRunState(
                    phase=ChildPhase.IMPLEMENTING,
                    attempts=1,
                    claim=Claim(owner="live-worker", lease_expires_at=10_000_000_000.0),
                ),
            }
        )
    )

    result = run_cli(
        ["reconcile-claims", str(config_path), "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["reset_child_ids"] == ["DANNY-70"]

    reloaded = PhaseLedger(workspace.ledger_path).load_scheduler_state()
    assert reloaded.children["DANNY-70"].claim is None
    assert reloaded.children["DANNY-71"].claim is not None


def test_daemon_cli_runs_injected_tick_loop():
    calls = []

    def tick() -> TickResult:
        calls.append("tick")
        return TickResult(status="idle")

    result = run_cli(
        ["daemon", "--max-ticks", "2", "--interval-seconds", "0"],
        daemon_tick=tick,
    )

    assert result.exit_code == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "status": "stopped",
        "ticks": 2,
        "last_tick": {
            "status": "idle",
            "detail": None,
            "dispatched": 0,
            "blocked": 0,
            "failed": 0,
            "skipped": 0,
        },
        "error_message": None,
    }
    assert calls == ["tick", "tick"]


def test_daemon_cli_builds_tick_from_config_when_not_injected(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    built = []

    def build_tick(
        *,
        config_path: Path,
        repo_root: Path,
        scan_states: list[str],
        scan_label: str,
        owner: str,
        max_parallel: int,
    ):
        built.append(
            {
                "config_path": config_path,
                "repo_root": repo_root,
                "scan_states": scan_states,
                "scan_label": scan_label,
                "owner": owner,
                "max_parallel": max_parallel,
            }
        )
        return lambda: TickResult(status="idle", detail="built")

    result = run_cli(
        [
            "daemon",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--state",
            "Todo",
            "--label",
            "agent",
            "--owner",
            "daemon-1",
            "--max-ticks",
            "1",
        ],
        daemon_tick_builder=build_tick,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["last_tick"] == {
        "status": "idle",
        "detail": "built",
        "dispatched": 0,
        "blocked": 0,
        "failed": 0,
        "skipped": 0,
    }
    assert built == [
        {
            "config_path": config_path,
            "repo_root": tmp_path,
            "scan_states": ["Todo"],
            "scan_label": "agent",
            "owner": "daemon-1",
            "max_parallel": 3,
        }
    ]


def test_daemon_cli_collects_repeated_state_and_max_parallel(tmp_path: Path):
    captured = {}

    def fake_builder(
        *,
        config_path,
        repo_root,
        scan_states,
        scan_label,
        owner,
        max_parallel,
    ):
        captured["scan_states"] = scan_states
        captured["max_parallel"] = max_parallel
        return lambda: TickResult(status="idle")

    cfg = tmp_path / "smda.config.json"
    cfg.write_text("{}")

    result = run_cli(
        [
            "daemon",
            str(cfg),
            "--repo-root",
            str(tmp_path),
            "--state",
            "In Progress",
            "--state",
            "Todo",
            "--max-parallel",
            "5",
            "--max-ticks",
            "1",
        ],
        daemon_tick_builder=fake_builder,
    )

    assert captured["scan_states"] == ["In Progress", "Todo"]
    assert captured["max_parallel"] == 5
    assert result.exit_code == 0


def test_daemon_cli_refuses_when_workspace_lock_is_held(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    lock_path = workspace.ledger_path.parent / "daemon.lock"
    lock_path.parent.mkdir(parents=True)

    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_cli(
            [
                "daemon",
                str(config_path),
                "--repo-root",
                str(tmp_path),
                "--max-ticks",
                "1",
            ]
        )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "status": "daemon_already_running",
        "lock_path": str(lock_path),
    }


def test_daemon_cli_reports_unwired_tick_loop():
    result = run_cli(["daemon", "--max-ticks", "1"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "status": "daemon_not_configured",
        "error_message": "No daemon tick function is wired",
    }
