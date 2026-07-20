<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## unattended-convergence-runtime-foundation
- status: in-progress
- parent: unattended-request-convergence
- source: `docs/superpowers/plans/2026-07-12-unattended-convergence-runtime-foundation.md`
- blocked-by: none
- acceptance: implement Tasks 1-7 so Workflow Definitions own Parent Role facts, Workflow Graph Artifacts are complete and typed, Attempt History is semantic, Parent/Roadmap transitions are expected-phase fenced, and Backlog Projection enqueue is atomic
- verify: both Task 7 architecture guards returned zero matches; scheduler suite `433 passed, 1 skipped`; TypeScript suite `15 passed, 1 skipped`; `npm run typecheck`, `npm run schema:export`, and `git diff --check` exited 0; explicit source/plugin and JavaScript bundle parity `2 passed`; focused atomic rollback, stale-phase, and structural evidence `7 passed`
- next: atomically include Roadmap members/edges in the fenced decomposition transition; rerun product gates and whole-branch review
- updated: 2026-07-20

## mcp-missing-config-timeout
- status: blocked
- source: user report 2026-06-30: MCP server times out in repos without SMDA config and from `~` in Codex CLI
- acceptance: MCP startup works from the installed plugin cache under Codex CLI stdio framing, and target repo config is checked lazily only when an SMDA tool is called
- verify: `uv run pytest packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_config.py packages/scheduler/tests/test_mcp.py -q` -> 35 passed; installed-cache newline-delimited JSON-RPC `initialize` returns a JSON response; installed-cache `Content-Length` initialize still returns a framed response; installed-cache newline-delimited `smda_status` missing-config call returns `isError: true` with `Config file not found`; `codex plugin remove smda-automation@smda && codex plugin add smda-automation@smda` refreshed `/Users/danny/.codex/plugins/cache/smda/smda-automation/0.1.0`; `codex --no-alt-screen` from `~` completed MCP startup without `smda` timeout
- next: ready-for-human review; human can move this entry to `completed.md`
- updated: 2026-06-30
