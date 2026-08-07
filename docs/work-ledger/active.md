<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## standalone-macos-plugin-runtime
- status: in-progress
- source: `docs/superpowers/specs/2026-08-07-standalone-macos-plugin-runtime-design.md`; approved conversation 2026-08-07
- blocked-by: none
- acceptance: SMDA builds as a standalone macOS executable for arm64 and x86_64; the Codex plugin registers `smda mcp` from the bundled executable without requiring user Python or uv; unsupported platforms fail with an actionable message; CLI and MCP use the same product executable
- verify: targeted packaging tests pass; a clean-environment MCP `initialize` succeeds without Python or uv on PATH; `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q`, `npm run test:ts`, `npm run typecheck`, and `git diff --check` pass
- next: write and self-review the implementation plan, then implement the macOS packaging slice with TDD
- updated: 2026-08-07

## mcp-missing-config-timeout
- status: blocked
- source: user report 2026-06-30: MCP server times out in repos without SMDA config and from `~` in Codex CLI
- acceptance: MCP startup works from the installed plugin cache under Codex CLI stdio framing, and target repo config is checked lazily only when an SMDA tool is called
- verify: `uv run pytest packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_config.py packages/scheduler/tests/test_mcp.py -q` -> 35 passed; installed-cache newline-delimited JSON-RPC `initialize` returns a JSON response; installed-cache `Content-Length` initialize still returns a framed response; installed-cache newline-delimited `smda_status` missing-config call returns `isError: true` with `Config file not found`; `codex plugin remove smda-automation@smda && codex plugin add smda-automation@smda` refreshed `/Users/danny/.codex/plugins/cache/smda/smda-automation/0.1.0`; `codex --no-alt-screen` from `~` completed MCP startup without `smda` timeout
- next: ready-for-human review; human can move this entry to `completed.md`
- updated: 2026-06-30
