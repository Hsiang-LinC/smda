import json
from pathlib import Path

from fakes import fake_registry
from smda_scheduler.daemon import TickResult
from smda_scheduler.cli import run_cli
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
        "last_tick": {"status": "idle", "detail": None},
        "error_message": None,
    }
    assert calls == ["tick", "tick"]


def test_daemon_cli_reports_unwired_tick_loop():
    result = run_cli(["daemon", "--max-ticks", "1"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "status": "daemon_not_configured",
        "error_message": "No daemon tick function is wired",
    }
