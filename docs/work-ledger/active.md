<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## setup-skill-projection-status-guidance
- status: blocked
- source: 2026-06-19 user request after DANNY-70 projection-lag diagnosis
- blocked-by: none
- acceptance: `setup-smda-automation` durable guidance tells future consumer
  repo agents that SMDA local ledger/status output is runtime truth, Linear is a
  tracker projection drained through `tracker_effect_ledger`, and
  `smda-scheduler status` / daemon status checks are the read-only way to
  distinguish normal projection lag from failed tracker sync.
- verify: `UV_CACHE_DIR=/private/tmp/uv-cache-smda uv run --project
  packages/scheduler pytest
  packages/scheduler/tests/test_cli.py::test_status_cli_returns_ledger_summary
  -q` -> 1 passed; `UV_CACHE_DIR=/private/tmp/uv-cache-smda uv run --project
  packages/scheduler pytest packages/scheduler/tests/test_cli.py -q` -> 14
  passed; `git diff --check` -> passed; active plugin cache copy refreshed.
- next: human review; if accepted, move this entry to `completed.md`.
- updated: 2026-06-19

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
