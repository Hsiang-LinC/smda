import pytest

from smda_scheduler.adapters import (
    AdapterDescriptor,
    CapabilityError,
    WorkflowRequirements,
    negotiate_capabilities,
)


def test_missing_required_capability_refuses_onboard():
    adapter = AdapterDescriptor(
        id="fake-backlog",
        version="0.1.0",
        capabilities=frozenset({"comments", "coarse_states"}),
    )
    requirements = WorkflowRequirements(
        required=frozenset({"create_child", "comments"}),
        optional_fallbacks={},
    )

    with pytest.raises(CapabilityError, match="create_child"):
        negotiate_capabilities(adapter, requirements)


def test_missing_optional_capability_records_fallback():
    adapter = AdapterDescriptor(
        id="fake-backlog",
        version="0.1.0",
        capabilities=frozenset({"create_child", "comments", "coarse_states"}),
    )
    requirements = WorkflowRequirements(
        required=frozenset({"create_child", "comments"}),
        optional_fallbacks={
            "blocking_relations": "gate_on_smda_graph_only",
            "hierarchy": "flat_issues_with_parent_label",
        },
    )

    result = negotiate_capabilities(adapter, requirements)

    assert result.enabled_capabilities == frozenset({"create_child", "comments"})
    assert result.fallbacks == {
        "blocking_relations": "gate_on_smda_graph_only",
        "hierarchy": "flat_issues_with_parent_label",
    }


def test_present_optional_capability_is_enabled_without_fallback():
    adapter = AdapterDescriptor(
        id="fake-backlog",
        version="0.1.0",
        capabilities=frozenset({"create_child", "comments", "blocking_relations"}),
    )
    requirements = WorkflowRequirements(
        required=frozenset({"create_child", "comments"}),
        optional_fallbacks={"blocking_relations": "gate_on_smda_graph_only"},
    )

    result = negotiate_capabilities(adapter, requirements)

    assert result.enabled_capabilities == frozenset(
        {"create_child", "comments", "blocking_relations"}
    )
    assert result.fallbacks == {}
