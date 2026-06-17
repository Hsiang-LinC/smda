---
status: accepted
---

# Kind-driven parent dispatch; routing is data where pure, hook where stateful

The parent tier interprets a Stage's `WorkHandlerKind` directly. `dispatch_parent_stage`
branches on `kind`: a `ROLE_ATTEMPT` stage runs through one generic parent
role-attempt runner; an `EFFECT` / `AGGREGATE` stage resolves its handler by phase.
`StageSpec` is therefore **pure data** — `(phase, kind, role_contract,
next_phase_on_success)` — with no opaque `work: Callable`. This realises
[ADR-0001](0001-one-workflow-engine-many-definitions.md)'s promise that the Work
Handler kind is first-class in dispatch, not only in the data, and brings the
parent tier to the maturity the child tier already had (one `run_child_workflow_tick`
driven by contract + transition table).

The five parent role-attempt handlers collapse into one runner because they share
a uniform spine: precondition → build request from `role_contract` → record
request → execute → on success route via the transition table. The bespoke bits
stay explicit, injected hooks rather than being forced into the generic path:

- **`post_success`** contributes an optional extra payload (decomposition's child
  graph + edges) which the runner folds into a **single atomic** ledger write —
  preserving the existing one-transaction `record_attempt_result_parent_run_and_graph`
  boundary. Splitting it would open a crash window between the parent_run advance
  and the graph write, changing recovery behaviour.
- **`on_failure`** owns the divergent failure write. A failed graph review is not
  a static transition edge: the same verdict routes to `GRAPH_FIXING` *or*
  `HUMAN_REVIEW_REQUIRED` depending on `prior_fix_cycles` vs `_MAX_GRAPH_FIX_CYCLES`
  — ledger state, not `(phase, verdict, action)`. The transition table is pure and
  structurally cannot encode this.

## Why routing is not *fully* data-driven

A future reader will ask: if a Mode is just a Definition, why isn't *all* routing —
including the fixer-budget escalation — a transition in the Definition? Because the
transition table is keyed `(phase, verdict, required_next_action) → phase` and is
**pure**. Stateful escalation (bounded fixer → human) depends on a ledger attempt
count, not the verdict. Encoding it would require manufacturing a synthetic
`"exhausted"` action the role never emits — a verdict-space lie that still leaves
the count→action computation somewhere. We rejected that: routing stays data where
it is genuinely pure, and an explicit hook where it is genuinely stateful.

Likewise the `EFFECT` / `AGGREGATE` handlers (publication, child-acceptance,
final-accept + probe + land, remediation, roadmap completion) stay six distinct
functions resolved by phase. Kind-driven dispatch removes *opacity* (typed `kind`
branch, pure-data stages), not *handler count* — these side effects are
irreducibly heterogeneous and a phase-keyed registry would be the same indirection
in a new shape.

## Consequences

- `dispatch_parent_stage` keeps a single call-time lazy import per kind to break
  the `runtime` → `workflow_engine` cycle (engine→runtime stays `TYPE_CHECKING`-only).
  We chose this over full constructor dependency injection, which would eliminate
  the lazy import but churn every `WorkflowEngine` build site plus the registry and
  tests for marginal gain — `PARENT_DEFINITION` stays constructed in the engine.
- Adding a parent role attempt = a `role_contract` + a transition entry + (if any)
  a `post_success` / `on_failure` hook. No new wrapper function.
- Pure refactor: every existing parent / child / roadmap test passes with
  assertions unchanged. The behaviour, including the atomic graph write and the
  fix-cycle escalation, is byte-for-byte preserved.
