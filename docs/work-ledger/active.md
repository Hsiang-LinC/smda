<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

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
- status: planned
- source: `docs/known-gaps.md` § 4 (Config schema missing live-operation fields)
- blocked-by: none
- acceptance: scan state/label and agent model are config-driven (not
  CLI-flag-only); credential and process-launch policy decided.
- verify: `npm run schema:export && npm run test:ts && pytest` — new config
  fields round-trip through the zod-canonical schema and Python consumes them.
- next: lift `--state` / `--label` / agent model from CLI flags into the config
  schema; decide packaging credential policy.
- updated: 2026-06-17
