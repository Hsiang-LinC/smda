from pathlib import Path

import pytest

from helpers import write_minimal_config
from fakes import fake_registry
from smda_scheduler.adapters import AdapterDescriptor, CapabilityError
from smda_scheduler.adapters import AdapterResolutionError
from smda_scheduler.boot import boot_workspace
from smda_scheduler.config import ConfigError


def test_boot_refuses_implicit_fake_registry(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path)

    with pytest.raises(AdapterResolutionError, match="fake-execution"):
        boot_workspace(config_path, repo_root=tmp_path)


def test_boots_workspace_with_explicit_test_registry(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path)

    result = boot_workspace(config_path, repo_root=tmp_path, registry=fake_registry())

    assert len(result.workspace.workspace_id) == 16
    assert result.workspace.ledger_path.name == "ledger.sqlite"
    assert result.adapters["backlog"].id == "fake-backlog"
    assert result.negotiation["backlog"].fallbacks == {
        "blocking_relations": "gate_on_smda_graph_only",
        "hierarchy": "flat_issues_with_parent_label",
    }


def test_boots_workspace_with_product_adapter_registry(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )

    result = boot_workspace(config_path, repo_root=tmp_path)

    assert result.adapters["execution"].id == "sandcastle"
    assert result.adapters["backlog"].id == "linear"
    assert result.adapters["context"].id == "codex-harness"
    assert result.negotiation["backlog"].fallbacks == {}


def test_boots_workspace_with_local_ledger_product_adapter(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="local-ledger",
        context_id="codex-harness",
    )

    result = boot_workspace(config_path, repo_root=tmp_path)

    assert result.adapters["backlog"].id == "local-ledger"
    assert result.negotiation["backlog"].fallbacks == {}


def test_boot_refuses_missing_required_capability(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path)
    registry = {
        "fake-execution": AdapterDescriptor(
            id="fake-execution",
            version="0.1.0",
            capabilities=frozenset(
                {"worktree_per_attempt", "structured_output_recovery"}
            ),
        ),
        "fake-backlog": AdapterDescriptor(
            id="fake-backlog",
            version="0.1.0",
            capabilities=frozenset({"comments", "coarse_states"}),
        ),
        "fake-context": AdapterDescriptor(
            id="fake-context",
            version="0.1.0",
            capabilities=frozenset({"bootloader", "spec_locations"}),
        ),
    }

    with pytest.raises(CapabilityError, match="create_child"):
        boot_workspace(config_path, repo_root=tmp_path, registry=registry)


def test_boot_refuses_config_schema_mismatch(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(config_path, schema_version=999)

    with pytest.raises(ConfigError, match="config_schema_version"):
        boot_workspace(config_path, repo_root=tmp_path)
