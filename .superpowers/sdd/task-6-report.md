# Task 6 Implementation Report

## Summary

Task 6 adds a durable AST-based production architecture guard in
`packages/scheduler/tests/test_packaging.py`. The guard:

- rejects calls or definitions of `record_parent_run`,
  `record_attempt_result_and_parent_run`, and
  `record_attempt_result_parent_run_and_graph` anywhere in the scheduler source
  package;
- reports the exact file, line, and retired method when it fails; and
- rejects any `force_parent_phase` caller outside the CLI boundary.

The guard defines the complete public Parent/Roadmap **phase-state** write
surface as `create_parent_run`, `transition_parent`, and `force_parent_phase`.
It rejects every retired phase-state method from that known surface and applies
the stricter CLI-only rule to the break-glass method. This contract is
intentionally about `parent_run_state`, not every API whose name contains
`parent` or `roadmap`: acceptance-operation, landing-operation, graph,
projection, membership, and effect APIs own separate durable subledgers and
remain valid explicit Runtime effects.

No production code changed. Task 5 (`e425a4d`, `Commit parent projections
atomically`) had already migrated and deleted the retired Parent/Roadmap write
paths, so the new structural test passed on its first run. This supersedes Task
6 Step 2's expected failing precondition. Production code was not reintroduced
to manufacture a red test.

## Changed Files

- `packages/scheduler/tests/test_packaging.py` — added the production-call
  architecture guard.
- `.superpowers/sdd/task-6-report.md` — recorded implementation and verification
  evidence.

The tracker and `.superpowers/sdd/progress.md` were not edited. No
`packages/sandcastle-runner` TypeScript or generated JavaScript bundle was
changed.

## Inspected Parent/Roadmap Result Combinations

1. **RoleAttempt success with Attempt result only.**
   `run_parent_role_attempt` routes successful reviews, QA, and conflict
   resolution through `_write_parent_success`. The corresponding success
   builders return `extra=None`; `_write_parent_success` calls
   `transition_parent` with the expected phase, next phase, Attempt result, and
   lifecycle effects.

2. **Graph decomposition/fixing success with Attempt result plus graph.**
   `_decomposition_build_success` and `_fixing_build_success` return a
   `WorkflowGraphArtifact`; `_write_parent_success` supplies it as `graph`
   alongside the Attempt result and effects in the same `transition_parent`
   call. Covered by the graph decomposition and graph fixing Runtime tests.

3. **Graph review failure with bounded next phase.**
   `_route_failed_graph_review` transitions to `GRAPH_FIXING` with the Attempt
   result and lifecycle effects. Once `_MAX_GRAPH_FIX_CYCLES` is exhausted,
   `_route_graph_review_to_human_review` transitions to
   `HUMAN_REVIEW_REQUIRED` with the same atomic fact bundle. Covered by the
   graph-review failure and exhausted-budget Runtime tests.

4. **Conflict resolver success/failure.**
   `_child_accept_conflict_build_success` returns no graph and uses the generic
   Attempt-result transition. `_child_accept_conflict_on_failure` commits the
   failed Attempt result and human-review lifecycle effects together.
   `_route_child_accept_conflict` separately commits the deterministic
   conflict-routing transition and lifecycle effects, bounded by
   `_MAX_CHILD_ACCEPT_CONFLICT_RESOLVER_ATTEMPTS`. Covered by resolver retry and
   repeated-conflict escalation Runtime tests.

5. **Remediation and landing Effect transitions.**
   `run_parent_remediation_planning_tick` uses `transition_parent` for both
   bounded human escalation and successful graph extension, with lifecycle
   effects. `run_parent_final_accept_tick` commits the terminal phase together
   with its final comment and Done-state effects after the durable land
   operation completes; conflict detection transitions to
   `LANDING_CONFLICT_REBASING`. `run_landing_conflict_rebase_tick` transitions
   either to bounded human review or back to parent QA with lifecycle effects.
   Git operations remain explicit Runtime effects rather than opaque
   callables. Covered by remediation, final-accept rollback, landing, conflict,
   rebase, and cap tests.

6. **Roadmap decomposition/completion transitions.**
   `run_roadmap_decomposition_tick` commits successful and failed Attempt
   results plus lifecycle effects through `transition_parent` (failure remains
   in the expected phase). Publication transitions only after explicit member
   projection work. `run_roadmap_completion_tick` performs the durable land
   operation first, then transitions to `ROADMAP_COMPLETED` with lifecycle
   effects. Covered by roadmap decomposition, publication, wait, and land-once
   Runtime tests.

7. **Concern/follow-up lifecycle effects required by the transition.**
   `_concern_followup_effects` produces the optional `create_child` effect for
   `DONE_WITH_CONCERNS`; `run_parent_role_attempt` includes it with the standard
   lifecycle effects in the same `_write_parent_success` /
   `transition_parent` transaction. Covered by the enabled concern-follow-up
   Runtime test.

The ledger exposes `create_parent_run`, `transition_parent`, and the CLI-only
`force_parent_phase`; all three retired compound methods are absent.
`record_attempt_result` remains for non-Parent execution evidence as required.
The only production call to `force_parent_phase` is in `cli.py`.

## Commands And Results

1. Structural test (first run, immediately green because Task 5 superseded the
   planned legacy state):

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py::test_parent_roadmap_production_writes_use_deep_interface -q
   ```

   Result: `1 passed in 0.21s`.

2. Focused Task 6 scheduler tests:

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py::test_parent_roadmap_production_writes_use_deep_interface packages/scheduler/tests/test_phase_ledger.py packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_workspace_tick.py -q
   ```

   Result: `125 passed in 3.10s`.

3. Complete scheduler suite:

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q
   ```

   Result: `425 passed, 1 skipped in 11.29s`. The complete run included and
   passed the generated JavaScript bundle parity test, so no test exclusion was
   used.

4. Focused source/plugin and generated-JavaScript parity checks:

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py::test_smda_plugin_bundles_scheduler_runtime_copy_in_sync packages/scheduler/tests/test_packaging.py::test_smda_plugin_bundles_sandcastle_runner_artifact_in_sync -q
   ```

   Result: `2 passed in 0.41s`.

5. Production retirement and break-glass scans:

   ```bash
   rg -n "record_parent_run\\(|record_attempt_result_and_parent_run\\(|record_attempt_result_parent_run_and_graph\\(" packages/scheduler/src/smda_scheduler
   rg -n "force_parent_phase\\(" packages/scheduler/src/smda_scheduler
   ```

   Result: no retired matches. `force_parent_phase` appears only as the ledger
   definition and the authorized `cli.py` call.

6. Final repository checks:

   ```bash
   git diff --check
   test -f docs/harness/index.md
   test -f docs/harness/tracker.md
   test -f docs/harness/roadmap.md
   test -f docs/harness/quality-gates.md
   test -f docs/work-ledger/active.md
   test -f docs/work-ledger/completed.md
   test -f docs/work-ledger/abandoned.md
   ```

   Result: all exited successfully with no output.

## Remaining Failure Classification

None. The full scheduler suite has one existing opt-in skip and no failures.
Generated JavaScript bundle parity is green and was not excluded.
