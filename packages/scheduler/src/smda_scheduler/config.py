from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_CONFIG_SCHEMA_VERSION = 1


class ConfigError(ValueError):
    """Raised when an SMDA config file cannot boot the runtime."""


@dataclass(frozen=True)
class RuntimeConfig:
    version_constraint: str
    state_root: str = ".smda/state"
    artifact_root: str = ".smda/artifacts"
    integration_branch: str | None = None


@dataclass(frozen=True)
class AgentConfig:
    provider: str
    model: str
    effort: str | None = None


@dataclass(frozen=True)
class ExecutionAdapterConfig:
    id: str
    version_constraint: str
    provider: str
    agent: AgentConfig


@dataclass(frozen=True)
class BacklogAdapterConfig:
    id: str
    version_constraint: str
    scope_id: str


@dataclass(frozen=True)
class ContextAdapterConfig:
    id: str
    version_constraint: str


@dataclass(frozen=True)
class AdapterConfig:
    execution: ExecutionAdapterConfig
    backlog: BacklogAdapterConfig
    context: ContextAdapterConfig


@dataclass(frozen=True)
class SchemaConfig:
    role_schema_package_version: str


@dataclass(frozen=True)
class ContextConfig:
    bootloader_path: str
    spec_locations: list[str]
    quality_gates: list[str]
    adr_locations: list[str]
    # Optional repo-relative dir holding methodology skills (ADR-0004). When unset,
    # methodology injection is disabled and prompts are unchanged.
    skills_dir: str | None = None


@dataclass(frozen=True)
class QaPolicy:
    max_same_feedback_fingerprint: int
    max_total_remediation_children: int
    max_parent_qa_cycles: int


@dataclass(frozen=True)
class PolicyConfig:
    issue_entry: str
    qa: QaPolicy


@dataclass(frozen=True)
class PromptConfig:
    overrides_dir: str | None


@dataclass(frozen=True)
class SmdaConfig:
    config_schema_version: int
    repo_root: Path
    runtime: RuntimeConfig
    adapters: AdapterConfig
    schemas: SchemaConfig
    context: ContextConfig
    policy: PolicyConfig
    prompts: PromptConfig
    labels: dict[str, Any]


@dataclass(frozen=True)
class WorkspacePaths:
    workspace_id: str
    ledger_path: Path
    artifact_dir: Path


def load_config(path: Path, *, repo_root: Path) -> SmdaConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema_version = _required(data, "config_schema_version")
    if schema_version != SUPPORTED_CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            "Unsupported config_schema_version "
            f"{schema_version}; expected {SUPPORTED_CONFIG_SCHEMA_VERSION}"
        )

    runtime = _required_mapping(data, "runtime")
    adapters = _required_mapping(data, "adapters")
    schemas = _required_mapping(data, "schemas")
    context = _required_mapping(data, "context")
    policy = _required_mapping(data, "policy")
    prompts = _required_mapping(data, "prompts")

    return SmdaConfig(
        config_schema_version=schema_version,
        repo_root=repo_root.resolve(),
        runtime=RuntimeConfig(
            version_constraint=_required(runtime, "version_constraint"),
            state_root=runtime.get("state_root", ".smda/state"),
            artifact_root=runtime.get("artifact_root", ".smda/artifacts"),
            integration_branch=runtime.get("integration_branch"),
        ),
        adapters=AdapterConfig(
            execution=_execution_adapter(_required_mapping(adapters, "execution")),
            backlog=_backlog_adapter(_required_mapping(adapters, "backlog")),
            context=_context_adapter(_required_mapping(adapters, "context")),
        ),
        schemas=SchemaConfig(
            role_schema_package_version=_required(
                schemas, "role_schema_package_version"
            )
        ),
        context=ContextConfig(
            bootloader_path=_required(context, "bootloader_path"),
            spec_locations=list(_required(context, "spec_locations")),
            quality_gates=list(context.get("quality_gates", [])),
            adr_locations=list(context.get("adr_locations", [])),
            skills_dir=context.get("skills_dir"),
        ),
        policy=PolicyConfig(
            issue_entry=_required(policy, "issue_entry"),
            qa=_qa_policy(_required_mapping(policy, "qa")),
        ),
        prompts=PromptConfig(overrides_dir=prompts.get("overrides_dir")),
        labels=dict(data.get("labels", {})),
    )


def derive_workspace_paths(config: SmdaConfig) -> WorkspacePaths:
    workspace_id = derive_workspace_id(config)
    state_root = _resolve_under_repo(config.repo_root, config.runtime.state_root)
    artifact_root = _resolve_under_repo(config.repo_root, config.runtime.artifact_root)
    return WorkspacePaths(
        workspace_id=workspace_id,
        ledger_path=state_root / workspace_id / "ledger.sqlite",
        artifact_dir=artifact_root / workspace_id,
    )


def derive_workspace_id(config: SmdaConfig) -> str:
    seed = "|".join(
        [
            str(config.repo_root),
            config.adapters.backlog.id,
            config.adapters.backlog.scope_id,
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _execution_adapter(data: dict[str, Any]) -> ExecutionAdapterConfig:
    return ExecutionAdapterConfig(
        id=_required(data, "id"),
        version_constraint=_required(data, "version_constraint"),
        provider=_required(data, "provider"),
        agent=_agent_config(data.get("agent", {})),
    )


def _agent_config(data: Any) -> AgentConfig:
    if not isinstance(data, dict):
        raise ConfigError("Config key must be an object: adapters.execution.agent")
    provider = data.get("provider", "codex")
    model = data.get("model", "gpt-5")
    effort = data.get("effort")
    if provider not in {"codex", "claudeCode"}:
        raise ConfigError(
            "Config key adapters.execution.agent.provider must be codex or "
            "claudeCode"
        )
    if not isinstance(model, str) or not model:
        raise ConfigError("Config key adapters.execution.agent.model must be a string")
    if effort is not None:
        allowed = (
            {"low", "medium", "high", "xhigh"}
            if provider == "codex"
            else {"low", "medium", "high", "xhigh", "max"}
        )
        if effort not in allowed:
            raise ConfigError(
                "Config key adapters.execution.agent.effort is not valid for "
                f"{provider}"
            )
    return AgentConfig(
        provider=provider,
        model=model,
        effort=effort,
    )


def _backlog_adapter(data: dict[str, Any]) -> BacklogAdapterConfig:
    return BacklogAdapterConfig(
        id=_required(data, "id"),
        version_constraint=_required(data, "version_constraint"),
        scope_id=_required(data, "scope_id"),
    )


def _context_adapter(data: dict[str, Any]) -> ContextAdapterConfig:
    return ContextAdapterConfig(
        id=_required(data, "id"),
        version_constraint=_required(data, "version_constraint"),
    )


def _qa_policy(data: dict[str, Any]) -> QaPolicy:
    return QaPolicy(
        max_same_feedback_fingerprint=_required(
            data, "max_same_feedback_fingerprint"
        ),
        max_total_remediation_children=_required(
            data, "max_total_remediation_children"
        ),
        max_parent_qa_cycles=_required(data, "max_parent_qa_cycles"),
    )


def _required(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ConfigError(f"Missing required config key: {key}")
    return data[key]


def _required_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = _required(data, key)
    if not isinstance(value, dict):
        raise ConfigError(f"Config key must be an object: {key}")
    return value


def _resolve_under_repo(repo_root: Path, path: str) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    return repo_root / raw
