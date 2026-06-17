<!-- codex-harness: generated 2026-06-17 -->
# Completed Work

Archive — newest first. Entry format: see `docs/harness/index.md` § Conventions.

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
