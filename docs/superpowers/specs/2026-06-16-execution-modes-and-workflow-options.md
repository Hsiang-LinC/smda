---
status: approved
created_at: 2026-06-16
owner: human
approved_at: 2026-06-16
approved_by: human
approval_evidence: conversation approval "ok approved"
---

# Execution Modes And Workflow Options

> **PARTIALLY SUPERSEDED (2026-06-16) by
> [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md) and the
> [target-C spec](2026-06-16-target-c-modular-parallel-engine.md).**
>
> **Retained as authority for:** the Mode catalog (`smda` / `smda-child` /
> `smda-task` / `smda-review` / `manual`), the Mode Tags vocabulary, the freeform
> issue-entry policies, and the dependency-gate invariants (a tag must never weaken
> dependency gating).
>
> **Superseded:** the `WorkflowOptions` boolean-bundle mechanism and "runtime
> resolves mode+tags into a typed options object that role attempts receive as
> context". Behaviour differences between modes are now expressed as distinct
> **Workflow Definitions** (different transition tables), not as `require_*`
> option flags threaded into role context. A Mode selects a Definition; tags map
> to definition selection / gate config, not to a boolean bundle. `smda-task` =
> the child SDD Definition minus the spec-review stage, NOT
> `require_spec_review=False`.
>
> The Design Principle below ("execution mode chooses the primary state machine")
> is correct and is generalized by the engine; only its *resolution mechanism* is
> replaced.

## Problem

SMDA currently treats the full parent-driven workflow as the main product path:
`Execution: smda` creates a parent run, decomposes a graph, publishes child
issues, runs child SDD loops, integrates accepted children, then runs parent QA.

That is correct for complex work, but too heavy for small bug fixes and
single-scope tasks. At the same time, letting any freeform issue be claimed
without a declared workflow would make scheduler behavior hard to predict.

SMDA needs multiple explicit execution modes that reuse the same scheduler,
ledger, role execution, typed output, review, and tracker-effect machinery, while
keeping each mode's state machine deterministic and testable.

## Design Principle

Execution mode chooses the primary state machine.

Mode tags are limited, typed modifiers. A tag may only alter predefined
workflow options. A tag must not create arbitrary transitions, bypass safety
gates, or redefine dependency truth.

This keeps the scheduler understandable:

- mode decides which workflow segment runs;
- tags decide which predefined gates/options are enabled;
- the runtime resolves both into typed `WorkflowOptions`;
- role attempts receive the resolved options as context;
- unsupported modes or tags are rejected before dispatch.

## Relationship To Child Dependency Dispatch Gate

This spec should remain separate from
`2026-06-16-child-dependency-dispatch-gate.md`.

The dependency-gate spec defines a scheduler safety invariant:

> A downstream child must not dispatch until every blocking upstream dependency
> is quality-passed and accepted into the parent integration branch.

This modes/options spec defines issue entry and workflow selection:

> Given an issue, choose the intended SMDA workflow segment and gate modifiers.

They are complementary:

- The dependency gate applies to `smda-child` and any mode that participates in
  a persisted parent graph.
- `smda-task` may run without a parent graph only when it is an independent
  single-task workflow.
- A tag cannot weaken dependency gating.
- `requires_integration` must use the same parent-accept/integration evidence
  rules as the dependency-gate spec.
- `full_review`, `quality_only`, `low_risk`, or model policy settings must not
  allow dispatch when dependency gating says blocked.

Keeping the specs separate allows independent implementation plans:

1. Dependency safety can be fixed first without introducing new modes.
2. New modes can then reuse the fixed scheduler gate rather than creating a
   second eligibility system.

## Mode Catalog

### `smda`

Issue marker:

```text
Execution: smda
```

Purpose:

Full parent-driven workflow for complex, multi-step, high-risk, or
spec-dependent work.

State machine:

```text
parent intake
-> graph decomposition
-> graph spec review
-> graph execution review
-> child issue publication
-> child SDD loops
-> parent integration branch acceptance
-> parent QA
-> final accept
```

Required context:

- `Source` pointing to an approved spec or enough parent intake context to find
  one.
