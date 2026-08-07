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
- standalone macOS arm64 and x86_64 scheduler bundles used by both CLI and MCP;
- the bundled Sandcastle runner artifact used for role attempts;
- `.mcp.json`, which registers the product-owned SMDA operator MCP server.

Plugin consumers do not need Python, uv, or a venv. The Sandcastle runner still
requires Node. Current artifacts are unsigned and unnotarized; signing and
automated marketplace publication remain release follow-ups.

Target repos should not carry SMDA runtime copies, Sandcastle runner sources,
or SMDA `node_modules`. They carry only config, harness routing, tracker
policy, ignored local env/state, and optional daemon controller glue.

Existing repos need an SMDA refresh only when their checked-in config or
handoff docs still point at a product checkout path, copied runtime files, or
old daemon scripts. Refreshing does not rerun the generic development harness;
it updates Tier-3 SMDA config/pointers so the repo uses the installed plugin
runtime and MCP tools.

## Current Status

MVP approved-spec execution runtime with the A-E unattended-convergence
foundation. The built-in daemon tick scans Linear or local-ledger backlogs,
classifies Task, Child, Parent, and Roadmap candidates, reconciles pending
tracker effects, and dispatches a bounded synchronous worker batch through the
Sandcastle adapter.

Workflow Definitions are the single static Parent Role residence. The SQLite
Runtime Ledger owns durable phases and claims, semantic Attempt History, typed
Workflow Graph Artifacts, expected-phase-fenced Parent/Roadmap transitions,
and transactional lifecycle Backlog Projection enqueue. Parent integration
recovery, concrete git integration branches, Codex harness context discovery,
package entrypoints, and Linear environment wiring are implemented. The local
setup skill points consumer repos at the plugin-bundled runtime and emits
Tier-3 config/wiring only.

Live daemon deployment remains an explicit operator step: provide repo config,
backlog credentials, and Sandcastle provider settings, then start the bundled
daemon. Raw Request admission and generated-spec review, Amendments, a
non-blocking Coordinator, typed Control Events/Escalations, external
Child/Roadmap publication sagas, and the AFK convergence suite remain
separately scoped unattended-convergence plans; the current timer-driven tick
waits for each dispatched batch.

## Local CLI

From a checkout:

```bash
uv run smda validate-config /path/to/repo/smda.config.json --repo-root /path/to/repo
uv run smda validate-context /path/to/repo/smda.config.json --repo-root /path/to/repo
```

From an installed Codex plugin bundle:

```bash
~/.codex/plugins/cache/smda/smda-automation/0.2.0/runtime/smda validate-config /path/to/repo/smda.config.json --repo-root /path/to/repo
~/.codex/plugins/cache/smda/smda-automation/0.2.0/runtime/smda validate-context /path/to/repo/smda.config.json --repo-root /path/to/repo
```

Run the manually dispatched `Build SMDA plugin runtime` GitHub Actions workflow
to produce the dual-architecture `smda-automation-0.2.0` tar artifact.

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
