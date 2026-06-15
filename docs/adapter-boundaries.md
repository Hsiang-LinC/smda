# Adapter Boundaries

Status: draft for review

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

## Context Adapter

Owns:

- harness discovery;
- source-of-truth docs;
- quality gates;
- repo commands;
- roadmap/spec/ADR locations.

SMDA uses this data to build context packets, but the adapter discovers where
the data lives.
