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

## Design decisions (locked via grill-with-docs, 2026-06-17 — see [ADR-0006](../../adr/0006-kind-driven-parent-dispatch.md))

- **A — parallel parent runner.** `run_parent_role_attempt(stage, ctx)` operates on
  the `parent_run` row (single-row FSM), mirroring the child tier's executor-closure
  Strategy. NOT a synthetic 1-node graph through `run_once_durable` (that engine is
  graph-centric; the costume would hide the 5 builders + 3-way routing, not remove
  them).
- **A3 — hybrid failure routing.** Transition table owns success edges; the runner
  owns the uniform protocol-error branch (`status != succeeded` → record + Blocked);
  an injected `on_failure` hook owns the *stateful* escalation
  (`prior_fix_cycles ≥ _MAX_GRAPH_FIX_CYCLES` → `GRAPH_FIXING` vs
  `HUMAN_REVIEW_REQUIRED`). The pure `(phase, verdict, action)` table structurally
  cannot encode the ledger-count escalation; a synthetic `"exhausted"` action is a
  rejected verdict-space lie.
- **B2 — runner owns one atomic success write.** `post_success` is a *pure*
  function returning `(extra_payload | None, comment)`. The runner does ONE write,
  picking `record_attempt_result_and_parent_run` when `extra is None` else
  `record_attempt_result_parent_run_and_graph(**extra)` — preserving decomposition's
  single-transaction parent_run+graph boundary (splitting it = crash window = parity
  break). `on_failure` is a self-contained writer (returns `ParentIntakeResult`).
  Asymmetry is principled: success write is uniform-with-optional-extra; failure
  write is policy-divergent. **No ledger schema change** — both record methods
  already exist.
- **D3 — pure-data `StageSpec` + one lazy resolver per kind.** `StageSpec` drops
  `work: Callable` entirely → `(phase, kind, role_contract, next_phase_on_success)`.
  `dispatch_parent_stage` branches on `kind`: `ROLE_ATTEMPT` → lazy-import
  `run_parent_role_attempt`; `EFFECT`/`AGGREGATE` → `resolve_parent_effect(phase)`.
  Runtime owns the phase→hook + phase→effect wiring. Keeps the cycle broken at one
  call-time site, `PARENT_DEFINITION` stays constructed in the engine, tests
  untouched. NOT full DI (D2) — that churns the `WorkflowEngine` constructor +
  registry + tests for marginal gain.

---

## Task 1: Generic parent role-attempt runner (decision A / A3 / B2)

**Files:** `runtime.py`; `test_runtime.py`.

- [ ] **Step 1: Failing test.** Write a focused `test_runtime.py` test that the new
  `run_parent_role_attempt(stage, ctx, *, post_success=None, on_failure=None)`
  reproduces `run_parent_graph_spec_review_tick`'s behaviour exactly (simplest:
  reviewer with `on_failure=_route_failed_graph_review`, no `post_success`): the
  three branches — passing verdict → table `next_phase` + InProgress; non-passing →
  `on_failure` (budget → `GRAPH_FIXING` / `HUMAN_REVIEW_REQUIRED`); `status !=
  succeeded` → `record_attempt_result` + Blocked.

- [ ] **Step 2: Implement** `run_parent_role_attempt`. Spine: precondition
  (`stage.phase`) → build request from `role_contract` + repo context →
  `record_role_attempt_request` → `execution.run_role_attempt`. On success: compute
  `next_phase` via the parent transition table, call `post_success(ctx, outcome,
  next_phase) -> (extra | None, comment)`, then ONE atomic write picking the ledger
  method by `extra is None`. On non-passing verdict: `return on_failure(...)`. On
  protocol error: uniform `record_attempt_result` + Blocked. `post_success` /
  `on_failure` default to None (pure happy/Blocked path).

