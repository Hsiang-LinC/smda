<!-- codex-harness: generated 2026-06-17 -->
# Completed Work

Archive — newest first. Entry format: see `docs/harness/index.md` § Conventions.

## local-ledger-backlog-contract
- done: 2026-06-27
- summary: defined `local-ledger` as a product backlog adapter that maps a
  target repo's harness ledger to `BacklogIssue` without replacing the harness
  or using SMDA's runtime ledger as work-item truth.
- verified: user reviewed on 2026-06-27; commit `d2c924c`; `git diff --check`
  -> passed; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py -q` -> 12 passed.
- follow-ups: `docs/work-ledger/active.md` § `local-ledger-backlog-adapter`

## mcp-operator-interface
- done: 2026-06-27
- summary: exposed the product-owned stdio MCP operator surface for read-only
  status and operator controls, and bundled the MCP server registration in the
  SMDA plugin without exposing daemon lifecycle control through MCP.
- verified: user reviewed on 2026-06-27; prior evidence in active ledger:
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_mcp.py
  -q` -> 13 passed; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q` -> 352 passed, 1 skipped; `git diff --check`
  -> passed.
- follow-ups: none

## plugin-execution-runner-bundle
- done: 2026-06-25
- summary: bundled the Sandcastle execution runner into the SMDA plugin as a
  release-built plugin-local JavaScript artifact. The scheduler now prefers the
  plugin-local runner for daemon role attempts and falls back to the product
  source runner during local product development.
- verified: commit `e003603`; `npm run plugin:sync-runtime` -> passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py
  packages/scheduler/tests/test_cli.py::test_resolve_sandcastle_runner_prefers_plugin_bundled_runner
  packages/scheduler/tests/test_cli.py::test_resolve_sandcastle_runner_falls_back_to_product_source
  packages/scheduler/tests/test_sandcastle_execution.py -q` -> 23 passed;
  `npm run test:ts` -> 14 passed, 1 skipped; `git diff --check` -> passed.
- follow-ups: none

## plugin-runtime-bundle-contract
- done: 2026-06-25
- summary: bundled the SMDA scheduler Python runtime into the plugin and changed
  the plugin MCP registration to launch the runtime from the plugin root instead
  of requiring `smda-scheduler` on PATH. Setup docs now distinguish Codex
  `apps` connectors from plugin-local runtime/MCP packaging.
- verified: commit `4a63e06`; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run
  pytest packages/scheduler/tests/test_packaging.py -q` -> 10 passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_mcp.py
  -q` -> 15 passed; `git diff --check` -> passed.
- follow-ups: none

## route-lifecycle-boundary-doc
- done: 2026-06-23
- summary: documented that Route means runtime lifecycle shape rather than
  work-content category. Debugging, test-writing, short tasks, and
  proof-of-concept work should fit existing route contracts, mode tags,
  methodology, or prompt context unless lifecycle semantics differ.
- verified: commit `ed6b660`; `git diff --check`.
- follow-ups: none

## route-dispatch-selection
- done: 2026-06-23
- summary: centralized configured route dispatch in `route_dispatch.py`.
  Child/task routes now select workflow definitions through
  `workflow_registry.definition_for_mode`; parent/roadmap routes keep explicit
  ADR-0006 effect handlers; `runtime_factory.py` only assembles configured
  dependencies.
- verified: commit `5d76f5e`; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run
  pytest packages/scheduler/tests/test_runtime_factory.py
  packages/scheduler/tests/test_workflow_registry.py -q` -> 15 passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q` -> 360 passed, 1 skipped; `git diff --check`.
- follow-ups: none

## structured-child-context
- done: 2026-06-23
- summary: routed child dispatch now builds `ChildTaskContext` from persisted
  graph children and dependency edges instead of reparsing child issue markdown;
  task-mode dispatch keeps the legacy issue-body fallback because it has no
  parent graph.
