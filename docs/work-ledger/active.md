<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## difficulty-aware-model-selection
- status: blocked
- parent: product-hardening
- source: `docs/known-gaps.md` "Future idea: difficulty-aware model selection"
- blocked-by: none
- acceptance: role attempts can resolve a config-driven role-specific
  `AgentSelection` while preserving the default execution agent for roles with
  no override; the selected provider/model/effort remains recorded on each
  attempt request.
- verify: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_config.py packages/scheduler/tests/test_role_attempts.py
  packages/scheduler/tests/test_runtime_factory.py -q` -> 32 passed;
  `npm run plugin:sync-runtime` -> passed; `UV_CACHE_DIR=/private/tmp/smda-uv-cache
  uv run pytest packages/scheduler/tests/test_packaging.py -q` -> 14 passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests
  -q` -> 380 passed, 1 skipped.
- next: human review; then move to `docs/work-ledger/completed.md`.
- updated: 2026-06-27
