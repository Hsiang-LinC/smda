---
status: draft
created_at: 2026-06-16
owner: human
approval_evidence: pending human approval
---

# Target-C: Modular, Parallelizable End-to-End SMDA

## Problem

SMDA is a strong single-parent node-execution engine but has no parent-level
orchestration, and its workflow logic is not modular:

1. The **child** workflow is data-driven (`TRANSITIONS` table + role-by-phase map
   + dependency gate), but the **parent** workflow is a hard-coded if-ladder
   (`runtime.py:190-263`), and each execution mode is dispatched by a bespoke
   `run_X_candidate_tick` in a route if-ladder (`runtime_factory.py:53-99`).
   Adding a role, a loop, or a mode touches control flow in several places.
2. There is no notion of a **Roadmap**: parents cannot block or auto-unblock each
   other, so a multi-node directional change cannot be executed in dependency
   order.
3. Cross-parent **conflict** is unguarded, and `FINAL_ACCEPT` does not land work
   on a base branch, so later parents cannot build on earlier landed code.
4. Role behaviour (decompose, implement, review, fix) depends on the model's
   per-turn ability — there is no bound methodology.
5. Role output schemas are hand-duplicated across Python and TypeScript.

The shared root cause: the largest unit of orchestration is a single parent, and
workflow behaviour is encoded as bespoke code paths instead of data.

## Current Baseline

Solid and must be preserved (see [known-gaps.md](../../known-gaps.md)):

- Single-parent end to end: intake → graph decompose → graph spec/execution
  review → child publish → child SDD loop → child accept → parent QA →
  remediation → final accept.
- Child SDD loop with bounded fixer loopback and `HUMAN_REVIEW_REQUIRED`
  escalation (`max_review_fix_cycles`).
- Durable SQLite ledgers (phase, attempt, tracker-effect outbox, parent-accept,
  graph, child-issue projection) with idempotency keys and crash recovery.
- Child dependency dispatch gate: dispatch proven against SMDA-owned state.
- Sandcastle TS runner with `Output.object` Zod-validated structured output.
- Reviewers are the sole severity arbiter; the scheduler routes mechanically.

## Goal

A modular, parallelizable, end-to-end SMDA in which:

- End-to-end is **one workflow among many**, expressed as data, not the only path.
- A **Roadmap** of parent nodes executes in dependency order, parents
  auto-unblock as upstreams complete, and the roadmap lands atomically.
- Independent parents run in **parallel**, with cross-parent conflict detected
  and repaired automatically where possible.
- Each role's quality is governed by a **bound methodology**, not model luck.
- Role schemas have a single source of truth.

## Source Of Truth

This spec implements the decisions recorded in:

- [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md) — one engine,
  many definitions; Work Handlers RoleAttempt / Effect / Aggregate.
- [ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md) —
  roadmap as in-engine decomposed parent set; ledger parent-graph authoritative.
- [ADR-0003](../../adr/0003-parent-integration-and-cross-parent-conflict.md) —
  parametric base landing + merge-tree probe + bounded auto-rebase.
- [ADR-0004](../../adr/0004-roles-bind-methodology-skills.md) — roles bind
  methodology skills; runner injects.
- [ADR-0005](../../adr/0005-zod-canonical-schema-single-source.md) — Zod canonical,
  Python consumes generated JSON Schema.
- [CONTEXT.md](../../CONTEXT.md) — domain glossary.

Ordered build path + per-phase gotchas:
[target-c-implementation-path](../plans/2026-06-16-target-c-implementation-path.md).

## Non-Goals

- The interactive roadmap **discussion** is a human+agent skill, not a daemon
  role. Only the structured breakdown is in-engine.
- No global serializability across roadmaps; decompose uses a point-in-time
  snapshot and the integrate-time conflict gate is the race backstop.
