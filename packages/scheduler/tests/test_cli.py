import json
from pathlib import Path

from fakes import fake_registry
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
