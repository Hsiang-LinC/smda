# SMDA Scheduler

SMDA is a workflow scheduler for agentic software development.

It extends Symphony-style issue automation with explicit
State-Machine-Driven Automation: parent specs, reviewed child graphs, child
phase machines, dependency-gated dispatch, parent integration, QA, and
remediation loops. In these docs, Symphony names the upstream scheduling
concept; `codex-symphony` names the local Python implementation used as an
extraction source.

The product uses Sandcastle as the default execution adapter for isolated,
typed agent attempts. Sandcastle owns sandbox/worktree/session mechanics and
structured output extraction. SMDA owns workflow routing and durable phase
truth.

## Product Shape

Two fixed cores, three pluggable adapters, one config surface.

```text
SMDA Scheduler
  Tier 1 — fixed cores (compiled in, coupled, not swappable)
    scheduling engine   scan, claim, retry, concurrency, reconciliation
    workflow engine     graph, transitions, phase ledger, QA/remediation

  Tier 2 — pluggable adapters (interface + shipped default; swap = product code)
    execution adapter   Sandcastle run/createSandbox/Output.object
    backlog adapter     Linear for MVP; GitHub/local-file deferred
    context adapters    Codex harness or equivalent repo context

  Tier 3 — config surface (no code)
    setup skill         repo onboarding, config, wiring, validation
```

Agnosticism is spent at Tier 1 and preserved only at the Tier-2 interfaces. The
setup skill never emits engine or adapter code.

## Codex Plugin Package

The Codex plugin bundle is `plugins/smda-automation/`. It packages the pieces
needed to operate SMDA from Codex:

- the `setup-smda-automation` skill for repo-local Tier-3 setup and refresh;
- the bundled Python scheduler runtime used by the plugin MCP server;
- the bundled Sandcastle runner artifact used for role attempts;
- `.mcp.json`, which registers the product-owned SMDA operator MCP server.

Target repos should not carry SMDA runtime copies, Sandcastle runner sources,
or SMDA `node_modules`. They carry only config, harness routing, tracker
policy, ignored local env/state, and optional daemon controller glue.

Existing repos need an SMDA refresh only when their checked-in config or
handoff docs still point at a product checkout path, copied runtime files, or
old daemon scripts. Refreshing does not rerun the generic development harness;
it updates Tier-3 SMDA config/pointers so the repo uses the installed plugin
runtime and MCP tools.

## Current Status

MVP product runtime. Boot, workflow, scheduling, Python-to-Sandcastle IPC,
test fixtures, durable child phase/claim state, the Linear backlog adapter,
backlog candidate scanning, and Codex harness context packet discovery exist.
The product adapter registry can boot `sandcastle + linear + codex-harness`
configs, the ledger records attempt request/result idempotency and pending
tracker effects, and the runtime can dispatch a child phase as a typed
Sandcastle-compatible role attempt. Tracker-effect retry primitives, parent
accept recovery, concrete git integration-branch plumbing, injectable
workspace ticks, package entrypoints, and Linear environment wiring exist.
The local setup skill points consumer repos at the plugin-bundled product
runtime and emits Tier-3 config/wiring only.

Live daemon deployment remains an explicit operator step: provide Linear env
vars, Sandcastle credentials/provider settings, and a repo-specific parent/child
dispatch composition before starting unattended loops.

## Local CLI

From a checkout:

```bash
uv run smda-scheduler validate-config /path/to/repo/smda.config.json --repo-root /path/to/repo
uv run smda-scheduler validate-context /path/to/repo/smda.config.json --repo-root /path/to/repo
```

Linear live wiring uses environment variables, not committed config:

- `LINEAR_API_KEY`
- `SMDA_LINEAR_TEAM_ID`
- `SMDA_LINEAR_STATE_TODO`, `SMDA_LINEAR_STATE_IN_PROGRESS`, etc.

Start with:

- `docs/architecture-rationale.md`
- `docs/product-spec.md`
- `docs/adapter-boundaries.md`
- `docs/contracts.md`
- `docs/component-inventory.md`
- `docs/trading-advisor-extraction-inventory.md`
