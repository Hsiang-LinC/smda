# Phase 4 — Parent Landing + Cross-Parent Conflict Repair Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time.

> **Agent handoff (read first — hand-rolled RepoContextPacket):**
> - **Branch:** work on `target-c`. Do NOT branch from `master`/`main`.
> - **Read first:** [CONTEXT.md](../../CONTEXT.md) (Parent, Roadmap, Integration
>   branch), [ADR-0003](../../adr/0003-parent-integration-and-cross-parent-conflict.md)
>   (this phase *is* ADR-0003), [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md)
>   (conflict handling = engine transitions, not a bespoke branch),
>   [ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md)
>   (roadmap member set), [target-C spec](../specs/2026-06-16-target-c-modular-parallel-engine.md) §6.
> - **Mirror existing seams:** child→parent-integration landing already exists —
>   `GitParentIntegration.apply_child_candidate` / `has_accepted_child_ref`
>   (`git_integration.py`), `recover_or_apply_child_accept` +
>   `parent_accept_ledger` (`parent_acceptance.py`, `phase_ledger.py`). Phase 4
>   lifts this one tier up (parent→base) and adds the merge-tree probe + rebase.
> - **Current reality:** `run_parent_final_accept_tick` (`runtime.py`) is a
>   **no-op land** today — it comments + sets `Done` + advances to
>   `FINAL_ACCEPTED` but never merges `parent-integration → base`. Phase 4 makes
>   the land real.
> - **Line numbers are indicative** — grep for symbols.
> - **Prereqs:** Phases 1–3 (engine, registry, methodology, roadmap decomposer +
>   gate). `merge-tree --write-tree` needs git ≥ 2.38 (the `GitRunner` seam keeps
>   it injectable for tests).
> - **Discipline:** TDD red→green. Parity = don't change existing assertions.
>   `uv run pytest packages/scheduler/tests/`, `npm run test:ts`,
>   `npx tsc --noEmit` all green at every commit.

**Goal:** Land accepted parent work to a base branch and repair late-discovered
cross-parent conflicts, so roadmap members build on each other's *landed* code and
a roadmap lands atomically. Implements [ADR-0003](../../adr/0003-parent-integration-and-cross-parent-conflict.md).

After this phase: parent `FINAL_ACCEPT` lands `parent-integration → base`
(ff-only + fallback) where `base` is parametric — a shared roadmap-integration
branch for roadmap members, `main` for standalone parents; a read-only
`merge-tree --write-tree` probe Stage runs before the land Effect and, on
conflict, routes the loser through a bounded rebase + mandatory quality re-review;
and roadmap completion (all members `FINAL_ACCEPTED`) lands the
roadmap-integration branch to `main` as a single gate.

**Scope split (one doc, three green commit boundaries):**
- **4a — Real parametric land.** `parent-integration → base` land Effect, base
  resolution (roadmap member vs standalone), idempotent land ledger op. No probe
  yet; standalone parents land to `main`, members land to their roadmap branch.
- **4b — Conflict probe + bounded auto-rebase.** `merge-tree --write-tree` probe
  Stage before land; on conflict, rebase loser onto the winner's landed base +
  re-run quality review, bounded by the existing fix-cycle →
  `HUMAN_REVIEW_REQUIRED` escalation.
- **4c — Roadmap completion Aggregate.** Roadmap-integration branch lifecycle
  (create on first member dispatch, delete after land) + a roadmap-tier Aggregate
  that lands roadmap-integration → `main` once, when every member is
  `FINAL_ACCEPTED`.

**Architecture:**
- `GitParentIntegration` grows `land_parent_to_base(operation)` (ff-only + cherry/
  merge fallback) and `probe_conflict(*, head, base) -> ConflictProbeResult` (via
  `git merge-tree --write-tree`, read-only). The `GitRunner` seam stays injectable.
- A `parent_land_ledger` table + `recover_or_apply_parent_land` mirror the child
  accept op (at-least-once, idempotent recovery).
- Base resolution: `resolve_parent_base(ledger, parent_id, *, standalone_base)` —
  roadmap-integration branch if the parent issue is a roadmap member (reverse
  lookup over `roadmap_member_projection`), else `standalone_base` (`main`).
- Conflict handling is **engine transitions** (ADR-0001): new `ParentPhase`s
  `LANDING_CONFLICT_PROBING` → land, or `LANDING_CONFLICT_REBASING` → re-review.
