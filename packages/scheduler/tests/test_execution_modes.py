import smda_scheduler.execution_modes as execution_modes
import pytest

from smda_scheduler.execution_modes import (
    ExecutionMode,
    ModeTag,
    SMDA_EXECUTION_MODE_CATALOG_MARKDOWN,
    SUPPORTED_MODE_TAGS,
    WorkflowOptionsError,
    parse_execution_mode,
    parse_mode_tags,
)


def test_parse_execution_mode_accepts_trimmed_case_insensitive_value():
    assert parse_execution_mode(" SMDA-TASK ") == ExecutionMode.SMDA_TASK


def test_parse_execution_mode_accepts_smda_roadmap():
    assert parse_execution_mode(" smda-roadmap ") == ExecutionMode.SMDA_ROADMAP


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


def test_workflow_options_bundle_is_removed():
    assert not hasattr(execution_modes, "WorkflowOptions")
    assert not hasattr(execution_modes, "resolve_workflow_options")


def test_execution_mode_catalog_marks_smda_review_not_enabled():
    assert (
        "`Execution: smda-review` is cataloged but not enabled in this implementation "
        "slice."
        in SMDA_EXECUTION_MODE_CATALOG_MARKDOWN
    )


def test_execution_mode_catalog_mentions_smda_roadmap():
    assert "`Execution: smda-roadmap`" in SMDA_EXECUTION_MODE_CATALOG_MARKDOWN
