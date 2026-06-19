# DANNY-70 Runtime Defects Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans or the repo harness bug/regression route to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Remove the runtime defects exposed by the DANNY-70 live execution
incident before treating live-integration validation as meaningful evidence.

**Architecture:** Split the incident into three independent remediation
workstreams. The execution-adapter boundary gets a new Attempt Result Artifact
contract; the parent aggregate wait and dispatch-capacity issues are conformance
fixes against the existing workflow-engine ADRs.

**Tech Stack:** TypeScript Sandcastle runner, Python scheduler package, pytest,
Vitest, Zod schema export. Package roots: `packages/sandcastle-runner` and
`packages/scheduler`.

## Global Constraints

- Keep the three workstreams independently reviewable. A live DANNY-70 retry
  must be diagnosable by layer: execution adapter, parent aggregate semantics,
  or workspace dispatch capacity.
- Do not use stdout/stderr as a workflow-control channel after the Attempt
  Result Artifact migration. Process logs are evidence only.
- Preserve the existing Sandcastle `Output.object` responsibility: the model
  produces the role payload; runner code produces the attempt envelope.
- Parent aggregate waiting and child dependency gating must remain workflow
  semantics, not adapter behavior.
- Before any implementation edit, the worker must use the matching
  `docs/work-ledger/active.md` item and update it per `docs/harness/tracker.md`.

## Decision Summary

- **Attempt Result Artifact:** every execution adapter returns a durable
  machine-readable artifact for each attempt.
- **Runner-authored envelope:** LLM output may fill the typed role payload only;
  runner/adapter code authors the artifact envelope and failure status.
- **Transport:** the scheduler passes the artifact destination as runner
  transport metadata, initially `--result-file <path>`.
- **Residence:** artifacts are retained under `runtime.artifact_root` as durable
  attempt evidence.
- **No production legacy fallback:** stdout/stderr JSON scanning is removed from
  the production control path rather than retained as an alternate runtime path.

## Workstream 1: Attempt Result Artifact Contract

**Tracker:** `attempt-result-artifact-contract` for docs/ADR, then a dedicated
implementation item before code changes.

**Files likely touched:**
- `docs/adr/0007-attempt-result-artifact.md`
- `docs/contracts.md`
- `packages/sandcastle-runner/src/cli.ts`
- `packages/sandcastle-runner/src/runRoleAttempt.ts`
- `packages/sandcastle-runner/tests/cli.test.ts`
- `packages/scheduler/src/smda_scheduler/sandcastle_execution.py`
- `packages/scheduler/tests/test_sandcastle_execution.py`

- [x] **Step 1: Write ADR-0007**
  - Record the adapter-wide Attempt Result Artifact contract.
  - State that stdout/stderr are Process Logs and never workflow-control input.
  - State that Sandcastle is the first implementation, using an atomic result
    file passed by `--result-file`.

- [x] **Step 2: Update contracts**
  - Update the execution adapter section in `docs/contracts.md` so
    `runAttempt(request) -> result` is expressed as an Attempt Result Artifact
    handoff.
  - Name missing/invalid artifacts as adapter contract violations.

- [x] **Step 3: Red TS runner tests**
  - Add a CLI test where `--result-file` writes the result artifact and stdout
    may contain unrelated process logs.
  - Add missing/invalid input tests that verify protocol failures are written as
    artifacts when the runner can parse enough request context to do so.
  - Add an atomic-write test that observes no final file until the write
    completes, using a temp file + rename implementation.

- [x] **Step 4: Implement TS result-file writing**
  - Parse `--result-file <path>` as runner transport metadata.
  - Write JSON to a sibling temp file, then rename to the final path.
  - Keep `RoleAttemptResult` runner-authored; do not ask the model for the
    envelope.

- [x] **Step 5: Red Python adapter tests**
  - Assert the scheduler passes `--result-file`.
  - Assert it reads only the artifact file, not stdout/stderr.
  - Assert missing artifact and invalid artifact produce explicit adapter
    contract violation errors with process-log snippets as evidence.
  - Assert a nonzero process with a valid artifact follows artifact status.

- [x] **Step 6: Implement Python artifact consumption**
  - Create the attempt artifact directory under configured artifact root.
  - Pass `--result-file` to the runner command.
  - Delete production `_extract_ipc_payload()` control-flow usage.
  - Keep stdout/stderr only in evidence/error snippets.

- [x] **Step 7: Verify**
  - Run `uv run pytest packages/scheduler/tests/test_sandcastle_execution.py -q`.
  - Run `npm run test:ts`.
  - Run `npm run typecheck`.
  - Run `npm run schema:export`.

## Workstream 2: Parent Aggregate Wait Semantics

**Tracker:** `parent-child-acceptance-aggregate-wait`.

**Files likely touched:**
- `packages/scheduler/src/smda_scheduler/runtime.py`
- `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Red regression test**
  - Construct a parent in `CHILDREN_PUBLISHED` with children not yet
    `QUALITY_REVIEW_PASSED` and no integration branch configured.
  - Expect the tick to wait/in-progress via child acceptance, not immediately
    block on missing integration config.

- [x] **Step 2: Move the guard to the owning stage**
  - Do not block at the phase gate before child readiness is known.
  - Only require integration configuration when a child acceptance/apply action
    actually needs it, or fail earlier at config validation if the runtime mode
    requires integration.

- [x] **Step 3: Verify aggregate behavior**
  - Existing child-acceptance tests still pass.
  - New regression proves parent aggregate waiting is idempotent and visible.

- [x] **Step 4: Verify**
  - Run the focused runtime test.
  - Run `uv run pytest packages/scheduler/tests -q`.

## Workstream 3: Dispatch Capacity Ignores Dependency Waits

**Tracker:** `dependency-wait-does-not-consume-dispatch-capacity`.

**Files likely touched:**
- `packages/scheduler/src/smda_scheduler/workspace_tick.py`
- `packages/scheduler/tests/test_workspace_tick.py`

- [x] **Step 1: Red regression test**
  - Create a DANNY-70-shaped child set where dependent children sort before
    ready root children.
  - Set `max_parallel=3`.
  - Expect dependency-wait/skipped candidates not to exhaust capacity; ready
    root children dispatch in the same tick.

- [x] **Step 2: Fix batch selection**
  - Treat dependency-wait results as non-dispatching candidates.
  - Continue scanning/planning until either `max_parallel` real dispatches are
    scheduled or no candidates remain.
  - Preserve one dispatch per distinct issue per tick.

- [x] **Step 3: Verify fairness and bounds**
  - Existing parallel fan-out behavior remains bounded by `max_parallel` for
    actual role attempts.
  - Skipped/dependency-wait candidates remain recorded for observability.

- [x] **Step 4: Verify**
  - Run the focused workspace tick regression.
  - Run `uv run pytest packages/scheduler/tests -q`.

## Closeout

- [x] Update `docs/work-ledger/active.md` items with verification evidence.
- [ ] If all three workstreams are green, retry DANNY-70 in the consumer repo
  before closing `gap-4-config-live-fields`.
- [ ] If the retry exposes a new live-only issue, create a separate work item
  rather than expanding these three workstreams.
