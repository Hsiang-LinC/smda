<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## gap-3-daemon-live-mode
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 3 (Daemon live mode never run)
- blocked-by: explicit approval for live agent data egress
- acceptance: one end-to-end daemon pass against a real repo + Linear + agent.
- verify: from `/Users/danny/Desktop/GitHub/trading-advisor`, load `.env` and
  run `uv run --project /Users/danny/Desktop/GitHub/smda smda-scheduler daemon
  smda.config.json --repo-root . --state "In Progress" --state Todo --state
  "Agent Review" --label agent --owner smda-daemon --max-ticks 1`.
- next: get explicit approval for live agent data egress against the
  trading-advisor repo and run a single live tick.
- updated: 2026-06-29

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
