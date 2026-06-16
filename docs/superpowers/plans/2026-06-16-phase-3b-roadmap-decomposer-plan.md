# Phase 3b — Roadmap Decomposer (Author The Parent Set + Edges) Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time.

> **Agent handoff (read first — hand-rolled RepoContextPacket):**
> - **Branch:** work on `target-c`. Do NOT branch from `master`/`main`.
> - **Read first:** [CONTEXT.md](../../CONTEXT.md) (Roadmap, Roadmap Spec,
>   Roadmap Decomposer, Parent), [ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md),
>   [ADR-0005](../../adr/0005-zod-canonical-schema-with-generated-artifact.md),
>   [target-C spec](../specs/2026-06-16-target-c-modular-parallel-engine.md) §4–§5.
> - **Mirror the parent tier:** this is the parent-graph decomposer
>   (`GRAPH_DECOMPOSING` role → child-publication Effect) lifted one tier up.
>   Read `run_parent_child_publication_tick` (`runtime.py`, the idempotency
>   model), the `graph_decomposer` `RoleContract`, and the `graphDecomposerResultSchema`
>   in `roleContracts.ts` first.
> - **Prereqs:** Phase 0 (schema artifact), Phase 1 (engine + registry),
>   Phase 2 (methodology injection), **Phase 3a** (gate + `record_roadmap_edges` +
>   `load_roadmap_blockers` already landed — this phase *writes* the edges 3a reads).
> - **Line numbers are indicative** — grep for symbols.
> - **Discipline:** TDD red→green. Parity = don't change existing assertions.
>   `uv run pytest packages/scheduler/tests/`, `npm run test:ts`, `npx tsc --noEmit`
>   all green at every commit.

**Goal:** Add a `roadmap_decomposer` role that reads an approved **Roadmap Spec**
and authors the whole parent set at once — every member parent issue + every
parent→parent dependency edge — reusing the child-publication + `link_blocking`
machinery one tier up. After this phase, an `Execution: smda-roadmap` issue
decomposes into N `Execution: smda` member parents wired with roadmap edges; the
Phase-3a gate then dispatches them in dependency order. Implements the authoring
half of [ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md).

**Emergent-roadmap constraint (ADR-0002):** there is **no first-class Roadmap
entity and no Roadmap FSM**. Do NOT build a parent-style QA/accept lifecycle for
the roadmap. The Roadmap Spec issue carries only a thin *authoring* path:
decompose → (publish) → terminal. Member parents then run as ordinary parents,
gated by 3a. Roadmap *completion* (all members `FINAL_ACCEPTED` → land
roadmap-integration → main) is the Phase-4 Aggregate, NOT this phase.

**Scope split:** 3b is the **decompose + author parents/edges + publish**
mechanism. The parent-tier landing / roadmap → main / `merge-tree` conflict probe
is **Phase 4**. Cross-roadmap edges and duplicate-scope skipping from the
open-parent snapshot are supported by giving the decomposer the snapshot
(Task 7), but the *gate* already treats any recorded edge uniformly.

**Architecture:**
- Zod `roadmapDecomposerResultSchema` (canonical) → regenerated JSON artifact →
  Python vocab + shape accessors (ADR-0005). One drift test.
- A `roadmap_decomposer` `RoleContract` (persona + `to-prd`/`to-issues`
  methodology, ADR-0004) authoring the parent set; the role does NOT mutate the
  tracker.
- `Execution: smda-roadmap` mode + `CandidateRoute.ROADMAP` routing.
- A thin `ROADMAP_DEFINITION` (decompose RoleAttempt → publish Effect → terminal)
  registered for `SMDA_ROADMAP`; reuses `WorkflowEngine`.
- A ledger roadmap-member store + projection table (mirror `smda_graph_child` +
  `child_issue_projection`); the publish Effect creates member parent issues
  idempotently, records edges via the existing `record_roadmap_edges` (3a), and
  projects edges to tracker `link_blocking`.

**Tech Stack:** TypeScript (zod) for the canonical schema; Python scheduler,
SQLite `PhaseLedger`, pytest.

## Relationship To Other Plans

- Phase 3 (step b) of
  [target-c-implementation-path](2026-06-16-target-c-implementation-path.md).
- Spec §4 (schema), §5 (roadmap tier); ADR-0002, ADR-0004, ADR-0005.
- **Consumes:** Phase 3a `record_roadmap_edges` / `load_roadmap_blockers`.
- **Feeds:** Phase 4 (roadmap completion Aggregate reads the member set +
  `FINAL_ACCEPTED`; landing uses the parametric base).

## Scope

In scope:
- Canonical Zod `roadmap_decomposer` schema + artifact regen + Python accessors +
  drift test.
