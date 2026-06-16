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
