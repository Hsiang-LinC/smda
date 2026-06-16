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

### 4. Config schema missing live-operation fields (PARTIAL)

`runtime.integration_branch` is now a config field and is wired into the live
daemon tick (a parent can reach child acceptance in live mode when it is set).
Still CLI-flag-only: scan state/label (`--state`/`--label`) and agent model.
Packaging has not decided credential and process-launch policy.

## Fixed defects (codex review, 2026-06-16)

A codex review surfaced concrete defects (beyond the "unverified" live gaps).
Fixed under TDD:

- **Routing-block tracker effect type**: `_record_block_effects` emitted
  `effect_type="state"` which reconciliation rejected, so obsolete/missing-
  context blocks never reached Linear. Now `set_state`.
- **Child SDD loop never re-dispatched**: `eligible_child_ids` gated on
  `phase==READY`, so once a child passed the implementer it stalled — the
  review/fix/quality loop never ran. Broadened to dispatch any active
  non-terminal phase (claim/retry/dependency gating preserved).
- **Fixer ran blind**: `ChildTaskContext.review_findings` was never populated;
  fixers now carry the latest review report (prevents a review->fix livelock).
- **`fix_quality` dead-ended**: added the `FIXING_QUALITY` phase/transitions and
  a quality-fixer contract.
- **Graph review failure crashed**: a non-PASS graph spec/execution review
  raised `GraphError`; now records the verdict and parks the parent in
  `HUMAN_REVIEW_REQUIRED` with findings.
- **Parent lifecycle not synced**: intermediate parent transitions
  (In Progress / Human Review / Blocked) are now recorded as tracker effects,
  not just routing-block and final-accept.

### Follow-ups from that pass (now done)

- **Automatic graph-fixer loop** (done): `ParentPhase.GRAPH_FIXING` + a
  `graph_fixer` role now loop a failed graph review through a findings-scoped
  fixer and re-review, bounded by `_MAX_GRAPH_FIX_CYCLES` (escalates to human
  review when exhausted — no infinite loop).
- **Child-level tracker-state sync** (done): `run_child_candidate_tick` records
  the child issue's coarse tracker state from its resulting SDD phase
  (In Progress / Agent Review / Human Review).

### 5. Consumer migration: dual-track dropped, product-only (DONE)

Verified against `/Users/danny/Desktop/GitHub/trading-advisor` on 2026-06-15:

- `smda.config.json` points the consumer at the product (`sandcastle` /
  `linear` / `codex-harness`); quality gates and `docs/harness/smda-daemon.sh`
  invoke the external `smda-scheduler` CLI, not repo-local runtime.
- Cross-repo product boot PASSES with no live creds:
  `validate-config` and `validate-context` both return `status: ok`, exit 0.

The user dropped the planned dual-track fallback (see [[trading-advisor-no-dual-track]]).
The entire repo-local `symphony/` package (old orchestrator/daemon/tracker AND
the `smda_*` prototypes), `tests/symphony/`, the `symphony` console entry point,
and the symphony launch scripts were deleted. The consumer harness contract
tests and live docs (`tracker.md`, `operating-process.md`, `WORKFLOW.md`,
`REVIEW.md`, ops/agent-system indexes) were flipped from dual-track to
product-only. Historical design docs (`docs/superpowers/specs|plans`,
`work-ledger`) intentionally retain Symphony as a record.

Result: `pytest` 247 passed / 4 skipped, `tests/harness` 15 passed, `uv build`
clean (no symphony package/entry point), cross-repo validate gates exit 0.

Remaining consumer gaps:

- Live end-to-end (real Linear + real Sandcastle) still unrun — same as product
  gaps 1-3 above. Incident-recovery is automatic in-daemon plus the new
  `reconcile-claims` CLI; manual `force-phase`/`HUMAN_REVIEW` clearing is the
  recorded thin spot (see operator model above).
- trading-advisor working tree is a large uncommitted blob (the whole migration
  predates its last commit); commit handling is left to the user.

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

## Fixed defects (second agent review, 2026-06-16)

