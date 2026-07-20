# Task 6 Implementation Report

## Summary

Task 6 now has a mutation-tested AST architecture scanner in
`packages/scheduler/tests/test_packaging.py`. It proves the exclusive
Parent/Roadmap **phase-state** write residence instead of checking only three
exact call names:

- the scheduler source package must exist and contain Python source;
- `PhaseLedger` must define exactly one `create_parent_run`,
  `transition_parent`, and `force_parent_phase`, all in `phase_ledger.py`;
- retired names are rejected as definitions, imports, names, or attribute
  references, so aliasing a retired writer cannot evade the guard;
- direct `INSERT`, `UPDATE`, or `DELETE` writes to `parent_run_state` may live
  only in `create_parent_run`, `force_parent_phase`, and private
  `_transition_parent`;
- `_transition_parent` must be called by public `transition_parent` and cannot
  be referenced elsewhere;
- `force_parent_phase` must have a nonempty reference boundary consisting only
  of `cli.py`; and
- extra `PhaseLedger` forwarding writers are rejected.

The scanner deliberately keys only on `parent_run_state`. Acceptance,
landing, graph, projection, roadmap-membership, and effect tables are separate
subledgers and remain outside this phase-write contract.

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

## Review Fix Wave

The review found that the original guard passed vacuously on an empty source
package, used a subset assertion for the CLI boundary, and inspected only
direct calls/definitions of three retired names. The fix extracted
`_parent_phase_write_violations` and drove it from small source-package
mutations. Fixtures prove rejection of:

- missing and empty source packages;
- missing and duplicate public `PhaseLedger` definitions;
- a retired writer captured as an alias;
- unexpected `PhaseLedger` forwarding and private transition calls;
- a direct SQL writer outside the ledger residence;
- a non-CLI `force_parent_phase` alias; and
- an empty CLI force boundary.

No production file changed in this review fix wave.

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

1. TDD red — the first missing/empty-package mutation failed before the scanner
   existed:

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py::test_parent_phase_write_guard_rejects_missing_and_empty_packages -q
   ```

   Result: `1 failed` with `NameError: name
   '_parent_phase_write_violations' is not defined`.

2. Focused guard and mutation suite after the minimal scanner implementation:

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py -q
   ```

   Result: `24 passed in 2.01s`.

3. Complete scheduler suite:

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q
   ```

   Result: `433 passed, 1 skipped in 14.29s`. The complete run included and
   passed the generated JavaScript bundle parity test, so no test exclusion was
   used.

4. Focused source/plugin and generated-JavaScript parity checks:

   ```bash
   UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py::test_smda_plugin_bundles_scheduler_runtime_copy_in_sync packages/scheduler/tests/test_packaging.py::test_smda_plugin_bundles_sandcastle_runner_artifact_in_sync -q
   ```

   Result: `2 passed in 0.23s`.

5. Final repository check:

   ```bash
   git diff --check
   ```

   Result: exited successfully with no output.

## Remaining Failure Classification

None. The full scheduler suite has one existing opt-in skip and no failures.
Generated JavaScript bundle parity is green and was not excluded.
