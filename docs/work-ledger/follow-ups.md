<!-- codex-harness: generated 2026-06-17 -->
# Follow-ups

Known debt and opportunities. Entry format: see `docs/harness/index.md` § Conventions.

## auto-follow-up-issue-for-concerns
- status: planned
- source: `docs/known-gaps.md` "Future idea: auto follow-up issue for deferred concerns"
- next: design a config-gated path where a `DONE_WITH_CONCERNS` verdict opens a
  low-priority follow-up child/backlog issue carrying the concern report
  (reuses child-publication + tracker-effect machinery).
- updated: 2026-06-17

## difficulty-aware-model-selection
- status: planned
- source: `docs/known-gaps.md` "Future idea: difficulty-aware model selection"
- next: resolve `AgentSelection` per attempt from a config-driven
  role/difficulty → model map instead of one fixed value threaded through the tick.
- updated: 2026-06-17

## force-phase-operator-command
- status: planned
- source: `docs/known-gaps.md` § Operator / manual intervention model (thin spot)
- next: add an `advance` / `force-phase` operator CLI to clear a
  `HUMAN_REVIEW_REQUIRED` parking state without editing tracker inputs by hand.
- updated: 2026-06-17