- `RoleName.ROADMAP_DECOMPOSER` + `RoleContract` (persona + methodology) + registry.
- `ExecutionMode.SMDA_ROADMAP` + `CandidateRoute.ROADMAP` + `classify_candidate`.
- `ROADMAP_DEFINITION` (decompose → publish → terminal) + `SMDA_ROADMAP` registry.
- Ledger roadmap-member store + projection; publication Effect (idempotent
  issue creation + `record_roadmap_edges` + `link_blocking`).
- Open-parent snapshot assembled and injected into the decomposer prompt.

Out of scope:
- Parent / roadmap landing, roadmap → main, `merge-tree` conflict probe (Phase 4).
- Roadmap completion Aggregate (Phase 4).
- Any Roadmap FSM beyond decompose → publish → terminal (ADR-0002: emergent).
- Modes-as-definitions registry refactor of the *other* modes (Phase 5).

## File Structure

- Modify `packages/sandcastle-runner/src/roleContracts.ts` (schemas + manifest +
  `roleResultSchemaForId`).
- Regenerate `packages/scheduler/src/smda_scheduler/schemas/role_schemas.v1.json`
  via the `exportSchemas` `--write` entrypoint.
- Modify `schema_artifact.py` (roadmap decomposer field accessors).
- Modify `role_contracts.py` (`RoleName`, `ROADMAP_ROLE_BY_PHASE`/registry, contract).
- Modify `execution_modes.py` (`SMDA_ROADMAP`, `resolve_workflow_options`, catalog).
- Modify `candidate_routing.py` (`CandidateRoute.ROADMAP`, classify branch).
- Modify `workflow.py` (`RoadmapPhase` thin enum) and `workflow_engine.py`
  (`ROADMAP_DEFINITION` + stages), `workflow_registry.py` (`SMDA_ROADMAP` mapping).
- Modify `phase_ledger.py` (roadmap-member store + projection).
- Modify `runtime.py` (decompose role tick + publish Effect tick + snapshot).
- Tests: `test_role_schema_artifact.py` (or the existing drift test),
  `test_role_contracts.py`, `test_execution_modes.py`, `test_candidate_routing.py`,
  `test_workflow_registry.py`, `test_phase_ledger.py`, `test_runtime.py`.

> **Suggested two-sitting split** (the phase is large; each sitting ends green):
> **3b-i = Tasks 1–4** (schema + contract + mode/routing + ledger store — all pure,
> no orchestration). **3b-ii = Tasks 5–8** (definition + publish Effect + snapshot
> + end-to-end).

---

## Task 1: Canonical roadmap-decomposer schema (Zod → artifact → Python)

**Files:** `roleContracts.ts`; `role_schemas.v1.json` (generated);
`schema_artifact.py`; the schema drift test.

- [ ] **Step 1: Failing tests.**
  - TS (`roleContracts` test): `roleResultSchemaForId("smda.roadmap-decomposer-result.v1")`
    returns a schema that parses a result with `parents` + `roadmap_edges` and
    rejects an empty `parents` array.
  - Python drift test (the existing artifact-equals-Zod contract test) will fail
    until the artifact is regenerated — that is the red signal for Step 3.
  - Python: `decomposer_roadmap_parent_fields()` / `roadmap_edge_fields()`
    accessors in `schema_artifact.py` return the expected key sets.

- [ ] **Step 2: Implement the Zod schema** in `roleContracts.ts`:
  `roadmapParentSchema` (`node_id`, `title`, `body`/spec text, `risk_level`,
  `dependencies: string[]` of upstream node_ids) and reuse a parent→parent edge
  shape (`from`, `to`, `blocks_dispatch`, `reason`, `type`). Define
  `roadmapDecomposerResultSchema = roleResultSchema.extend({ parents: z.array(...).min(1),
  roadmap_edges: z.array(...).default([]) })`. Add the role to `roleContractManifest`
  (`schema_id: "smda.roadmap-decomposer-result.v1"`, `output_tag:
  "smda_roadmap_decomposer_result"`) and branch it in `roleResultSchemaForId`.

- [ ] **Step 3: Regenerate the artifact** with the `--write` entrypoint
  (`exportSchemas.ts`); verify the drift test goes green. Add the Python
  accessors to `schema_artifact.py`.

- [ ] **Step 4: `npm run test:ts`, `npx tsc --noEmit`, the drift + accessor tests
  green. Commit.**

---

## Task 2: `roadmap_decomposer` role contract + persona + methodology

**Files:** `role_contracts.py`; `test_role_contracts.py`.

