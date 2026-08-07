# Private Plugin Distribution CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a complete, dual-architecture SMDA plugin from the source repository to a private Git marketplace through one manually dispatched, versioned GitHub Actions workflow.

**Architecture:** Keep build truth in `Hsiang-LinC/smda` and release payloads in `Hsiang-LinC/smda-plugin-dist`. The existing workflow validates one manifest version, builds both native runtimes, assembles one plugin tarball, then uses a repository-scoped SSH deploy key to replace an explicit distribution allowlist and atomically push `main` plus an immutable version tag.

**Tech Stack:** GitHub Actions, POSIX shell, Git/SSH deploy keys, Codex plugin marketplace, pytest

## Global Constraints

- Do not publish until `standalone-macos-plugin-runtime` has explicit human acceptance and is moved from `active.md` to `completed.md`.
- Keep the source repository private and the distribution repository private.
- Put `SMDA_DIST_DEPLOY_KEY` only in the publish step environment; never print it.
- Publish only `.agents/plugins/marketplace.json`, `.claude-plugin/marketplace.json`, `README.md`, and `plugins/smda-automation/`.
- Reject manifest drift and an existing `v<version>` tag before changing distribution history.
- Preserve executable bits with tar archives and use `git push --atomic` for `main` and the tag.
- Do not add a release framework, custom action, Python package, PAT, or GitHub App.

---

## File Map

- Modify: `docs/work-ledger/active.md` — dependency transition, implementation evidence, and review handoff.
- Modify: `docs/work-ledger/completed.md` — accepted standalone-runtime item.
- Modify: `.github/workflows/build-plugin-runtime.yml` — version input, metadata gate, dynamic artifact identity, and private publication.
- Create: `distribution/README.md` — consumer-facing contents for the distribution repository.
- Modify: `packages/scheduler/tests/test_packaging.py` — smallest static regression checks for the release contract.

### Task 1: Clear the accepted runtime dependency

**Files:**
- Modify: `docs/work-ledger/active.md`
- Modify: `docs/work-ledger/completed.md`

- [ ] **Step 1: Confirm the blocking human decision**

Record explicit user acceptance of `standalone-macos-plugin-runtime`. Do not infer acceptance from passing tests.

- [ ] **Step 2: Move the tracker entry without rewriting it**

Move the complete `standalone-macos-plugin-runtime` entry from `active.md` to `completed.md`, change its status to `done`, set `next: none`, and append the human acceptance evidence and date. Keep `private-plugin-distribution-cd` active and remove its resolved `blocked-by` value.

- [ ] **Step 3: Verify the tracker edit**

Run:

```bash
rg -n "private-plugin-distribution-cd|standalone-macos-plugin-runtime|blocked-by|status:" docs/work-ledger/active.md docs/work-ledger/completed.md
git diff --check
```

Expected: standalone runtime appears only in `completed.md`; private CD remains `in-progress` with no unresolved dependency; diff check exits 0.

- [ ] **Step 4: Commit**

```bash
git add docs/work-ledger/active.md docs/work-ledger/completed.md
git commit -m "docs: accept standalone plugin runtime"
```

### Task 2: Provision the private publication boundary

**External state:**
- Create: GitHub repository `Hsiang-LinC/smda-plugin-dist`
- Create: writable deploy key on `Hsiang-LinC/smda-plugin-dist`
- Create: Actions secret `SMDA_DIST_DEPLOY_KEY` on `Hsiang-LinC/smda`

- [ ] **Step 1: Verify the exact GitHub CLI operations before mutation**

Run:

```bash
gh auth status
gh repo view Hsiang-LinC/smda-plugin-dist
gh repo deploy-key add --help
gh secret set --help
```

Expected: authentication succeeds; `repo view` reports that the not-yet-created repository is absent; help confirms `--allow-write`, `--repo`, and secret stdin support. If the repository already exists, inspect its visibility, default branch, tree, and deploy keys before continuing instead of recreating it.

- [ ] **Step 2: Create the private distribution repository**

```bash
gh repo create Hsiang-LinC/smda-plugin-dist \
  --private \
  --add-readme \
  --description "Private installable distributions of the SMDA plugin"
gh repo view Hsiang-LinC/smda-plugin-dist --json nameWithOwner,visibility,defaultBranchRef
```

Expected: `visibility` is `PRIVATE` and the default branch is `main`.

- [ ] **Step 3: Generate and install the repository-scoped key**

Run from a shell with `set -e`:

