# Phase 0 — Schema Single Source Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time.

> **Agent handoff (read first — this is the hand-rolled RepoContextPacket):**
> - **Branch:** work on `target-c` (carries the engine work + decision docs). Do
>   NOT branch from `master`/`main`.
> - **Read first:** [CONTEXT.md](../../CONTEXT.md),
>   [ADR-0005](../../adr/0005-zod-canonical-schema-single-source.md), and
>   [target-C spec](../specs/2026-06-16-target-c-modular-parallel-engine.md) §4.
> - **Line numbers are indicative** — they drift as sibling phases land. Grep for
>   the named symbols to locate edits; never trust a bare line number.
> - **Prereqs:** none — Phase 0 is independent of Phase 1.
> - **Discipline:** TDD red→green per task. Parity = do NOT change existing test
>   assertions. `uv run pytest packages/scheduler/tests/`, `npm run test:ts`, and
>   `npx tsc --noEmit` all green before "done".

**Goal:** Make the TypeScript Zod schemas the single source of truth and have
Python consume a generated, drift-checked JSON Schema artifact for the shared
surface — the verdict / next-action / dependency-edge-type / risk-level vocab and
the graph-decomposer output shape. A parity test makes Py/TS schema drift
structurally impossible. Implements
[ADR-0005](../../adr/0005-zod-canonical-schema-single-source.md).

**Why now:** independent of the engine work, low-risk, and it stops the new roles
added in Phase 2/3 (roadmap_decomposer, methodology, etc.) from re-introducing
hand-synced drift.

**Key enabler:** the repo is on **zod v4** (`zod@^4.1.13`), which has native
`z.toJSONSchema(schema)` — **no new dependency**. The export is a small tsx
script.

**Architecture:** TS export script reads the Zod schemas → emits one checked-in
JSON artifact (`enums` + `schemas` keyed by schema_id) → a TS parity test
regenerates in-memory and deep-equals the committed file (drift fails CI) →
Python loads the artifact (package data via `importlib.resources`) and derives the
shared vocab + a decomposer-shape drift guard. Python keeps its orchestration-only
metadata (persona, task template, role→phase, methodology) hand-owned, as ADR-0005
specifies — only the output shapes/vocab are generated.

**Tech Stack:** TypeScript (zod v4, tsx, node:test), Python scheduler (pytest,
importlib.resources).

## Relationship To Other Plans

- Phase 0 of
  [target-c-implementation-path](2026-06-16-target-c-implementation-path.md).
- Spec: [target-C](../specs/2026-06-16-target-c-modular-parallel-engine.md) §4;
  [ADR-0005](../../adr/0005-zod-canonical-schema-single-source.md).
- Independent of Phase 1; can land in any order relative to 1a-1c.

## Scope

In scope:
- A TS export script + `npm run schema:export` producing
  `packages/scheduler/src/smda_scheduler/schemas/role_schemas.v1.json` (shipped as
  Python package data).
- The committed artifact.
- A TS parity test: regenerate == committed.
- A Python loader (`schema_artifact.py`) exposing `VERDICTS`, `NEXT_ACTIONS`,
  `EDGE_TYPES`, `RISK_LEVELS`, and the decomposer field sets.
- Single-source `workflow.validate_graph`'s edge-type set from the artifact.
- A Python drift guard: the keys Python parses from decomposer output are a subset
  of the artifact's decomposer shape.

Out of scope:
- Migrating every verdict/next-action string literal in the transition tables to
  artifact constants — they are already parity-tested (Phase 1) and the churn buys
  little safety. Only the *validation vocab* (edge types, risk) and the decomposer
  *shape* are single-sourced here.
- The `roleContractManifest` schema_id/output_tag mapping (role→schema). It stays
  as-is; revisit only if it drifts.

## File Structure

- Create `packages/sandcastle-runner/src/exportSchemas.ts` (the export logic +
  the canonical artifact object).
- Create `packages/scheduler/src/smda_scheduler/schemas/role_schemas.v1.json`
  (generated, checked in).
