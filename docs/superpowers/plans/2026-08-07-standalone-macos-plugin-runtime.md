# Standalone macOS Plugin Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one macOS plugin artifact containing native arm64 and x86_64 standalone SMDA runtimes, with both CLI and MCP routed through the same executable and no consumer Python or uv requirement.

**Architecture:** The canonical Python package gains a module entrypoint and is frozen as a PyInstaller `onedir` application on each native macOS runner. The plugin contains only a POSIX architecture selector, the two generated release bundles, the existing Sandcastle JavaScript runner, setup skill, and manifests; `.mcp.json` calls the selector with `mcp`.

**Tech Stack:** Python 3.12+, PyInstaller `onedir`, POSIX shell, pytest, GitHub Actions macOS runners

## Global Constraints

- Support only `darwin-arm64` and `darwin-x86_64` in this slice.
- Bundle CPython, the standard library, SMDA code, and `smda_scheduler` package data.
- Keep PyInstaller build-only; consumers install neither Python, uv, nor a venv.
- Keep the external Node requirement for the bundled Sandcastle runner.
- Use one executable for `smda daemon`, operator CLI commands, and `smda mcp`.
- Do not duplicate scheduler or MCP business logic in the plugin.
- Do not commit generated native bundles, PyInstaller work directories, or spec files.
- Signing, notarization, Linux, Windows, GUI packaging, and automated publication remain out of scope.

---

## File Map

- Create `packages/scheduler/src/smda_scheduler/__main__.py`: canonical module/frozen entrypoint that delegates to `cli.main`.
- Create `plugins/smda-automation/runtime/smda`: POSIX selector for the bundled native runtime.
- Create `scripts/build_standalone_runtime.py`: validate the native macOS host, run PyInstaller, and smoke-test CLI package data plus MCP initialization.
- Create `.github/workflows/build-plugin-runtime.yml`: build both native bundles and assemble the plugin artifact.
- Modify `packages/scheduler/tests/test_packaging.py`: assert module entrypoint, launcher behavior, plugin contract, build command, workflow, docs, and version.
- Modify `scripts/sync_plugin_runtime.py`: stop copying Python source; retain only the Sandcastle bundle sync.
- Modify `pyproject.toml` and `uv.lock`: add PyInstaller to the development dependency group and expose the `smda` console command.
- Modify plugin manifests, `.mcp.json`, README, daemon operations docs, and `.gitignore`: describe and route the standalone release.
- Delete the three legacy Python-dependent plugin wrappers and the copied `runtime/python/smda_scheduler` tree.

### Task 1: Canonical executable entrypoint

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/__main__.py`
- Modify: `pyproject.toml`
- Test: `packages/scheduler/tests/test_packaging.py`

**Interfaces:**
- Consumes: `smda_scheduler.cli.main(argv: Sequence[str] | None = None) -> int`
- Produces: `python -m smda_scheduler ...` and console script `smda = "smda_scheduler.cli:main"`

- [ ] **Step 1: Write failing tests**

Add assertions that `pyproject.toml` exposes `smda`, and run `python -m smda_scheduler validate-config ...` against the existing clean-ledger fixture.

- [ ] **Step 2: Verify RED**

Run: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py -k 'module_entrypoint or console_script' -q`

Expected: FAIL because `smda_scheduler.__main__` and the `smda` script do not exist.

- [ ] **Step 3: Implement the minimum entrypoint**

```python
from smda_scheduler.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `smda = "smda_scheduler.cli:main"` while retaining the old script as a compatibility alias.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 pytest command; expect PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add canonical smda executable entrypoint`

### Task 2: Plugin runtime selector and source removal

**Files:**
- Create: `plugins/smda-automation/runtime/smda`
- Modify: `plugins/smda-automation/.mcp.json`
- Modify: `scripts/sync_plugin_runtime.py`
- Modify: `plugins/smda-automation/skills/setup-smda-automation/daemon-operations.md`
- Delete: `plugins/smda-automation/runtime/smda-scheduler-cli.py`
- Delete: `plugins/smda-automation/runtime/smda-scheduler-mcp.py`
- Delete: `plugins/smda-automation/runtime/smda-scheduler-mcp.sh`
- Delete: `plugins/smda-automation/runtime/python/smda_scheduler/**`
- Test: `packages/scheduler/tests/test_packaging.py`

**Interfaces:**
- Consumes: plugin-relative `runtime/bin/darwin-{arm64,x86_64}/smda/smda`
- Produces: `runtime/smda <all original arguments>` and `.mcp.json` args `['./runtime/smda', 'mcp']`

- [ ] **Step 1: Replace legacy packaging assertions with failing release-seam tests**

The tests copy the selector into a temporary plugin fixture, provide fake `uname` plus executable fixture bundles, and assert arm64/x86_64 selection, exact argument forwarding, missing-bundle failure, unsupported-platform failure, and success with a `PATH` containing no Python or uv. Also assert the source-copy tree/wrappers are absent and `sync_plugin_runtime.py` only bundles Sandcastle.

- [ ] **Step 2: Verify RED**

