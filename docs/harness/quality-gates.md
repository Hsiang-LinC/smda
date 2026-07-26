<!-- codex-harness: generated 2026-06-23 -->
# Quality Gates

Last verified: 2026-07-26

Completion evidence must name the command run and the observed outcome. Pick the
smallest gate set that covers the touched surface, then run `git diff --check`
before reporting completion.

## Cheap Harness Checks

- `git diff --check`
- `test -f docs/harness/index.md`
- `test -f docs/harness/tracker.md`
- `test -f docs/harness/roadmap.md`
- `test -f docs/harness/quality-gates.md`
- `test -f docs/work-ledger/active.md`
- `test -f docs/work-ledger/completed.md`
- `test -f docs/work-ledger/abandoned.md`

## Product Gates

- Python scheduler: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q`
- TypeScript runtime/schema surface: `npm run test:ts`
- Type checking: `npm run typecheck`
- Schema parity: `npm run schema:export`
- Plugin runtime parity, when scheduler or Sandcastle runner source changes:
  `npm run plugin:sync-runtime`, then
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py -q`

Use targeted tests first when shaping or debugging. Run the broader product gate
set before moving implementation entries to `completed.md`, unless the tracker
entry names a narrower accepted gate and explains why it is sufficient.