- verified: commit `68f33a5`; targeted graph-context test -> 1 passed;
  runtime/factory/workspace dispatch tests -> 94 passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q` -> 360 passed, 1 skipped; `git diff --check`.
- follow-ups: none

## roadmap-publication-ordering
- done: 2026-06-23
- summary: extracted roadmap publication into one ordered effect. Roadmap
  member creation now owns held state, projections, ledger edges, tracker
  blocking links, release-to-`Todo`, and idempotent re-entry from
  `roadmap_publication.py`; `runtime.py` keeps only the phase gate and
  compatibility wrapper.
- verified: commit `90337dd`; targeted roadmap publication/workspace dispatch
  tests -> 4 passed; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q` -> 360 passed, 1 skipped; `git diff --check`.
- follow-ups: none

## harness-refresh-deepening-upgrade
- done: 2026-06-23
- summary: refreshed the repo harness, added `docs/harness/quality-gates.md`,
  updated current skill routing, recorded the architecture-review deepening
  upgrade in `docs/harness/roadmap.md`, and created ordered active ledger slices
  under `parent: architecture-review-deepening-upgrade`.
- verified: `git diff --check` -> passed; path existence checks for
  `docs/harness/index.md`, `docs/harness/tracker.md`,
  `docs/harness/roadmap.md`, `docs/harness/quality-gates.md`,
  `docs/work-ledger/active.md`, `docs/work-ledger/completed.md`, and
  `docs/work-ledger/abandoned.md` -> passed; harness block count -> one block
  in `AGENTS.md`; stale skill-name scan -> no `mattpocock-skills` references
  remain; human reviewed on 2026-06-23.
- follow-ups: active slices under `docs/work-ledger/active.md` §
  `parent-integration-conflict-recovery`, `roadmap-publication-ordering`,
  `structured-child-context`, and `route-dispatch-selection`.

## force-phase-operator-command
- done: 2026-06-23
- summary: added `smda-scheduler force-phase` so operators can move an existing
  parent or child runtime record to an explicit valid phase without editing the
  sqlite ledger by hand. Child force clears stale claim/backoff fields; tracker
  approvals remain outside the command by design.
- verified: `uv run pytest packages/scheduler/tests/test_cli.py -q` -> 17
  passed; `uv run pytest packages/scheduler/tests -q` -> 345 passed, 1 skipped.
- follow-ups: none

## parent-scoped-child-runtime-ids
- done: 2026-06-22
- summary: fixed the scheduler's child-runtime identity collision by scoping
  generated parent graph child node ids to the parent id before graph
  persistence, child issue publication, dependency edge generation, and
  remediation child publication. This prevents two parents that both generate
  `child-001` from sharing `child_run_state`, attempt history, or acceptance
  state.
- verified: `uv run pytest packages/scheduler/tests/test_runtime.py
  packages/scheduler/tests/test_workspace_tick.py -q` -> 80 passed;
  `uv run pytest packages/scheduler/tests -q` -> 340 passed, 1 skipped;
  `npm run test:ts` -> 14 passed, 1 skipped; `npm run typecheck` -> passed;
  `npm run schema:export` -> passed.
- follow-ups: repair or reissue any already-published consumer child issues
  whose persisted graph still uses unscoped node ids before resuming that
  parent.

## harness-first-smda-routing-follow-up
- done: 2026-06-21
- summary: aligned the SMDA automation plugin with the harness-first
  Engineering routing spec by removing the duplicate
  `setup-codex-development-harness` skill, making `setup-smda-automation`
  require the Engineering harness or equivalent, documenting SMDA execution
  routes and AFK/HITL mapping, and keeping runtime contracts product-owned.
- verified: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py -q` -> 6 passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest -q` -> 339 passed,
  1 skipped; `npm run test:ts` -> 14 passed, 1 skipped; `npm run typecheck`
  -> passed; `npm run schema:export` -> wrote current schema with no diff;
  human reviewed on 2026-06-21.
- follow-ups: none

## record-parent-integration-conflict-gap
- done: 2026-06-19
- summary: recorded the DANNY-70 child-006 parent acceptance conflict as an SMDA
  product known gap, and added a follow-up for branch/range integration plus an
  optional bounded parent-integration conflict resolver phase.
- verified: documentation diff review; `git diff --check` before commit.
- follow-ups: promoted on 2026-06-23 to `docs/work-ledger/active.md` §
  `parent-integration-conflict-recovery`