- Create `packages/scheduler/src/smda_scheduler/schema_artifact.py` (loader).
- Modify `package.json` (add `schema:export` script).
- Modify `packages/scheduler/src/smda_scheduler/workflow.py` (edge-type set from
  artifact).
- Modify `pyproject.toml` if needed (ensure `schemas/*.json` ships as package
  data).
- Tests:
  - `packages/sandcastle-runner/tests/schemaParity.test.ts`
  - `packages/scheduler/tests/test_schema_artifact.py`
  - `packages/scheduler/tests/test_workflow.py` (edge-type parity)

---

## Task 1: TS export — canonical artifact object + script

**Files:** `exportSchemas.ts`; `package.json`.

- [ ] **Step 1: Build the canonical artifact object** in `exportSchemas.ts`,
  importing the Zod schemas from `roleContracts.ts`:

```ts
import { z } from "zod";
import {
  verdictSchema, nextActionSchema, dependencyEdgeSchema, graphChildSchema,
  roleResultSchema, graphDecomposerResultSchema, roleContractManifest,
} from "./roleContracts.js";

export function buildSchemaArtifact() {
  return {
    schema_package_version: roleContractManifest.schema_package_version,
    enums: {
      verdict: verdictSchema.options,
      next_action: nextActionSchema.options,
      dependency_edge_type: dependencyEdgeSchema.shape.type.options,
      risk_level: graphChildSchema.shape.risk_level.options,
    },
    schemas: {
      "smda.graph-decomposer-result.v1": z.toJSONSchema(graphDecomposerResultSchema),
      "smda.review-result.v1": z.toJSONSchema(roleResultSchema),
      // child-implementer / child-fixer result schemas as needed
    },
  };
}

// Stable serialization so the parity test is deterministic.
export function serializeArtifact(obj: unknown): string {
  return JSON.stringify(sortKeysDeep(obj), null, 2) + "\n";
}
```

(Verify the zod v4 accessors: `.options` for enums, `.shape.<field>` for object
fields. Adjust to the real API if these differ.)

- [ ] **Step 2: Add a writer entrypoint** (run via tsx) that writes
  `serializeArtifact(buildSchemaArtifact())` to the artifact path, and a script:

```json
"schema:export": "tsx packages/sandcastle-runner/src/exportSchemas.ts --write"
```

- [ ] **Step 3: Generate the artifact**, inspect it, commit both.

```bash
npm run schema:export
git add packages/sandcastle-runner/src/exportSchemas.ts package.json \
        packages/scheduler/src/smda_scheduler/schemas/role_schemas.v1.json
git commit -m "Generate role schema artifact from zod (single source)"
```

---

## Task 2: TS parity test (regenerate == committed)

**Files:** `schemaParity.test.ts`.

- [ ] **Step 1: Failing test**

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildSchemaArtifact, serializeArtifact } from "../src/exportSchemas.js";

test("committed schema artifact matches the zod export", () => {
  const committed = readFileSync(
    "packages/scheduler/src/smda_scheduler/schemas/role_schemas.v1.json", "utf8");
  assert.equal(serializeArtifact(buildSchemaArtifact()), committed);
});
```

- [ ] **Step 2: Run** `npm run test:ts`. If it fails, the artifact is stale →
  rerun `schema:export` and commit. Green = drift-proof.

- [ ] **Step 3: Commit.**

---

## Task 3: Python loader

**Files:** `schema_artifact.py`; `test_schema_artifact.py`; maybe `pyproject.toml`.

- [ ] **Step 1: Failing test**

```python
from smda_scheduler.schema_artifact import (
    EDGE_TYPES, NEXT_ACTIONS, RISK_LEVELS, VERDICTS, decomposer_child_fields,
)

def test_vocab_loaded_from_artifact():
    assert "code_dependency" in EDGE_TYPES
    assert "PASS" in VERDICTS and "DONE_WITH_CONCERNS" in VERDICTS
    assert RISK_LEVELS == frozenset({"low", "medium", "high"})
    assert "submit_for_graph_review" in NEXT_ACTIONS

def test_decomposer_child_fields_present():
    assert {"node_id", "acceptance_criteria", "dependencies"} <= decomposer_child_fields()