```bash
SMDA_KEY_DIR="$(mktemp -d)"
trap 'rm -rf "$SMDA_KEY_DIR"' EXIT
ssh-keygen -t ed25519 -N '' \
  -C 'smda-plugin-dist GitHub Actions deploy key' \
  -f "$SMDA_KEY_DIR/smda-plugin-dist"
gh repo deploy-key add "$SMDA_KEY_DIR/smda-plugin-dist.pub" \
  --repo Hsiang-LinC/smda-plugin-dist \
  --title 'smda source CD' \
  --allow-write
gh secret set SMDA_DIST_DEPLOY_KEY \
  --repo Hsiang-LinC/smda \
  < "$SMDA_KEY_DIR/smda-plugin-dist"
gh repo deploy-key list --repo Hsiang-LinC/smda-plugin-dist
gh secret list --repo Hsiang-LinC/smda
```

Expected: one writable deploy key named `smda source CD` exists and the source repository lists `SMDA_DIST_DEPLOY_KEY`. Do not display the private key. The `EXIT` trap deletes the only local temporary copy; GitHub does not permit recovering it, so rotation means creating a new key.

### Task 3: Add the versioned release contract

**Files:**
- Modify: `packages/scheduler/tests/test_packaging.py`
- Modify: `.github/workflows/build-plugin-runtime.yml`
- Create: `distribution/README.md`

- [ ] **Step 1: Write the failing workflow contract test**

Extend `test_standalone_runtime_workflow_builds_and_assembles_both_architectures` with direct assertions for the required input, metadata job, dynamic artifact name, and both manifests:

```python
assert "version:" in workflow
assert "required: true" in workflow
assert "validate-release:" in workflow
assert 'plugins/smda-automation/.codex-plugin/plugin.json' in workflow
assert 'plugins/smda-automation/.claude-plugin/plugin.json' in workflow
assert "smda-automation-${{ needs.validate-release.outputs.version }}" in workflow
assert "smda-automation-0.2.0.tar.gz" not in workflow
```

Add a focused test that `distribution/README.md` contains the private installation commands from the approved design.

- [ ] **Step 2: Run the targeted test to prove RED**

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_packaging.py::test_standalone_runtime_workflow_builds_and_assembles_both_architectures \
  -q
```

Expected: FAIL because the version input and validation job do not exist and the artifact is still hard-coded.

- [ ] **Step 3: Implement the metadata gate with the Python standard library**

Change `workflow_dispatch` to require a `version` string, then add a cheap Ubuntu job before either macOS runner:

```yaml
on:
  workflow_dispatch:
    inputs:
      version:
        description: Plugin semantic version, without the v prefix
        required: true
        type: string

jobs:
  validate-release:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.version.outputs.version }}
    steps:
      - uses: actions/checkout@v7
      - id: version
        env:
          VERSION: ${{ inputs.version }}
        run: |
          python3 - <<'PY'
          import json
          import os
          import re
          from pathlib import Path

          version = os.environ["VERSION"]
          if re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version) is None:
              raise SystemExit(f"invalid semantic version: {version!r}")
          manifests = (
              Path("plugins/smda-automation/.codex-plugin/plugin.json"),
              Path("plugins/smda-automation/.claude-plugin/plugin.json"),
          )
          for manifest in manifests:
              actual = json.loads(manifest.read_text())["version"]
              if actual != version:
                  raise SystemExit(f"{manifest}: expected {version}, found {actual}")
          with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
              print(f"version={version}", file=output)
          PY
```

Make both native jobs depend on `validate-release`. Make `assemble-plugin` depend on validation plus both builds, and replace its hard-coded tarball and artifact names with `${{ needs.validate-release.outputs.version }}`.

- [ ] **Step 4: Add the distribution README**

Create `distribution/README.md` containing only the product purpose, supported macOS architectures, the private Codex marketplace/install commands, and the statement that Python and uv are bundled while Node remains required for Sandcastle:

````markdown
# SMDA Plugin Distribution

Private installable releases of the SMDA Automation plugin for macOS arm64 and x86_64.

```bash
codex plugin marketplace add git@github.com:Hsiang-LinC/smda-plugin-dist.git
codex plugin add smda-automation@smda
```

The SMDA executable bundles Python 3.12 and its Python dependencies. Python and uv are not consumer prerequisites. The bundled Sandcastle runner still requires a compatible Node runtime.
````

- [ ] **Step 5: Run the targeted tests to prove GREEN**

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_packaging.py \
  -q
git diff --check
```

