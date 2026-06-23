<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## parent-integration-conflict-recovery
- status: in-progress
- parent: architecture-review-deepening-upgrade
- source: 2026-06-23 architecture review `#parent-integration-resolver`;
  promoted from `docs/work-ledger/follow-ups.md` after the review made this the
  first deepening slice; design decision recorded in
  `docs/adr/0008-child-accept-conflicts-use-dedicated-resolver.md`.
- blocked-by: none
- acceptance: child accept, ancestry repair, merge strategy, conflict routing,
  and recovery evidence are handled behind one parent-integration resolver
  module; existing parent acceptance and conflict-recovery behavior is covered
  by targeted regression tests.
- verify: targeted scheduler tests for parent acceptance / git integration;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q`;
  `git diff --check`.
- next: resolve whether this slice is deterministic integration recovery only,
  or also includes an agent conflict-resolver phase. Decision: deepen the
  existing parent integration seam; deterministic recovery returns structured
  outcomes, unresolved conflicts route toward a dedicated conflict resolver
  path rather than generic Agent Review. The resolver's goal is to make the
  `CHILDREN_PUBLISHED` child acceptance pass for the conflicted child, then
  return through the deterministic accept path; retries must be bounded so the
  same unresolved conflict cannot loop indefinitely. Decision: bound resolver
  retries by a conflict fingerprint (`parent_id`, `child_id`, `candidate_ref`,
  conflicted paths, and last-error hash) plus a small attempt cap; repeated
  unresolved conflicts escalate to `HUMAN_REVIEW_REQUIRED`. Decision: the
  resolver may change only the parent integration branch, only conflict-scoped
  files, and only enough to make deterministic child acceptance pass; it must
  not edit the child candidate branch, change the parent spec, mutate graph
  structure, mark accept operations completed, or create new children. ADR:
  `docs/adr/0008-child-accept-conflicts-use-dedicated-resolver.md`. Decision:
  implement the resolver as a Parent `RoleAttempt` Stage, not as an agent call
  hidden inside an Effect handler. Decision: resolver control flow is binary:
  `DONE` with `retry_child_acceptance`, or `BLOCKED` with
  `request_human_review`; residual concerns are report text, not a
  `DONE_WITH_CONCERNS` retry path. Decision: name the Parent phase
  `CHILD_ACCEPT_CONFLICT_RESOLVING`. Decision: cap resolver retries at 2 per
  conflict fingerprint. Decision: reuse `smda.review-result.v1` and add
  `retry_child_acceptance` rather than introducing a resolver-only schema.
  Decision: persist fingerprint/count with `parent_accept_ledger`, and surface
  conflict history from `parent_accept_ledger` plus `attempt_ledger` in resolver
  requests and human-review escalation so retry agents and reviewers can see the
  operation id, fingerprint, attempt count, candidate ref, integration branch,
  conflicted paths, last error, resolver attempt ids, verdicts/actions, and
  report summaries. Decision: derive report summaries from `attempt_ledger`
  resolver result JSON when building context; do not copy them onto
  `parent_accept_ledger` or store them in `last_error`. Decision: add only
  `conflicted_paths_json`, `conflict_fingerprint`, and `resolver_attempts` to
  `parent_accept_ledger`. Decision: child accept must capture conflicted paths
  as structured git-integration failure data, not by parsing `last_error`.
  Decision: put the resolver report checklist in the resolver Role Contract
  prompt; expected sections are Conflict, Resolution, Verification, and
  Residual risk, with BLOCKED reports using Attempted / why unsafe.
- updated: 2026-06-23

## roadmap-publication-ordering
- status: planned
- parent: architecture-review-deepening-upgrade
- source: 2026-06-23 architecture review `#roadmap-publication`.
- blocked-by: parent-integration-conflict-recovery
- acceptance: Roadmap member publication owns held state, projections, ledger
  edges, tracker blocking, release-to-Todo, and idempotent re-entry through one
  ordered effect; crash-window ordering no longer depends on scattered tick
  call order.
