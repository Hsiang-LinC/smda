<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## gap-2-live-linear-smoke
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 2 (No live Linear smoke test)
- blocked-by: live Linear scratch workspace/API env
- acceptance: scan candidates, create a child issue, set state, post a comment
  against a real Linear workspace.
- verify: `SMDA_SMOKE_LIVE_LINEAR=1 LINEAR_API_KEY=... SMDA_LINEAR_TEAM_ID=... SMDA_LINEAR_STATE_TODO=... SMDA_SMOKE_LINEAR_PARENT_ID=... uv run pytest packages/scheduler/tests/test_linear_live_smoke.py -q -s` — 1 passed instead of skipped. Mutates a scratch workspace.
- evidence: 2026-06-27 `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_linear_live_smoke.py -q -s` -> 1 skipped; live run not attempted because this session has no Linear env and the test mutates a workspace.
- evidence: 2026-06-27 environment check showed no `LINEAR_*` or `SMDA_LINEAR_*`
  variables exported in this session.
- evidence: 2026-06-28 environment check still shows no `LINEAR_*` or
  `SMDA_LINEAR_*` variables exported in this session.
- next: obtain a live Linear API key + scratch team, export the required
  `LINEAR_*`/`SMDA_LINEAR_*` env, then run the harness once.
- updated: 2026-06-28

## gap-3-daemon-live-mode
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 3 (Daemon live mode never run)
- blocked-by: gap-2-live-linear-smoke
- acceptance: one end-to-end daemon pass against a real repo + Linear + agent.
- verify: from a consumer repo with Linear env exported, `docs/harness/smda-daemon.sh start --max-ticks 1` completes a real tick.
- next: complete gap 2 first; then run a single live tick.
- updated: 2026-06-28

## gap-4-config-live-fields
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 4 (Config schema missing live-operation fields)
  and DANNY-70 `GRAPH_DECOMPOSING-4`, where the hard-coded `gpt-5` default
  was rejected by the local Codex account.
- blocked-by: live retry intentionally deferred
- acceptance: agent provider/model/effort are config-driven and propagated to
  the Sandcastle runner; setup-skill docs make this consumer-facing config
  surface discoverable to target-repo agents; scan state/label are documented as
  daemon-controller policy for the consumer repo; credential and process-launch
  policy remain explicit operator/runtime concerns.
- verify: `uv run pytest -q` -> 330 passed, 1 skipped; `npm run test:ts` ->
  12 passed, 1 skipped; `npm run typecheck` -> passed; `npm run
  schema:export` -> passed; consumer `validate-config` and `validate-context`
  -> passed.
- next: retry DANNY-70 under `gpt-5.5` with `effort=high` when live validation
  resumes.
- evidence: 2026-06-28 Sandcastle smoke proved `gpt-5.5` works in the local
  Codex provider path; DANNY-70-specific retry remains unrun.
- updated: 2026-06-28
