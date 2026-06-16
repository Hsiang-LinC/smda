import pytest

from smda_scheduler.execution_modes import (
    ExecutionMode,
    ModeTag,
    SMDA_EXECUTION_MODE_CATALOG_MARKDOWN,
    SUPPORTED_MODE_TAGS,
    WorkflowOptions,
    WorkflowOptionsError,
    parse_execution_mode,
    parse_mode_tags,
    resolve_workflow_options,
)


def test_parse_execution_mode_accepts_trimmed_case_insensitive_value():
    assert parse_execution_mode(" SMDA-TASK ") == ExecutionMode.SMDA_TASK


def test_parse_execution_mode_rejects_unknown_mode():
    with pytest.raises(
        WorkflowOptionsError,
        match="Unsupported Execution mode: custom",
    ):
        parse_execution_mode("custom")


def test_parse_mode_tags_accepts_comma_separated_values():
    assert parse_mode_tags("full_review, high_risk") == frozenset(
        {ModeTag.FULL_REVIEW, ModeTag.HIGH_RISK}
    )


def test_parse_mode_tags_collapses_duplicates_and_empty_segments():
    assert parse_mode_tags("full_review,, full_review") == frozenset(
        {ModeTag.FULL_REVIEW}
    )


def test_parse_mode_tags_rejects_unknown_tag():
    with pytest.raises(WorkflowOptionsError, match="Unsupported Mode tags: custom"):
        parse_mode_tags("full_review, custom")


def test_parse_mode_tags_reports_unknown_tags_in_stable_order():
    with pytest.raises(
        WorkflowOptionsError,
        match="Unsupported Mode tags: aaa, zzz",
    ):
        parse_mode_tags("zzz, aaa")


def test_supported_mode_tags_exports_all_mode_tags():
    assert SUPPORTED_MODE_TAGS == frozenset(ModeTag)


def test_resolve_smda_task_defaults_to_quality_review_only():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset(),
    )

    assert options == WorkflowOptions(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset(),
        require_spec_review=False,
        require_quality_review=True,
        require_human_approval=False,
        require_integration=False,
        risk_level="normal",
    )


def test_full_review_requires_spec_and_quality_review():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset({ModeTag.FULL_REVIEW}),
    )

    assert options.require_spec_review is True
    assert options.require_quality_review is True


def test_quality_only_high_risk_is_invalid():
    with pytest.raises(
        WorkflowOptionsError,
        match="quality_only cannot be combined with high_risk",
    ):
        resolve_workflow_options(
            mode=ExecutionMode.SMDA_TASK,
            tags=frozenset({ModeTag.QUALITY_ONLY, ModeTag.HIGH_RISK}),
        )


def test_high_risk_requires_full_review():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset({ModeTag.HIGH_RISK}),
    )

    assert options.risk_level == "high"
    assert options.require_spec_review is True
    assert options.require_quality_review is True


def test_manual_mode_disables_all_automation_gates():
    options = resolve_workflow_options(
        mode=ExecutionMode.MANUAL,
        tags=frozenset(),
    )

    assert options.require_spec_review is False
    assert options.require_quality_review is False
    assert options.require_human_approval is True


def test_smda_child_tags_cannot_weaken_dependency_gate():
    options = resolve_workflow_options(
        mode=ExecutionMode.SMDA_CHILD,
        tags=frozenset({ModeTag.QUALITY_ONLY, ModeTag.LOW_RISK}),
    )

    assert options.mode == ExecutionMode.SMDA_CHILD
    assert options.require_spec_review is True
    assert options.require_quality_review is True


def test_workflow_options_context_packet_has_stable_keys_and_sorted_tags():
    options = WorkflowOptions(
        mode=ExecutionMode.SMDA_TASK,
        tags=frozenset({ModeTag.HIGH_RISK, ModeTag.FULL_REVIEW}),
        require_spec_review=True,
        require_quality_review=True,
        require_human_approval=False,
        require_integration=True,
        risk_level="high",
    )

    assert options.to_context_packet() == {
        "mode": "smda-task",
        "tags": ["full_review", "high_risk"],
        "require_spec_review": True,
        "require_quality_review": True,
        "require_human_approval": False,
        "require_integration": True,
        "risk_level": "high",
    }


def test_execution_mode_catalog_marks_smda_review_not_enabled():
    assert (
        "`Execution: smda-review` is cataloged but not enabled in this implementation "
        "slice."
        in SMDA_EXECUTION_MODE_CATALOG_MARKDOWN
    )
