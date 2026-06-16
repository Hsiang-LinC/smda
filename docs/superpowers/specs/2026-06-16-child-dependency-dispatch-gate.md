---
status: approved
created_at: 2026-06-16
owner: human
approved_at: 2026-06-16
approved_by: human
approval_evidence: conversation approval "ok, approved"
---

# Child Dependency Dispatch Gate

## Problem

SMDA can publish child issues with dependency edges and backlog blocking
relations, but the live child dispatch path can still dispatch a downstream
child too early.

The failure mode is:

1. A parent graph creates `child-001 -> child-002` with `blocks_dispatch: true`
   and `required_artifacts: ["accepted_commit"]`.
2. `run_parent_child_publication_tick` projects that edge as a backlog blocking
   relation.
3. The backlog scanner later returns `child-002` while `child-001` is not yet
   accepted into the parent integration branch.
4. `run_workspace_tick` currently routes the first scanned candidate without a
   dependency eligibility check.
5. `run_child_candidate_tick` hydrates `child-002` from the issue body, but then
   invokes the scheduler with a single-node graph for `child-002`, so the
   persisted parent graph dependency is not a hard dispatch gate.

The result violates the intended invariant: downstream work may start without
the latest upstream accepted commit/ref integrated into the parent integration
branch.

## Current Baseline

Already implemented in the current clean tree:

- Graph review failures route through a bounded `GRAPH_FIXING` loop before human
  review.
- Child lifecycle tracker effects are recorded from `run_child_candidate_tick`.
- Stale child handles are rejected when the issue body's graph checksum does not
  match the persisted parent graph checksum.
- Parent acceptance can apply a quality-passed child candidate to the parent
  integration branch and records idempotent accept operations.

This spec focuses on the remaining dependency-dispatch safety gap.

## Goal

For a child issue to dispatch automatically, SMDA must prove every blocking
upstream dependency is satisfied from SMDA-owned state before it invokes the
role execution adapter.

A blocking dependency is satisfied only when:

1. The upstream node exists in the current persisted parent graph.
2. The upstream child scheduler phase is `QUALITY_REVIEW_PASSED`.
3. The upstream child has a latest quality-review candidate ref (`branch` or
   commit SHA) recorded in the attempt ledger.
4. The parent accept ledger has a `completed` operation for that parent,
   upstream child, and candidate ref.
5. For the git integration adapter, recovery can confirm the parent integration
   branch contains that ref, or the existing completed accept operation was
   recorded by the same recovery path.

Only after those checks pass may a downstream child dispatch.

## Non-Goals

- Do not auto-merge, squash, rebase, or push the consumer repository main
  branch.
- Do not auto-resolve merge conflicts. If parent acceptance cannot apply an
  upstream candidate, it remains a blocked parent acceptance problem.
- Do not treat backlog blocking relations as the source of truth. They are a UI
  and tracker projection.
- Do not require all non-blocking dependency edges to be accepted before
  dispatch; only edges with `blocks_dispatch: true` gate execution.
- Do not redesign parent QA or final accept.

## Source Of Truth

SMDA dispatch eligibility must use these sources in this order:

1. Persisted parent graph in `PhaseLedger`
2. Child scheduler state in `PhaseLedger.load_scheduler_state()`
3. Child role attempt results for latest candidate refs
4. Parent accept ledger for completed integration accepts
5. Backlog blocking relations only as an optional secondary safety signal

Backlog issue body fields (`Dependency reasons`, `Required artifacts`) are
prompt context, not eligibility truth.

## Required Behavior

### 1. Child Candidate Hydration

`run_child_candidate_tick` must remain the child route boundary between backlog
issues and scheduler execution, but it must stop being a shallow single-node
adapter.

It must:

- Validate route kind, parent issue, node id, and graph checksum.
- Load the current persisted parent graph.
- Verify the child node exists in that graph.
- Hydrate the target child's task context from the issue body.
- Evaluate the target child against graph-derived dependency eligibility before
  dispatching.
- Only invoke `run_child_workflow_tick` when the target child is eligible.

It may still call `run_child_workflow_tick` with only the target child after the
eligibility check, as long as the dependency gate has already been enforced from
the persisted parent graph and ledger state.

### 2. Dependency Eligibility

Add a single policy function for child dependency readiness. It should be pure
or nearly pure, with tests around edge cases.

Suggested shape:

```python
def child_dependency_gate(
    *,
    parent_id: str,
    child_id: str,
    graph: dict,
    scheduler_state: SchedulerState,
    attempts: list[dict],
    parent_accept_operations: list[dict],
) -> ChildDependencyGateResult:
    ...
```

The result should include:

- `eligible: bool`
- `blocked_by: tuple[str, ...]`
- `missing_artifacts: tuple[str, ...]`
- `reason: str`

The gate must inspect incoming dependency edges for the target child. For each
edge where `blocks_dispatch` is true:

- If the upstream child is not `QUALITY_REVIEW_PASSED`, block.
- If no candidate ref exists, block.
- If the accept ledger has no completed operation for the candidate ref, block.

If a dependency edge requests `accepted_commit`, either a branch ref or a commit
SHA is acceptable as the candidate ref, provided parent acceptance completed for
that exact ref.

