# Target-C Implementation Path

Modular + parallelizable end-to-end SMDA. Decisions resolved in the 2026-06-16
grill-with-docs session; see [CONTEXT.md](../../CONTEXT.md) and ADRs 0001-0005.
This is the **ordered path + the details to watch**, not a task-by-task plan.

## Decision index

| # | Decision | Where |
|---|---|---|
| Roadmap = emergent (parents + edges) | [CONTEXT](../../CONTEXT.md) | — |
| One engine, many definitions; RoleAttempt/Effect/Aggregate | [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md) |
| Roadmap = in-engine decomposed parent set; ledger parent-graph authoritative | [ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md) |
| Parent lands to parametric base; merge-tree probe + bounded auto-rebase | [ADR-0003](../../adr/0003-parent-integration-and-cross-parent-conflict.md) |
| Roles bind methodology skills; runner injects | [ADR-0004](../../adr/0004-roles-bind-methodology-skills.md) |
| Zod canonical → generated JSON Schema for Python | [ADR-0005](../../adr/0005-zod-canonical-schema-single-source.md) |
| Execution-modes plan superseded, salvage typed enums | [plan banner](2026-06-16-execution-modes-and-workflow-options-plan.md) |

## Dependency graph of the work

```
Phase 0 (schema single-source) ─┐
                                ├─> Phase 3 (roadmap tier) ─> Phase 4 (land + conflict)
Phase 1 (engine + registry) ────┤
   │                            └─> Phase 2 (methodology injection)
   └─> Phase 5 (modes as definitions)
```

Phase 1 is the enabler; 2/3/4/5 ride it. Phase 0 is independent — do it first so
new roles don't add fresh drift.

## Phase 0 — Schema single-source (ADR-0005)

Make Zod canonical, export a checked-in JSON Schema, Python consumes enums +
decomposer shape, add a parity contract test.

Watch:
- Deterministic export ordering, or the parity test flaps.
- Python imports *only* the shared vocab + decomposer shape — not the whole
  contract. Persona/task/methodology stay Python-owned.

## Phase 1 — Workflow engine + definition registry (ADR-0001) — THE enabler

One engine interpreting `WorkflowDefinition = {phases, transition table, role map,
terminal set, dependency gate}`; Stage work ∈ {RoleAttempt, Effect, Aggregate}.

Order inside the phase (de-risk first):
1. Express the **existing child workflow** as the first Definition — it is already
   `TRANSITIONS`-driven, so this proves the engine with **zero behaviour change +
   full test parity**. This validates the riskiest assumption: the engine can
   express current behaviour losslessly.
2. Convert the **parent if-ladder** (`runtime.py:190-263`) into a parent
   Definition. Each handler becomes a Stage: decompose/reviews/fixes/QA =
   RoleAttempt; publish-children/final-accept = Effect; `CHILDREN_PUBLISHED` =
   Aggregate over the child sub-graph.

Watch:
- `Aggregate` drives a sub-scheduler (`scheduling.run_once`) and reports terminal
  when the node set is all-accepted. This is the new handler — same code will
  serve the roadmap tier in Phase 3.
- Effect stages must stay **idempotent** — preserve the existing tracker-effect
  idempotency keys.
- Do not lose `run_once_durable` semantics (attempt-request/result recording,
  claim/lease). The durable ledger path threads *through* the engine, not around
  it.
- Verdict/action stay stringly-typed at the agent boundary; the engine routes via
  the typed transition table (no scheduler-side severity logic — preserve the
  "reviewer is the sole severity arbiter" invariant).

## Phase 2 — Methodology-skill injection (ADR-0004 + skill provenance)

`RoleContract` declares `methodology_skills`; `RepoContextPacket` gains a skills
registry; `smda.config` gains `skills_dir`; runner composes
`persona + task + injected methodology`.

Watch:
- Token budget: whole skill files can be large. Inject a distilled methodology
  section, not the entire file, if it blows the context.
- Provenance is the consumer repo's `skills_dir` (provisioned by
  `setup-smda-automation`) — tests inject a fake skills dir.

## Phase 3 — Parent/roadmap tier (ADR-0002)

New: ledger parent-graph store (mirror child graph), `parent_dependency_gate`
(mirror `child_dependency_gate`), `roadmap_decomposer` role + Zod schema (rides
Phase 0). Parent gate slots into `workspace_tick.py:80-85` next to
`is_parent_paused` — skip if any blocker ≠ `FINAL_ACCEPTED`.

Watch:
- Completion source is **ledger `FINAL_ACCEPTED`**, not tracker state.
- Cycle-check the parent graph (reuse `_reject_cycles`).
- `roadmap_decomposer` reuses child-publication + `link_blocking` to emit parents
  + edges; feed it the **open-parent snapshot** (Todo+InProgress, all roadmaps)
  for cross-roadmap edges + scope de-dup.
- Auto-unblock is free via the next scan tick — do not build an event system.

## Phase 4 — Landing + cross-parent conflict (ADR-0003)

Parametric base (roadmap-integration branch for members, main for standalone).
Parent `FINAL_ACCEPT` Effect lands parent-int → base via `GitParentIntegration`
(ff-only + fallback). Roadmap-completion Aggregate stage lands roadmap-int → main
as one gate. A `merge-tree --write-tree` probe Stage runs before the land Effect;
conflict → bounded rebase-loser-onto-base + re-quality-review → escalate to
`HUMAN_REVIEW_REQUIRED` at the cap.

Watch:
- `merge-tree --write-tree` needs git 2.38+; keep it behind the `GitRunner` seam
  for testability.
- Rebased agent code may be semantically broken — the **mandatory re-review** is
  the catch; the cycle cap prevents rebase livelock.
- Roadmap branch lifecycle: create on first member dispatch, delete after
  roadmap → main lands.

## Phase 5 — Modes as definitions (salvage the superseded plan)

`smda-task` / `manual` / `smda-review` become `WorkflowDefinition`s on the engine.
Salvage `ExecutionMode` / `ModeTag` enums + `candidate_routing` → Mode. Drop the
`WorkflowOptions` boolean bundle, `require_spec_review` threading, and the net-new
`run_task_candidate_tick`.

Watch:
- `smda-task` = the child SDD definition **minus the spec-review stage** — a
  different transition table, NOT a boolean flag. That is the whole point of the
  supersession.

## First vertical slice to validate

Phase 0 + Phase 1 step 1 (child workflow on the engine, zero behaviour change,
green test parity). If the engine can re-express the existing child workflow
losslessly, the entire target-C rests on solid ground. Build that before anything
else.