## setup-skill-projection-status-guidance
- done: 2026-06-19
- summary: documented the SMDA runtime-ledger vs Linear tracker-projection
  boundary in product contracts/specs and `setup-smda-automation` guidance, so
  future consumer repo agents know to use `smda-scheduler status`
  `tracker_effects` and daemon controller status before judging tracker sync.
- verified: `UV_CACHE_DIR=/private/tmp/uv-cache-smda uv run --project
  packages/scheduler pytest
  packages/scheduler/tests/test_cli.py::test_status_cli_returns_ledger_summary
  -q` -> 1 passed; `UV_CACHE_DIR=/private/tmp/uv-cache-smda uv run --project
  packages/scheduler pytest packages/scheduler/tests/test_cli.py -q` -> 14
  passed; `git diff --check` -> passed; active plugin cache copy refreshed;
  human reviewed on 2026-06-19.
- follow-ups: none

## danny-70-candidate-commit-publication
- done: 2026-06-19
- summary: fixed live child candidate publication so successful dirty SandCastle
  branch worktrees become SMDA-owned commits, and child implementation/review/fix
  phases share a stable `smda/<parent>/<child>/candidate` branch. This removed
  the DANNY-70 failure mode where spec review ran on a base branch and reported
  missing files even though the implementer/fixer had produced the patch.
- verified: red TypeScript regression first, then `npm run test:ts` -> 14
  passed, 1 skipped; `npm run typecheck` -> passed; `uv run pytest
  packages/scheduler/tests/test_role_attempts.py
  packages/scheduler/tests/test_child_dependency_gate.py
  packages/scheduler/tests/test_runtime_factory.py
  packages/scheduler/tests/test_runtime.py -q` -> 94 passed. Live DANNY-70
  evidence: `child-001-FIXING_SPEC-6` produced commit
  `1b4f742b41346b0d90426742e1d0943e5e32a462` on
  `smda/danny-70/child-001/candidate`; `child-001-SPEC_REVIEWING-9` reviewed the
  candidate branch and `child-001-QUALITY_REVIEWING-10` advanced child-001 to
  `QUALITY_REVIEW_PASSED`.
- follow-ups: continue DANNY-70 from child-001 candidate acceptance, then
  dispatch the remaining child issues.

## danny-70-child-implementer-result-contract
- done: 2026-06-19
- summary: tightened the child implementer prompt so workers return the child
  role payload (`verdict`, `required_next_action`, `report`) instead of a
  hand-authored scheduler envelope. This keeps the runner/adapter responsible
  for the Attempt Result Artifact envelope.
- verified: `UV_CACHE_DIR=/private/tmp/uv-cache-smda uv run pytest
  packages/scheduler/tests/test_role_contracts.py
  packages/scheduler/tests/test_runtime_factory.py -q` -> 16 passed. Live
  DANNY-70 evidence: `child-001-IMPLEMENTING-2` emitted
  `smda.child-implementer-result.v1` successfully and advanced to
  `SPEC_REVIEWING`.
- follow-ups: none

## danny-70-runtime-defects-remediation-plan
- done: 2026-06-19
- summary: completed the DANNY-70 runtime-defect remediation plan and live
  retry. The original graph decomposition issue was not replayed; the retry
  resumed from the published-child state and validated the patched SMDA workflow
  through child dispatch, structured role output, retry backoff, candidate
  publication, spec review, fix loop, and progression to quality review.
- verified: review
  `docs/superpowers/plans/2026-06-19-danny-70-runtime-defects-remediation.md`;
  focused Python and TypeScript tests listed in the linked completed items; live
  consumer repo status after the retry shows DANNY-70 parent
  `CHILDREN_PUBLISHED` and child-001 `QUALITY_REVIEW_PASSED` with no active
  claim.
- follow-ups: DANNY-70 is not complete yet; accept child-001's candidate, then
  dispatch remaining child issues DANNY-74 through DANNY-78.

## dependency-wait-does-not-consume-dispatch-capacity
- done: 2026-06-19
- summary: fixed workspace tick batching so dependency-wait/skipped candidates
  do not consume `max_parallel` dispatch capacity. The tick now keeps filling
  capacity after skipped results until real dispatch capacity is consumed or no
  candidates remain, preserving bounded parallelism for actual work.
