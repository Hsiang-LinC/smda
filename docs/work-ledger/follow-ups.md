<!-- codex-harness: generated 2026-06-17 -->
# Follow-ups

Known debt and opportunities. Entry format: see `docs/harness/index.md` § Conventions.

## live-codex-safe-directory-config-race
- status: planned
- parent: live-integration-validation
- source: 2026-06-29 live daemon tick against trading-advisor
- blocked-by: none
- acceptance: concurrent live Codex/Sandcastle child attempts do not fail when
  registering `safe.directory`; no attempt reports `could not lock config file
  /Users/danny/.gitconfig`.
- verify: run a live or simulated parallel dispatch with at least two Codex
  Sandcastle attempts; both attempts either succeed or fail for task-local
  reasons, not global gitconfig lock contention.
- next: isolate or serialize `safe.directory` registration for live Codex
  Sandcastle attempts.
- updated: 2026-06-29