- `Acceptance criteria`
- `Verification`

### `smda-child`

Issue marker:

```text
Execution: smda-child
Parent issue: <parent-id>
Graph checksum: <sha256:...>
Node id: <child-node-id>
Acceptance criteria: <...>
```

Purpose:

Scheduler-created child handle from a persisted parent graph.

State machine:

```text
implement
-> spec review
-> fix spec, if needed
-> quality review
-> fix quality, if needed
-> quality review passed
```

Rules:

- Only scheduler-created child issues should use this mode.
- The runtime must validate parent id, graph checksum, and node id.
- Dependency gating is owned by SMDA graph/ledger state, not by tracker labels.

### `smda-task`

Issue marker:

```text
Execution: smda-task
Acceptance criteria: <...>
Verification: <...>
```

Purpose:

Small bug fixes and single-scope tasks that need implementation plus automated
review, but do not need graph decomposition or parent QA.

State machine:

```text
task intake
-> synthetic child implement
-> review gates from resolved WorkflowOptions
-> task done or human review
```

Default gates:

- implementation
- quality review

Optional gates:

- spec review, when `full_review` is set or risk/context requires it;
- human approval before done, when `human_approval_required` is set;
- integration branch acceptance, when `requires_integration` is set.

The task mode should reuse child role contracts where possible. It should not
run graph decomposer, graph spec reviewer, graph execution reviewer, child issue
publication, or parent QA unless a future explicit tag enables a typed,
predefined extension.

### `smda-review`

Issue marker:

```text
Execution: smda-review
Candidate ref: <branch-or-commit>
Acceptance criteria: <...>
Verification: <...>
```

Purpose:

Review an existing branch, commit, or diff without authoring implementation
changes.

State machine:

```text
review intake
-> selected review gate(s)
-> done or human review
```

This mode is optional for the first implementation slice. It is included in the
catalog so setup/harness documentation can explain that review-only automation
is a separate mode, not a tag on arbitrary work.

### `manual`

Issue marker:

```text
Execution: manual
```

Purpose:

Explicitly prevent automatic claim. The scheduler may comment with guidance or
route to Human Review, but it must not run role attempts.

## Mode Tags

Tags are provided through the issue body in v1:

```text
Mode tags: full_review, high_risk
```

Tracker labels may later become UI shortcuts, but the first implementation
should parse issue-body tags only. This avoids expanding backlog adapter
contracts before the workflow behavior is stable.

Supported v1 tags:

### `full_review`

For `smda-task`, require both spec review and quality review.

For `smda`, this tag is redundant because full mode already includes graph
review, child review, and parent QA.

### `quality_only`

For `smda-task`, run implementation and quality review but skip spec review.

Rules:

- May only be used with low-risk or normal-risk task mode.
- Must be rejected with `high_risk`.
- Must not bypass quality review.

### `human_approval_required`

After all automated gates pass, park the issue in Human Review before terminal
Done/final accept.

### `requires_integration`

Require the completed candidate ref to be accepted into an integration branch
before the task is marked Done.

Rules:

- Must use the same parent-accept/integration evidence concepts as child
  acceptance.
- If no integration branch is configured, block with a clear tracker comment.

### `high_risk`

Increase scrutiny:

- disallow `quality_only`;
- prefer stronger model policy;
- require full review gates for task mode;
- allow future security or human approval gates as explicit options.

### `low_risk`

Allow lighter defaults for task mode, but do not allow bypassing required safety
gates.

## WorkflowOptions

> **SUPERSEDED by [ADR-0001](../../adr/0001-one-workflow-engine-many-definitions.md).**
> The `require_*` boolean bundle below is NOT the mechanism. A Mode selects a
> Workflow Definition (its own transition table); tag validation (unsupported /
> invalid-combination → routing block) is retained, but the resolved object is a
> Definition selector, not a set of behaviour flags passed into role context. The
> shape below survives only as the typed `ExecutionMode` / `ModeTag` vocabulary +
> validation; the `require_spec_review` / `require_quality_review` / … fields are
> dropped.

