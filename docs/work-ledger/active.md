<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## live-codex-safe-directory-config-race
- status: blocked
- parent: live-integration-validation
- source: 2026-06-29 live daemon tick against trading-advisor
- blocked-by: none
- acceptance: concurrent live Codex/Sandcastle child attempts do not fail when
  registering `safe.directory`; no attempt reports `could not lock config file
  /Users/danny/.gitconfig`.
- verify: `npm run test:ts` -> 15 passed, 1 skipped, including simulated
  parallel Sandcastle attempts with distinct attempt-scoped git config paths;
  `npm run typecheck` -> passed; `npm run schema:export` -> passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py -q` -> 14 passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests -q` -> 385 passed, 1 skipped;
  `git diff --check` -> passed.
- next: human review; on `reviewed`, archive to completed work.
- updated: 2026-06-29