- Roadmap completion is the **parent-tier Aggregate** (ADR-0002/§6): the
  `ROADMAP_DEFINITION` gains a post-publish aggregate stage that polls member
  `FINAL_ACCEPTED` and lands once.

**Tech Stack:** Python scheduler, real `git` in tmp repos for the integration
seam, SQLite `PhaseLedger`, pytest. (No TS/schema changes expected.)

## Relationship To Other Plans

- Phase 4 of [target-c-implementation-path](2026-06-16-target-c-implementation-path.md);
  spec §6; ADR-0003 (+ ADR-0001, ADR-0002).
- **Consumes:** Phase 3a `parent_dependency_gate` + `FINAL_ACCEPTED` signal;
  Phase 3b roadmap member set + `roadmap_member_projection`.
- **Feeds:** Phase 5 (modes as definitions) is independent and can follow.

## Scope

In scope:
- Parent `parent-integration → base` land (ff-only + fallback) + idempotent land
  ledger op + recovery.
- Parametric base resolution (roadmap member → roadmap branch; standalone →
  `main`).
- `merge-tree --write-tree` conflict probe Stage + bounded auto-rebase + mandatory
  quality re-review, capped to `HUMAN_REVIEW_REQUIRED`.
- Roadmap-integration branch lifecycle + roadmap completion Aggregate
  (roadmap-integration → `main`, once).

Out of scope:
- Any change to the canonical Zod schema / artifact (no role output shape changes).
- New methodology bindings (Phase 2 set stands).
- Phase 5 modes-as-definitions registry refactor.
- Cross-*roadmap* serializability (ADR-0002 keeps point-in-time snapshots).

## File Structure

- Modify `git_integration.py` (`land_parent_to_base`, `probe_conflict`,
  `ConflictProbeResult`).
- Modify `parent_acceptance.py` (parent land op + `recover_or_apply_parent_land`).
- Modify `phase_ledger.py` (`parent_land_ledger` table + record/load;
  `load_roadmap_for_member` reverse lookup; roadmap branch bookkeeping if needed).
- Modify `workflow.py` (new `ParentPhase` conflict phases; roadmap completion
  phases) and `workflow_engine.py` (stages + transitions for both definitions).
- Modify `runtime.py` (real land in `run_parent_final_accept_tick`; probe + rebase
  ticks; roadmap completion aggregate tick; base resolution helper).
- Modify `runtime_factory.py` / `cli.py` (thread `base` / `main` + the
  `ParentIntegration` into the roadmap path; roadmap branch create/delete).
- Tests: `test_git_integration.py`, `test_parent_acceptance.py`,
  `test_phase_ledger.py`, `test_workflow_engine.py`, `test_runtime.py`,
  `test_runtime_factory.py`.

---

# 4a — Real Parametric Land

## Task 1: `GitParentIntegration.land_parent_to_base`

**Files:** `git_integration.py`; `test_git_integration.py`.

- [ ] **Step 1: Failing test** (real git in `tmp_path`, mirror the existing
  child-land tests): given `parent-integration` ahead of `base`,
  `land_parent_to_base` fast-forwards `base` to the parent ref; when `base` has
  diverged but is mergeable, the fallback lands it; an idempotent re-land is a
  no-op (`has_landed_parent_ref` → True).

- [ ] **Step 2: Implement** `land_parent_to_base(operation)` and
  `has_landed_parent_ref(operation)` mirroring `apply_child_candidate` /
  `has_accepted_child_ref` but switching to `base` and merging the
  parent-integration ref. Reuse the `_git` / `GitRunner` seam.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 2: Parent land ledger op + recovery

**Files:** `parent_acceptance.py`; `phase_ledger.py`; `test_parent_acceptance.py`,
`test_phase_ledger.py`.

- [ ] **Step 1: Failing tests** — a `ParentLandOperation`
  (`operation_id`, `idempotency_key`, `parent_id`, `parent_ref`, `base_branch`,
  status) records pending → completed; `recover_or_apply_parent_land` is
  idempotent (re-entry after a recorded-but-not-applied op does not double-land);
  the ledger round-trips the op.

- [ ] **Step 2: Implement** the `parent_land_ledger` table (mirror
  `parent_accept_ledger`) + `record_parent_land_operation` /
  `mark_parent_land_completed` / `mark_parent_land_failed` /
  `load_parent_land_operations`, and `recover_or_apply_parent_land` in
  `parent_acceptance.py` mirroring `recover_or_apply_child_accept`.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 3: Parametric base resolution + real land in FINAL_ACCEPT

