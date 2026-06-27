<!-- codex-harness: generated 2026-06-17 -->
# Roadmap

Last verified: 2026-06-23

Long-horizon direction. Work items live in the tracker
(`docs/harness/tracker.md`); this file holds the milestone sequence and the
current position. Node transitions are user decisions made in interactive
sessions: an agent may propose advancing — with evidence that the current
node's items are all terminal — but never advances a node alone.

## Current Node

product-hardening — deferred live validation remains tracked, but current local
work is durable handling of deferred concerns and cost/quality tuning.

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
- status: deferred
- goal: exercise the real Sandcastle runner, the real Linear adapter, and a
  full live daemon pass — closing the "code complete vs validated product" gap.
- spec: `docs/known-gaps.md` (gaps 1–4); smoke harnesses already in place,
  awaiting credentials.
- items: `docs/work-ledger/follow-ups.md` — `gap-1-live-sandcastle-smoke`,
  `gap-2-live-linear-smoke`, `gap-3-daemon-live-mode`,
  `gap-4-config-live-fields`.

### product-hardening: Deferred concerns & tuning
- status: current
- goal: durable handling of deferred concerns and cost/quality tuning.
- spec: not yet specced — see `docs/known-gaps.md` "Future idea" sections.
- items: `docs/work-ledger/active.md` and `docs/work-ledger/follow-ups.md`.
  `linear-scope-id-ignored`, `force-phase-operator-command`, and
  `mcp-operator-interface` are done — see `docs/work-ledger/completed.md`.

### architecture-review-deepening-upgrade: Deepen scheduler seams
- status: done
- goal: turn the 2026-06-23 architecture review into ordered deepening slices
  that improve locality around product-runtime seams without adding a new
  orchestration model.
- review: `/private/var/folders/v2/609g53p957q4tgsgsbmb_5nw0000gq/T/architecture-review-20260623-135410.html`
- items: completed — see `docs/work-ledger/completed.md`
  (`parent-integration-conflict-recovery`, `roadmap-publication-ordering`,
  `structured-child-context`, `route-dispatch-selection`).

Rollout order:
1. `parent-integration-conflict-recovery` — deepen parent integration conflict
   handling behind a parent-integration resolver.
2. `roadmap-publication-ordering` — concentrate Roadmap publication ordering so
   held state, projections, edges, and release happen through one safe effect.
3. `structured-child-context` — build Child task context from graph/ledger truth;
   keep issue markdown as a human adapter projection.
4. `route-dispatch-selection` — collapse repeated route selection into one
   dispatch module while keeping ADR-0006's explicit effect handlers.

## Direction Notes

- The product (`smda-scheduler`) is config-only against consumer repos; never
  vendor engine or adapter code into a target repo (Tier-3 boundary, ADR/known-gaps).
- Live-integration items are blocked on external credentials (agent provider +
  Linear), not on code — they stay `blocked` until creds are supplied, then
  become a single opt-in test run each.
- Base branch is `main` (reconciled from `master` 2026-06-17).
- smda is the SMDA Scheduler *product* repo, not an SMDA *target*: its tracker
  stays the local ledger (`docs/work-ledger/`) and it is developed via the
  general dev harness, not self-dispatched. Product support for a
  `local-ledger` backlog adapter does not make this repo an SMDA target; running
  an autonomous self-modifying / auto-merge loop on the engine repo is a
  deliberate non-goal. Decided 2026-06-17; revisit only with an explicit dogfood
  spec.
