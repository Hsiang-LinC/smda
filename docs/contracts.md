# SMDA Contracts — Boot Contract (config, adapters, versions)

Status: draft for review (skeleton; shapes and rules fixed, exact signatures
deferred to implementation)

This document defines the contracts that let the SMDA Scheduler product start
against a given repo and adapter set. Three things are one coupled cluster — the
**boot contract** — and are specified together here: the config surface (Tier
3), the adapter interface + capability negotiation (Tier 2), and the version
compatibility matrix that the setup skill verifies before the daemon starts.

Override-compatibility for prompts/templates and provider-selection ownership
are included because they share the same validation gate.

---

## 1. Config surface (Tier 3)

Config is a first-class, versioned contract — not loose flags.

- **Residence:** `smda.config.yaml` (or `.json`) at the repo root, plus optional
  `smda.config.local.*` for secrets/overrides not committed.
- **Versioned:** carries `config_schema_version`. The daemon refuses to start on
  an unknown/incompatible config schema version (see §4).
- **Precedence (lowest → highest):** product defaults < repo `smda.config.*` <
  `smda.config.local.*` < environment variables < CLI flags. Higher wins per
  key; merges are shallow per top-level section unless a section documents deep
  merge.

Required top-level fields (skeleton):

```yaml
config_schema_version: <int>
runtime:
  version_constraint: <range>          # acceptable runtime versions
adapters:
  execution: { id: sandcastle, version_constraint: <range>, provider: noSandbox }
  backlog:   { id: linear,     version_constraint: <range> }
  context:   { id: codex-harness, version_constraint: <range> }
schemas:
  role_schema_package_version: <range> # the *-result / role schema set
context:
  bootloader_path: <path>
  spec_locations: [ <path>, ... ]
  adr_locations: [ <path>, ... ]
  quality_gates: [ <command>, ... ]
policy:
  issue_entry: explicit-only | implicit-one-child | blocked
  qa:
    max_same_feedback_fingerprint: <int>
    max_total_remediation_children: <int>
    max_parent_qa_cycles: <int>
prompts:
  overrides_dir: <path or null>        # Tier-3 wording/context only (see §3)
labels:
  ...tracker-specific handles...
```

The setup skill writes this file. It writes nothing else executable.

---

## 2. Adapter interface + capability negotiation (Tier 2)

Each adapter is selected by id in config and resolved by the product to a shipped
or installed implementation. Every adapter MUST expose:

- `id` and `version`;
- `capabilities() -> CapabilitySet` — what this implementation actually
  supports;
- its core methods (named below; exact signatures deferred).

The workflow engine declares, per feature it runs, which capabilities are
**required** vs **optional**. On onboard/boot the product intersects
`workflow.required_capabilities` with `adapter.capabilities()`:

- missing **required** capability → **refuse onboard** with a named error (no
  silent degrade);
- missing **optional** capability → enable the documented fallback and record it.

### Execution adapter

- Core: `runAttempt(request) -> result` (run prompt in isolation, extract typed
  output, return result + evidence). Default: Sandcastle.
- Capabilities: `sandbox_providers: [noSandbox|docker|podman|vercel|custom]`,
  `session_resume`, `worktree_per_attempt`, `structured_output_recovery`.
- Required by workflow: `worktree_per_attempt` (concurrency safety),
  `structured_output_recovery`.

### Backlog adapter (the hard case — capability-sensitive)

- Core: `fetchIssue`, `setCoarseState`, `comment`, `createChild`,
  `linkBlocking`, `projectHierarchy`, `setLabels`.
- Capabilities: `hierarchy`, `blocking_relations`, `coarse_states`, `comments`,
  `labels`, `custom_fields`.
- Required by workflow: `coarse_states`, `comments`, `createChild`.
- Optional with fallback: `blocking_relations` (fallback: gate purely on SMDA
  graph DAG, skip tracker-side blocking projection), `hierarchy` (fallback: flat
  issues + parent-id label).

### Context adapter

- Core: `discoverBootloader`, `discoverGates`, `resolveDocLocations`,
  `repoCommands`.
- Capabilities: `roadmap`, `adr`, `quality_gates`.
- Required: bootloader + at least one spec location.

A new adapter is **product code against these interfaces** — never a setup-skill
output (Tier-2 vs Tier-3 line).

---

## 3. Prompt / template override compatibility (Tier 3, gated)

Setup may supply prompt/template artifacts, but must not become a hidden workflow
fork.

- **Product owns (fixed):** role result schema, required report sections,
  transition semantics (`required_next_action` enum, verdict→phase routing).
- **Setup may override (Tier 3):** prompt wording, repo-specific context blocks.
- **Gate:** every override is run through a compatibility check — it MUST still
  satisfy the role schema and emit the required final `<output>` block with all
  required sections. Failing the check fails setup; it does not start a degraded
  daemon.

---

## 4. Version compatibility matrix (the boot gate)

Four versioned dimensions must be mutually compatible before the daemon starts:

```
runtime version  ↔  adapter version(s)  ↔  config_schema_version  ↔  role_schema_package_version
```

- Each dimension declares an accepted range against the others (skeleton: store
  the ranges; exact semver-range syntax deferred to implementation).
- **Boot gate:** the setup skill (and the daemon on startup) verifies the full
  matrix. Any incompatible pair → do not start; emit a named version error
  naming both sides and the expected range.
- This is the single precondition that makes "onboard then run" safe across
  product upgrades.

---

## 5. Tier-boundary test strategy (enforcement)

These tests mechanically prevent regression to a vendored runtime and keep the
tiers honest:

- **Core tests (Tier 1):** run the scheduling + workflow engines against **fake
  adapters**. No real sandbox, tracker, or repo. Asserts routing, ledger
  durability, QA bounds, dependency gating.
- **Adapter contract tests (Tier 2):** run each adapter against **shared
  fixtures** that exercise the interface + every declared capability and
  fallback. Same fixtures for all implementations of an interface.
- **Setup-skill tests (Tier 3):** assert the skill **emits config only and
  zero executable code**, and that override-compatibility (§3) and the version
  matrix (§4) checks fire. This test is the guardrail for the whole 3-tier model.