Expected: packaging suite and diff check pass.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/build-plugin-runtime.yml distribution/README.md packages/scheduler/tests/test_packaging.py
git commit -m "ci: validate plugin release version"
```

### Task 4: Publish only the approved distribution tree

**Files:**
- Modify: `packages/scheduler/tests/test_packaging.py`
- Modify: `.github/workflows/build-plugin-runtime.yml`

- [ ] **Step 1: Write the failing publication contract test**

Add `test_plugin_workflow_publishes_private_distribution_atomically` with the minimum security and dependency assertions:

```python
workflow = Path(".github/workflows/build-plugin-runtime.yml").read_text(encoding="utf-8")

publish = workflow.split("  publish-plugin:\n", 1)[1]
assert "needs: [validate-release, assemble-plugin]" in publish
assert "SMDA_DIST_DEPLOY_KEY" in publish
assert "Hsiang-LinC/smda-plugin-dist.git" in publish
assert ".agents/plugins/marketplace.json" in publish
assert ".claude-plugin/marketplace.json" in publish
assert "role_schemas.v1.json" in publish
assert "git rev-parse -q --verify" in publish
assert "git push --atomic" in publish
assert "SMDA_DIST_DEPLOY_KEY" not in workflow.split("  publish-plugin:\n", 1)[0]
```

- [ ] **Step 2: Run the test to prove RED**

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_packaging.py::test_plugin_workflow_publishes_private_distribution_atomically \
  -q
```

Expected: FAIL because `publish-plugin` does not exist.

- [ ] **Step 3: Add the gated publish job**

Add an Ubuntu `publish-plugin` job that checks out source, downloads the assembled artifact, installs the deploy key with mode `0600`, obtains GitHub host keys through the TLS-authenticated GitHub API, and clones the private repository:

```yaml
  publish-plugin:
    needs: [validate-release, assemble-plugin]
    runs-on: ubuntu-latest
    env:
      VERSION: ${{ needs.validate-release.outputs.version }}
      DIST_REPO: git@github.com:Hsiang-LinC/smda-plugin-dist.git
      GIT_SSH_COMMAND: ssh -i ${{ runner.temp }}/smda_dist_key -o IdentitiesOnly=yes
    steps:
      - uses: actions/checkout@v7
      - uses: actions/download-artifact@v7
        with:
          name: smda-automation-${{ needs.validate-release.outputs.version }}
          path: release
      - name: Configure distribution deploy key
        env:
          SMDA_DIST_DEPLOY_KEY: ${{ secrets.SMDA_DIST_DEPLOY_KEY }}
          GH_TOKEN: ${{ github.token }}
        run: |
          install -d -m 700 ~/.ssh
          install -m 600 /dev/null "$RUNNER_TEMP/smda_dist_key"
          printf '%s\n' "$SMDA_DIST_DEPLOY_KEY" > "$RUNNER_TEMP/smda_dist_key"
          gh api meta --jq '.ssh_keys[] | "github.com " + .' > ~/.ssh/known_hosts
          chmod 600 ~/.ssh/known_hosts
      - name: Stage verified distribution
        run: |
          set -eu
          mkdir release/plugin
          tar -xzf "release/smda-automation-${VERSION}.tar.gz" -C release/plugin
          git clone "$DIST_REPO" release/dist
          cd release/dist
          if git rev-parse -q --verify "refs/tags/v${VERSION}" >/dev/null; then
            echo "release tag v${VERSION} already exists" >&2
            exit 1
          fi
          unexpected="$(git ls-files | awk '!/^(\.agents\/plugins\/marketplace\.json|\.claude-plugin\/marketplace\.json|README\.md|plugins\/smda-automation\/)/')"
          test -z "$unexpected" || { printf 'unexpected distribution paths:\n%s\n' "$unexpected" >&2; exit 1; }
          git rm -r --ignore-unmatch -- .agents .claude-plugin plugins README.md
          mkdir -p .agents/plugins .claude-plugin plugins
          cp ../../.agents/plugins/marketplace.json .agents/plugins/marketplace.json
          cp ../../.claude-plugin/marketplace.json .claude-plugin/marketplace.json
          cp ../../distribution/README.md README.md
          cp -R ../plugin/smda-automation plugins/smda-automation
          test -x plugins/smda-automation/runtime/bin/darwin-arm64/smda/smda
          test -x plugins/smda-automation/runtime/bin/darwin-x86_64/smda/smda
          test -f plugins/smda-automation/runtime/bin/darwin-arm64/smda/_internal/smda_scheduler/schemas/role_schemas.v1.json
          test -f plugins/smda-automation/runtime/bin/darwin-x86_64/smda/_internal/smda_scheduler/schemas/role_schemas.v1.json
          git add .agents .claude-plugin README.md plugins
          git config user.name github-actions[bot]
          git config user.email 41898282+github-actions[bot]@users.noreply.github.com
          git commit -m "Release smda-automation ${VERSION}"
          git tag "v${VERSION}"
          git push --atomic origin main "v${VERSION}"
```