### 3. Workspace Scan Must Not Starve On A Blocked Candidate

`run_workspace_tick` must not stop forever on the first scanned child when that
child is dependency-blocked.

The workspace tick should iterate through the scanned page until it either:

- dispatches one eligible candidate,
- records a real routing block,
- or exhausts the page and returns idle/skipped detail.

Normal dependency waiting is not a hard routing block. It should not move the
issue to a manual `Blocked` state by default, because it must become eligible
automatically when upstream accepts complete.

The scheduler may record an idempotent tracker comment such as:

```text
SMDA is waiting to dispatch <child> until dependencies are accepted:
- child-001: waiting for accepted_commit
```

The comment must be deduped by parent id, child id, graph checksum, and blocked
dependency set.

### 4. Tracker Projection

When parent acceptance completes for a child:

- Record the existing parent accept operation as today.
- Record a durable child tracker lifecycle effect that makes the child issue
  visibly complete, preferably state `Done`, with a comment containing the
  accepted candidate ref and parent integration branch.

This tracker projection is not the dispatch source of truth, but it keeps Linear
or GitHub issue relations understandable and may allow tracker-native unblock UI
to reflect reality.

### 5. Optional Backlog Blocking Safety

If a backlog adapter supports `query_blocked_by`, the workspace tick may use it
as an additional safety rail:

- If SMDA ledger says eligible but tracker still reports blockers, the scheduler
  should not blindly trust the tracker relation as canonical.
- It may record a reconciliation warning, but the SMDA graph/ledger decision
  remains authoritative.

The core fix must pass with an adapter that has no blocking relation capability.

## Error Handling

### Stale Or Missing Graph

If the child handle references a parent/graph that cannot be found, or a node id
not present in the persisted graph, do not dispatch. Record a durable tracker
comment and route to Human Review or Blocked according to the existing routing
block policy.

### Missing Candidate Ref

If an upstream child is `QUALITY_REVIEW_PASSED` but has no branch/commit in the
latest quality-review attempt, do not dispatch downstream. This is a workflow
invariant failure and should route the upstream/parent context to Human Review
with the missing evidence named.

### Parent Accept Failure

If parent acceptance fails due to merge conflict or git error, downstream
children remain in dependency-wait. The parent acceptance tick already returns
Blocked with the operation id/action; do not dispatch downstream until recovery
marks the accept completed.

## Acceptance Criteria

- A downstream child is not dispatched before every blocking upstream child is
  accepted into the parent integration branch.
- A downstream child is dispatched after all blocking upstream accept operations
  are completed.
- If the backlog scanner returns a blocked downstream child before an eligible
  upstream child, the tick skips the downstream child and dispatches the
  upstream child.
- Stale graph checksum and unknown node id remain hard stops.
- The implementation works without relying on Linear/GitHub blocking relation
  queries.
- Parent main-branch merge remains outside daemon behavior.
- Merge conflicts in parent acceptance block/retry recovery; they do not trigger
  downstream dispatch.

## Required Tests

### Unit Tests

- `child_dependency_gate` blocks when upstream child has no scheduler state.
- `child_dependency_gate` blocks when upstream child is not
  `QUALITY_REVIEW_PASSED`.
- `child_dependency_gate` blocks when upstream passed but no candidate ref is
  recorded.
- `child_dependency_gate` blocks when candidate ref exists but parent accept is
  not completed.
- `child_dependency_gate` allows dispatch when upstream passed and parent accept
  completed for the same candidate ref.
- Non-blocking edges do not block dispatch.

### Runtime Tests

- `run_child_candidate_tick` loads the persisted parent graph and blocks a child
  whose graph dependency is not accepted.
- `run_child_candidate_tick` dispatches the child after the upstream accept
  operation is completed.
- `run_child_candidate_tick` rejects an issue whose node id is not present in
  the current parent graph.
- `run_child_candidate_tick` preserves existing stale checksum rejection.

### Workspace Tick Tests

- When the scanned page returns `[downstream_blocked, upstream_ready]`, the tick
  skips the blocked downstream child and dispatches the upstream child.
- When all scanned child candidates are dependency-waiting, the tick returns a
  non-error idle/skipped result and records only idempotent wait comments.
- A routing-block issue still records Blocked effects as before.

### Parent Acceptance Tests

- Completing parent acceptance records a child tracker effect that includes the
  candidate ref and integration branch.
- Downstream gate uses parent accept operation completion, not child tracker
  state, as eligibility proof.

## Implementation Notes

- Prefer adding a small typed result for child candidate dispatch instead of
  raising `GraphError` for normal dependency waiting.
- Keep graph hydration and dependency gating close to `run_child_candidate_tick`;
  do not move SMDA workflow truth into `linear_backlog.py`.
- Keep role prompt dependency context, but treat it as descriptive context only.
- Avoid mutating child issue state to `Blocked` for ordinary dependency waiting,
  because that can prevent automatic eligibility after upstream completion.

## Done Definition

- The tests above pass.
- Existing scheduler/runtime tests continue to pass.
- `docs/product-spec.md` or `docs/known-gaps.md` is updated if the implemented
  behavior changes or closes an existing known gap.
- No daemon path can dispatch a child whose blocking dependency has not been
  accepted into the parent integration branch.
