<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

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