- **Child review/fix infinite loop** (F1, was HIGH): a reviewer FAIL/fix verdict
  is a *succeeded* attempt, and the succeeded branch never checked the attempt
  cap, so SPEC_REVIEWING↔FIXING_SPEC (or quality) could oscillate forever. Added
  a persisted `review_fix_cycles` counter on child run state, bounded by
  `max_review_fix_cycles` → `HUMAN_REVIEW_REQUIRED`.
- **GraphError killed the daemon** (F5): an uncaught `GraphError` in a tick
  halted the whole daemon with no tracker evidence. The workspace tick now
  contains it to the issue as a Blocked effect and keeps serving.
- **Env errors not classified** (F3): the Sandcastle adapter forwarded raw
  `execution_failed` messages, so unfixable environment errors (permission
  denied, missing binary/image, docker down, no space) were retried to the cap.
  Recognized env errors are now prefixed `non_transient:` → straight to human
  review.
- **Stale child handle dispatch** (F4): `run_child_candidate_tick` ignored the
  handle's graph checksum; a handle from a superseded decomposition would still
  run. Now validated against the persisted parent graph checksum.
- **Child failure had no report** (F2 residual): the child lifecycle comment now
  includes the latest child report/error, not just the phase name.

Note: the earlier review's "child lifecycle not synced to tracker" was already
fixed (parent + child phase changes record tracker effects); only the missing
report in the child comment remained, now closed by F2 above.

## Reviewer feedback model

Reviewers (`child_spec`, `child_quality`, `graph_spec`, `graph_execution`,
`parent_qa`) are the sole severity arbiter: they emit `verdict` +
`required_next_action` + `report`, and the scheduler routes mechanically via the
transition table. There is no scheduler-side severity logic.

- **FAIL** → loops back through a bounded fixer (child fix cycles, graph fix
  cycles, parent remediation — all capped, escalating to human review).
- **PASS** → proceeds; the optional `report` carries any residual note and now
  surfaces in the tracker comment (child + parent).
- **DONE_WITH_CONCERNS** → proceeds like PASS but flags a minor, non-blocking
  issue recorded in `report` — the "small issue, don't loop, pass it down" path.

### Future idea: auto follow-up issue for deferred concerns

Today a `DONE_WITH_CONCERNS` verdict records the concern only in the result
report + tracker comment; nothing tracks it as actionable work, so a deferred
minor issue can silently disappear once the parent closes.

Proposed (not built): when a reviewer returns `DONE_WITH_CONCERNS`, optionally
open a low-priority follow-up child/backlog issue carrying the concern report
(linked to the source issue), so deferred concerns become durable, schedulable
work instead of a buried comment. Make it config-gated (some repos may prefer
comment-only). Reuses the existing child publication + tracker-effect machinery;
the main decisions are issue template/labels and whether it attaches to the
current parent graph or a standalone backlog item.

### Future idea: difficulty-aware model selection

Today every role attempt uses one fixed `AgentSelection` (single provider +
model) threaded through the whole workspace tick — e.g. the factory default
`codex` / `gpt-5`. A trivial child implement, a deep graph decomposition, and a
quick spec review all get the same model.

Proposed (not built): let the dispatching layer (planner/decomposer, reviewers,
or any role-attempt builder) choose a model tier by task difficulty — small/fast
models for cheap, well-scoped work (simple reviews, tiny fixes) and large models
for hard work (graph decomposition, ambiguous specs, remediation planning).
Inputs could be the phase/role, the child's risk_level / acceptance-criteria
size, prior fix-cycle count, or an explicit difficulty hint in the issue. Make
it config-driven (a role/difficulty → model map) so cost/quality is tunable per
repo. Mechanically, `AgentSelection` would be resolved per attempt instead of
passed as one fixed value; the role contracts already carry the phase/role
needed to drive the choice.

## By design — not gaps

- Parent main-branch merge/squash/push is a v1 non-goal. Final accept records
  idempotent tracker effects only; `accept-parent --strategy ...` is a future
  separate operator CLI, never a daemon side effect.
- Python `role_contracts.py` is a small duplicated dispatch-metadata registry;
  role output validation stays TypeScript/Sandcastle-owned. Spec explicitly
  permits this for the MVP.
