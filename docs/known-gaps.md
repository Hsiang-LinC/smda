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
- Harness: `packages/sandcastle-runner/tests/sandcastle.smoke.test.ts` runs one
  real attempt through default deps; skips unless `SMDA_SMOKE_SANDCASTLE=1` +
  `SMDA_SMOKE_CWD` are set. Awaiting creds to flip from skipped to passing.

### 2. No live Linear smoke test (HIGH)

`LinearBacklogAdapter` is unit-tested with an injected GraphQL transport only.
Real endpoint, personal API key auth, and team/workspace/state-id resolution
have never been exercised. `build_linear_backlog_adapter` reads
`LINEAR_API_KEY`, `SMDA_LINEAR_TEAM_ID`, `SMDA_LINEAR_STATE_<NAME>` but no run
has confirmed those env values resolve against a live workspace.

- Blocked by: live Linear API key + a scratch team/project.
- Exit criterion: scan candidates, create a child issue, set state, post a
  comment against a real Linear workspace.
- Harness: `packages/scheduler/tests/test_linear_live_smoke.py` does
  scan -> create child -> comment -> set state -> hierarchy read; skips unless
  `SMDA_SMOKE_LIVE_LINEAR=1` + `LINEAR_API_KEY` + `SMDA_LINEAR_TEAM_ID` +
  `SMDA_LINEAR_STATE_<NAME>` + `SMDA_SMOKE_LINEAR_PARENT_ID` are set. Mutates a
  real workspace — opt-in only. Awaiting creds to flip from skipped to passing.

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

### 5. Consumer migration: live path done, prototype not pruned (MEDIUM)

Verified against `/Users/danny/Desktop/GitHub/trading-advisor` on 2026-06-15:

- Its migration plan (`docs/superpowers/plans/2026-06-15-smda-product-migration-execution-plan.md`)
  is 51/51 checked off.
- `smda.config.json` points the consumer at the product (`sandcastle` /
  `linear` / `codex-harness`); quality gates and `docs/harness/smda-daemon.sh`
  invoke the external `smda-scheduler` CLI, not repo-local runtime.
- Cross-repo product boot PASSES with no live creds:
  `validate-config` and `validate-context` both return `status: ok`, exit 0.
  Consumer harness gate `tests/harness` passes (15 tests).
- So onboarding-without-hand-writing-runtime-code IS demonstrated for the
  non-live (boot/config/context) surface.

Remaining consumer gaps:

- `symphony/smda_*` (39 Python files) still on disk as **semantic-reference
  prototypes**, deliberately retained (migration Task 10 pruned only dead
  duplicate plumbing). They are imported only by `tests/symphony/` reference
  tests — no live consumer code (`src/`, `skills/`, harness) imports them. Dead
  island, not the live path, but not yet retired.
- Task 12 "end-to-end dry run" uses fake adapters only — same no-live-Linear/
  no-live-Sandcastle gap as the product side (gaps 1-3 above).
- trading-advisor working tree has ~72 uncommitted files (migration + unrelated
  DANNY-65 work intermixed); not committed by this assessment.

## Running the live smoke tests

Both smoke harnesses skip by default and require explicit opt-in env. They are
the cheapest way to flip gaps 1-3 from "unverified" to "verified".

### Sandcastle (gap 1)

Needs a branchable git working tree and whatever credentials the chosen agent
provider requires.

```bash
SMDA_SMOKE_SANDCASTLE=1 \
SMDA_SMOKE_CWD="$(pwd)" \
SMDA_SMOKE_AGENT_PROVIDER=codex \
SMDA_SMOKE_AGENT_MODEL=gpt-5-codex \
npm run test:ts
```

Pass = the one smoke test flips from `skipped` to `pass` with a typed result.

### Linear (gap 2) — MUTATES a real workspace, use a scratch team

```bash
SMDA_SMOKE_LIVE_LINEAR=1 \
LINEAR_API_KEY=<personal api key> \
SMDA_LINEAR_TEAM_ID=<team uuid> \
SMDA_LINEAR_STATE_TODO=<workflow state uuid> \
SMDA_SMOKE_LINEAR_PARENT_ID=<existing parent issue id> \
uv run pytest packages/scheduler/tests/test_linear_live_smoke.py -q -s
```

Creates an issue titled `[smda-smoke] live child <marker>` under the parent;
delete it afterward. Pass = `1 passed` instead of `1 skipped`.

### Daemon live mode (gap 3) — after 1 and 2 are green

Only attempt once both adapters are individually proven. From the consumer
repo with the same Linear env exported:

```bash
cd /Users/danny/Desktop/GitHub/trading-advisor
docs/harness/smda-daemon.sh start --max-ticks 1
```

This is end-to-end (real tracker + real agent) and is not yet validated.

## Operator / manual intervention model

When the daemon is stuck, the product is driven declaratively — edit the source
of truth and let the next tick converge — not by imperative state-poking. The
operator surfaces:

| Need | Surface | CLI? |
|---|---|---|
| Dead worker / stuck claim | `reconcile-claims` | yes |
| Stop/resume a parent | `pause` / `resume` | yes |
| Single-step the workflow | `daemon --max-ticks 1` (this is the manual workflow runner) | yes |
| Inspect where it is stuck | `status` (parent/child phase, claim, paused) | yes |
| Config/context/state health | `validate-config` / `validate-context` / `validate-state` | yes |
| Approve a spec / approve QA | edit the source of truth (spec front matter `status: approved`, or tracker state); next tick reads it | no — by design |
| Resolve `HUMAN_REVIEW_REQUIRED` | edit inputs + resume; no force-transition command | thin spot |

Two deliberate non-builds (capability already covered automatically — building a
manual CLI would duplicate the daemon):

- **`reconcile-applied`** (already-applied accept reconciliation): the core
  `recover_or_apply_child_accept` already runs inside the automatic child
  acceptance tick (`runtime.py`). A standalone CLI only matters for a pure
  manual no-daemon mode. Deferred.
- **`accept-parent --strategy`** (final accept + main-branch merge): final
  closeout effects are recorded automatically; main-branch merge/squash/PR is a
  deliberate v1 non-goal (see below). Deferred as net-new feature, not a wrapper.

Genuine thin spot: there is no CLI to force a phase transition or clear a
`HUMAN_REVIEW_REQUIRED` parking state. Today that is handled by editing tracker
state/inputs and single-stepping the daemon. A future `advance` / `force-phase`
operator command would close it. (`reconcile-claims` — the one incident-recovery
primitive that previously had no operator surface — now exists.)

## By design — not gaps

- Parent main-branch merge/squash/push is a v1 non-goal. Final accept records
  idempotent tracker effects only; `accept-parent --strategy ...` is a future
  separate operator CLI, never a daemon side effect.
- Python `role_contracts.py` is a small duplicated dispatch-metadata registry;
  role output validation stays TypeScript/Sandcastle-owned. Spec explicitly
  permits this for the MVP.
