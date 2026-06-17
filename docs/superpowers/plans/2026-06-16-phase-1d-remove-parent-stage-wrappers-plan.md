# Phase 1d — Deepen Parent Stage Dispatch (Remove The Opaque Wrappers) Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time. **Status: OPTIONAL / deferrable** — read
> "Is this worth doing?" before starting.

> **Agent handoff (read first — hand-rolled RepoContextPacket):**
> - **Branch:** work on `target-c`. Do NOT branch from `master`/`main`.
> - **Read first:** [CONTEXT.md](../../CONTEXT.md) (Work Handler, Stage,
>   Workflow Definition), [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md)
>   (Work Handler kinds: RoleAttempt / Effect / Aggregate),
>   [target-C spec](../specs/2026-06-16-target-c-modular-parallel-engine.md) §1.
> - **The thing this targets:** the `StageSpec.work` opaque callables in
>   `workflow_engine.py` (the `_spec_finalized_work` / `_graph_fixing_work` /
>   `_child_publication_work` / … wrappers) and `WorkflowEngine.dispatch_parent_stage`.
> - **Line numbers are indicative** — grep for symbols.
> - **Prereqs:** Phases 1a–1c (engine, parent on engine, transitions-as-data).
>   This is the deferred tail of Phase 1b/1c.
> - **Discipline:** TDD red→green, but this is a **pure refactor** — the parity
>   contract is absolute: every existing parent / child / roadmap test passes with
>   its assertions **unchanged**. No behaviour change, byte-for-byte.

## Is This Worth Doing? (read before committing to it)

The `StageSpec.work` comment says *"Phase 1d replaces these opaque callables with
generic kind interpretation."* That aspiration is **only partly real**, and the
plan is honest about it:

- The `_*_work` wrappers are **not accidental tech debt** — they are thin
  lazy-import shims that break a genuine import cycle (`runtime.py` imports
  `workflow_engine.py`; the wrappers lazy-import `runtime` at call time).
- **Effect / Aggregate handlers are irreducibly heterogeneous.** Publication,
  child-acceptance, final-accept (+ probe + land), remediation, and roadmap
  completion each do *different* ledger / git / tracker work. No amount of "kind
  interpretation" derives them from `WorkHandlerKind.EFFECT` alone — a registry
  keyed by phase is the same indirection in a different shape, not a deepening.
- **Role-attempt handlers are also non-uniform**: decomposition records the child
  graph + roadmap members; the reviewers only route. So a single generic
  role-attempt interpreter still needs per-stage post-processing.

**Recommendation: do the narrow, real win or skip.** The only genuine deepening
here is unifying the five *parent role-attempt* handlers' shared machinery
(request build → execute → record attempt → route via the transition table) into
one generic runner — the way the child tier already works through
`run_child_workflow_tick` — with the bespoke bits (decomposition's graph/member
recording) as an explicit post-attempt hook. The Effect/Aggregate stages stay
explicit handlers; we only replace the *opaque `work` callable* with a typed,
self-documenting dispatch. If the team would rather not touch working,
parity-green code for marginal structural gain, **skipping 1d is a legitimate
choice** — target-C's 7 gaps are already closed without it.