- verified: red regression first, then `uv run pytest
  packages/scheduler/tests/test_workspace_tick.py::test_workspace_tick_skipped_dependencies_do_not_exhaust_max_parallel
  -q` -> passed; `uv run pytest packages/scheduler/tests/test_workspace_tick.py
  -q` -> 16 passed; `uv run pytest packages/scheduler/tests -q` -> 333
  passed, 1 skipped; `npm run test:ts` -> 13 passed, 1 skipped; `npm run
  typecheck` -> passed; `npm run schema:export` -> passed.
- follow-ups: retry DANNY-70 in the consumer repo.

## parent-child-acceptance-aggregate-wait
- done: 2026-06-19
- summary: moved the missing integration guard out of the parent phase gate and
  into child acceptance only when a quality-passed child is ready to apply. A
  parent in `CHILDREN_PUBLISHED` now waits idempotently for children before
  requiring integration configuration.
- verified: red regression first, then `uv run pytest
  packages/scheduler/tests/test_runtime.py::test_parent_workflow_waits_for_children_before_requiring_integration
  -q` -> passed; `uv run pytest packages/scheduler/tests/test_runtime.py -q` ->
  63 passed; `uv run pytest packages/scheduler/tests -q` -> 332 passed, 1
  skipped; `npm run test:ts` -> 13 passed, 1 skipped; `npm run typecheck` ->
  passed; `npm run schema:export` -> passed.
- follow-ups: retry DANNY-70 in the consumer repo.

## sandcastle-ipc-noisy-streams
- done: 2026-06-19
- summary: resolved the DANNY-70 noisy stdout/stderr IPC failure by replacing
  production stream parsing with ADR-0007 Attempt Result Artifact handling. The
  earlier compatibility patch made stream parsing more robust, but the accepted
  fix removes stdout/stderr from the workflow-control path entirely while keeping
  process logs as diagnostic evidence.
- verified: superseded by `sandcastle-result-file-migration` verification.
- follow-ups: none

## sandcastle-result-file-migration
- done: 2026-06-19
- summary: migrated the Sandcastle execution adapter from stdout/stderr JSON IPC
  to the ADR-0007 Attempt Result Artifact contract. The TypeScript runner now
  requires `--result-file` and writes the result artifact atomically; the Python
  adapter creates per-attempt artifact paths, passes them to the runner, and
  reads only the artifact for workflow control. stdout/stderr are retained as
  process-log evidence for missing/invalid artifact errors.
- verified: red tests first, then `npx tsx --test
  packages/sandcastle-runner/tests/cli.test.ts` -> 4 passed; `uv run pytest
  packages/scheduler/tests/test_sandcastle_execution.py -q` -> 9 passed;
  `npm run test:ts` -> 13 passed, 1 skipped; `npm run typecheck` -> passed;
  `uv run pytest packages/scheduler/tests -q` -> 331 passed, 1 skipped;
  `npm run schema:export` -> passed.
- follow-ups: DANNY-70 workflow conformance fixes in `active.md`
  (`parent-child-acceptance-aggregate-wait`,
  `dependency-wait-does-not-consume-dispatch-capacity`).

## attempt-result-artifact-contract
- done: 2026-06-19
- summary: captured the execution adapter machine-result boundary in
  `docs/CONTEXT.md`, `docs/adr/0007-attempt-result-artifact.md`, and
  `docs/contracts.md`. Canonical terms are Attempt Result Artifact and Process
  Logs; the scheduler advances workflow state from durable artifacts, not
  stdout/stderr process streams.
- verified: documentation review and accepted in the 2026-06-19 grill-with-docs
  session; implementation verification recorded in
  `sandcastle-result-file-migration`.
- follow-ups: none

## linear-scope-id-ignored
- done: 2026-06-17
- summary: scoped the Linear backlog adapter to an optional project. Added
  `project_id` to `LinearBacklogAdapter` (applied as a `project` filter in
  `list_issues` and a `projectId` stamp on `create_child`), read from env
  `SMDA_LINEAR_PROJECT_ID` in `build_linear_backlog_adapter`, with a warning when
  config `scope_id` is declared but the project env id is absent. Lets multiple
  SMDA repos share one Linear team without cross-dispatching. Spec + plan:
  `docs/superpowers/specs/2026-06-17-linear-project-scope-isolation.md`,
  `docs/superpowers/plans/2026-06-17-linear-project-scope-isolation.md`.
