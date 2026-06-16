from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkflowOptionsError(ValueError):
    """Raised when execution mode or mode tag options are invalid."""


class ExecutionMode(StrEnum):
    SMDA = "smda"
    SMDA_CHILD = "smda-child"
    SMDA_ROADMAP = "smda-roadmap"
    SMDA_TASK = "smda-task"
    SMDA_REVIEW = "smda-review"
    MANUAL = "manual"


class ModeTag(StrEnum):
    FULL_REVIEW = "full_review"
    QUALITY_ONLY = "quality_only"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    REQUIRES_INTEGRATION = "requires_integration"
    HIGH_RISK = "high_risk"
    LOW_RISK = "low_risk"


SUPPORTED_MODE_TAGS = frozenset(ModeTag)


@dataclass(frozen=True)
class WorkflowOptions:
    mode: ExecutionMode
    tags: frozenset[ModeTag]
    require_spec_review: bool
    require_quality_review: bool
    require_human_approval: bool
    require_integration: bool
    risk_level: str

    def to_context_packet(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "tags": sorted(tag.value for tag in self.tags),
            "require_spec_review": self.require_spec_review,
            "require_quality_review": self.require_quality_review,
            "require_human_approval": self.require_human_approval,
            "require_integration": self.require_integration,
            "risk_level": self.risk_level,
        }


SMDA_EXECUTION_MODE_CATALOG_MARKDOWN = """## SMDA Execution Modes

- `Execution: smda` runs the full parent-driven workflow.
- `Execution: smda-child` runs a scheduler-created child workflow.
- `Execution: smda-roadmap` decomposes an approved roadmap spec into member parents.
- `Execution: smda-task` runs a single-task implementation workflow.
- `Execution: smda-review` is cataloged but not enabled in this implementation slice.
- `Execution: manual` prevents automatic claim.

Supported `Mode tags:` values:

- `full_review`
- `quality_only`
- `human_approval_required`
- `requires_integration`
- `high_risk`
- `low_risk`
"""


def parse_execution_mode(value: str) -> ExecutionMode:
    normalized = value.strip().lower()
    try:
        return ExecutionMode(normalized)
    except ValueError as error:
        raise WorkflowOptionsError(f"Unsupported Execution mode: {value}") from error


def parse_mode_tags(value: str | None) -> frozenset[ModeTag]:
    if value is None or not value.strip():
        return frozenset()

    parsed: set[ModeTag] = set()
    unsupported: set[str] = set()
    for raw_tag in value.split(","):
        normalized = raw_tag.strip().lower()
        if not normalized:
            continue
        try:
            parsed.add(ModeTag(normalized))
        except ValueError:
            unsupported.add(normalized)

    if unsupported:
        raise WorkflowOptionsError(
            "Unsupported Mode tags: " + ", ".join(sorted(unsupported))
        )
    return frozenset(parsed)


def resolve_workflow_options(
    *,
    mode: ExecutionMode,
    tags: frozenset[ModeTag],
) -> WorkflowOptions:
    _validate_tag_combination(tags)
    risk_level = _risk_level(tags)
    require_human_approval = ModeTag.HUMAN_APPROVAL_REQUIRED in tags
    require_integration = ModeTag.REQUIRES_INTEGRATION in tags

    if mode == ExecutionMode.MANUAL:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=False,
            require_quality_review=False,
            require_human_approval=True,
            require_integration=False,
            risk_level=risk_level,
        )

    if mode in {ExecutionMode.SMDA, ExecutionMode.SMDA_CHILD}:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=True,
            require_quality_review=True,
            require_human_approval=require_human_approval,
            require_integration=require_integration,
            risk_level=risk_level,
        )

    if mode == ExecutionMode.SMDA_ROADMAP:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=True,
            require_quality_review=False,
            require_human_approval=require_human_approval,
            require_integration=False,
            risk_level=risk_level,
        )

    if mode == ExecutionMode.SMDA_TASK:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=(
                ModeTag.FULL_REVIEW in tags or ModeTag.HIGH_RISK in tags
            ),
            require_quality_review=True,
            require_human_approval=require_human_approval,
            require_integration=require_integration,
            risk_level=risk_level,
        )

    if mode == ExecutionMode.SMDA_REVIEW:
        return WorkflowOptions(
            mode=mode,
            tags=tags,
            require_spec_review=ModeTag.FULL_REVIEW in tags,
            require_quality_review=True,
            require_human_approval=require_human_approval,
            require_integration=False,
            risk_level=risk_level,
        )

    raise WorkflowOptionsError(f"Unsupported Execution mode: {mode}")


def _validate_tag_combination(tags: frozenset[ModeTag]) -> None:
    if ModeTag.FULL_REVIEW in tags and ModeTag.QUALITY_ONLY in tags:
        raise WorkflowOptionsError("full_review cannot be combined with quality_only")
    if ModeTag.QUALITY_ONLY in tags and ModeTag.HIGH_RISK in tags:
        raise WorkflowOptionsError("quality_only cannot be combined with high_risk")


def _risk_level(tags: frozenset[ModeTag]) -> str:
    if ModeTag.HIGH_RISK in tags:
        return "high"
    if ModeTag.LOW_RISK in tags:
        return "low"
    return "normal"
