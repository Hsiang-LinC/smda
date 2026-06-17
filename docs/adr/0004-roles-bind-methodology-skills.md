---
status: accepted
---

# Roles bind methodology skills

Each `RoleContract` declares the methodology skill(s) its work is governed by, and
the runner deterministically loads that skill's content and composes the prompt as
`persona + task context + injected methodology`. Decompose, implement, review, and
fix quality must not depend on the model's per-turn luck; the methodology that
makes each good is the same versioned knowledge a human invokes via the
engineering skill library, so SMDA roles consume that same library rather than
re-encoding it. Methodology becomes data and pluggable — swapping a role's
methodology is a change to its declared skill, not to code.

We rejected inlining methodology text into each prompt (duplicates the skill,
drifts out of sync, not reusable) and letting the agent self-select skills at
runtime (reintroduces the per-turn-luck problem this decision exists to remove).

## Initial role → skill binding

| Role | Methodology skill(s) |
|---|---|
| `roadmap_decomposer` | `to-prd`, `to-issues` |
| `graph_decomposer` | `to-issues` |
| `child_implementer` | `tdd` |
| `child_fixer`, `graph_fixer` | `diagnose` |
| spec reviewers | `grill-with-docs` / `triage` |
| `child_quality_reviewer` | `improve-codebase-architecture` |
| `parent_qa_reviewer` | `triage` |

The binding is illustrative of the mechanism; exact mappings are tuned during
implementation.

## Consequences

- The runner gains a skill-resolution step; skill provenance/versioning is decided
  separately (where skills physically resolve from for a consumer repo).
- Pairs with [ADR-0001](0001-one-workflow-engine-many-definitions.md): a Stage's
  `RoleAttempt` work handler carries the declared methodology skill.
