# SMDA Known Gaps

Status: living checklist
Date: 2026-06-15

This file records the real gap between "code + unit tests complete" and
"validated working product". The 51-task slice plan
(`docs/superpowers/plans/2026-06-15-smda-product-slices.md`) is fully checked
off and the gate is green (150 Python tests, 9 TypeScript tests, `tsc --noEmit`
clean), but every slice's `Note:` deferred the live-integration axis. These are
the deferred items, grouped by what blocks them.

## Verified complete

- Tier-1 parent state machine end to end: intake -> graph decompose -> graph
  spec review -> graph execution review -> child publish -> child SDD loop ->
  child accept -> parent QA -> remediation -> final accept.
- Child SDD loop with fixer loopback.
- Sandcastle TypeScript runner: `Output.object` structured output, status
  mapping (`succeeded` / `structured_output_failed` / `execution_failed`),
  product-owned schema registry in `roleContracts.ts`.
- Durable SQLite ledgers: phase, attempt, tracker-effect outbox, parent-accept,
  graph, child-issue projection; idempotency keys; crash-recovery primitive
  plus git cherry-pick integration adapter.
- Full QA policy matrix enforced from durable evidence: total remediation
  children (graph truth), repeated feedback (report fingerprint), parent QA
  cycles (attempt ledger).
- Config-driven workspace tick factory and `daemon` CLI wiring.
- Setup skill refreshed to Tier-3 config-only boundary (external plugin repo).

## Gaps blocking "production-done"

### 1. No live Sandcastle smoke test (HIGH)

All 9 TS tests inject fake Sandcastle dependencies. `@ai-hero/sandcastle@0.8.0`
is a real dependency and is imported by `runRoleAttempt.ts`, but the execution
path has never run against a real agent runtime end to end. Spec asks for "a
small smoke suite [that] should exercise the real Sandcastle adapter" — absent.

- Blocked by: real agent runtime + API credentials; a `noSandbox` worktree run.
- Exit criterion: one role attempt dispatched through the real runner produces
  a typed result and a worktree/branch/commit.

### 2. No live Linear smoke test (HIGH)

`LinearBacklogAdapter` is unit-tested with an injected GraphQL transport only.
Real endpoint, personal API key auth, and team/workspace/state-id resolution
have never been exercised. `build_linear_backlog_adapter` reads
`LINEAR_API_KEY`, `SMDA_LINEAR_TEAM_ID`, `SMDA_LINEAR_STATE_<NAME>` but no run
has confirmed those env values resolve against a live workspace.

- Blocked by: live Linear API key + a scratch team/project.
- Exit criterion: scan candidates, create a child issue, set state, post a
  comment against a real Linear workspace.

### 3. Daemon live mode never run (HIGH)

`smda-scheduler daemon <config> --repo-root <repo>` composes a live tick from
Linear + Sandcastle defaults via `runtime_factory.build_configured_workspace_tick`,
but live mode has only been exercised through injected ticks in tests. No
end-to-end daemon pass against a real repo + tracker + agent.

- Blocked by: gaps 1 and 2.

### 4. Config schema missing live-operation fields (MEDIUM)

Task 49 note: scan state/label, agent model, and integration branch are CLI
flags (`--state`, `--label`, `--owner`), not config schema fields. Packaging
has not decided credential and process-launch policy. A consumer cannot fully
declare daemon operation from `smda.config.json` alone.

### 5. Consumer migration unproven (MEDIUM)

Spec success criterion: trading-advisor replaces its hand-rolled
`symphony/smda_*` runtime with this product. Product packaging exists; the
consumer-side migration has not been validated here. Onboarding-without-
hand-writing-runtime-code is therefore not yet demonstrated. (Tracking
separately against the trading-advisor repo.)

## By design — not gaps

- Parent main-branch merge/squash/push is a v1 non-goal. Final accept records
  idempotent tracker effects only; `accept-parent --strategy ...` is a future
  separate operator CLI, never a daemon side effect.
- Python `role_contracts.py` is a small duplicated dispatch-metadata registry;
  role output validation stays TypeScript/Sandcastle-owned. Spec explicitly
  permits this for the MVP.
