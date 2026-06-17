<!-- codex-harness: generated 2026-06-17 -->
# Roadmap

Last verified: 2026-06-17

Long-horizon direction. Work items live in the tracker
(`docs/harness/tracker.md`); this file holds the milestone sequence and the
current position. Node transitions are user decisions made in interactive
sessions: an agent may propose advancing — with evidence that the current
node's items are all terminal — but never advances a node alone.

## Current Node

live-integration-validation — flip the live-integration gaps in
`docs/known-gaps.md` (1–4) from "unverified / skipped" to "verified / passing".

## Milestones

### target-c: Modular parallel SMDA engine
- status: done
- goal: one workflow engine interpreting WorkflowDefinitions; parent/roadmap
  tier; methodology-skill injection; parent landing + cross-parent conflict;
  modes as definitions (Phases 0–5 + 1d).
- spec: `docs/superpowers/specs/2026-06-16-target-c-modular-parallel-engine.md`;
  ADR-0001–0006; `docs/superpowers/plans/2026-06-16-target-c-implementation-path.md`
- items: completed — see `docs/work-ledger/completed.md`
  (`target-c-modular-parallel-engine`).

### live-integration-validation: Prove the live path
- status: current
- goal: exercise the real Sandcastle runner, the real Linear adapter, and a
  full live daemon pass — closing the "code complete vs validated product" gap.
- spec: `docs/known-gaps.md` (gaps 1–4); smoke harnesses already in place,
  awaiting credentials.
- items: `docs/work-ledger/active.md` — `gap-1-live-sandcastle-smoke`,
  `gap-2-live-linear-smoke`, `gap-3-daemon-live-mode`,
  `gap-4-config-live-fields`.

### product-hardening: Deferred concerns & tuning
- status: later
- goal: durable handling of deferred concerns and cost/quality tuning.
- spec: not yet specced — see `docs/known-gaps.md` "Future idea" sections.
- items: not yet issueized — tracked in `docs/work-ledger/follow-ups.md`
  (`auto-follow-up-issue-for-concerns`, `difficulty-aware-model-selection`,
  `force-phase-operator-command`).

## Direction Notes

- The product (`smda-scheduler`) is config-only against consumer repos; never
  vendor engine or adapter code into a target repo (Tier-3 boundary, ADR/known-gaps).
- Live-integration items are blocked on external credentials (agent provider +
  Linear), not on code — they stay `blocked` until creds are supplied, then
  become a single opt-in test run each.
- Base branch is `master` (not `main`).
