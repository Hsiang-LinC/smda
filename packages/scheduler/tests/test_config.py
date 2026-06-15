import json
from pathlib import Path

import pytest

from helpers import write_minimal_config
from smda_scheduler.config import ConfigError, derive_workspace_paths, load_config


def test_loads_integration_branch_from_runtime(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    config_path.write_text(
        json.dumps(
            {
                "config_schema_version": 1,
                "runtime": {
                    "version_constraint": ">=0.1.0",
                    "state_root": ".smda/state",
                    "artifact_root": ".smda/artifacts",
                    "integration_branch": "smda/integration",
                },
                "adapters": {
                    "execution": {
                        "id": "fake-execution",
                        "version_constraint": ">=0.1.0",
                        "provider": "noSandbox",
                    },
                    "backlog": {
                        "id": "fake-backlog",
                        "version_constraint": ">=0.1.0",
                        "scope_id": "demo",
                    },
                    "context": {"id": "fake-context", "version_constraint": ">=0.1.0"},
                },
                "schemas": {"role_schema_package_version": ">=0.1.0"},
                "context": {
                    "bootloader_path": "AGENTS.md",
                    "spec_locations": ["docs"],
                    "quality_gates": ["pytest"],
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
                "labels": {},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path, repo_root=tmp_path)

    assert config.runtime.integration_branch == "smda/integration"


def test_loads_minimal_json_config(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path)

    config = load_config(config_path, repo_root=tmp_path)

    assert config.runtime.state_root == ".smda/state"
    assert config.runtime.artifact_root == ".smda/artifacts"
    assert config.adapters.backlog.scope_id == "demo"
    assert config.context.spec_locations == ["docs"]


def test_rejects_unknown_config_schema_version(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path, schema_version=999)

    with pytest.raises(ConfigError, match="config_schema_version"):
        load_config(config_path, repo_root=tmp_path)


def test_derives_workspace_paths_from_repo_and_backlog_scope(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path)
    config = load_config(config_path, repo_root=tmp_path)

    paths = derive_workspace_paths(config)

    assert len(paths.workspace_id) == 16
    assert paths.ledger_path == tmp_path / ".smda/state" / paths.workspace_id / "ledger.sqlite"
    assert paths.artifact_dir == tmp_path / ".smda/artifacts" / paths.workspace_id