- [ ] **Step 3:** Re-express the five handlers as thin calls into
  `run_parent_role_attempt`: decomposition passes a `post_success` returning the
  graph payload (`children`, `dependency_edges`, `graph_checksum`); spec/execution
  review pass `on_failure=_route_failed_graph_review`; fixing/qa pass their existing
  edges (table-routed). **Parity gate:** full parent suite passes unchanged. Commit.

---

## Task 2: Pure-data StageSpec + kind-driven dispatch (decision D3)

**Files:** `workflow_engine.py`; `runtime.py`; `test_workflow_engine.py`.

- [ ] **Step 1: Failing test** — `dispatch_parent_stage` routes by `kind`:
  `ROLE_ATTEMPT` → `run_parent_role_attempt(stage, ctx)` (lazy import);
  `EFFECT`/`AGGREGATE` → `resolve_parent_effect(stage.phase)(ctx)` (lazy import).
  Add `resolve_parent_effect(phase) -> Callable` in `runtime.py` mapping each
  effect/aggregate phase to its existing handler. The dispatch reads `kind`, not an
  anonymous `work`.

- [ ] **Step 2: Implement** the kind branch + `resolve_parent_effect`. Keep the six
  effect/aggregate handlers themselves unchanged in `runtime.py` — only how dispatch
  reaches them changes. Confirm the `runtime` → `workflow_engine` cycle stays broken
  (the two lazy imports inside `dispatch_parent_stage` are the only call-time edges).

- [ ] **Step 3: Run, green. Commit.**

---

## Task 3: Remove the `_*_work` wrappers + drop `StageSpec.work` (decision D3)

**Files:** `workflow_engine.py`; `test_workflow_engine.py`.

- [ ] **Step 1:** Delete the `_spec_finalized_work` / `_graph_fixing_work` /
  `_graph_spec_review_work` / `_graph_execution_review_work` /
  `_child_publication_work` / `_child_acceptance_work` / `_parent_qa_work` /
  `_remediation_work` / `_final_accept_work` / `_landing_conflict_rebasing_work` /
  `_roadmap_*_work` wrappers and the `_parent_stage(..., work)` / stage-table `work=`
  args. **Remove the `work` field from `StageSpec`** → `(phase, kind, role_contract,
  next_phase_on_success)`. Roadmap-tier dispatch uses the same kind branch (extend
  `dispatch_parent_stage` or its roadmap analogue to resolve roadmap effects too).

- [ ] **Step 2: Parity gate** — full suite + TS + tsc green, every existing
  assertion unchanged; confirm import cycle stays broken (`python -c "import
  smda_scheduler.workflow_engine"` clean, no runtime at module load). Commit.

## Acceptance Criteria

1. `dispatch_parent_stage` interprets `WorkHandlerKind` directly — a generic
   role-attempt runner for `ROLE_ATTEMPT`, `resolve_parent_effect(phase)` for
   `EFFECT` / `AGGREGATE`; `StageSpec` has **no `work` field** and no anonymous
   callables remain.
2. The five parent role-attempt handlers share `run_parent_role_attempt`; the
   uniform spine lives in the runner, the bespoke policy in `post_success` /
   `on_failure` hooks; behaviour byte-for-byte unchanged (incl. decomposition's
   atomic graph write and the fix-cycle → human escalation).
3. Every existing parent / child / roadmap test passes with assertions unchanged
   (pure refactor); TS + tsc green.
4. Adding a new parent role attempt needs a contract + transition entry + (if
   any) a `post_success` / `on_failure` hook — no new wrapper function.

## Done Definition

- The last "shallow" seam from Phase 1b is gone: parent stage dispatch is typed
  and generic where it can be, and explicit where the work is irreducibly bespoke
  — with zero behaviour change. ADR-0001's Work Handler kinds are first-class in
  the dispatch, not just in the data.

## Out Of Scope — Next

- Nothing queued after 1d. With Phases 0–5 + 1d done, target-C's 7 gaps are
  closed and the engine is fully data-driven. Remaining future work would be new
  modes/roles (each now a registry + definition entry) or enabling `smda-review`.