**Files:** `phase_ledger.py` (reverse lookup); `runtime.py`; `runtime_factory.py`;
`test_phase_ledger.py`, `test_runtime.py`, `test_runtime_factory.py`.

- [ ] **Step 1: Failing tests**
  - `load_roadmap_for_member(parent_issue_id)` returns the owning `roadmap_id`
    (and member node_id) for a published member, `None` for a standalone parent.
  - `resolve_parent_base(ledger, parent_id, standalone_base="main")` →
    the roadmap-integration branch for a member, `"main"` for a standalone parent.
  - `run_parent_final_accept_tick` (given a `ParentIntegration` + base) records +
    applies the land op against the resolved base, then advances to
    `FINAL_ACCEPTED`; with no integration configured it degrades to the current
    comment-only behaviour (keep existing tests green).

- [ ] **Step 2: Implement** `load_roadmap_for_member` (scan
  `roadmap_member_projection`), `resolve_parent_base`, and the real land in
  `run_parent_final_accept_tick`: resolve base → build a `ParentLandOperation` for
  the parent's accepted integration ref → `recover_or_apply_parent_land` → record
  the lifecycle effects (comment + state) → advance phase. Thread the
  `ParentIntegration` + standalone base (`main`) through `runtime_factory` exactly
  as the child path threads `integration` / `integration_branch`.

- [ ] **Step 3: Parity gate** — existing final-accept tests still pass (no-op land
  path preserved when no integration). Commit. **4a green boundary.**

---

# 4b — Conflict Probe + Bounded Auto-Rebase

## Task 4: `merge-tree --write-tree` conflict probe

**Files:** `git_integration.py`; `test_git_integration.py`.

- [ ] **Step 1: Failing test** (real git) — `probe_conflict(head=parent-integration,
  base=base)` returns `ConflictProbeResult(clean=True)` when the trees merge and
  `clean=False` (with conflicted paths) when they do not. Read-only: the probe
  mutates no branch.

- [ ] **Step 2: Implement** `ConflictProbeResult` (frozen: `clean`,
  `conflicted_paths: tuple[str, ...]`) and `probe_conflict` via
  `git merge-tree --write-tree --name-only <base> <head>`, parsing the conflict
  output. Raise `GitIntegrationError` on an unexpected git failure.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 5: Probe Stage + conflict transitions in the parent engine

**Files:** `workflow.py`; `workflow_engine.py`; `runtime.py`;
`test_workflow_engine.py`, `test_runtime.py`.

- [ ] **Step 1: Failing tests** — `FINAL_ACCEPT_READY` now routes through a
  `LANDING_CONFLICT_PROBING` stage: a clean probe advances to the land Effect
  (→ `FINAL_ACCEPTED`); a conflicted probe advances to `LANDING_CONFLICT_REBASING`.
  The engine exposes both transitions as data.

- [ ] **Step 2: Implement** `ParentPhase.LANDING_CONFLICT_PROBING` and
  `LANDING_CONFLICT_REBASING`; insert the probe stage between `FINAL_ACCEPT_READY`
  and the land; wire success/conflict edges in `PARENT_TRANSITIONS` /
  `_PARENT_STAGES`. The probe tick calls `probe_conflict` against the resolved
  base. Keep the land Effect unchanged from 4a (now reached only on a clean probe).

- [ ] **Step 3: Run, green. Commit.**

---

## Task 6: Bounded auto-rebase + mandatory re-review

**Files:** `runtime.py`; `git_integration.py` (rebase op);
`test_runtime.py`, `test_git_integration.py`.

- [ ] **Step 1: Failing tests**
  - The rebase tick rebases the loser `parent-integration` onto the winner's
    landed base and routes the parent back through quality re-review
    (`PARENT_QA_READY`), then re-probes on the next QA pass.
  - The rebase respects the **existing fix-cycle cap**: after the cap it escalates
    to `HUMAN_REVIEW_REQUIRED` (reuse the parent QA cycle bound — do not invent a
    new counter).
  - Idempotent: a re-entered rebase tick does not double-apply.

- [ ] **Step 2: Implement** `GitParentIntegration.rebase_onto_base(operation)` and
  the `LANDING_CONFLICT_REBASING` tick: rebase, then transition to the re-review
  phase; on cap, transition to `HUMAN_REVIEW_REQUIRED`. The mandatory re-review is
  what catches rebase semantic breakage (ADR-0003 consequence).

