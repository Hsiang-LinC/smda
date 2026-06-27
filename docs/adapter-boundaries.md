# Adapter Boundaries

Status: draft for review

## Product Shape: two cores, three adapters, one config surface

SMDA Scheduler is not a stack of symmetric adapters. It is:

- **Tier 1 — fixed cores (compiled into the product):** scheduling engine +
  workflow engine. Coupled, opinionated, not swappable. This is where
  agnosticism is intentionally spent.
- **Tier 2 — pluggable adapters (code against an interface, ship with
  defaults):** execution, backlog, context. Swapping one means writing an
  adapter — a product contribution, never a setup-skill output.
- **Tier 3 — config surface (setup skill, no code):** adapter selection,
  credentials, paths, policy numbers, prompt wording, labels.

The sections below detail each. Scheduling Engine + SMDA Workflow Engine are the
Tier-1 cores; Sandcastle / Backlog / Context are the Tier-2 adapters.

## Boundary Rule

Ask: would this logic still apply if the workflow were not SMDA?

- Yes: scheduling engine or backlog/execution/context adapter.
- No: SMDA workflow engine.

The scheduling engine is product core in the initial SMDA Scheduler. It is not
treated as a swappable external adapter. `codex-symphony` is an extraction
source for this engine; upstream Symphony is terminology lineage, not the
runtime dependency.

## Scheduling Engine

Owns:

- polling;
- dispatch eligibility;
- querying workflow engines for workflow-derived dispatch eligibility;
- claim/lease;
- concurrency;
- retry/backoff;
- pending tracker update retry;
- reconciliation;
- attempt ledger indexing when it is used for scheduling decisions;
- daemon lifecycle.

Does not own:

- child phase transitions;
- graph review semantics;
- parent QA remediation policy;
- role prompt contents;
- structured output extraction.

When dispatch eligibility depends on the SMDA graph, the scheduler asks the
SMDA workflow engine for eligible node ids. It only owns the generic scan,
claim, lease, and queue mechanics around that answer.

## SMDA Workflow Engine

Owns:

- parent intake state;
- graph, dependency type, and graph mutation policy;
- parent and child phase enums;
- transition table from typed role result to next phase;
- phase ledger fields that describe workflow truth only;
- context packet composition;
- parent integration and QA loop;
- remediation child routing.

Does not own:

- sandboxing;
- session capture;
- branch/worktree mechanics;
- JSON extraction from agent stdout;
- attempt history as execution bookkeeping;
- claim/lease/retry/backoff metadata;
- tracker reconciliation reports;
- backlog API specifics.

## Sandcastle Execution Adapter

Owns:

- `run()` / `createSandbox()`;
- `Output.object`;
- Standard Schema validation;
- structured output errors and same-session recovery;
- sandbox providers;
- worktree/branch strategy;
- commit/log/session metadata.

The adapter returns typed role results and execution evidence. SMDA core treats
that as an input event.

Execution evidence should be stored in an attempt ledger or execution artifact
store. SMDA child state may reference it, but should not embed the full attempt
history.

## Backlog Adapter

Owns:

- issue fetching;
- state updates;
- comments;
- hierarchy/sub-issue projection;
- blocking relation projection;
- tracker projection drift detection and repair effects;
- tracker-specific labels and identifiers.

SMDA asks for adapter-neutral effects; backlog adapters translate them.

For a `local-ledger` backlog adapter, the target repo's file-backed work ledger
is the backlog source and projection target. The SMDA runtime ledger remains the
workflow source of truth for phases, claims, attempts, pause state, accepted
refs, and pending projection effects. The local adapter may map harness fields,
append evidence, create scheduler-owned child entries, and project coarse
states; it must preserve harness-owned fields and must not bypass the repo's
human review or completion gate.

## Context Adapter

Owns:

- harness discovery;
- source-of-truth docs;
- quality gates;
- repo commands;
- roadmap/spec/ADR locations.

SMDA uses this data to build context packets, but the adapter discovers where
the data lives.

## Config Surface (setup skill)

The setup skill writes Tier-3 config only. It never emits engine or adapter
code. Allowed outputs: adapter selection + credentials, bootloader/spec/ADR
paths, quality-gate commands, issue-entry policy, QA policy numbers, sandbox
provider choice, role-prompt wording overrides, labels/handles. A new adapter is
product code against a Tier-2 interface, not a setup output.

Generic Codex development harness setup is also outside this surface. SMDA
setup consumes an Engineering harness or equivalent repo context contract and
adds only SMDA execution-routing, config, and operator guidance.
