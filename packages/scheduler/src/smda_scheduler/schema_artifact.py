from __future__ import annotations

import json
from functools import cache
from importlib.resources import files


@cache
def _artifact() -> dict:
    resource = files("smda_scheduler").joinpath("schemas/role_schemas.v1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _enum(name: str) -> frozenset[str]:
    return frozenset(_artifact()["enums"][name])


# Shared vocab, derived from the zod-canonical artifact (ADR-0005). Python does
# not hand-maintain these — they regenerate with `npm run schema:export`.
VERDICTS: frozenset[str] = _enum("verdict")
NEXT_ACTIONS: frozenset[str] = _enum("next_action")
EDGE_TYPES: frozenset[str] = _enum("dependency_edge_type")
RISK_LEVELS: frozenset[str] = _enum("risk_level")


def decomposer_child_fields() -> frozenset[str]:
    return frozenset(_artifact()["shapes"]["graph_decomposer_child"])


def dependency_edge_fields() -> frozenset[str]:
    return frozenset(_artifact()["shapes"]["dependency_edge"])
