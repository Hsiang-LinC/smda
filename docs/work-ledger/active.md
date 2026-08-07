<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## private-plugin-distribution-cd
- status: in-progress
- source: `docs/superpowers/specs/2026-08-07-private-plugin-distribution-cd-design.md`; `docs/superpowers/plans/2026-08-07-private-plugin-distribution-cd.md`; approved conversation 2026-08-07
- blocked-by: none
- acceptance: a manually dispatched source-repo workflow validates the manifest version, builds and tests native arm64/x86_64 runtimes, and atomically publishes an installable complete plugin plus immutable version tag to a private `Hsiang-LinC/smda-plugin-dist` repository using a repository-scoped SSH deploy key; installation from that Git marketplace completes MCP initialize without Python or uv on PATH
- verify: workflow tests and repository product gates pass; the private distribution workflow succeeds; the published tag and main commit contain only approved distribution files; Codex installs the published plugin version from the private Git marketplace and its cached MCP server completes initialize without Python or uv on PATH
- next: provision the private distribution repository and repository-scoped deploy key
- updated: 2026-08-07

## mcp-missing-config-timeout
- status: blocked
- source: user report 2026-06-30: MCP server times out in repos without SMDA config and from `~` in Codex CLI
- acceptance: MCP startup works from the installed plugin cache under Codex CLI stdio framing, and target repo config is checked lazily only when an SMDA tool is called
- verify: `uv run pytest packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_config.py packages/scheduler/tests/test_mcp.py -q` -> 35 passed; installed-cache newline-delimited JSON-RPC `initialize` returns a JSON response; installed-cache `Content-Length` initialize still returns a framed response; installed-cache newline-delimited `smda_status` missing-config call returns `isError: true` with `Config file not found`; `codex plugin remove smda-automation@smda && codex plugin add smda-automation@smda` refreshed `/Users/danny/.codex/plugins/cache/smda/smda-automation/0.1.0`; `codex --no-alt-screen` from `~` completed MCP startup without `smda` timeout
- next: ready-for-human review; human can move this entry to `completed.md`
- updated: 2026-06-30
