<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## gap-3-daemon-live-mode
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 3 (Daemon live mode never run)
- blocked-by: human review
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
- evidence: 2026-06-29 after permissions changed, the documented one-shot
  daemon command exited 0 with `status=stopped`, `ticks=1`, and
  `last_tick.status=dispatched`; detail was `dispatched=3; blocked=0;
  failed=0; skipped=4; pending=3; reconciled=0`.
- evidence: 2026-06-29 live tick launched Sandcastle/Codex via
  `gpt-5.5`/high from trading-advisor config. `DANNY-98-IMPLEMENTING-1`
  succeeded, produced branch `smda/danny-98/danny-98/candidate`, and commit
  `8579e4dd1aa2eddcbe5342fc2b37035f15e10831`; `DANNY-97-IMPLEMENTING-1`
  reached the live runner but failed on a global gitconfig lock race.
- evidence: 2026-06-29 post-run `status` -> `status: ok`; `DANNY-98` is
  `QUALITY_REVIEWING`; tracker effects pending 6, failed 0; both smda and
  trading-advisor worktrees are clean.
- next: human review; after acceptance, archive this entry to `completed.md`.
- updated: 2026-06-29

## gap-4-config-live-fields
- status: blocked
- parent: live-integration-validation
- source: `docs/known-gaps.md` § 4 (Config schema missing live-operation fields)
  and DANNY-70 `GRAPH_DECOMPOSING-4`, where the hard-coded `gpt-5` default
  was rejected by the local Codex account.
- blocked-by: human review
- acceptance: agent provider/model/effort are config-driven and propagated to
  the Sandcastle runner; setup-skill docs make this consumer-facing config
  surface discoverable to target-repo agents; scan state/label are documented as
  daemon-controller policy for the consumer repo; credential and process-launch
  policy remain explicit operator/runtime concerns.
- verify: `uv run pytest -q` -> 330 passed, 1 skipped; `npm run test:ts` ->
  12 passed, 1 skipped; `npm run typecheck` -> passed; `npm run
  schema:export` -> passed; consumer `validate-config` and `validate-context`
  -> passed.
- next: human review; DANNY-70 is already `FINAL_ACCEPTED`, so the historical
  DANNY-70 retry is superseded by the 2026-06-29 live daemon dispatch proving
  config-driven `gpt-5.5`/high propagation.
- evidence: 2026-06-28 Sandcastle smoke proved `gpt-5.5` works in the local
  Codex provider path; DANNY-70-specific retry remains unrun.
- evidence: 2026-06-29 daemon live retry remains blocked in this Codex session
  by the same live-provider data-egress approval-layer rejection.
- evidence: 2026-06-29 live daemon dispatch used trading-advisor config
  `agent.model=gpt-5.5` and `effort=high`; live Codex process was observed as
  `codex exec ... -m gpt-5.5 -c model_reasoning_effort="high"`.
- evidence: 2026-06-29 `smda-scheduler status` reports DANNY-70
  `FINAL_ACCEPTED`, so there is no remaining DANNY-70 retry to run.
- updated: 2026-06-29
