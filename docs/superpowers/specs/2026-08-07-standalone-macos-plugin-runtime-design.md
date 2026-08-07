---
status: approved
created_at: 2026-08-07
owner: agent
approved_at: 2026-08-07
approved_by: human
approval_evidence: conversation approval 2026-08-07 ("我們繼續往這兩個架構走")
---

# Standalone macOS Plugin Runtime

## Problem

The SMDA Scheduler is already modeled as a versioned runtime product, while
the Codex/Claude plugin is its installation and host-integration layer. The
plugin currently ships Python source and launches it through a host-provided
`python3`. That leaks the development runtime requirement into installation:
the installed cache can resolve an incompatible Python, fail before MCP
initialization, and leave the plugin unavailable even though the scheduler
source itself is valid.

The release boundary must match the product boundary. A plugin consumer should
receive an executable SMDA product, not source that depends on the consumer's
Python or uv installation.

## Scope

The first standalone release supports native macOS bundles for:

- `darwin-arm64`
- `darwin-x86_64`

Linux and Windows are out of scope. The existing bundled Sandcastle runner
continues to require a compatible external Node runtime; this design removes
the Python/uv prerequisite only.

## Product Boundary

One executable owns every product entrypoint:

```text
smda daemon
smda status
smda pause
smda resume
smda validate-config
smda mcp
```

The scheduler, CLI, daemon, and MCP implementation remain in the canonical
Python package. The plugin does not gain a second MCP implementation. It ships
the built product executable, registers `smda mcp`, and retains the setup skill
and host-specific manifests.

## Build Form

Use a native PyInstaller `onedir` build on each target architecture. `onedir`
avoids per-start extraction and keeps startup failures inspectable. The bundle
contains the CPython runtime, standard library, SMDA package, and package data
such as role schemas.

PyInstaller is a build-only dependency. Users do not install PyInstaller,
Python, uv, or a venv.

Each native runner produces:

```text
darwin-<arch>/smda/
├── smda
└── _internal/
```

The source repository ignores local PyInstaller work/output directories.
Release automation assembles both native outputs into one plugin artifact:

```text
plugins/smda-automation/runtime/bin/
├── darwin-arm64/smda/
└── darwin-x86_64/smda/
```

Generated binaries are release artifacts, not source-controlled files.

## Runtime Selection

The plugin keeps one POSIX shell launcher because a single plugin package
contains both architectures. The launcher:

1. requires `uname -s` to resolve `Darwin`;
2. maps `uname -m` values `arm64` and `x86_64` to the matching bundle;
3. executes the bundled `smda` with all original arguments;
4. fails with one actionable unsupported-platform or missing-bundle message.

It never searches for Python or uv. `.mcp.json` invokes the launcher with the
`mcp` argument. The same launcher is the documented installed-plugin CLI
entrypoint, so CLI and MCP cannot drift onto different runtimes.

## Build and Release Automation

A repository build script performs one native build. It validates macOS and
the native architecture, invokes PyInstaller with package-data collection,
places output under a caller-selected artifact root, and runs a smoke check.

GitHub Actions uses the current native runner labels:

- `macos-15` for arm64;
- `macos-15-intel` for x86_64.

Each job builds and verifies its native bundle. An assembly job downloads both
artifacts, inserts them under the plugin runtime layout, and uploads the complete
plugin artifact. The workflow is manually dispatchable until release signing
and publication policy are defined.

## Verification

Tests cover the release seam rather than the developer environment:

- the canonical package supports `python -m smda_scheduler`;
- the plugin manifest registers the shared launcher with `mcp`;
- the launcher selects arm64 and x86_64 paths and rejects unsupported systems;
- the launcher succeeds with a deliberately minimal `PATH` that contains no
  Python or uv when a native test executable is supplied;
- the native PyInstaller bundle completes newline-delimited MCP `initialize`;
- the standalone CLI can read bundled package data;
- existing scheduler, MCP framing, plugin parity, TypeScript, and type-check
  gates remain green.

## Alternatives Rejected

### Continue with a Python/uv resolver

Smallest local fix, but still transfers runtime provisioning to every plugin
consumer and fails when neither a compatible Python nor uv is present.

### PyInstaller `onefile`

Produces a tidier single file but extracts on every MCP startup, increasing
latency and adding a new temporary-directory failure mode.

### Rewrite the MCP shell in Node

Only moves the protocol adapter. The scheduler core remains Python, so a Node
MCP would still spawn Python and would add process/serialization complexity
without removing the prerequisite.

## Out of Scope

- Linux or Windows artifacts.
- Removing the Sandcastle runner's Node requirement.
- A GUI or macOS `.app` bundle.
- Apple Developer ID signing, notarization, and automated marketplace release.
- Shipping generated binaries in Git history.

## Acceptance Criteria

- Native arm64 and x86_64 macOS jobs each build an executable SMDA `onedir`
  bundle.
- One assembled plugin artifact contains both bundles and selects the host
  architecture at runtime.
- Codex starts the plugin's MCP server through `smda mcp` without Python or uv
  on the consumer PATH.
- Installed-plugin CLI commands and MCP use the same executable and bundled
  package data.
- Unsupported platforms and missing artifacts fail immediately with actionable
  errors.
- No scheduler or MCP business logic is duplicated into the plugin layer.