- [ ] **Step 3: Parity gate** — full parent-flow tests green. Commit.
  **4b green boundary.**

---

# 4c — Roadmap Completion Aggregate

## Task 7: Roadmap-integration branch lifecycle

**Files:** `runtime.py`; `runtime_factory.py` / `cli.py`;
`test_runtime.py`, `test_git_integration.py`.

- [ ] **Step 1: Failing tests** — the roadmap-integration branch name is derived
  per roadmap (e.g. `smda/<roadmap_id>/integration`); it is created (off `main`)
  on first member dispatch and is the base the member land (4a) targets; a helper
  reports whether it exists.

- [ ] **Step 2: Implement** branch derivation + create-if-absent on first member
  land, and expose it from `resolve_parent_base` (Task 3) for members. Deletion is
  deferred to Task 8 (after the roadmap lands).

- [ ] **Step 3: Run, green. Commit.**

---

## Task 8: Roadmap completion Aggregate (roadmap-integration → main, once)

**Files:** `workflow.py`; `workflow_engine.py` (extend `ROADMAP_DEFINITION`);
`runtime.py`; `test_workflow_engine.py`, `test_runtime.py`.

- [ ] **Step 1: Failing tests**
  - `ROADMAP_PUBLISHED` is no longer terminal; the roadmap advances through a
    members-integrating Aggregate that polls member `FINAL_ACCEPTED` and only fires
    when **every** member is accepted.
  - When all members are accepted, the completion tick lands
    roadmap-integration → `main` **once** (idempotent via a land op), deletes the
    roadmap branch, and advances to a terminal `ROADMAP_COMPLETED`.
  - Partial acceptance is a no-op (roadmap stays integrating); auto-fires on a
    later tick once the last member lands (mirror the 3a auto-unblock pattern —
    no event system).

- [ ] **Step 2: Implement** the roadmap-tier Aggregate stage(s)
  (`ROADMAP_MEMBERS_INTEGRATING` → `ROADMAP_COMPLETED`) on `ROADMAP_DEFINITION`,
  reusing `load_roadmap_member_projections` + `load_parent_runs` to test
  member `FINAL_ACCEPTED`, and `land_parent_to_base` (base = `main`) for the
  roadmap branch. Record the land op idempotently; delete the roadmap branch after.

- [ ] **Step 3: Parity gate** — full suite green. Commit. **4c green boundary.**

---

## Task 9: Full gate + end-to-end

- [ ] `uv run pytest packages/scheduler/tests/ -q`; `npm run test:ts`;
  `npx tsc --noEmit`. All green.
- [ ] End-to-end: a standalone parent lands to `main` on `FINAL_ACCEPT`; a
  ≥3-member roadmap lands each member to the roadmap branch in dependency order
  and then lands the roadmap branch to `main` exactly once.
- [ ] End-to-end: two independent parents that textually conflict — the loser
  rebases, re-reviews, and lands; the cap escalates to `HUMAN_REVIEW_REQUIRED`
  when rebase cannot converge.
- [ ] Confirm: with no integration configured, parent final-accept behaviour is
  unchanged (no-op land path).
- [ ] Commit.

## Acceptance Criteria

1. Parent `FINAL_ACCEPT` lands `parent-integration → base` (ff-only + fallback);
   the land op is idempotent and recoverable.
2. `base` is parametric: roadmap-integration branch for members, `main` for
   standalone parents.
3. A read-only `merge-tree --write-tree` probe runs before the land; a clean probe
   lands, a conflicted probe routes to bounded rebase + mandatory quality
   re-review, capped to `HUMAN_REVIEW_REQUIRED`.
4. Roadmap completion lands the roadmap-integration branch to `main` once and only
   once, when every member is `FINAL_ACCEPTED`; the roadmap branch is deleted
   after.
5. With no integration configured, parent final-accept is unchanged.
6. Full suite + TS + tsc green.

## Done Definition

- Accepted parent work lands to a parametric base; roadmap members build on each
  other's landed code and the roadmap lands atomically to `main`; cross-parent
  conflicts self-heal via bounded rebase + re-review, escalating to human review
  on livelock. Conflict handling lives in the stage engine, not a bespoke branch
  (ADR-0001/0003).

## Out Of Scope — Next Plans

- **Phase 5:** modes-as-definitions registry refactor (the remaining execution
  modes resolve to definitions; supersede the modes plan).
- **Phase 1d (optional):** remove the parent stage-work wrappers once every stage
  is generic kind interpretation.
