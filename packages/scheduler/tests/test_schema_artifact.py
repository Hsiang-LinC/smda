from smda_scheduler.schema_artifact import (
    EDGE_TYPES,
    NEXT_ACTIONS,
    RISK_LEVELS,
    VERDICTS,
    decomposer_child_fields,
    dependency_edge_fields,
)


def test_vocab_loaded_from_artifact():
    assert "code_dependency" in EDGE_TYPES
    assert {"PASS", "DONE_WITH_CONCERNS", "FAIL"} <= VERDICTS
    assert RISK_LEVELS == frozenset({"low", "medium", "high"})
    assert "submit_for_graph_review" in NEXT_ACTIONS
    assert "accept_parent" in NEXT_ACTIONS


def test_decomposer_shape_fields_present():
    assert {"node_id", "acceptance_criteria", "dependencies"} <= decomposer_child_fields()
    assert {"from", "to", "type", "blocks_dispatch"} <= dependency_edge_fields()


def test_artifact_edge_types_match_legacy_validate_graph_set():
    # Characterization: the artifact reproduces the edge-type set validate_graph
    # used to hardcode (behaviour parity for the single-source swap).
    assert EDGE_TYPES == frozenset(
        {"code_dependency", "contract_dependency", "test_dependency", "sequencing_only"}
    )


def test_python_consumed_decomposer_fields_present_in_artifact():
    # The fields the scheduler parses from graph_decomposer output. If TS renames
    # or removes one, this fails — the real cross-language drift guard.
    python_child_fields = {
        "node_id",
        "title",
        "body",
        "in_scope",
        "out_of_scope",
        "touched_surfaces",
        "acceptance_criteria",
        "verification",
        "risk_level",
        "dependencies",
    }
    python_edge_fields = {
        "from",
        "to",
        "type",
        "blocks_dispatch",
        "reason",
        "required_artifacts",
    }
    assert python_child_fields <= decomposer_child_fields()
    assert python_edge_fields <= dependency_edge_fields()