**Skip criteria (any one ⇒ don't do it):** no new role/effect is imminent that
would benefit; the import-cycle shim is acceptable; appetite for refactor risk on
green code is low.

## Goal

Replace the opaque `StageSpec.work` callables with a **typed, generic dispatch**:
the engine interprets `WorkHandlerKind` directly — a single generic parent
role-attempt runner for `ROLE_ATTEMPT`, and a typed effect-handler reference for
`EFFECT` / `AGGREGATE` — so a reader sees each stage's *kind* and *handler*
without chasing a lazy-import wrapper, and a new parent role attempt is added by a
contract + transition entry with no new wrapper function.

## Scope

In scope:
- A generic parent role-attempt runner driving `ROLE_ATTEMPT` stages from
  `role_contract` + the transition table (mirror `run_child_workflow_tick`).
- A typed effect-handler seam for `EFFECT` / `AGGREGATE` stages replacing the
  opaque `work` callable (explicit handler reference, not a bare `Callable`).
- Delete the per-stage `_*_work` wrappers once both are in place.

Out of scope:
- Any behaviour change (pure refactor; parity is the whole point).
- Collapsing the heterogeneous Effect handlers into one function (they stay
  distinct; only the *dispatch shape* is unified).
- The child tier (already generic) and roadmap-specific work beyond reusing the
  same seam.

## File Structure

- Modify `workflow_engine.py` (`StageSpec`, the stage tables, `dispatch_parent_stage`
  → typed kind interpretation; remove `_*_work` wrappers).
- Modify `runtime.py` (generic parent role-attempt runner + post-attempt hooks;
  the existing `run_parent_*_tick` handlers become either the generic runner's
  callers or registered effect handlers).
- Tests: `test_workflow_engine.py`, `test_runtime.py` (only **additive** tests for
  the new seam; existing assertions untouched).

---

## Task 1: Generic parent role-attempt runner (behind the wrappers)

**Files:** `runtime.py`; `test_runtime.py`.

- [ ] **Step 1: Characterise the shared shape.** The five parent `ROLE_ATTEMPT`
  handlers (`run_parent_graph_decomposition_tick`, `run_parent_graph_fixing_tick`,
  `run_parent_graph_spec_review_tick`, `run_parent_graph_execution_review_tick`,
  `run_parent_qa_review_tick`) share: precondition phase check → build request from
  `role_contract` + repo context → `record_role_attempt_request` → `execution.run_role_attempt`
  → on success route via the parent transition table; on failure the bespoke
  fixer/remediation/human-review routing. Write a focused test that the new
  `run_parent_role_attempt(stage, ctx, *, post_success=...)` reproduces one
  handler's behaviour exactly (start with the simplest: graph spec review).

- [ ] **Step 2: Implement** `run_parent_role_attempt`, parameterised by the stage's
  `role_contract` + a `post_success` hook for stage-specific recording
  (decomposition records graph + members; reviewers record nothing extra). Keep
  the dynamic failure routing identical.

- [ ] **Step 3:** Re-express each of the five handlers as a thin call into
  `run_parent_role_attempt` with its `post_success` hook. **Parity gate:** the full
  parent suite passes unchanged. Commit.

---

## Task 2: Typed Effect/Aggregate handler seam

**Files:** `workflow_engine.py`; `test_workflow_engine.py`.

- [ ] **Step 1: Failing test** — `StageSpec` carries an explicit handler reference
  for `EFFECT` / `AGGREGATE` (e.g. a small typed `EffectHandler` protocol or a
  named callable field) and `dispatch_parent_stage` routes by `kind`:
  `ROLE_ATTEMPT` → the generic runner (Task 1); `EFFECT` / `AGGREGATE` → the
  registered effect handler. The dispatch reads `kind`, not an anonymous `work`.

- [ ] **Step 2: Implement** the typed seam; keep the effect handlers themselves
  (publication, acceptance, final-accept, remediation, completion) unchanged in
  `runtime.py` — only how the stage table references them changes.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 3: Remove the `_*_work` wrappers

**Files:** `workflow_engine.py`; `test_workflow_engine.py`.

- [ ] **Step 1:** Delete the `_spec_finalized_work` / `_graph_fixing_work` /
  `_graph_spec_review_work` / `_graph_execution_review_work` /
  `_child_publication_work` / `_child_acceptance_work` / `_parent_qa_work` /
  `_remediation_work` / `_final_accept_work` / `_landing_conflict_rebasing_work` /
  `_roadmap_*_work` wrappers, now that stages reference the generic runner +
  typed effect handlers. Update the `StageSpec` `work` field comment / remove it.

- [ ] **Step 2: Parity gate** — full suite + TS + tsc green, every existing
  assertion unchanged; confirm the import cycle stays broken (the typed effect
  seam must keep the lazy-import boundary or move the handlers so no module-load
  cycle reappears). Commit.

## Acceptance Criteria

1. `dispatch_parent_stage` interprets `WorkHandlerKind` directly — a generic
   role-attempt runner for `ROLE_ATTEMPT`, a typed handler for `EFFECT` /
   `AGGREGATE`; no anonymous `StageSpec.work` callables remain.
2. The five parent role-attempt handlers share one runner; their behaviour is
   byte-for-byte unchanged.
3. Every existing parent / child / roadmap test passes with assertions unchanged
   (pure refactor); TS + tsc green.
4. Adding a new parent role attempt needs a contract + transition entry + (if
   any) a post-success hook — no new wrapper function.

## Done Definition

- The last "shallow" seam from Phase 1b is gone: parent stage dispatch is typed
  and generic where it can be, and explicit where the work is irreducibly bespoke
  — with zero behaviour change. ADR-0001's Work Handler kinds are first-class in
  the dispatch, not just in the data.

## Out Of Scope — Next

- Nothing queued after 1d. With Phases 0–5 + 1d done, target-C's 7 gaps are
  closed and the engine is fully data-driven. Remaining future work would be new
  modes/roles (each now a registry + definition entry) or enabling `smda-review`.