Run: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py -k 'plugin_runtime or product_owned_mcp or runtime_copy' -q`

Expected: FAIL because `.mcp.json` and the existing launcher still select host Python and copied source exists.

- [ ] **Step 3: Implement the selector and remove Python source syncing**

Use `uname -s`/`uname -m`, map only Darwin arm64 and x86_64, verify the selected `smda` is executable, then `exec "$runtime" "$@"`. Emit one actionable stderr line for unsupported hosts and one for missing artifacts. Change sync `main()` to call only `bundle_sandcastle_runner()` and delete the obsolete copy function/constants and plugin Python runtime files.

- [ ] **Step 4: Update MCP and operator docs**

Set `.mcp.json` to command `sh`, args `['./runtime/smda', 'mcp']`, cwd `.`. Document `./runtime/smda status ...` and `./runtime/smda mcp` as the installed-plugin surfaces.

- [ ] **Step 5: Verify GREEN**

Run the Task 2 pytest command and `npm run plugin:sync-runtime`; expect PASS and only the JavaScript artifact to be rebuilt.

- [ ] **Step 6: Commit**

Commit message: `feat: route plugin through standalone smda runtime`

### Task 3: Native PyInstaller build and smoke verification

**Files:**
- Create: `scripts/build_standalone_runtime.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.gitignore`
- Test: `packages/scheduler/tests/test_packaging.py`

**Interfaces:**
- Consumes: `--output-root PATH`, native `platform.system()` and `platform.machine()`, `python -m PyInstaller`
- Produces: `<output-root>/darwin-<arch>/smda/smda`

- [ ] **Step 1: Write failing build-contract tests**

Import the build script and assert `platform_tag('Darwin', 'arm64')`, `platform_tag('Darwin', 'x86_64')`, rejection of other values, and a PyInstaller command containing `--onedir`, `--collect-data smda_scheduler`, package source path, entrypoint path, and caller-selected output root.

- [ ] **Step 2: Verify RED**

Run: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py -k standalone_build -q`

Expected: FAIL because the build module does not exist.

- [ ] **Step 3: Implement the build script**

Use only stdlib orchestration. Build into `build/pyinstaller`, emit the native `onedir` under the requested root, then run:

1. the frozen executable against a generated minimal config to exercise bundled `schemas/role_schemas.v1.json`;
2. newline-delimited JSON-RPC `initialize` through `smda mcp`, requiring a valid response and zero exit status.

- [ ] **Step 4: Add the build dependency and ignores**

Add `pyinstaller>=6.0` to the dev group, refresh `uv.lock`, and ignore `/build/`, `/dist/`, `*.spec`, and `plugins/smda-automation/runtime/bin/`.

- [ ] **Step 5: Verify GREEN and build the current architecture**

Run the Task 3 pytest command, then:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run python scripts/build_standalone_runtime.py --output-root /private/tmp/smda-standalone
```

Expected: tests PASS and the native x86_64 bundle completes both smoke checks on the current host.

- [ ] **Step 6: Commit**

Commit message: `build: package native standalone smda runtime`

### Task 4: Dual-architecture artifact assembly and release identity

**Files:**
- Create: `.github/workflows/build-plugin-runtime.yml`
- Modify: `plugins/smda-automation/.codex-plugin/plugin.json`
- Modify: `plugins/smda-automation/.claude-plugin/plugin.json`
- Modify: `README.md`
- Modify: `packages/scheduler/tests/test_packaging.py`
- Modify: `docs/work-ledger/active.md`

**Interfaces:**
- Consumes: native build artifacts from `macos-15` and `macos-15-intel`
- Produces: one uploaded `smda-automation` plugin directory with both runtime trees

- [ ] **Step 1: Write failing workflow/release tests**

Assert the workflow is manually dispatchable, uses `macos-15` for arm64 and `macos-15-intel` for x86_64, invokes the build script in each job, assembles both exact runtime paths, and uploads the complete plugin. Assert the Codex plugin version is `0.2.0` and both manifest descriptions say standalone runtime rather than host Python.

- [ ] **Step 2: Verify RED**

Run: `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests/test_packaging.py -k 'workflow or plugin_version' -q`

Expected: FAIL because no workflow exists and the plugin version remains `0.1.0`.

- [ ] **Step 3: Add the two-build/one-assembly workflow**

Use two explicit native jobs so runner-to-architecture mapping is auditable. Each installs uv, syncs dev dependencies, runs the build script, and uploads its native directory. The assembly job downloads both, copies them under `plugins/smda-automation/runtime/bin/`, asserts both executables exist, and uploads the plugin directory.

- [ ] **Step 4: Update release identity and README**

Bump the plugin to `0.2.0` so caches cannot reuse the Python-dependent `0.1.0` payload. Describe the standalone macOS scope, shared CLI/MCP entrypoint, retained Node prerequisite, unsigned/unnotarized state, and manual artifact workflow.

- [ ] **Step 5: Run full verification**

Run:

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q
npm run test:ts
npm run typecheck
git diff --check
```

Expected: all commands pass.

- [ ] **Step 6: Record tracker evidence**

Keep `standalone-macos-plugin-runtime` out of `completed.md` because the author cannot self-accept. Update its source to include this plan, record exact local verification evidence, and set `next:` to human review plus a GitHub Actions arm64/x86_64 run.

- [ ] **Step 7: Commit**

Commit message: `ci: assemble dual-architecture smda plugin`
