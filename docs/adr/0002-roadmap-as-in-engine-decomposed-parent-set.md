---
status: accepted
---

# Roadmap as an in-engine decomposed parent set

A Roadmap is decomposed *inside* the engine: a `roadmap_decomposer` role reads an
approved Roadmap Spec and authors the whole parent set at once — every member
Parent issue plus every parent-to-parent dependency edge — with global visibility
of the set. We chose this over ad-hoc human authoring because a single author with
global visibility resolves cross-parent **dependency** at source (the parent-tier
analogue of how parent→child decomposition authors child dependencies), turning a
weak after-the-fact concern into a first-class authored output. The interactive
roadmap *discussion* still happens outside the daemon (a skill); only the
structured breakdown is in-engine.

The authored edges are persisted as a **ledger parent-graph** (authoritative,
cycle-checked, offline-testable) and projected to tracker `blocks` relations for
human visibility via the existing `link_blocking` machinery. The parent
dependency gate reads the ledger parent-graph plus ledger `FINAL_ACCEPTED`
completion — an exact mirror of `child_dependency_gate`. `query_blocked_by` stays
display-only and is not used for gating.

## Scope boundary

This resolves cross-parent **dependency** only. Cross-parent **conflict** (two
Parents editing the same file) is a file-level fact invisible from specs at
authoring time and is handled by a separate integrate-time gate (tracked
separately; see [known-gaps.md](../known-gaps.md)).

## Consequences

- Reuses the parent's existing child-publication + `link_blocking` path one tier
  up; no new tracker plumbing, only a new role + a parent-graph store + a parent
  dependency gate mirroring the child one.
- Roadmap progression and auto-unblock ride the engine's `Aggregate` stage at the
  parent tier (see [ADR-0001](0001-one-workflow-engine-many-definitions.md)); no
  separate roadmap FSM, consistent with the emergent Roadmap model in
  [CONTEXT.md](../CONTEXT.md).