Do not add a separate publication script: this one workflow is the only caller, and the static contract test covers the dangerous invariants.

- [ ] **Step 4: Run targeted verification**

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest \
  packages/scheduler/tests/test_packaging.py \
  -q
git diff --check
```

Expected: packaging suite and diff check pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/build-plugin-runtime.yml packages/scheduler/tests/test_packaging.py
git commit -m "ci: publish private plugin distribution"
```

### Task 5: Publish and test the private consumer path

**Files:**
- Modify: `docs/work-ledger/active.md`

- [ ] **Step 1: Run all local gates before publication**

```bash
UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest packages/scheduler/tests -q
npm run test:ts
npm run typecheck
git diff --check
```

Expected: all product gates pass. If this host repeats the documented legacy Git-default-branch or file-descriptor failures, rerun with the already verified temporary `init.defaultBranch=master` test config and `ulimit -n 1024`, and record both the literal and normalized outcomes.

- [ ] **Step 2: Push source commits and dispatch the release**

The current manifests are version `0.2.0`, so the first private release uses that exact version unless a tag already exists:

```bash
git push origin main
gh workflow run build-plugin-runtime.yml \
  --repo Hsiang-LinC/smda \
  --ref main \
  -f version=0.2.0
SMDA_RUN_ID="$(gh run list \
  --repo Hsiang-LinC/smda \
  --workflow build-plugin-runtime.yml \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')"
gh run watch "$SMDA_RUN_ID" --repo Hsiang-LinC/smda --exit-status
```

Expected: validation, both native builds, assembly, and publication succeed.

- [ ] **Step 3: Verify immutable distribution state**

```bash
gh api repos/Hsiang-LinC/smda-plugin-dist/git/ref/heads/main --jq '.object.sha'
gh api repos/Hsiang-LinC/smda-plugin-dist/git/ref/tags/v0.2.0 --jq '.object.sha'
gh api repos/Hsiang-LinC/smda-plugin-dist/git/trees/main?recursive=1 --jq '.tree[].path'
```

Expected: `main` and `v0.2.0` resolve to the same commit and every path is within the approved distribution layout. Verify both native executables and both role-schema files appear.

- [ ] **Step 4: Switch this development machine from the local marketplace to the real private consumer path**

First inspect the installed state and CLI syntax:

```bash
codex plugin list
codex plugin marketplace list
codex plugin marketplace remove --help
```

Then remove `smda-automation@smda`, remove the local `smda` marketplace, add the private Git marketplace, and reinstall:

```bash
codex plugin remove smda-automation@smda
codex plugin marketplace remove smda
codex plugin marketplace add git@github.com:Hsiang-LinC/smda-plugin-dist.git
codex plugin add smda-automation@smda
codex plugin list
```

Expected: version `0.2.0` is installed from the private marketplace. Local source development continues through `uv run`; the plugin installation now exercises the same path as another authorized consumer. If installation fails, restore the local marketplace from this repository before further diagnosis.

- [ ] **Step 5: Prove the installed MCP has no Python or uv dependency**

Locate the installed cache with `codex plugin list`, create a temporary PATH containing only a fake `uname` plus the system commands required by the launcher, run the cached `runtime/smda mcp` from `/private/tmp`, and send one newline-delimited JSON-RPC `initialize` request:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smda-dist-smoke","version":"1"}}}
```

Expected: a JSON-RPC initialize result, exit status 0, and no `python`, `python3`, or `uv` executable in the test PATH.

- [ ] **Step 6: Record evidence and route to human review**

Update `private-plugin-distribution-cd` in `docs/work-ledger/active.md` with:

- local gate command outcomes;
- GitHub Actions run URL and job outcomes;
- distribution `main`/tag SHA;
- approved-tree verification;
- Codex installed version and cache path;
- no-Python/no-uv MCP initialize outcome.

Set `status: blocked` and `next: ready-for-human — accept the private plugin distribution CD and move this entry to completed.md`. This is a human-review wait state, not a technical failure.

- [ ] **Step 7: Commit and push the evidence**

```bash
git add docs/work-ledger/active.md
git commit -m "docs: record private plugin distribution verification"
git push origin main
```

Expected: source `main` is clean and the tracker points to reproducible evidence; the agent does not mark its own implementation `done`.
