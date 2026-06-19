from pathlib import Path


def write_minimal_config(
    path: Path,
    *,
    schema_version: int = 1,
    execution_id: str = "fake-execution",
    backlog_id: str = "fake-backlog",
    context_id: str = "fake-context",
    max_total_remediation_children: int = 3,
    agent_provider: str = "codex",
    agent_model: str = "gpt-5",
    agent_effort: str | None = None,
) -> None:
    effort_line = (
        ""
        if agent_effort is None
        else f',\n        "effort": "{agent_effort}"'
    )
    path.write_text(
        f"""
{{
  "config_schema_version": {schema_version},
  "runtime": {{
    "version_constraint": ">=0.1.0",
    "state_root": ".smda/state",
    "artifact_root": ".smda/artifacts"
  }},
  "adapters": {{
    "execution": {{
      "id": "{execution_id}",
      "version_constraint": ">=0.1.0",
      "provider": "noSandbox",
      "agent": {{
        "provider": "{agent_provider}",
        "model": "{agent_model}"{effort_line}
      }}
    }},
    "backlog": {{
      "id": "{backlog_id}",
      "version_constraint": ">=0.1.0",
      "scope_id": "demo"
    }},
    "context": {{
      "id": "{context_id}",
      "version_constraint": ">=0.1.0"
    }}
  }},
  "schemas": {{
    "role_schema_package_version": ">=0.1.0"
  }},
  "context": {{
    "bootloader_path": "AGENTS.md",
    "spec_locations": ["docs"],
    "quality_gates": ["pytest"]
  }},
  "policy": {{
    "issue_entry": "explicit-only",
    "qa": {{
      "max_same_feedback_fingerprint": 2,
      "max_total_remediation_children": {max_total_remediation_children},
      "max_parent_qa_cycles": 2
    }}
  }},
  "prompts": {{
    "overrides_dir": null
  }},
  "labels": {{}}
}}
""",
        encoding="utf-8",
    )
