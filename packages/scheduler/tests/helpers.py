from pathlib import Path


def write_minimal_config(path: Path, *, schema_version: int = 1) -> None:
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
      "id": "fake-execution",
      "version_constraint": ">=0.1.0",
      "provider": "noSandbox"
    }},
    "backlog": {{
      "id": "fake-backlog",
      "version_constraint": ">=0.1.0",
      "scope_id": "demo"
    }},
    "context": {{
      "id": "fake-context",
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
      "max_total_remediation_children": 3,
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
