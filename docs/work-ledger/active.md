<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## private-plugin-distribution-cd
- status: blocked
- source: `docs/superpowers/specs/2026-08-07-private-plugin-distribution-cd-design.md`; `docs/superpowers/plans/2026-08-07-private-plugin-distribution-cd.md`; approved conversation 2026-08-07
- blocked-by: none
- acceptance: a manually dispatched source-repo workflow validates the manifest version, builds and tests native arm64/x86_64 runtimes, and atomically publishes an installable complete plugin plus immutable version tag to a private `Hsiang-LinC/smda-plugin-dist` repository using a repository-scoped SSH deploy key; installation from that Git marketplace completes MCP initialize without Python or uv on PATH
- verify: private `Hsiang-LinC/smda-plugin-dist` exists on `main`; deploy key `smda source CD` is repository-scoped read-write and source Actions secret `SMDA_DIST_DEPLOY_KEY` exists. Packaging suite -> 31 passed; normalized scheduler suite with temporary `init.defaultBranch=master` and `ulimit -n 1024` -> 444 passed, 1 skipped; TypeScript -> 16 passed, 1 skipped; typecheck and diff check passed. The literal scheduler run reproduced the documented host assumptions (10 failed, 6 errors), and the sandboxed TypeScript run was denied a tsx IPC socket before its allowed rerun passed. Initial release dispatch was rejected at parse time because job-level `env` cannot use `runner.temp`; regression commit `e9f7951` moved SSH command setup into runner-time `GITHUB_ENV`. GitHub Actions run `31174360705` passed version validation, native arm64/x86_64 builds, assembly, and publish. Private distribution `main` and `v0.2.0` both resolve to `c9efadb4911fe3c390ddc0e3cb2fa021fd491058`; its 46 tree entries contain no allowlist violations, both native executables are mode `100755`, and both role schemas exist. Codex now installs `smda-automation@smda` version `0.2.0` from `/Users/danny/.codex/.tmp/marketplaces/smda` into `/Users/danny/.codex/plugins/cache/smda/smda-automation/0.2.0`; from `/private/tmp`, that cached MCP returned a JSON-RPC initialize result with a PATH containing `uname` but no Python, Python 3, or uv.
- next: ready-for-human — accept the private plugin distribution CD and move this entry to `completed.md`
- updated: 2026-08-07

## mcp-missing-config-timeout
- status: blocked
- source: user report 2026-06-30: MCP server times out in repos without SMDA config and from `~` in Codex CLI
- acceptance: MCP startup works from the installed plugin cache under Codex CLI stdio framing, and target repo config is checked lazily only when an SMDA tool is called
- verify: `uv run pytest packages/scheduler/tests/test_packaging.py packages/scheduler/tests/test_config.py packages/scheduler/tests/test_mcp.py -q` -> 35 passed; installed-cache newline-delimited JSON-RPC `initialize` returns a JSON response; installed-cache `Content-Length` initialize still returns a framed response; installed-cache newline-delimited `smda_status` missing-config call returns `isError: true` with `Config file not found`; `codex plugin remove smda-automation@smda && codex plugin add smda-automation@smda` refreshed `/Users/danny/.codex/plugins/cache/smda/smda-automation/0.1.0`; `codex --no-alt-screen` from `~` completed MCP startup without `smda` timeout
- next: ready-for-human review; human can move this entry to `completed.md`
- updated: 2026-06-30