- No pessimistic file-claim registry (specs don't enumerate exact files).
- No first-class Roadmap entity / Roadmap FSM; roadmaps are emergent.
- No per-role model-tier selection (separate future idea).

## Required Behavior

### 1. Workflow Engine And Definition Registry (ADR-0001)

- A single engine interprets a `WorkflowDefinition = {phases, transition table
  (phase × verdict × action → phase), role-by-phase map, terminal set, dependency
  gate}`.
- A registry maps a Route/Mode to a Definition. Dispatch is a registry lookup, not
  an if-branch. Adding a workflow is a registry entry.
- The existing child workflow MUST be expressed as the first Definition with **no
  behaviour change** and full test parity (the riskiest assumption — validate it
  first).
- The parent if-ladder MUST be converted to a parent Definition; durable
  semantics (`run_once_durable` attempt-request/result recording, claim/lease)
  thread through the engine, not around it.

### 2. Work Handlers (ADR-0001)

A Stage's work is exactly one of:

- **RoleAttempt** — run one agent role, verdict from structured output.
- **Effect** — deterministic tracker/git operations, verdict from success;
  effects MUST stay idempotent (reuse tracker-effect idempotency keys).
- **Aggregate** — run a sub-workflow over a node set, terminal when the set
  reaches its terminal condition. The SAME Aggregate handler serves
  "parent waits for children" and "roadmap waits for member parents".

### 3. Methodology Skill Injection (ADR-0004)

- Each `RoleContract` declares `methodology_skills`.
- The runner composes the prompt as `persona + task context + injected
  methodology`; the agent does NOT self-select methodology.
- Skills resolve from the consumer repo's configured `skills_dir`
  (`smda.config`), provisioned by `setup-smda-automation`; `RepoContextPacket`
  carries the skills registry. Tests inject a fake skills dir.
- If a skill exceeds the context budget, inject a distilled methodology section,
  not the whole file.

### 4. Schema Single Source (ADR-0005)

- Zod in `roleContracts.ts` is canonical. A build step exports a checked-in JSON
  Schema artifact.
- Python loads the artifact for the shared vocab (verdict, next-action, edge
  type, risk level) and the decomposer output shape it parses into the ledger
  graph. Python keeps orchestration-only metadata (persona, task template,
  methodology bindings, role→phase).
- A contract test asserts the checked-in artifact equals the current Zod export.

### 5. Roadmap Tier (ADR-0002)

- A `roadmap_decomposer` role reads an approved **Roadmap Spec** and authors the
  whole parent set at once — every member parent issue + every parent→parent
  dependency edge — reusing the child-publication + `link_blocking` machinery one
  tier up.
- The decomposer receives a read-only **snapshot of open parents** (Todo +
  In Progress, all roadmaps) and may author cross-roadmap edges or skip
  duplicate-scope parents.
- Authored edges persist as a **ledger parent-graph** (authoritative,
  cycle-checked via the existing `_reject_cycles`) and project to tracker
  `blocks` relations for display. `query_blocked_by` stays display-only.
- A `parent_dependency_gate` (mirror of `child_dependency_gate`) gates parent
  dispatch: a parent is eligible only when every blocking upstream parent is
  `FINAL_ACCEPTED` in the ledger. The gate slots into the workspace scan next to
  `is_parent_paused` (`workspace_tick.py:80-85`) — skip + continue, not block.
- Auto-unblock is implicit via the next scan tick; no event system.

### 6. Parent Landing And Cross-Parent Conflict (ADR-0003)

- `FINAL_ACCEPT` lands `parent-integration → base` via `GitParentIntegration`
  (ff-only + fallback). `base` is parametric: a shared roadmap-integration branch
  for roadmap members, `main` for standalone parents.
- Roadmap completion (the parent-tier Aggregate stage: all members
  `FINAL_ACCEPTED`) lands `roadmap-integration → main` as one gate. Roadmap branch
  is created on first member dispatch and deleted after it lands.
- Before the land Effect, a `merge-tree --write-tree` probe Stage (read-only)
  checks `parent-integration` against `base`. On conflict, the loser parent is
  rebased onto the winner's landed base and re-runs quality review, bounded by the
  existing fix-cycle → `HUMAN_REVIEW_REQUIRED` escalation. The mandatory
  re-review catches rebase breakage.

### 7. Modes As Definitions (supersede the modes plan)

- `smda-task`, `manual`, `smda-review` become `WorkflowDefinition`s. `smda-task`
  is the child SDD definition **minus the spec-review stage** (a different
  transition table, NOT a boolean flag).
- Salvage the typed `ExecutionMode` / `ModeTag` enums and `candidate_routing`
  resolving `Execution:` → a Mode. Drop the `WorkflowOptions` boolean bundle, the
  `require_spec_review` threading, and any net-new `run_task_candidate_tick`.

## Error Handling

- **Engine transition miss** → `GraphError`, contained to the issue as a Blocked
  tracker effect; the daemon keeps serving (preserve current containment).
- **Parent dependency unmet** → skip the candidate in the scan, do not block; it
  retries on the next tick (auto-unblock).
- **Conflict probe finds conflict** → bounded rebase + re-review; on cap →
  `HUMAN_REVIEW_REQUIRED` with conflicting files in the report.
- **Missing methodology skill** → non-transient configuration error →
  `HUMAN_REVIEW_REQUIRED`; do not run the role with no methodology.
- **Schema artifact stale** → the parity contract test fails CI; the build does
  not ship.

## Acceptance Criteria

1. The child workflow runs on the new engine with byte-for-byte equivalent
   behaviour and the existing child test suite green (no behaviour change).
2. The parent workflow runs on the engine; the if-ladder is gone.
3. A new role or mode is added by a registry/definition entry with no change to
   dispatch control flow.
4. A roadmap of ≥3 parents executes in dependency order; a downstream parent does
   not dispatch until its upstreams are `FINAL_ACCEPTED`; completion of an
   upstream auto-unblocks the next on the following tick.
5. Two independent parents land to base; a forced same-file conflict triggers the
   merge-tree probe, an automatic rebase + re-review, and escalation when the cap
   is hit.
6. Roadmap completion lands the roadmap-integration branch to `main` once and only
   once (idempotent), and standalone parents land directly to `main`.
7. Each role attempt's prompt contains its declared methodology; removing the
   skill from `skills_dir` fails closed (no methodology-less run).
8. The Python schema vocab + decomposer shape derive from the generated artifact;
   the parity test catches an induced Zod/JSON divergence.

## Required Tests

### Unit
- Engine: transition table routing, terminal detection, dependency gate, for both
  a child Definition and a parent Definition.
- Work Handlers: RoleAttempt verdict mapping, Effect idempotency, Aggregate
  terminal-condition over a node set.
- `parent_dependency_gate`: blocked until upstream `FINAL_ACCEPTED`; cycle
  rejection.
- Methodology injection: prompt contains declared skill; missing skill fails
  closed.
- Schema parity: checked-in artifact == Zod export; induced divergence fails.

### Runtime / Integration
- Child workflow parity: existing suite green on the engine.
- Roadmap order: 3-parent graph dispatch order + auto-unblock across ticks.
- Landing: parametric base resolution; roadmap → main once; standalone → main.
- Conflict: merge-tree probe → bounded rebase + re-review → escalation, behind the
  `GitRunner` seam.
- Modes: `smda-task` skips spec review as a Definition; `manual` never dispatches;
  `smda-review` cataloged-but-disabled message.

## Implementation Notes

Build in the dependency order in
[target-c-implementation-path](../plans/2026-06-16-target-c-implementation-path.md):
schema single-source (0) → engine + registry, child-first (1) → methodology
injection (2) → roadmap tier (3) → landing + conflict (4) → modes as definitions
(5). The first vertical slice to validate the whole approach is (0) + (1, child
on the engine with green parity).

Each task is implemented under TDD (red → green → refactor); the
[plan](../plans/2026-06-16-target-c-implementation-path.md) is the source for the
per-phase gotchas (idempotency, durable-path threading, git 2.38+ for
`merge-tree --write-tree`, token budget for skill injection, ledger completion
source, deterministic schema export).

## Done Definition

- All Acceptance Criteria met with tests green (Python + TypeScript) and the
  schema parity test in CI.
- The parent if-ladder and per-route tick if-ladder are removed; routes dispatch
  through the registry.
- ADRs 0001-0005 reflected in code; CONTEXT.md terms accurate; known-gaps.md
  overturns realized.
- A roadmap of ≥3 parents has run end to end (sequential and with one parallel
  pair exercising the conflict path) in a test harness.
