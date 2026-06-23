<!-- codex-harness: generated 2026-06-17 -->
# Follow-ups

Known debt and opportunities. Entry format: see `docs/harness/index.md` § Conventions.

## parent-integration-conflict-recovery
- status: planned
- source: `docs/known-gaps.md` § 5 (Parent integration conflicts block instead
  of entering a resolver phase) and DANNY-70 child-006 acceptance recovery.
- next: design and implement the product-owned recovery path for parent
  integration git failures: first fix branch/range integration so multi-commit
  candidate branches preserve ancestry, then decide whether to add a bounded
  `parent-integration-conflict-resolver` role/phase for selected merge conflicts
  with verification and Human Review escalation.
- updated: 2026-06-19

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