- verify: targeted scheduler tests for roadmap decomposition/publication and
  phase-ledger edges; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q`; `git diff --check`.
- next: extract the publication sequence into a focused Roadmap publication
  module with replay-safe tests before changing additional route logic.
- updated: 2026-06-23

## structured-child-context
- status: planned
- parent: architecture-review-deepening-upgrade
- source: 2026-06-23 architecture review `#structured-child-context`.
- blocked-by: roadmap-publication-ordering
- acceptance: Child task context is built from graph/ledger truth instead of
  reparsing issue markdown; issue body content remains a human adapter
  projection, not machine truth.
- verify: targeted scheduler tests for Child / Task context construction and
  issue projection; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q`; `git diff --check`.
- next: identify the graph/ledger fields needed for ChildTaskContext and replace
  markdown parsing at the execution boundary.
- updated: 2026-06-23

## route-dispatch-selection
- status: planned
- parent: architecture-review-deepening-upgrade
- source: 2026-06-23 architecture review `#route-dispatch`.
- blocked-by: structured-child-context
- acceptance: repeated route selection is centralized behind one dispatch
  module using existing Workflow Definition / registry data; ADR-0006 explicit
  effect handlers remain explicit and no generic effect abstraction is added.
- verify: targeted scheduler tests for route dispatch and workflow registry
  selection; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q`; `git diff --check`.
- next: collapse only the repeated mode-selection branches, stopping before a
  broader effect-abstraction refactor.
- updated: 2026-06-23

## mcp-operator-interface
- status: blocked
- source: 2026-06-17 design discussion; 2026-06-23 user approval after
  `force-phase` CLI completion; 2026-06-23 follow-up to bundle MCP registration
  in the SMDA plugin.
- blocked-by: human acceptance gate
- acceptance: `smda-scheduler mcp` exposes product-owned stdio MCP tools for
  read-only `status` and operator controls `pause`, `resume`,
  `reconcile-claims`, and `force-phase`; the SMDA plugin bundles the MCP server
  registration; it does not expose `daemon`.
- verify: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_mcp.py -q` -> 13 passed; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q` -> 352 passed, 1 skipped; `git diff --check` -> passed.
- next: human review; then move to completed ledger.
- updated: 2026-06-23

## per-parent-integration-branch
- status: blocked
- source: 2026-06-23 trading-advisor DANNY-79 incident; repo-global `runtime.integration_branch` reused DANNY-80 for DANNY-79.
- blocked-by: human acceptance gate
- acceptance: live SMDA parent acceptance derives the integration branch from the parent issue id; single-task routes keep bypassing parent integration; parent accept probe/apply failures record `last_error` instead of silent pending rows.
- verify: `uv run pytest packages/scheduler/tests/test_parent_acceptance.py packages/scheduler/tests/test_runtime.py::test_run_parent_child_acceptance_tick_integrates_quality_passed_children packages/scheduler/tests/test_runtime.py::test_run_parent_final_accept_tick_lands_parent_to_resolved_base packages/scheduler/tests/test_config.py -q` (13 passed); `uv run pytest packages/scheduler/tests -q` (343 passed, 1 skipped).
- next: human review; then move to completed ledger.
- updated: 2026-06-23

## child-runtime-id-owner-gate
- status: blocked
- source: 2026-06-22 interactive incident follow-up for cross-parent child id collision
- blocked-by: none
- acceptance: smda-child intake rejects an unscoped child runtime id when prior attempts show the id belongs to another parent.
- verify: `uv run pytest packages/scheduler/tests/test_runtime.py::test_run_child_candidate_tick_rejects_child_id_owned_by_other_parent -q` -> 1 passed; `uv run pytest packages/scheduler/tests -q` -> 341 passed, 1 skipped.
- next: human acceptance gate; then move to `docs/work-ledger/completed.md`.
- updated: 2026-06-22

## daemon-workspace-lock
- status: blocked
- source: 2026-06-22 interactive incident follow-up for overlapping daemon/tick processes
- blocked-by: none
- acceptance: live `smda-scheduler daemon` refuses to start when another process holds the same workspace lock.
- verify: `uv run pytest packages/scheduler/tests/test_cli.py::test_daemon_cli_refuses_when_workspace_lock_is_held -q` -> 1 passed; `uv run pytest packages/scheduler/tests/test_cli.py -q` -> 15 passed; `uv run pytest packages/scheduler/tests -q` -> 342 passed, 1 skipped.
- next: human acceptance gate; then move to `docs/work-ledger/completed.md`.
- updated: 2026-06-22

## gap-1-live-sandcastle-smoke
- status: blocked
- source: `docs/known-gaps.md` § 1 (No live Sandcastle smoke test)
- blocked-by: none
- acceptance: one role attempt dispatched through the real Sandcastle runner
  produces a typed result and a worktree/branch/commit.
- verify: `SMDA_SMOKE_SANDCASTLE=1 SMDA_SMOKE_CWD="$(pwd)" SMDA_SMOKE_AGENT_PROVIDER=codex SMDA_SMOKE_AGENT_MODEL=gpt-5-codex npm run test:ts` — the smoke test flips from skipped to pass.
- next: obtain agent-provider credentials, then run the smoke harness once.
- updated: 2026-06-17

## gap-2-live-linear-smoke
- status: blocked
- source: `docs/known-gaps.md` § 2 (No live Linear smoke test)
- blocked-by: none
- acceptance: scan candidates, create a child issue, set state, post a comment
  against a real Linear workspace.
- verify: `SMDA_SMOKE_LIVE_LINEAR=1 LINEAR_API_KEY=… SMDA_LINEAR_TEAM_ID=… SMDA_LINEAR_STATE_TODO=… SMDA_SMOKE_LINEAR_PARENT_ID=… uv run pytest packages/scheduler/tests/test_linear_live_smoke.py -q -s` — 1 passed (was 1 skipped). Mutates a scratch workspace.
- next: obtain a live Linear API key + scratch team, then run the harness once.
- updated: 2026-06-17

## gap-3-daemon-live-mode
- status: blocked
- source: `docs/known-gaps.md` § 3 (Daemon live mode never run)
- blocked-by: gap-1-live-sandcastle-smoke, gap-2-live-linear-smoke
- acceptance: one end-to-end daemon pass against a real repo + Linear + agent.
- verify: from a consumer repo with Linear env exported, `docs/harness/smda-daemon.sh start --max-ticks 1` completes a real tick.
- next: complete gaps 1 and 2 first; then run a single live tick.
- updated: 2026-06-17

## gap-4-config-live-fields
- status: active
- source: `docs/known-gaps.md` § 4 (Config schema missing live-operation fields)
  and DANNY-70 `GRAPH_DECOMPOSING-4`, where the hard-coded `gpt-5` default
  was rejected by the local Codex account.
- blocked-by: none
- acceptance: agent provider/model/effort are config-driven and propagated to
  the Sandcastle runner; setup-skill docs make this consumer-facing config
  surface discoverable to target-repo agents; scan state/label are documented as
  daemon-controller policy for the consumer repo; credential and process-launch
  policy remain explicit operator/runtime concerns.
- verify: `uv run pytest -q` -> 330 passed, 1 skipped; `npm run test:ts` ->
  12 passed, 1 skipped; `npm run typecheck` -> passed; `npm run
  schema:export` -> passed; consumer `validate-config` and `validate-context`
  -> passed.
- next: retry DANNY-70 under `gpt-5.5` with `effort=high`; if the model is
  still unsupported, update `adapters.execution.agent` in consumer config
  rather than patching daemon scripts.
- updated: 2026-06-19
