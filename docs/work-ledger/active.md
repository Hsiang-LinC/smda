<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## mcp-missing-config-timeout
- status: blocked
- source: user report 2026-06-30: MCP server times out in repos without SMDA config
- acceptance: MCP startup works from the installed plugin cache under GUI-like PATH, and target repo config is checked lazily only when an SMDA tool is called
- verify: `uv run pytest packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_config.py packages/scheduler/tests/test_mcp.py -q` -> 34 passed; installed-cache MCP launcher returned `initialize` in 0.265s with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`; direct installed-cache missing-config tool call returned `isError: true` with `Config file not found` and exit 0; `codex mcp get smda` from `~` returns enabled with cache-root `cwd`; `~/.codex/config.toml` parses with `tomllib`; `git diff --check` clean
- next: human review can move this entry to `completed.md`
- updated: 2026-06-30
