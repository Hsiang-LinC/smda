---
status: accepted
---

# Parent integration to base and cross-parent conflict repair

Parent `FINAL_ACCEPT` now lands work to a base branch (overturning the prior v1
non-goal in [known-gaps.md](../known-gaps.md)), because roadmap members must build
on each other's *landed* code. The integration topology is parametric:
`child → parent-integration → base`, where `base` is a shared
roadmap-integration branch for roadmap members and `main` for standalone Parents.
Landing reuses the existing `GitParentIntegration` ff-only-then-fallback seam one
tier up. Roadmap completion (the parent-tier `Aggregate` stage — all members
`FINAL_ACCEPTED`) lands the roadmap-integration branch to `main` as a single gate.

Cross-parent **conflict** can only occur between *independent* Parents (dependent
ones serialize via edges and build on landed work, so they cannot collide by
construction). A conflict is therefore a **dependency discovered late**. A
read-only `merge-tree --write-tree` probe runs as a Stage before the land Effect;
on conflict the loser is rebased onto the winner's landed base and re-runs quality
review, bounded by the existing fix-cycle → `HUMAN_REVIEW_REQUIRED` escalation. We
chose bounded auto-rebase over (a) straight-to-human (not self-healing) and (b) a
pessimistic file-claim registry (specs don't enumerate exact files → false blocks
that fight the parallelism goal).

## Consequences

- The known risk: agent-generated code may not rebase cleanly. The mandatory
  re-review after rebase is what catches semantic breakage; the cycle cap prevents
  rebase livelock.
- Conflict handling is a transition target in the stage engine
  ([ADR-0001](0001-one-workflow-engine-many-definitions.md)), not a bespoke
  branch.
- `merge-tree --write-tree` requires a git that supports it (2.38+); the
  `GitRunner` seam keeps this injectable/testable.