- [ ] **Step 1: Failing test** — a `ROADMAP_DECOMPOSER` contract exists, maps in
  the roadmap registry, declares `methodology_skills = ("to-prd", "to-issues")`
  (ADR-0004), uses `schema_id = "smda.roadmap-decomposer-result.v1"`, and its
  prompt template has the snapshot + spec placeholders.

- [ ] **Step 2: Implement** `RoleName.ROADMAP_DECOMPOSER` and the `RoleContract`.
  Persona: authors the whole member parent set from the approved Roadmap Spec;
  receives a read-only **open-parent snapshot**; may author cross-roadmap edges or
  skip duplicate-scope parents; MUST NOT create issues or mutate tracker state
  (the scheduler owns publication). Add a `ROADMAP_ROLE_BY_PHASE` mapping (or fold
  into a roadmap registry) + a `roadmap_role_contract_for_phase` accessor mirroring
  `parent_role_contract_for_phase`. Ensure `_load_declared_skills`
  (`context_packets.py`) still discovers the new skills (it iterates all
  contracts; confirm the roadmap contract is included in that iteration).

- [ ] **Step 3: Run, green. Commit.**

---

## Task 3: `Execution: smda-roadmap` mode + routing

**Files:** `execution_modes.py`; `candidate_routing.py`;
`test_execution_modes.py`; `test_candidate_routing.py`.

- [ ] **Step 1: Failing tests** — `parse_execution_mode("smda-roadmap")` →
  `ExecutionMode.SMDA_ROADMAP`; `resolve_workflow_options` returns sane options
  (spec review on, no integration tag required at intake); `classify_candidate`
  on a body with `Execution: smda-roadmap` returns `CandidateRoute.ROADMAP`.

- [ ] **Step 2: Implement** `ExecutionMode.SMDA_ROADMAP`, the
  `resolve_workflow_options` branch, the catalog markdown line,
  `CandidateRoute.ROADMAP`, and the `classify_candidate` branch.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 4: Ledger roadmap-member store + projection

**Files:** `phase_ledger.py`; `test_phase_ledger.py`.

Mirror `smda_graph_child` + `child_issue_projection` at the parent tier. (Edges
already have `smda_roadmap_edge` from 3a — reuse it.)

- [ ] **Step 1: Failing tests** — `record_roadmap_members(roadmap_id, members)` +
  `load_roadmap_members(roadmap_id)` round-trips the member parent specs;
  `record_roadmap_member_projection(roadmap_id, node_id, issue_id)` +
  `load_roadmap_member_projections(roadmap_id)` round-trips idempotently
  (`ON CONFLICT … DO UPDATE`).

- [ ] **Step 2: Implement** the `roadmap_member` + `roadmap_member_projection`
  tables in `_ensure_schema` and the record/load methods, following the existing
  graph-store idioms (`BEGIN IMMEDIATE`, `json.dumps(..., sort_keys=True)`).

- [ ] **Step 3: Run, green. Commit.**

---

## Task 5: Roadmap workflow definition + registry

**Files:** `workflow.py`; `workflow_engine.py`; `workflow_registry.py`;
`test_workflow_engine.py` / `test_workflow_registry.py`.

- [ ] **Step 1: Failing tests** — `definition_for_mode(ExecutionMode.SMDA_ROADMAP)`
  returns the `ROADMAP_DEFINITION`; its stages are
  `ROADMAP_DECOMPOSING` (`ROLE_ATTEMPT`) → `ROADMAP_PUBLICATION_READY` (`EFFECT`,
  `next_phase_on_success = ROADMAP_PUBLISHED`); `ROADMAP_PUBLISHED` is terminal.

- [ ] **Step 2: Implement** a thin `RoadmapPhase` enum
  (`ROADMAP_DECOMPOSING`, `ROADMAP_PUBLICATION_READY`, `ROADMAP_PUBLISHED`,
  optionally `HUMAN_REVIEW_REQUIRED`) — **keep it thin per ADR-0002**, no QA/accept
  tail. Build `ROADMAP_DEFINITION` (lazy-import the runtime handlers as the other
  parent stages do to avoid the import cycle) and register
  `SMDA_ROADMAP → ROADMAP_DEFINITION` in `_REGISTRY`.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 6: Roadmap publication Effect (idempotent author → publish)

**Files:** `runtime.py`; `test_runtime.py`.

This is the **idempotency-critical** seam the 3a plan flagged: tracker-first issue
creation + ledger edge recording must survive a partial failure without the gate
seeing a member with no blockers.

