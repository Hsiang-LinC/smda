---
status: approved
created_at: 2026-08-07
owner: agent
approved_at: 2026-08-07
approved_by: human
approval_evidence: conversation approval 2026-08-07
---

# Private Plugin Distribution CD

## Problem

The source repository can build and assemble a dual-architecture standalone
SMDA plugin, but GitHub Actions artifacts are temporary build outputs rather
than a Codex marketplace. The verified local installation required manually
downloading the artifact and staging `runtime/bin/` into a local marketplace.
Other authorized users cannot install the complete product directly from a Git
marketplace.

The release boundary must remain separate from the source boundary. The source
repository owns code, tests, and builds; a dedicated distribution repository
must contain only the complete installable plugin.

## Scope

Create a private GitHub repository named `Hsiang-LinC/smda-plugin-dist` and
extend the existing manually dispatched build workflow to publish verified
plugin releases to it.

The first CD release remains manually triggered. Tag-driven releases, public
visibility, signing, notarization, Linux, and Windows remain out of scope.

## Repository Boundaries

`Hsiang-LinC/smda` remains the source of truth for:

- scheduler, daemon, CLI, and MCP source;
- the Codex and Claude Code plugin source;
- tests and build scripts;
- CI/CD workflow definitions.

`Hsiang-LinC/smda-plugin-dist` contains only:

```text
.agents/plugins/marketplace.json
.claude-plugin/marketplace.json
README.md
plugins/smda-automation/
├── .codex-plugin/plugin.json
├── .claude-plugin/plugin.json
├── .mcp.json
├── skills/
└── runtime/
    ├── smda
    ├── js/sandcastle-runner.mjs
    └── bin/
        ├── darwin-arm64/smda/
        └── darwin-x86_64/smda/
```

The distribution repository never receives Python source, tests, `.venv`,
`node_modules`, PyInstaller work files, or the source repository history.

## Release Identity

Manual workflow dispatch accepts one required semantic version input such as
`0.2.1`. Before any build, the workflow reads
`plugins/smda-automation/.codex-plugin/plugin.json` and requires its version to
match the input exactly. The Claude Code plugin manifest must carry the same
version.

The distribution `main` branch always holds the latest published version. Each
release also creates an immutable `v<version>` Git tag. An existing tag is an
error and is never overwritten. Rollback is performed by publishing a new patch
version, not by moving a tag.

## Authentication and Authorization

Use one new ED25519 SSH deploy key dedicated to
`Hsiang-LinC/smda-plugin-dist`:

- the public key is registered on the distribution repository with write
  access;
- the private key is stored only as the source repository Actions secret
  `SMDA_DIST_DEPLOY_KEY`;
- the key has no passphrase because the non-interactive runner cannot supply
  one;
- the key does not grant access to other repositories;
- the workflow never prints private-key material;
- local temporary private-key files are deleted after the GitHub secret is
  confirmed.

The existing personal SSH keys and the workflow's repository-scoped
`GITHUB_TOKEN` are not reused for cross-repository publication.

## Workflow Data Flow

The existing GitHub Actions workflow remains the single release pipeline:

```text
manual workflow dispatch(version)
  -> validate Codex and Claude manifest versions
  -> build and smoke-test darwin-arm64
  -> build and smoke-test darwin-x86_64
  -> assemble complete plugin artifact
  -> verify manifests, both executables, and package data
  -> clone private distribution repository with deploy key
  -> replace only approved distribution paths
  -> commit and create v<version> tag
  -> atomically push main and the tag
```

Native bundles continue to travel between jobs inside tar archives so GitHub
artifact transport cannot discard executable permissions.

The publish job explicitly copies the source repository's Codex and Claude
marketplace manifests, a distribution-specific README, and the assembled
plugin. It does not copy the source checkout wholesale.

## Failure Handling

- Version mismatch fails before native runners are started.
- Any build, package-data, CLI, or MCP smoke failure prevents publication.
- Missing or invalid deploy-key authentication fails without changing the
  distribution repository.
- An existing release tag fails before staging a new release.
- Missing native executables or lost executable bits fail before commit.
- `git push --atomic` publishes the `main` update and release tag together or
  publishes neither.
- A rerun of an already published version is rejected rather than overwriting
  history.

## Consumer Flow

During the private phase, an authorized GitHub user configures the Git
marketplace and installs the plugin:

```bash
codex plugin marketplace add git@github.com:Hsiang-LinC/smda-plugin-dist.git
codex plugin add smda-automation@smda
```

Codex copies the complete selected plugin into its versioned cache. The plugin
manifest registers `runtime/smda mcp`; the launcher selects the native bundled
runtime. Neither Python nor uv is required on the consumer PATH. The bundled
Sandcastle runner continues to require compatible Node.

When the distribution repository becomes public, the marketplace may switch to
an HTTPS URL without changing the plugin contents or runtime architecture.

## Verification

Repository tests cover:

- required manual version input;
- exact Codex/Claude manifest version validation;
- publication gated on both native build jobs and assembly;
- use of `SMDA_DIST_DEPLOY_KEY` only in the publish job;
- explicit distribution allowlist and atomic push;
- rejection of an existing tag.

Live release verification covers:

- the private distribution workflow completes successfully;
- `main` and `v<version>` resolve to the same release commit;
- the distribution tree contains only approved paths;
- arm64 and x86_64 bundles and role schema data are present;
- Codex installs the published version from the private Git marketplace;
- the installed cache completes newline-delimited MCP `initialize` from outside
  the source repository with no Python or uv on PATH.

Existing Python scheduler, plugin packaging, TypeScript, typecheck, and diff
quality gates remain green.

## Alternatives Rejected

### Fine-grained personal access token

Simpler to bootstrap, but tied to a user account and its token lifetime. A
repository-scoped deploy key grants less authority for this one-to-one publish
path.

### GitHub App

Best for a multi-repository organization or service, but adds installation,
token minting, and maintenance that this two-repository release path does not
need.

### Commit binaries to the source repository

Would make the existing local marketplace immediately installable, but mixes
generated release payloads into source history and scales poorly as platforms
and versions accumulate.

### Publish only a GitHub Actions or Release artifact

Appropriate binary storage, but the current Codex plugin CLI installs from
configured marketplace snapshots rather than directly from arbitrary tar
assets. The distribution repository is the compatibility adapter for that
installation model.

## Out of Scope

- Public distribution repository visibility.
- Apple Developer ID signing and notarization.
- Automatic tag-triggered publication.
- Linux or Windows runtime bundles.
- Bundling or removing the external Node runtime requirement.
- Automatic deletion or rewriting of distribution history.

## Acceptance Criteria

- A private `Hsiang-LinC/smda-plugin-dist` repository exists with only the
  approved distribution layout.
- A repository-scoped writable deploy key publishes without using a personal
  token or personal SSH key.
- Manual publication refuses version drift and existing tags.
- Native arm64 and x86_64 builds and smoke checks gate publication.
- One atomic push updates distribution `main` and creates `v<version>`.
- Codex installs the complete published plugin from the private Git marketplace.
- The installed MCP server initializes without Python or uv on PATH.