Runtime should resolve mode and tags into a typed options object before dispatch.

Suggested shape:

```python
@dataclass(frozen=True)
class WorkflowOptions:
    mode: ExecutionMode
    tags: frozenset[str]
    require_spec_review: bool
    require_quality_review: bool
    require_human_approval: bool
    require_integration: bool
    risk_level: str
```

Rules:

- Unsupported mode -> routing block.
- Unsupported tag -> routing block.
- Invalid tag combination -> routing block.
- Resolved options should be persisted in the ledger or attempt request context
  so later ticks do not reinterpret the issue differently after body edits.

## Freeform Issue Entry

`policy.issue_entry` should evolve as follows:

### `explicit-only`

Only issues with supported `Execution:` markers are claimed.

Missing `Execution:` remains blocked with a clear comment.

### `blocked`

All unmodeled issues remain blocked.

### `implicit-one-child`

If an issue has minimum task context:

- `Acceptance criteria`
- `Verification`
- enough source/body context to identify the target change

then route it as `smda-task`, not as `IMPLICIT_PARENT`.

If the issue lacks minimum context, block or Human Review with a comment that
names the missing fields.

## Setup And Harness Surface

Setup must write the mode catalog into the target repo's agent-facing harness
docs, such as `AGENTS.md`, `docs/harness/tracker.md`, or a dedicated SMDA
section.

Minimum text:

```md
## SMDA Execution Modes

- Use `Execution: smda` for complex spec-driven work that may need decomposition.
- Use `Execution: smda-task` for small scoped bugs and single-task fixes.
- Use `Execution: smda-child` only for scheduler-created child issues.
- Use `Execution: smda-review` for review-only automation, if enabled.
- Use `Execution: manual` to prevent automatic claim.

Optional `Mode tags:` values: full_review, quality_only,
human_approval_required, requires_integration, high_risk, low_risk.

Mode chooses the primary state machine. Tags only modify predefined gates.
```

The setup skill must not generate project-specific custom modes unless the SMDA
product runtime supports and validates them.

## Model Policy

Current implementation uses one `AgentSelection(provider, model)` for all role
attempts in a tick. This spec allows a future model policy but does not require
it for the first modes implementation.

Future shape:

```python
def resolve_agent_selection(
    *,
    mode: ExecutionMode,
    phase: ChildPhase | ParentPhase | TaskPhase,
    risk_level: str,
    tags: frozenset[str],
    default: AgentSelection,
) -> AgentSelection:
    ...
```

Initial policy may be a config table:

- task implementer: default or smaller model;
- task/full quality reviewer: stronger/default model;
- graph decomposer and graph reviewers: stronger model;
- high risk: stronger model for every phase.

The model resolver must be deterministic and recorded in the attempt request.
Agents may recommend a mode, but the scheduler owns validation and final
resolution.

## Acceptance Criteria

- The product docs define the supported modes and tags.
- Setup/harness output surfaces those modes to repo agents.
- `Execution: smda-task` can run a small bug through a reusable child SDD segment
  without parent graph decomposition.
- `implicit-one-child` routes suitable freeform issues to `smda-task`.
- Tags resolve into typed `WorkflowOptions`.
- Invalid tags or invalid tag combinations block before role execution.
- Tags cannot override dependency gating or stale graph checksum checks.
- Existing `smda` and `smda-child` behavior remains compatible.

## Required Tests

- Candidate routing classifies `Execution: smda-task`.
- Candidate routing parses `Mode tags`.
- Unsupported tags block with a clear reason.
- `quality_only + high_risk` blocks.
- `implicit-one-child` routes minimum-context freeform issues to `smda-task`.
- `smda-task` builds a child-style role attempt context without parent graph
  decomposition.
- `full_review` on `smda-task` enables spec review before quality review.
- Setup/harness generated docs include the mode catalog.

## Done Definition

- Specs/docs describe mode and tag semantics.
- Runtime validates modes/tags before dispatch.
- Small bug issues can use `smda-task` without the full parent workflow.
- The child dependency dispatch gate spec remains satisfied.
- Existing full SMDA E2E behavior is not weakened.
