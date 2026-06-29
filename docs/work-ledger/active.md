<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## gap-3-daemon-live-mode
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 3 (Daemon live mode never run)
- blocked-by: approval-layer live-provider policy; needs manual operator run
- acceptance: one end-to-end daemon pass against a real repo + Linear + agent.
- verify: from `/Users/danny/Desktop/GitHub/trading-advisor`, load `.env` and
  run `uv run --project /Users/danny/Desktop/GitHub/smda smda-scheduler daemon
  smda.config.json --repo-root . --state "In Progress" --state Todo --state
  "Agent Review" --label agent --owner smda-daemon --max-ticks 1`.
- evidence: 2026-06-29 user approved live agent data egress, but the approval
  layer rejected the one-shot daemon command before execution because it would
  send trading-advisor repo context to a live external provider and mutate
  repo/Linear state.
- evidence: 2026-06-29 safer preflight still passes with trading-advisor `.env`:
  `validate-config` -> `status: ok`; `validate-context` -> `status: ok`.
- next: run the documented one-shot daemon command manually from an operator
  terminal that permits the live provider boundary, then record the result here.
- updated: 2026-06-29

## gap-4-config-live-fields
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 4 (Config schema missing live-operation fields)
  and DANNY-70 `GRAPH_DECOMPOSING-4`, where the hard-coded `gpt-5` default
  was rejected by the local Codex account.
- blocked-by: approval-layer live-provider policy; needs manual operator run
- acceptance: agent provider/model/effort are config-driven and propagated to
  the Sandcastle runner; setup-skill docs make this consumer-facing config
  surface discoverable to target-repo agents; scan state/label are documented as
  daemon-controller policy for the consumer repo; credential and process-launch
  policy remain explicit operator/runtime concerns.
- verify: `uv run pytest -q` -> 330 passed, 1 skipped; `npm run test:ts` ->
  12 passed, 1 skipped; `npm run typecheck` -> passed; `npm run
  schema:export` -> passed; consumer `validate-config` and `validate-context`
  -> passed.
- next: run the DANNY-70 retry manually from an operator terminal that permits
  the live provider boundary, then record the result here.
- evidence: 2026-06-28 Sandcastle smoke proved `gpt-5.5` works in the local
  Codex provider path; DANNY-70-specific retry remains unrun.
- evidence: 2026-06-29 daemon live retry remains blocked in this Codex session
  by the same live-provider data-egress approval-layer rejection.
- updated: 2026-06-29
