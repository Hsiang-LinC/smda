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

```text
SMDA Scheduler
  scheduling engine     scan, claim, retry, concurrency, reconciliation
  workflow engine       graph, transitions, phase ledger, QA/remediation
  execution adapter     Sandcastle run/createSandbox/Output.object
  backlog adapters      Linear, GitHub, local
  context adapters      Codex harness or equivalent repo context
  setup skill           repo onboarding and validation
```

## Current Status

Design/spec phase. No runtime implementation has been extracted into this repo
yet.

Start with:

- `docs/architecture-rationale.md`
- `docs/product-spec.md`
- `docs/adapter-boundaries.md`
- `docs/trading-advisor-extraction-inventory.md`
