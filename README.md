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

## Current Status

Early product implementation. Boot, workflow, scheduling, Sandcastle IPC, test
fixtures, durable child phase/claim state, and the Linear backlog adapter exist.
Full attempt/idempotency ledger, daemon/control surfaces, live adapter wiring,
and setup-skill product integration are still in progress.

Start with:

- `docs/architecture-rationale.md`
- `docs/product-spec.md`
- `docs/adapter-boundaries.md`
- `docs/contracts.md`
- `docs/component-inventory.md`
- `docs/trading-advisor-extraction-inventory.md`
