<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## private-plugin-distribution-cd
- status: in-progress
- source: `docs/superpowers/specs/2026-08-07-private-plugin-distribution-cd-design.md`; `docs/superpowers/plans/2026-08-07-private-plugin-distribution-cd.md`; approved conversation 2026-08-07
- blocked-by: standalone-macos-plugin-runtime
- acceptance: a manually dispatched source-repo workflow validates the manifest version, builds and tests native arm64/x86_64 runtimes, and atomically publishes an installable complete plugin plus immutable version tag to a private `Hsiang-LinC/smda-plugin-dist` repository using a repository-scoped SSH deploy key; installation from that Git marketplace completes MCP initialize without Python or uv on PATH
- verify: workflow tests and repository product gates pass; the private distribution workflow succeeds; the published tag and main commit contain only approved distribution files; Codex installs the published plugin version from the private Git marketplace and its cached MCP server completes initialize without Python or uv on PATH
- next: ready-for-human — review the implementation plan, then execute it after accepting the standalone runtime blocker
- updated: 2026-08-07

## standalone-macos-plugin-runtime
- status: blocked
- source: `docs/superpowers/specs/2026-08-07-standalone-macos-plugin-runtime-design.md`; `docs/superpowers/plans/2026-08-07-standalone-macos-plugin-runtime.md`; approved conversation 2026-08-07
- blocked-by: none
- acceptance: SMDA builds as a standalone macOS executable for arm64 and x86_64; the Codex plugin registers `smda mcp` from the bundled executable without requiring user Python or uv; unsupported platforms fail with an actionable message; CLI and MCP use the same product executable
- verify: local `darwin-x86_64` PyInstaller build plus bundled CLI/schema and newline MCP initialize smoke checks passed; packaging 29 passed; normalized full suite 442 passed, 1 skipped; TypeScript 16 passed, 1 skipped; typecheck and diff check passed. Workflow run `31163888915` passed native arm64, native x86_64, and plugin assembly jobs; the downloaded artifact contains executable Mach-O bundles for both architectures, bundled Python 3.12, and role schema data. Codex installed `smda-automation@smda` version `0.2.0` into its cache, and the cached launcher completed MCP initialize from `/private/tmp` with a PATH containing no Python or uv. Earlier run `31163767307` failed before build on the nonexistent `setup-uv@v9` tag; regression coverage now pins the official immutable v8.1.0 commit. The literal full-suite command first reported 425 passed, 1 skipped, 11 failed, 6 errors because this host uses Git `main` while legacy tests assume `master`, and its 256-FD limit exhausts existing SQLite handles; isolated Git tests pass with a temporary `init.defaultBranch=master`, and the full suite passes with that config plus `ulimit -n 1024`.
- next: ready-for-human — accept the verified standalone macOS plugin runtime and move this entry to `completed.md`
- updated: 2026-08-07

## mcp-missing-config-timeout
- status: blocked
- source: user report 2026-06-30: MCP server times out in repos without SMDA config and from `~` in Codex CLI
- acceptance: MCP startup works from the installed plugin cache under Codex CLI stdio framing, and target repo config is checked lazily only when an SMDA tool is called
- verify: `uv run pytest packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_config.py packages/scheduler/tests/test_mcp.py -q` -> 35 passed; installed-cache newline-delimited JSON-RPC `initialize` returns a JSON response; installed-cache `Content-Length` initialize still returns a framed response; installed-cache newline-delimited `smda_status` missing-config call returns `isError: true` with `Config file not found`; `codex plugin remove smda-automation@smda && codex plugin add smda-automation@smda` refreshed `/Users/danny/.codex/plugins/cache/smda/smda-automation/0.1.0`; `codex --no-alt-screen` from `~` completed MCP startup without `smda` timeout
- next: ready-for-human review; human can move this entry to `completed.md`
- updated: 2026-06-30