- verified: `uv run --project . pytest packages/scheduler/tests -q` → 316 passed,
  1 skipped (on branch `feat/linear-project-scope`, pending merge).
- follow-ups: setup-skill env contract updated (daemon-operations.md, adapters.md).

## parent-integration-conflict-recovery
- done: 2026-06-23
- summary: implemented the parent accept conflict resolver slice. Child accept
  now preserves ancestry with `git merge --no-edit` fallback, records structured
  conflict paths/fingerprints on `parent_accept_ledger`, routes unresolved
  conflicts through `CHILD_ACCEPT_CONFLICT_RESOLVING`, retries deterministic
  `CHILDREN_PUBLISHED` acceptance on `DONE/retry_child_acceptance`, and
  escalates repeated same-fingerprint conflicts to `HUMAN_REVIEW_REQUIRED`.
- verified: commit `2767275`; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run
  pytest packages/scheduler/tests -q` -> 360 passed, 1 skipped; `npm run
  test:ts` -> 14 passed, 1 skipped; `npm run typecheck`; `git diff --check`.
- follow-ups: none

## setup-codex-development-harness-plugin
- done: 2026-06-17
- summary: added the `setup-codex-development-harness` skill to the
  `smda-automation` plugin (tracker/roadmap/ledger/index/bootloader substrate).
- verified: backfilled from git history (9311527)
- follow-ups: none

## host-setup-smda-automation-plugin
- done: 2026-06-17
- summary: hosted `setup-smda-automation` as a repo-local plugin (Claude +
  Codex marketplace).
- verified: backfilled from git history (388a6f8)
- follow-ups: none

## target-c-modular-parallel-engine
- done: 2026-06-17
- summary: merged target-C — modular parallel SMDA engine (Phases 0–5 + 1d):
  one engine + definition registry, zod-canonical schema single-source,
  methodology-skill injection, parent/roadmap tier + dependency gate, parent
  landing + cross-parent conflict repair, modes as definitions, kind-driven
  parent dispatch.
- verified: backfilled from git history (daf3ec1); recorded green at merge
  (150 Python + 9 TypeScript tests, `tsc --noEmit` clean)
- follow-ups: live-integration gaps — see `active.md`

## smda-product-slices
- done: 2026-06-16
- summary: 51-task product slice plan completed — Tier-1 parent state machine
  end to end, child SDD loop, durable SQLite ledgers, QA policy matrix,
  config-driven workspace tick + daemon CLI.
- verified: backfilled from git history (b879de7)
- follow-ups: live-integration gaps — see `active.md`

## child-dependency-dispatch-gate
- done: 2026-06-16
- summary: child dependency dispatch gate — live child dispatch validates
  persisted parent-graph dependencies, quality candidate refs, and completed
  accepts before role execution; dependency-waiting children skipped in scans.
- verified: backfilled from git history (bb6d3ce)
- follow-ups: none

## component-inventory-and-boot-contract
- done: 2026-06-15
- summary: component inventory + pruning list and the three-tier model + boot
  contract documented.
- verified: backfilled from git history (1b80748, 86d65de)
- follow-ups: none

## consumer-migration-product-only
- done: 2026-06-15
- summary: dropped the dual-track fallback; consumer (trading-advisor) migrated
  to product-only — `smda.config.json` points at the product, repo-local
  `symphony/` package and prototypes deleted, harness docs flipped to
  product-only.
- verified: cross-repo `validate-config` / `validate-context` exit 0 with no
  live creds; `pytest` 247 passed / 4 skipped, `tests/harness` 15 passed,
  `uv build` clean (see `docs/known-gaps.md` § 5)
- follow-ups: dual-track path abandoned — see `abandoned.md`

## project-started
- done: 2026-06-15
- summary: project started
- verified: backfilled from git history (first commit "Add SMDA scheduler product spec")
- follow-ups: none
