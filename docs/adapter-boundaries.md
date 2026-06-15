# Adapter Boundaries

Status: draft for review

## Boundary Rule

Ask: would this logic still apply if the workflow were not SMDA?

- Yes: scheduling/backlog/execution adapter.
- No: SMDA workflow engine.

## Scheduling Engine

Owns:

- polling;
- dispatch eligibility;
- claim/lease;
- concurrency;
- retry/backoff;
- pending tracker update retry;
- reconciliation;
- daemon lifecycle.

Does not own:

- child phase transitions;
- graph review semantics;
- parent QA remediation policy;
- role prompt contents;
- structured output extraction.

## SMDA Workflow Engine

Owns:

- parent intake state;
- graph, dependency type, and graph mutation policy;
- parent and child phase enums;
- transition table from typed role result to next phase;
- context packet composition;
- parent integration and QA loop;
- remediation child routing.

Does not own:

- sandboxing;
- session capture;
- branch/worktree mechanics;
- JSON extraction from agent stdout;
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

## Backlog Adapter

Owns:

- issue fetching;
- state updates;
- comments;
- hierarchy/sub-issue projection;
- blocking relation projection;
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