- [ ] **Step 1: Failing tests**
  - Happy path: given persisted roadmap members + edges, the publish Effect
    creates one `Execution: smda` parent issue per member (skipping any already in
    `roadmap_member_projection`), records the parent→parent edges via
    `record_roadmap_edges` keyed by the **minted issue ids**, calls
    `link_blocking(blocker_id, blocked_id)` per edge, and advances the roadmap run
    to `ROADMAP_PUBLISHED`.
  - **Idempotency / partial-failure:** re-running the Effect after all issues
    exist creates no duplicate issues and records no duplicate edges; a run that
    created issues but is re-entered still ends with every edge recorded (the gate
    must never observe a member whose upstream edge is missing). Drive this by
    invoking the Effect twice and asserting `load_roadmap_blockers` is complete
    after the second call even if the first is interrupted before edge recording.

- [ ] **Step 2: Implement** `run_roadmap_publication_tick` mirroring
  `run_parent_child_publication_tick`: load members + projections; create missing
  member issues (body carries `Execution: smda` + spec pointer) and record each
  projection immediately after minting; **then** map member node_ids → issue_ids
  and `record_roadmap_edges` (idempotent upsert from 3a) + `link_blocking`. Record
  edges in the same load-then-write pass so a re-entry always reconciles. Advance
  the run via `ROADMAP_DEFINITION.stage(ROADMAP_PUBLICATION_READY).next_phase_on_success`.
  Also add `run_roadmap_decomposition_tick` (the `ROADMAP_DECOMPOSING` RoleAttempt)
  that persists members via `record_roadmap_members`.

- [ ] **Step 3: Parity gate** — full `test_runtime` + `test_workspace_tick` green;
  only additive tests. Commit.

---

## Task 7: Open-parent snapshot into the decomposer prompt

**Files:** `runtime.py` (and the backlog read seam); `test_runtime.py`.

- [ ] **Step 1: Failing test** — the decomposer prompt includes a read-only
  snapshot of open parents (Todo + In Progress) so the role can author
  cross-roadmap edges / skip duplicate scope. With no open parents the prompt
  still renders (empty snapshot section).

- [ ] **Step 2: Implement** a point-in-time snapshot read (reuse the backlog
  listing the scanner already uses) and thread it into the decomposer prompt
  values. Snapshot is advisory context only — the gate stays ledger-authoritative.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 8: Full gate + end-to-end

- [ ] `uv run pytest packages/scheduler/tests/ -q`; `npm run test:ts`;
  `npx tsc --noEmit`. All green.
- [ ] End-to-end test: an `Execution: smda-roadmap` issue decomposes into ≥3
  members with edges; after the publish Effect, the Phase-3a gate skips downstream
  members until upstreams are `FINAL_ACCEPTED` and dispatches them in order
  (drive parent runs to `FINAL_ACCEPTED` to prove auto-unblock across ticks).
- [ ] Confirm: with no `smda-roadmap` issues, all existing behaviour is unchanged.
- [ ] Commit.

## Acceptance Criteria

1. The canonical Zod schema defines a `roadmap_decomposer` result
   (`parents` + `roadmap_edges`); the checked-in artifact equals the Zod export;
   Python exposes the roadmap vocab + shape from the artifact.
2. A `roadmap_decomposer` `RoleContract` exists with `to-prd`/`to-issues`
   methodology and a persona that authors the parent set without mutating the
   tracker.
3. `Execution: smda-roadmap` routes to `CandidateRoute.ROADMAP` and resolves to
   `ROADMAP_DEFINITION` via the registry.
4. The publish Effect creates member parent issues + records parent→parent edges +
   `link_blocking`, idempotently (no duplicate issues/edges; every edge present
   after a re-entry).
5. The decomposer receives a read-only open-parent snapshot.
6. End-to-end: a ≥3-parent roadmap dispatches in dependency order via the
   Phase-3a gate; existing behaviour unchanged when no roadmap issues are present.
7. Full suite + TS + tsc green.

## Done Definition

- An approved Roadmap Spec decomposes into N member parents wired with
  authoritative ledger edges (cycle-checked) and tracker `blocks` projections; the
  Phase-3a gate orders their dispatch. The roadmap itself stays emergent — no FSM
  beyond decompose → publish (ADR-0002).
- Ready for **Phase 4** (parent landing to the parametric base, roadmap → main
  completion Aggregate, `merge-tree` conflict probe), which consumes the member
  set + the `FINAL_ACCEPTED` completion signal.

## Out Of Scope — Next Plans

- **Phase 4:** parent `FINAL_ACCEPT` lands to a parametric base
  (roadmap-integration for members, `main` for standalone); roadmap completion
  Aggregate lands roadmap-integration → main once; `merge-tree --write-tree`
  conflict probe + bounded auto-rebase + mandatory re-review.
- **Phase 5:** modes-as-definitions registry refactor for the remaining modes.
