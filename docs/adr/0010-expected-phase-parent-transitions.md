---
status: accepted
---

# Parent transitions preserve intake facts and require the expected phase

Parent and Roadmap intake establish approved-spec facts once. Every later
Parent Transition must preserve those facts and move from an expected current
phase to the next phase atomically. A stale transition fails instead of
silently overwriting newer Runtime Ledger state.

## Considered options

- **Keep caller-supplied spec facts and blind upsert:** rejected because every
  caller can repeat, omit, or corrupt immutable data, and concurrent stale work
  becomes last-writer-wins.
- **Preserve spec facts but update phase without an expectation:** rejected
  because it removes duplicated metadata but leaves the stale-write window.
- **Force Parent and Child through one transition Interface:** rejected because
  Child attempts already use a deep durable workflow path, while Parent and
  Roadmap transitions have different atomic facts and effects.

## Consequences

- Initial intake remains responsible for spec path, checksum, and approval
  evidence; later Parent Transitions do not accept replacements for them.
- A Parent Transition may atomically include an Attempt Result Artifact,
  Workflow Graph changes, and required Backlog Projection effects.
- Child implement, fix, spec review, and quality review continue through their
  existing durable scheduling path.
- Current `record_parent_run` callers repeat immutable fields and perform blind
  upserts, so the implementation does not yet satisfy this decision.