```

- [ ] **Step 2: Implement** `schema_artifact.py` loading the JSON via
  `importlib.resources.files("smda_scheduler.schemas")`:

```python
import json
from functools import cache
from importlib.resources import files

@cache
def _artifact() -> dict:
    text = files("smda_scheduler.schemas").joinpath("role_schemas.v1.json").read_text()
    return json.loads(text)

VERDICTS = frozenset(_artifact()["enums"]["verdict"])
NEXT_ACTIONS = frozenset(_artifact()["enums"]["next_action"])
EDGE_TYPES = frozenset(_artifact()["enums"]["dependency_edge_type"])
RISK_LEVELS = frozenset(_artifact()["enums"]["risk_level"])

def decomposer_child_fields() -> frozenset[str]:
    schema = _artifact()["schemas"]["smda.graph-decomposer-result.v1"]
    child = schema["properties"]["children"]["items"]
    return frozenset(child.get("properties", {}))
```

- [ ] **Step 3: Ensure package data ships** — confirm `pyproject.toml` includes
  `smda_scheduler/schemas/*.json` (add package-data/`force-include` if the build
  excludes non-`.py` files). Run `uv build` to verify the json is in the wheel.

- [ ] **Step 4: Run tests, green. Commit.**

---

## Task 4: Single-source the edge-type validation + decomposer drift guard

**Files:** `workflow.py`; `test_workflow.py`; `test_schema_artifact.py`.

- [ ] **Step 1: Characterization test** — the artifact edge types equal the set
  `validate_graph` currently hardcodes:

```python
def test_artifact_edge_types_match_legacy_validate_graph_set():
    assert EDGE_TYPES == frozenset(
        {"code_dependency", "contract_dependency", "test_dependency", "sequencing_only"}
    )
```

- [ ] **Step 2: Replace the hardcoded set** in `workflow.validate_graph`
  (lines ~178-184) with `EDGE_TYPES` from the artifact:

```python
from smda_scheduler.schema_artifact import EDGE_TYPES
...
        if edge.type not in EDGE_TYPES:
            raise GraphError(f"Dependency edge has unknown type: {edge.type}")
```

Watch for an import cycle (`schema_artifact` imports only stdlib, so it is a safe
leaf — no cycle).

- [ ] **Step 3: Decomposer-shape drift guard** — the fields Python actually reads
  from decomposer output are present in the artifact shape. Enumerate the keys
  `_graph_children_from_outcome` / `_dependency_edges_from_outcome` consume and
  assert they are `<= decomposer_child_fields()` (and the edge equivalent). This
  is the real cross-language guard: if TS renames/removes a field Python parses,
  this fails.

- [ ] **Step 4: Run `test_workflow.py` + `test_schema_artifact.py`, green.
  Commit.**

---

## Task 5: Full gate

- [ ] **Step 1:** `uv run pytest packages/scheduler/tests/ -q` ; `npm run test:ts`
  ; `npx tsc --noEmit`. All green.
- [ ] **Step 2:** Confirm `npm run schema:export` is idempotent (re-running
  produces no diff).
- [ ] **Step 3: Commit.**

---

## Acceptance Criteria

1. `role_schemas.v1.json` is generated from the Zod schemas and committed.
2. The TS parity test fails on any Zod/artifact divergence (drift-proof).
3. Python derives `VERDICTS` / `NEXT_ACTIONS` / `EDGE_TYPES` / `RISK_LEVELS` and
   the decomposer field set from the artifact.
4. `validate_graph` uses the artifact edge-type set; behaviour unchanged
   (characterization parity).
5. A drift guard fails if TS removes/renames a decomposer field Python parses.
6. Package data ships the json (`uv build` includes it); full suite + TS + tsc
   green.

## Done Definition

- Zod is canonical; Python consumes the generated artifact for the shared
  surface; drift is structurally caught by the TS parity test + the Python drift
  guard.
- New roles added later (Phase 2/3) extend the Zod schemas + regenerate, and
  Python picks up the vocab without hand-editing.

## Out Of Scope — Later

- Single-sourcing the `roleContractManifest` (role→schema_id/output_tag) across
  Py/TS. Revisit only if it drifts.
